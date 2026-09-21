import tempfile
import unittest

from pathlib import Path

import image_to_video_generator

from image_to_video_generator import (
    get_provider_duration,
    get_render_duration,
    video_metadata_matches_current_request,
)


class ImageToVideoTimingTests(
    unittest.TestCase
):

    def test_render_duration_comes_from_passed_timing(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id": 2,
                        "duration_sec": 7.0,
                        "timing": {
                            "status": "passed",
                            "render_duration_sec": 8.2,
                        },
                    },
                ],
            },
        }

        self.assertEqual(
            get_render_duration(
                job,
                2,
            ),
            8.2,
        )


    def test_unpassed_timing_has_no_render_duration(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id": 2,
                        "timing": {
                            "status": "failed",
                            "render_duration_sec": None,
                        },
                    },
                ],
            },
        }

        self.assertIsNone(
            get_render_duration(
                job,
                2,
            )
        )


    def test_provider_duration_rounds_up(
        self,
    ):

        self.assertEqual(
            get_provider_duration(
                8.2
            ),
            9,
        )

        self.assertEqual(
            get_provider_duration(
                9.0
            ),
            9,
        )


    def test_provider_duration_rejects_out_of_range(
        self,
    ):

        with self.assertRaises(
            RuntimeError
        ):

            get_provider_duration(
                10.1
            )


    def test_cached_video_from_other_provider_is_stale(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            old_root = (
                image_to_video_generator
                .PROJECT_ROOT
            )

            try:

                image_to_video_generator.PROJECT_ROOT = (
                    Path(
                        directory
                    )
                )

                output_file = (
                    Path(
                        directory
                    )
                    / "output"
                    / "job"
                    / "videos"
                    / "scene_002.mp4"
                )

                output_file.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                output_file.write_bytes(
                    b"video"
                )

                scene = {
                    "video": {
                        "status":
                            "generated",

                        "file": (
                            "output/job/videos/"
                            "scene_002.mp4"
                        ),

                        "provider":
                            "runway",

                        "provider_duration_sec":
                            3.0,

                        "target_render_duration_sec":
                            2.75,

                        "source_image":
                            "scene.png",
                    },
                }

                self.assertFalse(
                    video_metadata_matches_current_request(
                        scene=scene,
                        output_file=output_file,
                        render_duration_sec=2.75,
                        provider_duration_sec=3.0,
                        source_image="scene.png",
                        provider="local_ltx",
                    )
                )

                self.assertTrue(
                    video_metadata_matches_current_request(
                        scene=scene,
                        output_file=output_file,
                        render_duration_sec=2.75,
                        provider_duration_sec=3.0,
                        source_image="scene.png",
                        provider="runway",
                    )
                )

            finally:

                image_to_video_generator.PROJECT_ROOT = (
                    old_root
                )


    def test_stale_metadata_does_not_match(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            old_root = (
                image_to_video_generator
                .PROJECT_ROOT
            )

            try:

                image_to_video_generator.PROJECT_ROOT = (
                    Path(
                        directory
                    )
                )

                output_file = (
                    Path(
                        directory
                    )
                    / "output"
                    / "job"
                    / "videos"
                    / "scene_002.mp4"
                )

                output_file.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                output_file.write_bytes(
                    b"video"
                )

                scene = {
                    "video": {
                        "status": "generated",
                        "file": (
                            "output/job/videos/"
                            "scene_002.mp4"
                        ),
                        "provider_duration_sec": 8,
                        "target_render_duration_sec": 7.0,
                        "source_image": "scene.png",
                    },
                }

                self.assertFalse(
                    video_metadata_matches_current_request(
                        scene=scene,
                        output_file=output_file,
                        render_duration_sec=8.2,
                        provider_duration_sec=9,
                        source_image="scene.png",
                    )
                )

            finally:

                image_to_video_generator.PROJECT_ROOT = (
                    old_root
                )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
