import unittest

import script_timing_rewriter

from script_timing_rewriter import (
    TimingRewriteOutput,
    apply_rewrite,
    calculate_rewrite_budget,
    validate_rewrite,
)


class ScriptTimingRewriterTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_safety = (
            script_timing_rewriter
            .VOICE_SAFETY_SEC
        )

        script_timing_rewriter.VOICE_SAFETY_SEC = (
            0.35
        )


    def tearDown(
        self,
    ):

        script_timing_rewriter.VOICE_SAFETY_SEC = (
            self.old_safety
        )


    def make_scene(
        self,
    ):

        return {

            "scene_id":
                4,

            "voiceover":
                (
                    "This is a deliberately long voiceover "
                    "with many unnecessary words that should "
                    "be shortened significantly for timing."
                ),

            "timing": {

                "status":
                    "failed",

                "voice_duration_sec":
                    12.3,

                "headroom_sec":
                    0.3,

                "max_video_duration_sec":
                    10.0,

                "script_revision_required":
                    True,
            },
        }


    def test_budget_is_shorter_than_original(
        self,
    ):

        scene = self.make_scene()

        original = scene[
            "voiceover"
        ]

        budget = calculate_rewrite_budget(
            scene,
            original,
        )

        self.assertLess(
            budget[
                "max_words"
            ],
            budget[
                "current_words"
            ],
        )

        self.assertLess(
            budget[
                "max_chars"
            ],
            budget[
                "current_chars"
            ],
        )


    def test_target_is_below_maximum_voice_duration(
        self,
    ):

        scene = self.make_scene()

        budget = calculate_rewrite_budget(
            scene,
            scene[
                "voiceover"
            ],
        )

        self.assertLess(
            budget[
                "target_voice_duration_sec"
            ],
            budget[
                "maximum_voice_duration_sec"
            ],
        )


    def test_valid_short_rewrite_passes(
        self,
    ):

        scene = self.make_scene()

        original = scene[
            "voiceover"
        ]

        budget = calculate_rewrite_budget(
            scene,
            original,
        )

        output = TimingRewriteOutput(
            scene_id=4,
            voiceover=(
                "This long voiceover must be "
                "shortened for timing."
            ),
        )

        errors = validate_rewrite(
            scene_id=4,
            original_text=original,
            budget=budget,
            output=output,
        )

        self.assertEqual(
            errors,
            [],
        )


    def test_unchanged_rewrite_fails(
        self,
    ):

        scene = self.make_scene()

        original = scene[
            "voiceover"
        ]

        budget = calculate_rewrite_budget(
            scene,
            original,
        )

        output = TimingRewriteOutput(
            scene_id=4,
            voiceover=original,
        )

        errors = validate_rewrite(
            scene_id=4,
            original_text=original,
            budget=budget,
            output=output,
        )

        self.assertTrue(
            errors
        )


    def test_apply_invalidates_voice_timing_and_video(
        self,
    ):

        scene = self.make_scene()

        scene[
            "voice"
        ] = {
            "status":
                "generated",
        }

        job = {

            "script": {
                "scenes": [
                    scene
                ],
            },

            "visuals": {
                "scenes": [
                    {
                        "scene_id":
                            4,

                        "image": {
                            "status":
                                "generated",
                        },

                        "video": {
                            "status":
                                "generated",
                        },
                    },
                ],
            },
        }

        original = scene[
            "voiceover"
        ]

        budget = calculate_rewrite_budget(
            scene,
            original,
        )

        output = TimingRewriteOutput(
            scene_id=4,
            voiceover=(
                "This voiceover is shorter "
                "and fits naturally."
            ),
        )

        apply_rewrite(
            job=job,
            scene_id=4,
            source_field=
                "voiceover",
            original_text=
                original,
            output=output,
            budget=budget,
        )

        updated_scene = (
            job[
                "script"
            ][
                "scenes"
            ][0]
        )

        visual = (
            job[
                "visuals"
            ][
                "scenes"
            ][0]
        )

        self.assertNotIn(
            "voice",
            updated_scene,
        )

        self.assertNotIn(
            "timing",
            updated_scene,
        )

        self.assertNotIn(
            "video",
            visual,
        )

        self.assertIn(
            "image",
            visual,
        )

        self.assertEqual(
            len(
                updated_scene[
                    "timing_revisions"
                ]
            ),
            1,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )