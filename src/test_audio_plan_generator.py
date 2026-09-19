import unittest

from audio_plan_generator import (
    AudioPlanOutput,
    SoundEffectPlan,
    apply_audio_plan,
    validate_audio_plan,
)


class AudioPlanGeneratorTests(
    unittest.TestCase
):

    def make_job(
        self,
    ) -> dict:

        return {
            "script": {
                "scenes": [
                    {
                        "scene_id":
                            1,

                        "timing": {
                            "render_duration_sec":
                                3.0,
                        },
                    },
                    {
                        "scene_id":
                            2,

                        "timing": {
                            "render_duration_sec":
                                6.5,
                        },
                    },
                ],
            },

            "audio": {
                "background_music": {
                    "required":
                        True,

                    "audio_file":
                        "old.mp3",
                },

                "sound_effects": {
                    "enabled":
                        True,

                    "effects":
                        [],
                },

                "assets": {
                    "status":
                        "passed",
                },

                "mix": {
                    "status":
                        "passed",
                },
            },

            "output": {
                "mixed_video_file":
                    "old.mp4",

                "video_file":
                    "final.mp4",
            },

            "final_qc": {
                "status":
                    "passed",
            },
        }


    def test_valid_plan_accepts_scene_relative_effect(
        self,
    ):

        job = self.make_job()

        plan = AudioPlanOutput(
            background_music_style="playful acoustic comedy",
            effects=[
                SoundEffectPlan(
                    scene_id=2,
                    effect="soft puppy lick",
                    offset_sec=1.0,
                    duration_sec=1.0,
                    volume=0.5,
                ),
            ],
        )

        self.assertEqual(
            validate_audio_plan(
                job,
                plan,
            ),
            [],
        )


    def test_invalid_scene_is_rejected(
        self,
    ):

        job = self.make_job()

        plan = AudioPlanOutput(
            background_music_style="playful",
            effects=[
                SoundEffectPlan(
                    scene_id=9,
                    effect="meow",
                    offset_sec=0.0,
                    duration_sec=1.0,
                    volume=0.5,
                ),
            ],
        )

        errors = validate_audio_plan(
            job,
            plan,
        )

        self.assertTrue(
            any(
                "invalid scene_id"
                in error
                for error in errors
            )
        )


    def test_apply_plan_invalidates_old_assets_and_mix(
        self,
    ):

        job = self.make_job()

        plan = AudioPlanOutput(
            background_music_style="soft playful pizzicato",
            effects=[],
        )

        apply_audio_plan(
            job,
            plan,
        )

        self.assertEqual(
            job[
                "audio"
            ][
                "plan"
            ][
                "status"
            ],
            "passed",
        )

        self.assertNotIn(
            "assets",
            job[
                "audio"
            ],
        )

        self.assertNotIn(
            "mix",
            job[
                "audio"
            ],
        )

        self.assertIsNone(
            job[
                "audio"
            ][
                "background_music"
            ][
                "audio_file"
            ]
        )

        self.assertNotIn(
            "final_qc",
            job,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
