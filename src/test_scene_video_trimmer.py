import tempfile
import unittest

from pathlib import Path

import scene_video_trimmer

from scene_video_trimmer import (
    build_ffmpeg_command,
    evaluate_trimmed_video,
    get_target_render_duration,
    trimmed_metadata_matches_current_request,
)


class SceneVideoTrimmerTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_tolerance = (
            scene_video_trimmer
            .DURATION_TOLERANCE_SEC
        )

        scene_video_trimmer.DURATION_TOLERANCE_SEC = (
            0.08
        )


    def tearDown(
        self,
    ):

        scene_video_trimmer.DURATION_TOLERANCE_SEC = (
            self.old_tolerance
        )


    def test_target_duration_comes_from_passed_timing(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id":
                            2,

                        "timing": {
                            "status":
                                "passed",

                            "render_duration_sec":
                                6.55,
                        },
                    },
                ],
            },
        }

        self.assertEqual(
            get_target_render_duration(
                job,
                2,
            ),
            6.55,
        )


    def test_unpassed_timing_has_no_target_duration(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id":
                            2,

                        "timing": {
                            "status":
                                "failed",

                            "render_duration_sec":
                                None,
                        },
                    },
                ],
            },
        }

        self.assertIsNone(
            get_target_render_duration(
                job,
                2,
            )
        )


    def test_ffmpeg_command_uses_exact_duration_and_reencode(
        self,
    ):

        command = build_ffmpeg_command(
            source_file=
                Path(
                    "raw.mp4"
                ),
            output_file=
                Path(
                    "trimmed.mp4"
                ),
            target_duration_sec=
                6.55,
        )

        duration_index = (
            command.index(
                "-t"
            )
        )

        self.assertEqual(
            command[
                duration_index
                + 1
            ],
            "6.550",
        )

        self.assertIn(
            "libx264",
            command,
        )

        self.assertIn(
            "-an",
            command,
        )


    def test_trimmed_video_within_frame_tolerance_passes(
        self,
    ):

        passed, errors, warnings = (
            evaluate_trimmed_video(
                actual={
                    "duration_sec":
                        6.583,

                    "video_stream_count":
                        1,

                    "audio_stream_count":
                        0,

                    "codec":
                        "h264",

                    "width":
                        720,

                    "height":
                        1280,
                },
                target_duration_sec=
                    6.55,
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )


    def test_trimmed_video_outside_tolerance_fails(
        self,
    ):

        passed, errors, warnings = (
            evaluate_trimmed_video(
                actual={
                    "duration_sec":
                        6.75,

                    "video_stream_count":
                        1,

                    "audio_stream_count":
                        0,

                    "codec":
                        "h264",

                    "width":
                        720,

                    "height":
                        1280,
                },
                target_duration_sec=
                    6.55,
            )
        )

        self.assertFalse(
            passed
        )

        self.assertTrue(
            any(
                "differs from target"
                in error
                for error in errors
            )
        )


    def test_current_trim_metadata_matches(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            old_root = (
                scene_video_trimmer
                .PROJECT_ROOT
            )

            try:

                root = Path(
                    directory
                )

                scene_video_trimmer.PROJECT_ROOT = (
                    root
                )

                output_file = (
                    root
                    / "output"
                    / "job"
                    / "videos"
                    / "trimmed"
                    / "scene_002.mp4"
                )

                output_file.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                output_file.write_bytes(
                    b"trimmed"
                )

                scene = {
                    "video": {
                        "file":
                            (
                                "output/job/videos/"
                                "scene_002.mp4"
                            ),

                        "task_id":
                            "task-123",

                        "trimmed": {
                            "status":
                                "passed",

                            "file":
                                (
                                    "output/job/videos/"
                                    "trimmed/"
                                    "scene_002.mp4"
                                ),

                            "source_video":
                                (
                                    "output/job/videos/"
                                    "scene_002.mp4"
                                ),

                            "source_task_id":
                                "task-123",

                            "target_duration_sec":
                                6.55,
                        },
                    },
                }

                self.assertTrue(
                    trimmed_metadata_matches_current_request(
                        scene=scene,
                        output_file=output_file,
                        target_duration_sec=6.55,
                    )
                )

                scene[
                    "video"
                ][
                    "task_id"
                ] = "task-new"

                self.assertFalse(
                    trimmed_metadata_matches_current_request(
                        scene=scene,
                        output_file=output_file,
                        target_duration_sec=6.55,
                    )
                )

            finally:

                scene_video_trimmer.PROJECT_ROOT = (
                    old_root
                )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
