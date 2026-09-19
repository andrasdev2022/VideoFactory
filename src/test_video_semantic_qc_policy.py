import unittest

from video_semantic_qc import (
    CharacterVideoQC,
    VideoSemanticQCOutput,
    evaluate_result,
)


def make_result(
    *,
    present=True,
    motion=True,
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
