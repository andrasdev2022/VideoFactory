import unittest

from new_job import (
    BootstrapOutput,
    CharacterBlueprint,
    IdeaBlueprint,
    MetadataBlueprint,
    StyleBlueprint,
    build_job,
    sanitize_hashtags,
)


class NewJobTests(
    unittest.TestCase
):

    def make_output(
        self,
    ) -> BootstrapOutput:

        return BootstrapOutput(
            idea=IdeaBlueprint(
                title="Puppy Meets Kitten",
                concept=(
                    "A puppy licks a kitten's face and "
                    "the kitten delivers a dry punchline."
                ),
                genre="cute_comedy",
                target_audience="general",
                hook="The puppy has one very affectionate idea.",
                core_joke="The kitten reacts like a tiny annoyed adult.",
                ending="The kitten asks for personal space.",
            ),
            characters=[
                CharacterBlueprint(
                    name="Pip",
                    role="main_character",
                    description="A tiny golden retriever puppy.",
                    personality="sweet, enthusiastic",
                ),
                CharacterBlueprint(
                    name="Mochi",
                    role="main_character",
                    description="A tiny gray-and-white kitten.",
                    personality="cute, dry, unimpressed",
                ),
            ],
            style=StyleBlueprint(
                visual="soft colorful cute comedy",
                cinematic=True,
                realistic=False,
                lighting="warm soft daylight",
                camera="gentle close-ups",
                color_palette="warm pastel colors",
            ),
            metadata=MetadataBlueprint(
                title="Puppy vs Kitten Personal Space",
                description="A very affectionate puppy meets a tiny critic.",
                hashtags=[
                    "cute",
                    "#puppy",
                    "#kitten",
                ],
                thumbnail_text="TOO MANY KISSES",
            ),
            background_music_style="light playful pizzicato comedy",
        )


    def make_spec(
        self,
    ) -> dict:

        return {
            "version":
                "1.0",

            "video": {
                "language":
                    "en",

                "resolution":
                    "1080x1920",

                "fps":
                    30,
            },

            "subtitles": {
                "max_lines":
                    2,

                "max_chars_per_line":
                    32,
            },

            "output": {
                "video_format":
                    "mp4",

                "video_codec":
                    "h264",

                "audio_codec":
                    "aac",
            },

            "platforms": {
                "youtube_shorts": {
                    "enabled":
                        True,
                },

                "tiktok": {
                    "enabled":
                        True,
                },
            },
        }


    def test_hashtags_are_normalized_and_minimum_is_filled(
        self,
    ):

        result = sanitize_hashtags(
            [
                "cute animals",
            ]
        )

        self.assertGreaterEqual(
            len(
                result
            ),
            3,
        )

        self.assertTrue(
            all(
                value.startswith(
                    "#"
                )
                for value in result
            )
        )

        self.assertIn(
            "#cuteanimals",
            result,
        )


    def test_build_job_assigns_stable_character_ids(
        self,
    ):

        job = build_job(
            self.make_output(),
            self.make_spec(),
            "20260919-test",
        )

        self.assertEqual(
            [
                character[
                    "character_id"
                ]
                for character
                in job[
                    "characters"
                ]
            ],
            [
                "char-001",
                "char-002",
            ],
        )

        self.assertEqual(
            job[
                "script"
            ],
            {},
        )

        self.assertEqual(
            job[
                "visuals"
            ][
                "scenes"
            ],
            [],
        )

        self.assertTrue(
            job[
                "audio"
            ][
                "background_music"
            ][
                "required"
            ]
        )

        self.assertEqual(
            job[
                "audio"
            ][
                "sound_effects"
            ][
                "effects"
            ],
            [],
        )

        self.assertEqual(
            job[
                "output"
            ][
                "directory"
            ],
            "output/20260919-test/",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
