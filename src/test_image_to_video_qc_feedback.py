import unittest

from image_to_video_generator import (
    build_qc_correction,
    compact_qc_observation,
)


class ImageToVideoQCFeedbackTests(
    unittest.TestCase
):

    def test_compact_qc_observation_prefers_problem_clause(
        self,
    ):

        value = (
            "The shot is stable and coherent. "
            "However, Miso looks toward Biscuit instead of "
            "holding the requested deadpan camera stare."
        )

        result = compact_qc_observation(
            value
        )

        self.assertTrue(
            result.startswith(
                "However"
            )
        )

        self.assertIn(
            "deadpan camera stare",
            result,
        )


    def test_qc_correction_includes_specific_semantic_notes(
        self,
    ):

        job = {
            "characters": [
                {
                    "character_id":
                        "char-001",

                    "name":
                        "Biscuit",
                },
            ],
        }

        scene = {
            "video": {
                "semantic_qc": {
                    "status":
                        "failed",

                    "motion_matches_prompt":
                        False,

                    "temporal_progression_coherent":
                        True,

                    "source_frame_continuity_ok":
                        True,

                    "morphing_or_shape_drift":
                        False,

                    "unexpected_scene_cut":
                        False,

                    "characters": [
                        {
                            "character_id":
                                "char-001",

                            "present_throughout":
                                True,

                            "identity_stable":
                                True,

                            "appearance_stable":
                                True,

                            "clothing_stable":
                                True,
                        },
                    ],

                    "overall_notes":
                        (
                            "The shot is coherent. However, Biscuit "
                            "drops the card instead of holding it."
                        ),
                },
            },
        }

        correction = build_qc_correction(
            job,
            scene,
        )

        self.assertIn(
            "Follow the requested motion exactly.",
            correction,
        )

        self.assertIn(
            "Previous QC observation:",
            correction,
        )

        self.assertIn(
            "drops the card",
            correction,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
