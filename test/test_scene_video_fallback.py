import unittest

from pathlib import Path

from scene_video_fallback import (
    FALLBACK_HEIGHT,
    FALLBACK_WIDTH,
    build_ffmpeg_command,
    get_target_duration,
)


class SceneVideoFallbackTests(
    unittest.TestCase
):

    def test_target_duration_comes_from_passed_timing(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id":
                            5,

                        "timing": {
                            "status":
                                "passed",

                            "render_duration_sec":
                                7.1,
                        },
                    },
                ],
            },
        }

        self.assertEqual(
            get_target_duration(
                job,
                5,
            ),
            7.1,
        )


    def test_ffmpeg_command_is_deterministic_image_video(
        self,
    ):

        command = build_ffmpeg_command(
            image_path=
                Path(
                    "scene.png"
                ),

            output_path=
                Path(
                    "scene_fallback.mp4"
                ),

            duration_sec=
                7.1,
        )

        self.assertIn(
            "-loop",
            command,
        )

        self.assertIn(
            "libx264",
            command,
        )

        self.assertIn(
            "-an",
            command,
        )

        filter_index = (
            command.index(
                "-vf"
            )
        )

        filter_text = command[
            filter_index
            + 1
        ]

        self.assertIn(
            "zoompan=",
            filter_text,
        )

        self.assertIn(
            (
                f"s={FALLBACK_WIDTH}"
                f"x{FALLBACK_HEIGHT}"
            ),
            filter_text,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
