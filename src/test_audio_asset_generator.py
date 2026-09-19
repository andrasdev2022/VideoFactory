import tempfile
import unittest

from pathlib import Path

import audio_asset_generator

from audio_asset_generator import (
    build_music_prompt,
    build_music_request,
    build_sfx_prompt,
    build_sfx_request,
    existing_generation_matches,
    generate_sfx,
    get_scene_ids,
    get_total_duration_ms,
    sanitize_slug,
)


class AudioAssetGeneratorTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_root = (
            audio_asset_generator
            .PROJECT_ROOT
        )


    def tearDown(
        self,
    ):

        audio_asset_generator.PROJECT_ROOT = (
            self.old_root
        )


    def test_total_duration_uses_assembly_actual(
        self,
    ):

        job = {
            "assembly": {
                "actual": {
                    "duration_sec":
                        30.767,
                },
            },
        }

        timeline = [
            {
                "scene_id":
                    1,

                "end_sec":
                    30.75,
            },
        ]

        self.assertEqual(
            get_total_duration_ms(
                job,
                timeline,
            ),
            30767,
        )


    def test_scene_ids_come_from_final_timeline(
        self,
    ):

        self.assertEqual(
            get_scene_ids(
                [
                    {
                        "scene_id":
                            1,
                    },
                    {
                        "scene_id":
                            5,
                    },
                ]
            ),
            {
                1,
                5,
            },
        )


    def test_music_prompt_is_instrumental_and_voice_friendly(
        self,
    ):

        job = {
            "idea": {
                "genre":
                    "absurd_comedy",

                "concept":
                    "A cat becomes CEO.",
            },

            "audio": {
                "background_music": {
                    "style":
                        "quirky cinematic comedy",
                },
            },
        }

        prompt = build_music_prompt(
            job,
            30000,
        )

        self.assertIn(
            "instrumental",
            prompt.lower(),
        )

        self.assertIn(
            "no vocals",
            prompt.lower(),
        )

        self.assertIn(
            "spoken narration",
            prompt.lower(),
        )


    def test_music_request_uses_current_model_and_duration(
        self,
    ):

        url, body = build_music_request(
            "test prompt",
            30767,
        )

        self.assertIn(
            "/v1/music?",
            url,
        )

        self.assertIn(
            "output_format=",
            url,
        )

        self.assertEqual(
            body[
                "music_length_ms"
            ],
            30767,
        )

        self.assertEqual(
            body[
                "model_id"
            ],
            audio_asset_generator.MUSIC_MODEL,
        )

        self.assertTrue(
            body[
                "force_instrumental"
            ]
        )


    def test_sfx_request_clamps_duration_and_uses_v2_model(
        self,
    ):

        url, body = build_sfx_request(
            "door slam",
            0.1,
        )

        self.assertIn(
            "/v1/sound-generation?",
            url,
        )

        self.assertEqual(
            body[
                "duration_seconds"
            ],
            0.5,
        )

        self.assertEqual(
            body[
                "model_id"
            ],
            audio_asset_generator.SFX_MODEL,
        )

        self.assertFalse(
            body[
                "loop"
            ]
        )


    def test_sfx_prompt_has_no_music_or_speech(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id":
                            3,

                        "voice": {
                            "input_text":
                                "The cat knocks over the coffee.",
                        },
                    },
                ],
            },

            "visuals": {
                "scenes": [
                    {
                        "scene_id":
                            3,

                        "motion_prompt":
                            "The cup tips and falls.",
                    },
                ],
            },
        }

        prompt = build_sfx_prompt(
            job,
            {
                "effect":
                    "coffee cup impact",
            },
            3,
        )

        self.assertIn(
            "coffee cup impact",
            prompt,
        )

        self.assertIn(
            "No speech",
            prompt,
        )

        self.assertIn(
            "no music bed",
            prompt,
        )


    def test_sanitize_slug(
        self,
    ):

        self.assertEqual(
            sanitize_slug(
                "Office Door Slam!"
            ),
            "office_door_slam",
        )


    def test_existing_generation_requires_signature_and_file(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            path = (
                Path(
                    directory
                )
                / "asset.mp3"
            )

            path.write_bytes(
                b"audio"
            )

            signature = {
                "model":
                    "x",
            }

            self.assertTrue(
                existing_generation_matches(
                    {
                        "status":
                            "passed",

                        "source_signature":
                            signature,
                    },
                    signature,
                    path,
                )
            )

            self.assertFalse(
                existing_generation_matches(
                    {
                        "status":
                            "passed",

                        "source_signature": {
                            "model":
                                "old",
                        },
                    },
                    signature,
                    path,
                )
            )


    def test_stale_scene_sfx_is_skipped_without_api_call(
        self,
    ):

        job = {
            "audio": {
                "sound_effects": {
                    "enabled":
                        True,

                    "effects": [
                        {
                            "scene_id":
                                6,

                            "effect":
                                "notification sound",
                        },
                    ],
                },
            },
        }

        generated, skipped, warnings = (
            generate_sfx(
                job=job,
                timeline=[
                    {
                        "scene_id":
                            5,
                    },
                ],
                force=False,
                api_key="unused",
            )
        )

        self.assertEqual(
            generated,
            0,
        )

        self.assertEqual(
            skipped,
            1,
        )

        self.assertTrue(
            any(
                "not in the final assembly timeline"
                in warning
                for warning in warnings
            )
        )

        self.assertEqual(
            job[
                "audio"
            ][
                "sound_effects"
            ][
                "effects"
            ][0][
                "generation"
            ][
                "status"
            ],
            "skipped",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
