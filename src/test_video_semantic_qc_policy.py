import unittest

from video_semantic_qc import (
    CharacterVideoQC,
    VideoSemanticQCOutput,
    evaluate_result,
    get_evaluation_duration,
)


def make_result(
    *,
    present=True,
    motion=True,
    instances=1,
):

    return VideoSemanticQCOutput(
        motion_matches_prompt=
            motion,

        temporal_progression_coherent=
            True,

        source_frame_continuity_ok=
            True,

        anatomy_ok=
            True,

        morphing_or_shape_drift=
            False,

        unexpected_scene_cut=
            False,

        unwanted_text_or_logo=
            False,

        extra_main_characters=
            False,

        character_checks=[
            CharacterVideoQC(
                character_id=
                    "char-001",

                present_throughout=
                    present,

                max_visible_instances=
                    instances,

                identity_stable=
                    True,

                appearance_stable=
                    True,

                clothing_stable=
                    True,

                confidence=
                    0.98,

                notes=
                    "Stable before approved exit.",
            ),
        ],

        problematic_sample_indices=
            (
                [
                    5,
                ]
                if not present
                else []
            ),

        overall_notes=
            "Continuous coherent shot.",
    )


class VideoSemanticQCPolicyTests(
    unittest.TestCase
):

    def test_evaluation_duration_uses_final_trim_window(
        self,
    ):

        scene = {
            "video": {
                "target_render_duration_sec":
                    7.1,

                "qc": {
                    "actual": {
                        "duration_sec":
                            8.083,
                    },
                },
            },
        }

        self.assertEqual(
            get_evaluation_duration(
                scene
            ),
            7.1,
        )


    def test_evaluation_duration_falls_back_to_raw_duration(
        self,
    ):

        scene = {
            "video": {
                "qc": {
                    "actual": {
                        "duration_sec":
                            8.083,
                    },
                },
            },
        }

        self.assertEqual(
            get_evaluation_duration(
                scene
            ),
            8.083,
        )


    def test_missing_character_fails_without_exit_policy(
        self,
    ):

        scene = {
            "characters": [
                "char-001",
            ],
        }

        passed, errors, warnings = (
            evaluate_result(
                scene,
                make_result(
                    present=False,
                ),
            )
        )

        self.assertFalse(
            passed
        )

        self.assertTrue(
            any(
                "not consistently present"
                in error
                for error in errors
            )
        )


    def test_approved_exit_downgrades_presence_to_warning(
        self,
    ):

        scene = {
            "characters": [
                "char-001",
            ],

            "semantic_qc_policy": {
                "version":
                    "safe_fallback_v2",

                "allowed_exit_character_ids": [
                    "char-001",
                ],
            },
        }

        passed, errors, warnings = (
            evaluate_result(
                scene,
                make_result(
                    present=False,
                ),
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )

        self.assertTrue(
            any(
                "approved scene-exit policy"
                in warning
                for warning in warnings
            )
        )


    def test_duplicate_expected_character_always_fails(
        self,
    ):

        scene = {
            "characters": [
                "char-001",
            ],
        }

        passed, errors, warnings = (
            evaluate_result(
                scene,
                make_result(
                    instances=2,
                ),
            )
        )

        self.assertFalse(
            passed
        )

        self.assertTrue(
            any(
                "duplicated main character"
                in error
                for error in errors
            )
        )


    def test_exit_policy_does_not_hide_motion_failure(
        self,
    ):

        scene = {
            "characters": [
                "char-001",
            ],

            "semantic_qc_policy": {
                "version":
                    "safe_fallback_v2",

                "allowed_exit_character_ids": [
                    "char-001",
                ],
            },
        }

        passed, errors, warnings = (
            evaluate_result(
                scene,
                make_result(
                    present=False,
                    motion=False,
                ),
            )
        )

        self.assertFalse(
            passed
        )

        self.assertTrue(
            any(
                "motion"
                in error.lower()
                for error in errors
            )
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
