import unittest

import scene_timing

from scene_timing import (
    calculate_job_timing_summary,
    calculate_scene_timing,
)


class SceneTimingTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_headroom = (
            scene_timing.HEADROOM_SEC
        )

        self.old_min = (
            scene_timing.MIN_VIDEO_SEC
        )

        self.old_max = (
            scene_timing.MAX_VIDEO_SEC
        )

        self.old_tolerance = (
            scene_timing
            .TARGET_TOLERANCE_SEC
        )

        scene_timing.HEADROOM_SEC = 0.30
        scene_timing.MIN_VIDEO_SEC = 2.0
        scene_timing.MAX_VIDEO_SEC = 10.0
        scene_timing.TARGET_TOLERANCE_SEC = 4.0


    def tearDown(
        self,
    ):

        scene_timing.HEADROOM_SEC = (
            self.old_headroom
        )

        scene_timing.MIN_VIDEO_SEC = (
            self.old_min
        )

        scene_timing.MAX_VIDEO_SEC = (
            self.old_max
        )

        scene_timing.TARGET_TOLERANCE_SEC = (
            self.old_tolerance
        )


    def test_normal_voice_sets_render_duration(
        self,
    ):

        result = calculate_scene_timing(
            voice_duration_sec=2.507,
            planned_duration_sec=5.0,
        )

        self.assertEqual(
            result["status"],
            "passed",
        )

        self.assertAlmostEqual(
            result[
                "render_duration_sec"
            ],
            2.807,
            places=3,
        )


    def test_short_voice_uses_minimum_video_duration(
        self,
    ):

        result = calculate_scene_timing(
            voice_duration_sec=1.1,
            planned_duration_sec=3.0,
        )

        self.assertEqual(
            result[
                "render_duration_sec"
            ],
            2.0,
        )


    def test_long_voice_requires_script_revision(
        self,
    ):

        result = calculate_scene_timing(
            voice_duration_sec=10.2,
            planned_duration_sec=7.0,
        )

        self.assertEqual(
            result["status"],
            "failed",
        )

        self.assertTrue(
            result[
                "script_revision_required"
            ]
        )

        self.assertIsNone(
            result[
                "render_duration_sec"
            ]
        )


    def test_total_near_target_needs_no_revision(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id": 1,
                        "timing": {
                            "status":
                                "passed",
                            "render_duration_sec":
                                6.0,
                        },
                    }
                    for _ in range(5)
                ],
            },
        }

        spec = {
            "video": {
                "target_duration_sec":
                    30,
                "min_duration_sec":
                    20,
                "max_duration_sec":
                    45,
            },
        }

        summary = (
            calculate_job_timing_summary(
                job,
                spec,
            )
        )

        self.assertEqual(
            summary[
                "total_render_duration_sec"
            ],
            30.0,
        )

        self.assertFalse(
            summary[
                "script_revision_recommended"
            ]
        )


    def test_total_far_from_target_recommends_revision(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id": index,
                        "timing": {
                            "status":
                                "passed",
                            "render_duration_sec":
                                3.0,
                        },
                    }
                    for index in range(
                        1,
                        6,
                    )
                ],
            },
        }

        spec = {
            "video": {
                "target_duration_sec":
                    30,
                "min_duration_sec":
                    20,
                "max_duration_sec":
                    45,
            },
        }

        summary = (
            calculate_job_timing_summary(
                job,
                spec,
            )
        )

        self.assertEqual(
            summary[
                "total_render_duration_sec"
            ],
            15.0,
        )

        self.assertTrue(
            summary[
                "script_revision_recommended"
            ]
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )