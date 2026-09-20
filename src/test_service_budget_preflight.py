import io
import json
import os
import unittest
import urllib.error

from unittest.mock import patch

from service_budget_preflight import (
    BLOCK,
    PASS,
    UNKNOWN,
    WARN,
    blocking,
    check_elevenlabs,
    estimate_elevenlabs_audio_credits,
    estimate_runway_budget,
    evaluate_runway_capacity,
)


class ServiceBudgetPreflightTests(
    unittest.TestCase
):

    def runway_job(
        self,
    ) -> dict:

        return {
            "script": {
                "scenes": [
                    {
                        "scene_id": 1,
                        "timing": {
                            "status": "passed",
                            "render_duration_sec": 2.2,
                        },
                    },
                    {
                        "scene_id": 2,
                        "timing": {
                            "status": "passed",
                            "render_duration_sec": 4.1,
                        },
                    },
                ],
            },
            "visuals": {
                "scenes": [
                    {
                        "scene_id": 1,
                        "video": {},
                    },
                    {
                        "scene_id": 2,
                        "video": {},
                    },
                ],
            },
        }


    def test_runway_budget_uses_pending_scene_duration_and_retries(
        self,
    ):

        budget = estimate_runway_budget(
            job=self.runway_job(),
            model="gen4_turbo",
            max_video_attempts=4,
        )

        self.assertEqual(
            budget[
                "provider_durations_sec"
            ],
            [
                3.0,
                5.0,
            ],
        )

        self.assertEqual(
            budget[
                "base_required_credits"
            ],
            40.0,
        )

        self.assertEqual(
            budget[
                "worst_case_required_credits"
            ],
            160.0,
        )

        self.assertEqual(
            budget[
                "base_required_generations"
            ],
            2,
        )

        self.assertEqual(
            budget[
                "worst_case_required_generations"
            ],
            8,
        )


    def test_runway_ready_scene_is_not_budgeted_again(
        self,
    ):

        job = self.runway_job()

        job[
            "visuals"
        ][
            "scenes"
        ][0][
            "video"
        ] = {
            "provider": "runway",
            "status": "passed",
            "semantic_qc": {
                "status": "passed",
            },
        }

        budget = estimate_runway_budget(
            job=job,
            model="gen4_turbo",
            max_video_attempts=4,
        )

        self.assertEqual(
            budget[
                "provider_durations_sec"
            ],
            [
                5.0,
            ],
        )

        self.assertEqual(
            budget[
                "base_required_credits"
            ],
            25.0,
        )


    def test_runway_capacity_blocks_warns_and_passes(
        self,
    ):

        budget = estimate_runway_budget(
            job=self.runway_job(),
            model="gen4_turbo",
            max_video_attempts=4,
        )

        status, _ = evaluate_runway_capacity(
            balance=20.0,
            budget=budget,
            remaining_daily=100,
        )

        self.assertEqual(
            status,
            BLOCK,
        )

        status, _ = evaluate_runway_capacity(
            balance=50.0,
            budget=budget,
            remaining_daily=100,
        )

        self.assertEqual(
            status,
            WARN,
        )

        status, _ = evaluate_runway_capacity(
            balance=200.0,
            budget=budget,
            remaining_daily=8,
        )

        self.assertEqual(
            status,
            PASS,
        )


    def test_elevenlabs_missing_scope_warns_instead_of_blocking(
        self,
    ):

        error = RuntimeError(
            (
                "HTTP 401 from "
                "https://api.elevenlabs.io/v1/user/subscription: "
                '{"detail":{"code":"missing_permissions",'
                '"message":"missing permission models_read"}}'
            )
        )

        with (
            patch.dict(
                os.environ,
                {
                    "ELEVENLABS_API_KEY":
                        "test-key",
                },
            ),
            patch(
                "service_budget_preflight.http_json",
                side_effect=error,
            ) as mocked_http,
        ):

            check = check_elevenlabs(
                required_credits=521.25,
            )

        self.assertEqual(
            check.status,
            WARN,
        )

        self.assertEqual(
            check.details[
                "quota_visibility"
            ],
            "permission_required",
        )

        self.assertEqual(
            check.details[
                "required_credits_estimate"
            ],
            521.25,
        )

        self.assertEqual(
            mocked_http.call_count,
            1,
        )

        self.assertEqual(
            mocked_http.call_args.kwargs[
                "url"
            ],
            (
                "https://api.elevenlabs.io"
                "/v1/user/subscription"
            ),
        )


    def test_elevenlabs_insufficient_scope_warns_instead_of_blocking(
        self,
    ):

        error = RuntimeError(
            (
                "HTTP 403 from "
                "https://api.elevenlabs.io/v1/user/subscription: "
                '{"detail":{"code":"insufficient_permissions",'
                '"message":"insufficient permission user_read"}}'
            )
        )

        with (
            patch.dict(
                os.environ,
                {
                    "ELEVENLABS_API_KEY":
                        "test-key",
                },
            ),
            patch(
                "service_budget_preflight.http_json",
                side_effect=error,
            ) as mocked_http,
        ):

            check = check_elevenlabs()

        self.assertEqual(
            check.status,
            WARN,
        )

        self.assertEqual(
            check.details[
                "quota_visibility"
            ],
            "permission_required",
        )

        self.assertEqual(
            mocked_http.call_count,
            1,
        )

        self.assertNotIn(
            "/v1/models",
            mocked_http.call_args.kwargs[
                "url"
            ],
        )


    def test_elevenlabs_invalid_auth_still_blocks(
        self,
    ):

        error = urllib.error.HTTPError(
            "https://api.elevenlabs.io/v1/user/subscription",
            401,
            "Unauthorized",
            {},
            io.BytesIO(
                b'{"detail":{"code":"unauthorized",'
                b'"message":"invalid API key"}}'
            ),
        )

        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "bad-key"}),
            patch("urllib.request.urlopen", side_effect=error),
        ):
            check = check_elevenlabs()

        self.assertEqual(check.status, BLOCK)


    def test_elevenlabs_http_error_policy_at_startup_and_audio_stage(self):
        url = "https://api.elevenlabs.io/v1/user/subscription"
        cases = [
            (401, "missing_permissions", WARN),
            (403, "missing_permissions", WARN),
            (401, "insufficient_permissions", WARN),
            (403, "insufficient_permissions", WARN),
            (401, "invalid_api_key", BLOCK),
            (403, "invalid_api_key", BLOCK),
            (401, "unauthorized", BLOCK),
            (403, "unauthorized", BLOCK),
            (403, "forbidden", UNKNOWN),
            (429, "rate_limit_exceeded", UNKNOWN),
            (503, "internal_server_error", UNKNOWN),
        ]
        for http_status, code, expected in cases:
            for field in ("code", "status"):
                for required in (None, 521.25):
                    with self.subTest(
                        http_status=http_status, code=code,
                        field=field, required=required,
                    ):
                        body = json.dumps({"detail": {field: code}}).encode()
                        error = urllib.error.HTTPError(
                            url, http_status, "error", {}, io.BytesIO(body)
                        )
                        with (
                            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}),
                            patch("urllib.request.urlopen", side_effect=error) as request,
                        ):
                            check = check_elevenlabs(required_credits=required)
                        self.assertEqual(check.status, expected)
                        self.assertEqual(bool(blocking([check])), expected == BLOCK)
                        self.assertEqual(check.details["required_credits_estimate"], required)
                        request.assert_called_once()
                        self.assertEqual(request.call_args.args[0].full_url, url)


    def test_elevenlabs_unavailable_quota_is_unknown(self):
        for error in (
            TimeoutError("timed out"),
            urllib.error.URLError("connection failed"),
            ValueError("invalid JSON"),
        ):
            with (
                self.subTest(error=error),
                patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}),
                patch("urllib.request.urlopen", side_effect=error),
            ):
                check = check_elevenlabs(required_credits=521.25)
                self.assertEqual(check.status, UNKNOWN)
                self.assertEqual(check.details["authentication"], "unknown")
                self.assertFalse(blocking([check]))


    def test_elevenlabs_success_reads_subscription_only(self):
        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}),
            patch("urllib.request.urlopen") as request,
        ):
            request.return_value.__enter__.return_value.read.return_value = (
                b'{"character_count":100,"character_limit":1000}'
            )
            check = check_elevenlabs(required_credits=521.25)
        self.assertEqual(check.status, PASS)
        self.assertEqual(check.details["visible_available_credits"], 900)
        request.assert_called_once()
        req = request.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.elevenlabs.io/v1/user/subscription")
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.get_header("Xi-api-key"), "test-key")


    def test_elevenlabs_missing_api_key_blocks_without_request(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("urllib.request.urlopen") as request,
        ):
            check = check_elevenlabs()
        self.assertEqual(check.status, BLOCK)
        request.assert_not_called()


    def test_elevenlabs_audio_estimate_uses_music_and_sfx_durations(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "timing": {
                            "render_duration_sec": 12.0,
                        },
                    },
                    {
                        "timing": {
                            "render_duration_sec": 18.0,
                        },
                    },
                ],
            },
            "audio": {
                "background_music": {
                    "required": True,
                },
                "sound_effects": {
                    "enabled": True,
                    "effects": [
                        {
                            "duration_sec": 1.5,
                        },
                        {
                            "duration_sec": 2.0,
                        },
                    ],
                },
            },
        }

        with patch.dict(
            os.environ,
            {
                "ELEVENLABS_MUSIC_CREDITS_PER_MINUTE":
                    "900",
                "ELEVENLABS_SFX_CREDITS_PER_SECOND":
                    "40",
            },
        ):

            estimate = (
                estimate_elevenlabs_audio_credits(
                    job
                )
            )

        self.assertEqual(
            estimate[
                "estimated_music_credits"
            ],
            450.0,
        )

        self.assertEqual(
            estimate[
                "estimated_sfx_credits"
            ],
            140.0,
        )

        self.assertEqual(
            estimate[
                "estimated_total_credits"
            ],
            590.0,
        )


    def test_blocking_returns_only_hard_blocks(
        self,
    ):

        from service_budget_preflight import (
            ServiceCheck,
        )

        checks = [
            ServiceCheck(
                "a",
                PASS,
                "ok",
                {},
            ),
            ServiceCheck(
                "b",
                WARN,
                "warning",
                {},
            ),
            ServiceCheck(
                "c",
                BLOCK,
                "stop",
                {},
            ),
        ]

        self.assertEqual(
            [
                check.service
                for check
                in blocking(
                    checks
                )
            ],
            [
                "c",
            ],
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
