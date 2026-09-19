import unittest

from voice_generator import (
    build_voice_instructions,
    extract_scene_voice_text,
    normalize_spoken_value,
    validate_voice_text,
)


class VoiceGeneratorTests(
    unittest.TestCase
):

    def test_string_normalization(
        self,
    ):

        result = normalize_spoken_value(
            "  Hello world.  "
        )

        self.assertEqual(
            result,
            "Hello world.",
        )


    def test_voiceover_field(
        self,
    ):

        scene = {
            "scene_id": 1,
            "voiceover":
                "My cat fired me.",
        }

        text, field = (
            extract_scene_voice_text(
                scene
            )
        )

        self.assertEqual(
            text,
            "My cat fired me.",
        )

        self.assertEqual(
            field,
            "voiceover",
        )


    def test_narration_field(
        self,
    ):

        scene = {
            "scene_id": 1,
            "narration":
                "Something strange happened.",
        }

        text, field = (
            extract_scene_voice_text(
                scene
            )
        )

        self.assertEqual(
            text,
            "Something strange happened.",
        )

        self.assertEqual(
            field,
            "narration",
        )


    def test_dialogue_list(
        self,
    ):

        scene = {

            "scene_id": 1,

            "dialogue": [
                {
                    "speaker":
                        "Mike",

                    "text":
                        "You're the CEO?"
                },

                {
                    "speaker":
                        "Cat",

                    "text":
                        "You're fired."
                },
            ],
        }

        text, field = (
            extract_scene_voice_text(
                scene
            )
        )

        self.assertEqual(
            text,
            (
                "You're the CEO? "
                "You're fired."
            ),
        )

        self.assertEqual(
            field,
            "dialogue",
        )


    def test_missing_voice_text_fails(
        self,
    ):

        scene = {
            "scene_id": 1,
        }

        with self.assertRaises(
            RuntimeError
        ):

            extract_scene_voice_text(
                scene
            )


    def test_too_long_text_fails(
        self,
    ):

        with self.assertRaises(
            RuntimeError
        ):

            validate_voice_text(
                1,
                "x" * 5000,
            )


    def test_instruction_contains_style(
        self,
    ):

        spec = {

            "video": {
                "language":
                    "en",
            },

            "audio": {
                "voiceover": {
                    "style":
                        "energetic",

                    "speed":
                        "natural",
                },
            },
        }

        instructions = (
            build_voice_instructions(
                spec
            )
        )

        self.assertIn(
            "energetic",
            instructions,
        )

        self.assertIn(
            "en",
            instructions,
        )

        self.assertIn(
            "natural conversational speaking pace",
            instructions,
        )

        self.assertIn(
            "Do not rush",
            instructions,
        )

        self.assertNotIn(
            "fast",
            instructions.lower(),
        )

if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )