import unittest

import image_to_video_generator as video_generator

from local_ltx_worker import (
    fit_prompt_to_token_budget,
)


class FakeTokenizer:

    def __init__(
        self,
    ):

        self.words = []


    def encode(
        self,
        text,
        add_special_tokens=False,
    ):

        self.words = text.split()

        return list(
            range(
                len(
                    self.words
                )
            )
        )


    def decode(
        self,
        token_ids,
        skip_special_tokens=True,
    ):

        return " ".join(
            self.words[
                index
            ]
            for index in token_ids
        )


class LocalLTXPromptBudgetTests(
    unittest.TestCase
):

    def test_prompt_is_compacted_before_diffusers_limit(
        self,
    ):

        tokenizer = FakeTokenizer()

        prompt = " ".join(
            f"word{index}"
            for index in range(
                200
            )
        )

        (
            fitted,
            original_count,
            used_count,
        ) = fit_prompt_to_token_budget(
            prompt,
            tokenizer,
            max_tokens=120,
        )

        self.assertEqual(
            original_count,
            200,
        )

        self.assertEqual(
            used_count,
            120,
        )

        self.assertEqual(
            len(
                fitted.split()
            ),
            120,
        )


    def test_short_prompt_is_unchanged(
        self,
    ):

        tokenizer = FakeTokenizer()

        (
            fitted,
            original_count,
            used_count,
        ) = fit_prompt_to_token_budget(
            "small controlled motion",
            tokenizer,
            max_tokens=120,
        )

        self.assertEqual(
            fitted,
            "small controlled motion",
        )

        self.assertEqual(
            original_count,
            3,
        )

        self.assertEqual(
            used_count,
            3,
        )


    def test_local_ltx_retry_prioritizes_continuity_and_omits_observation(
        self,
    ):

        job = {
            "characters": [
                {
                    "character_id":
                        "char-001",

                    "name":
                        "Pip",
                },
            ],
        }

        scene = {
            "motion_prompt":
                "Pip gently pushes the cart forward.",

            "continuity_notes":
                "Keep Pip's teal robe and gold turban unchanged.",

            "video": {
                "semantic_qc": {
                    "status":
                        "failed",

                    "motion_matches_prompt":
                        False,

                    "characters": [],

                    "overall_notes":
                        (
                            "This is deliberately verbose QC observation "
                            "text that should not be repeated into the "
                            "Local LTX retry prompt."
                        ),
                },
            },
        }

        previous_provider = (
            video_generator
            .VIDEO_PROVIDER
        )

        try:

            video_generator.VIDEO_PROVIDER = (
                "local_ltx"
            )

            prompt = (
                video_generator
                .build_video_prompt(
                    job,
                    scene,
                    use_qc_feedback=True,
                )
            )

        finally:

            video_generator.VIDEO_PROVIDER = (
                previous_provider
            )

        self.assertIn(
            "Keep Pip's teal robe and gold turban unchanged.",
            prompt,
        )

        self.assertIn(
            "Follow the requested motion exactly.",
            prompt,
        )

        self.assertNotIn(
            "Previous QC observation:",
            prompt,
        )

        self.assertLess(
            prompt.index(
                "Continuity:"
            ),
            prompt.index(
                "Correction from previous attempt:"
            ),
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
