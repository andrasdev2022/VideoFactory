from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runwayml import RunwayML

from validator import load_json


OPENAI_API_BASE = "https://api.openai.com"
ELEVENLABS_API_BASE = "https://api.elevenlabs.io"

PASS = "PASS"
WARN = "WARN"
BLOCK = "BLOCK"
UNKNOWN = "UNKNOWN"

RUNWAY_DEFAULT_CREDITS_PER_SECOND = {
    "gen4_turbo": 5.0,
}


@dataclass(frozen=True)
class ServiceCheck:
    service: str
    status: str
    message: str
    details: dict[str, Any]


def enabled() -> bool:
    return (
        os.getenv("SERVICE_PREFLIGHT_ENABLED", "1")
        .strip()
        .lower()
        not in {"0", "false", "no", "off"}
    )


def timeout_sec() -> float:
    return float(
        os.getenv(
            "SERVICE_PREFLIGHT_TIMEOUT_SEC",
            "10",
        )
    )


def is_permission_scope_error(
    exc: Exception,
) -> bool:
    text = str(
        exc
    ).lower()

    return any(
        marker in text
        for marker in (
            '"code":"missing_permissions"',
            '"code":"insufficient_permissions"',
            '"code": "missing_permissions"',
            '"code": "insufficient_permissions"',
            "missing the permission",
            "insufficient permissions",
        )
    )


def http_json(
    *,
    url: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    request = urllib.request.Request(
        url=url,
        headers=headers,
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_sec(),
        ) as response:
            payload = response.read()

    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            pass

        raise RuntimeError(
            f"HTTP {exc.code} from {url}: {body[:500]}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Network error calling {url}: {exc}"
        ) from exc

    if not payload:
        return {}

    return json.loads(
        payload.decode("utf-8")
    )


def check_openai() -> ServiceCheck:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return ServiceCheck(
            "openai",
            BLOCK,
            "OPENAI_API_KEY is missing.",
            {},
        )

    try:
        http_json(
            url=f"{OPENAI_API_BASE}/v1/models",
            headers={
                "Authorization":
                    f"Bearer {api_key}",
            },
        )
    except Exception as exc:
        return ServiceCheck(
            "openai",
            BLOCK,
            (
                "OpenAI authentication/availability "
                f"check failed: {exc}"
            ),
            {},
        )

    details: dict[str, Any] = {
        "authentication": "ok",
        "remaining_balance_known": False,
    }

    admin_key = os.getenv("OPENAI_ADMIN_KEY")
    raw_budget = os.getenv(
        "OPENAI_PREFLIGHT_MONTHLY_BUDGET_USD"
    )

    if admin_key and raw_budget:
        try:
            budget = float(raw_budget)
            now = datetime.now(timezone.utc)
            start = int(
                datetime(
                    now.year,
                    now.month,
                    1,
                    tzinfo=timezone.utc,
                ).timestamp()
            )

            query = urllib.parse.urlencode(
                {
                    "start_time": start,
                    "limit": 31,
                }
            )

            costs = http_json(
                url=(
                    f"{OPENAI_API_BASE}"
                    f"/v1/organization/costs?{query}"
                ),
                headers={
                    "Authorization":
                        f"Bearer {admin_key}",
                },
            )

            spent = 0.0

            for bucket in costs.get("data", []):
                for result in bucket.get(
                    "results",
                    [],
                ):
                    amount = result.get(
                        "amount",
                        {},
                    )

                    if (
                        amount.get("currency")
                        == "usd"
                    ):
                        spent += float(
                            amount.get(
                                "value",
                                0.0,
                            )
                        )

            details["monthly_spend_usd"] = round(
                spent,
                6,
            )
            details[
                "configured_monthly_budget_usd"
            ] = budget

            if spent >= budget:
                return ServiceCheck(
                    "openai",
                    BLOCK,
                    (
                        "OpenAI configured monthly "
                        "budget has been reached: "
                        f"{spent:.2f} / {budget:.2f} USD."
                    ),
                    details,
                )

        except Exception as exc:
            details[
                "admin_cost_check_error"
            ] = str(exc)

            return ServiceCheck(
                "openai",
                WARN,
                (
                    "OpenAI API key is valid, but "
                    "the optional admin cost-budget "
                    f"check failed: {exc}"
                ),
                details,
            )

    return ServiceCheck(
        "openai",
        UNKNOWN,
        (
            "OpenAI authentication is valid. "
            "The documented API does not expose "
            "a reliable remaining prepaid-credit "
            "balance, so sufficiency cannot be "
            "proved automatically."
        ),
        details,
    )


def check_elevenlabs(
    *,
    required_credits: float | None = None,
) -> ServiceCheck:
    api_key = os.getenv(
        "ELEVENLABS_API_KEY"
    )

    if not api_key:
        return ServiceCheck(
            "elevenlabs",
            BLOCK,
            "ELEVENLABS_API_KEY is missing.",
            {},
        )

    try:
        subscription = http_json(
            url=(
                f"{ELEVENLABS_API_BASE}"
                "/v1/user/subscription"
            ),
            headers={
                "xi-api-key": api_key,
            },
        )

    except Exception as exc:
        if is_permission_scope_error(
            exc
        ):
            return ServiceCheck(
                "elevenlabs",
                WARN,
                (
                    "ElevenLabs API key was recognized, "
                    "but it lacks permission to read "
                    "subscription/quota information. "
                    "Credit sufficiency cannot be "
                    f"verified: {exc}"
                ),
                {
                    "authentication":
                        "recognized",

                    "quota_visibility":
                        "permission_required",

                    "required_credits_estimate":
                        required_credits,
                },
            )

        return ServiceCheck(
            "elevenlabs",
            BLOCK,
            (
                "ElevenLabs subscription/quota "
                f"check failed: {exc}"
            ),
            {
                "quota_visibility":
                    "unavailable",

                "required_credits_estimate":
                    required_credits,
            },
        )

    used = float(
        subscription.get(
            "character_count",
            0,
        )
        or 0
    )
    limit = float(
        subscription.get(
            "character_limit",
            0,
        )
        or 0
    )

    included_remaining = max(
        0.0,
        limit - used,
    )

    extension = subscription.get(
        "max_credit_limit_extension"
    )

    extension_remaining: float | None

    if extension == "unlimited":
        extension_remaining = None
    else:
        try:
            extension_value = float(
                extension or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            extension_value = 0.0

        extension_remaining = max(
            0.0,
            limit
            + extension_value
            - used,
        )

    visible_available = (
        extension_remaining
        if extension_remaining is not None
        else included_remaining
    )

    details: dict[str, Any] = {
        "tier":
            subscription.get("tier"),
        "subscription_status":
            subscription.get("status"),
        "used_credits":
            used,
        "included_credit_limit":
            limit,
        "included_remaining_credits":
            included_remaining,
        "max_credit_limit_extension":
            extension,
        "visible_available_credits":
            visible_available,
        "required_credits_estimate":
            required_credits,
        "payg_balance_known":
            False,
    }

    if required_credits is None:
        if (
            extension == "unlimited"
            or visible_available > 0
        ):
            return ServiceCheck(
                "elevenlabs",
                PASS,
                (
                    "ElevenLabs account is "
                    "reachable and has visible "
                    "quota available."
                ),
                details,
            )

        return ServiceCheck(
            "elevenlabs",
            WARN,
            (
                "ElevenLabs visible quota is "
                "exhausted. PAYG balance is not "
                "exposed by this endpoint."
            ),
            details,
        )

    if extension == "unlimited":
        return ServiceCheck(
            "elevenlabs",
            PASS,
            (
                "ElevenLabs extension is unlimited; "
                f"estimated requirement is "
                f"{required_credits:.0f} credits."
            ),
            details,
        )

    if visible_available >= required_credits:
        return ServiceCheck(
            "elevenlabs",
            PASS,
            (
                "ElevenLabs visible quota covers "
                "the estimated audio requirement: "
                f"{required_credits:.0f} needed, "
                f"{visible_available:.0f} visible."
            ),
            details,
        )

    assume_no_payg = (
        os.getenv(
            "ELEVENLABS_PREFLIGHT_ASSUME_NO_PAYG",
            "0",
        )
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )

    return ServiceCheck(
        "elevenlabs",
        BLOCK if assume_no_payg else WARN,
        (
            "ElevenLabs visible quota does not "
            "cover the estimated audio requirement: "
            f"{required_credits:.0f} needed, "
            f"{visible_available:.0f} visible. "
            "PAYG balance cannot be verified."
        ),
        details,
    )


def runway_credits_per_second(
    model: str,
) -> float | None:
    override = os.getenv(
        "RUNWAY_PREFLIGHT_CREDITS_PER_SECOND"
    )

    if override:
        return float(override)

    return (
        RUNWAY_DEFAULT_CREDITS_PER_SECOND
        .get(model)
    )


def runway_pending_scene_durations(
    job: dict,
) -> list[float]:
    visual_by_id = {
        scene.get("scene_id"):
            scene
        for scene in (
            job.get(
                "visuals",
                {},
            ).get(
                "scenes",
                [],
            )
        )
    }

    durations: list[float] = []

    for script_scene in (
        job.get(
            "script",
            {},
        ).get(
            "scenes",
            [],
        )
    ):
        scene_id = script_scene.get(
            "scene_id"
        )
        timing = script_scene.get(
            "timing",
            {},
        )

        if timing.get("status") != "passed":
            continue

        render_duration = timing.get(
            "render_duration_sec"
        )

        if render_duration is None:
            continue

        visual_scene = visual_by_id.get(
            scene_id,
            {},
        )
        video = visual_scene.get(
            "video",
            {},
        )

        video_ready = (
            video.get("provider")
            == "runway"
            and video.get("status")
            in {
                "generated",
                "completed",
                "passed",
            }
            and video.get(
                "semantic_qc",
                {},
            ).get(
                "status"
            )
            != "failed"
        )

        if video_ready:
            continue

        durations.append(
            float(
                math.ceil(
                    float(render_duration)
                    - 1e-9
                )
            )
        )

    return durations


def estimate_runway_budget(
    *,
    job: dict,
    model: str,
    max_video_attempts: int,
) -> dict[str, Any]:
    durations = (
        runway_pending_scene_durations(
            job
        )
    )
    rate = runway_credits_per_second(
        model
    )

    if rate is None:
        return {
            "model": model,
            "pending_scenes":
                len(durations),
            "rate_known": False,
        }

    base_credits = sum(
        duration * rate
        for duration in durations
    )
    attempts = max(
        1,
        int(max_video_attempts),
    )

    return {
        "model": model,
        "pending_scenes":
            len(durations),
        "provider_durations_sec":
            durations,
        "credits_per_second":
            rate,
        "base_required_credits":
            base_credits,
        "worst_case_required_credits":
            base_credits * attempts,
        "base_required_generations":
            len(durations),
        "worst_case_required_generations":
            len(durations) * attempts,
        "max_video_attempts":
            attempts,
        "rate_known": True,
    }


def evaluate_runway_capacity(
    *,
    balance: float,
    budget: dict[str, Any],
    remaining_daily: int | None,
) -> tuple[str, str]:
    if balance <= 0:
        return (
            BLOCK,
            "Runway credit balance is zero.",
        )

    if not budget.get("rate_known"):
        return (
            WARN,
            "Runway model credit rate is unknown.",
        )

    base_required = float(
        budget[
            "base_required_credits"
        ]
    )
    worst_required = float(
        budget[
            "worst_case_required_credits"
        ]
    )

    if balance < base_required:
        return (
            BLOCK,
            (
                "Runway credits are insufficient "
                "for one generation of each "
                "pending scene."
            ),
        )

    if (
        remaining_daily is not None
        and remaining_daily
        < budget[
            "base_required_generations"
        ]
    ):
        return (
            BLOCK,
            (
                "Runway daily generation limit "
                "cannot cover one attempt for "
                "each pending scene."
            ),
        )

    if (
        balance < worst_required
        or (
            remaining_daily is not None
            and remaining_daily
            < budget[
                "worst_case_required_generations"
            ]
        )
    ):
        return (
            WARN,
            (
                "Runway can cover one attempt per "
                "pending scene but not the configured "
                "worst-case retry budget."
            ),
        )

    return (
        PASS,
        (
            "Runway balance and daily limits cover "
            "the configured worst-case retry budget."
        ),
    )


def check_runway(
    *,
    model: str,
    budget: dict[str, Any] | None = None,
) -> ServiceCheck:
    if not os.getenv(
        "RUNWAYML_API_SECRET"
    ):
        return ServiceCheck(
            "runway",
            BLOCK,
            "RUNWAYML_API_SECRET is missing.",
            {},
        )

    try:
        organization = (
            RunwayML()
            .organization
            .retrieve()
        )
    except Exception as exc:
        return ServiceCheck(
            "runway",
            BLOCK,
            (
                "Runway organization/credit "
                f"check failed: {exc}"
            ),
            {},
        )

    balance = float(
        organization.credit_balance
    )
    details: dict[str, Any] = {
        "credit_balance": balance,
        "model": model,
    }

    tier_model = (
        organization
        .tier
        .models
        .get(model)
    )
    usage_model = (
        organization
        .usage
        .models
        .get(model)
    )

    remaining_daily: int | None = None

    if tier_model is not None:
        used_daily = (
            usage_model.daily_generations
            if usage_model is not None
            else 0
        )

        remaining_daily = max(
            0,
            tier_model.max_daily_generations
            - used_daily,
        )

        details.update(
            {
                "max_daily_generations":
                    tier_model
                    .max_daily_generations,
                "daily_generations_used":
                    used_daily,
                "daily_generations_remaining":
                    remaining_daily,
                "max_concurrent_generations":
                    tier_model
                    .max_concurrent_generations,
            }
        )

    if budget is None:
        status = (
            PASS
            if balance > 0
            else BLOCK
        )
        message = (
            (
                "Runway organization is reachable "
                f"with {balance:.0f} credits remaining."
            )
            if balance > 0
            else (
                "Runway credit balance is zero; "
                "billable video generation should "
                "not start."
            )
        )

        return ServiceCheck(
            "runway",
            status,
            message,
            details,
        )

    details.update(budget)

    status, message = (
        evaluate_runway_capacity(
            balance=balance,
            budget=budget,
            remaining_daily=
                remaining_daily,
        )
    )

    if (
        status == BLOCK
        and budget.get("rate_known")
    ):
        message += (
            " Required base: "
            f"{budget['base_required_credits']:.0f} "
            f"credits; available: {balance:.0f}."
        )

    return ServiceCheck(
        "runway",
        status,
        message,
        details,
    )


def estimate_elevenlabs_audio_credits(
    job: dict,
) -> dict[str, Any]:
    music_rate = float(
        os.getenv(
            "ELEVENLABS_MUSIC_CREDITS_PER_MINUTE",
            "900",
        )
    )
    sfx_rate = float(
        os.getenv(
            "ELEVENLABS_SFX_CREDITS_PER_SECOND",
            "40",
        )
    )

    total_duration_sec = 0.0

    for scene in (
        job.get(
            "script",
            {},
        ).get(
            "scenes",
            [],
        )
    ):
        duration = scene.get(
            "timing",
            {},
        ).get(
            "render_duration_sec"
        )

        if duration is not None:
            total_duration_sec += float(
                duration
            )

    audio = job.get("audio", {})
    music_required = bool(
        audio.get(
            "background_music",
            {},
        ).get(
            "required",
            False,
        )
    )

    music_credits = (
        total_duration_sec
        / 60.0
        * music_rate
        if music_required
        else 0.0
    )

    sfx_seconds = 0.0

    if audio.get(
        "sound_effects",
        {},
    ).get(
        "enabled",
        False,
    ):
        for effect in (
            audio.get(
                "sound_effects",
                {},
            ).get(
                "effects",
                [],
            )
        ):
            sfx_seconds += float(
                effect.get(
                    "duration_sec",
                    0.0,
                )
                or 0.0
            )

    sfx_credits = (
        sfx_seconds * sfx_rate
    )

    return {
        "music_duration_sec":
            total_duration_sec
            if music_required
            else 0.0,
        "music_credits_per_minute":
            music_rate,
        "estimated_music_credits":
            music_credits,
        "sfx_duration_sec":
            sfx_seconds,
        "sfx_credits_per_second":
            sfx_rate,
        "estimated_sfx_credits":
            sfx_credits,
        "estimated_total_credits":
            music_credits
            + sfx_credits,
    }


def print_checks(
    title: str,
    checks: list[ServiceCheck],
) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)

    for check in checks:
        print(
            f"[{check.status}] "
            f"{check.service}: "
            f"{check.message}"
        )

        for key, value in (
            check.details.items()
        ):
            print(
                f"    {key}: {value}"
            )


def blocking(
    checks: list[ServiceCheck],
) -> list[ServiceCheck]:
    return [
        check
        for check in checks
        if check.status == BLOCK
    ]


def startup_checks(
    *,
    video_provider: str,
    runway_model: str,
) -> list[ServiceCheck]:
    if not enabled():
        return []

    checks = [
        check_openai(),
        check_elevenlabs(),
    ]

    if video_provider == "runway":
        checks.append(
            check_runway(
                model=runway_model,
            )
        )

    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check external VideoFactory provider "
            "authentication, quota, and optional "
            "active-job budgets without generating media."
        )
    )

    parser.add_argument(
        "--job-budget",
        action="store_true",
        help=(
            "Also estimate provider capacity for "
            "jobs/video_job.json."
        ),
    )

    parser.add_argument(
        "--max-video-attempts",
        type=int,
        default=4,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not enabled():
        print(
            "Service preflight is disabled."
        )
        return 0

    provider = os.getenv(
        "VIDEO_PROVIDER",
        "local_ltx",
    ).strip().lower()

    runway_model = os.getenv(
        "RUNWAY_VIDEO_MODEL",
        "gen4_turbo",
    )

    checks = startup_checks(
        video_provider=provider,
        runway_model=runway_model,
    )

    print_checks(
        "SERVICE ACCOUNT / QUOTA PREFLIGHT",
        checks,
    )

    all_checks = list(
        checks
    )

    if args.job_budget:
        job_file = (
            Path(__file__)
            .resolve()
            .parent
            .parent
            / "jobs"
            / "video_job.json"
        )

        if not job_file.exists():
            print(
                "\nNo active jobs/video_job.json; "
                "stage budget checks skipped."
            )
        else:
            job = load_json(
                job_file
            )

            if provider == "runway":
                runway_budget = (
                    estimate_runway_budget(
                        job=job,
                        model=runway_model,
                        max_video_attempts=
                            args.max_video_attempts,
                    )
                )

                runway_check = check_runway(
                    model=runway_model,
                    budget=runway_budget,
                )

                print_checks(
                    "RUNWAY SCENE BUDGET PREFLIGHT",
                    [
                        runway_check,
                    ],
                )

                all_checks.append(
                    runway_check
                )

            audio_estimate = (
                estimate_elevenlabs_audio_credits(
                    job
                )
            )

            audio_check = check_elevenlabs(
                required_credits=float(
                    audio_estimate.get(
                        "estimated_total_credits",
                        0.0,
                    )
                )
            )

            audio_check = ServiceCheck(
                service=audio_check.service,
                status=audio_check.status,
                message=audio_check.message,
                details={
                    **audio_check.details,
                    **audio_estimate,
                },
            )

            print_checks(
                "ELEVENLABS AUDIO BUDGET PREFLIGHT",
                [
                    audio_check,
                ],
            )

            all_checks.append(
                audio_check
            )

    blockers = blocking(
        all_checks
    )

    if blockers:
        print(
            "\nPREFLIGHT RESULT: BLOCK"
        )
        return 1

    print(
        "\nPREFLIGHT RESULT: CONTINUE"
    )

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
