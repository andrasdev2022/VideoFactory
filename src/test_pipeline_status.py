import copy
import unittest

from pipeline_status import (
    refresh_pipeline_status,
    set_legacy_status_from_stage,
)


def make_job() -> dict:

    return {
        "job_id": "test-job",

        "status": "old_stale_status",

        "script": {
            "scenes": [
                {
                    "scene_id": 1,
                    "duration_sec": 5,
                },
                {
                    "scene_id": 2,
                    "duration_sec": 7,
                },
                {
                    "scene_id": 3,
                    "duration_sec": 5,
                },
            ],
        },

        "characters": [
            {
                "character_id": "char-001",
            },
            {
                "character_id": "char-002",
            },
        ],

        "visuals": {
            "scenes": [
                {
                    "scene_id": 1,
                },
                {
                    "scene_id": 2,
                },
                {
                    "scene_id": 3,
                },
            ],
        },
    }


class PipelineStatusTests(
    unittest.TestCase
):

    def test_initial_statuses(
        self,
    ):

        job = make_job()

        status = (
            refresh_pipeline_status(
                job
            )
        )

        self.assertEqual(
            status[
                "script"
            ]["state"],
            "completed",
        )

        self.assertEqual(
            status[
                "visual_prompts"
            ]["state"],
            "pending",
        )

        self.assertEqual(
            status[
                "scene_videos"
            ]["state"],
            "pending",
        )

        self.assertEqual(
            status[
                "video_semantic_qc"
            ]["state"],
            "pending",
        )


    def test_one_video_generated_is_partial(
        self,
    ):

        job = make_job()

        scene2 = (
            job["visuals"]["scenes"][1]
        )

        scene2["video"] = {
            "status": "generated",
            "file":
                "output/test/videos/"
                "scene_002.mp4",
        }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        summary = status[
            "scene_videos"
        ]

        self.assertEqual(
            summary["state"],
            "partial",
        )

        self.assertEqual(
            summary["ready"],
            1,
        )

        self.assertEqual(
            summary["pending"],
            2,
        )


    def test_video_generation_clears_old_semantic_failure(
        self,
    ):

        job = make_job()

        scene2 = (
            job["visuals"]["scenes"][1]
        )

        scene2["video"] = {
            "status": "generated",
            "file":
                "output/test/videos/"
                "scene_002.mp4",

            "semantic_qc": {
                "status": "failed",
            },
        }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        self.assertEqual(
            status[
                "video_semantic_qc"
            ]["state"],
            "failed",
        )

        # Simulate a newly generated video.
        #
        # New artifact replaces the old video metadata.
        # Old QC must NOT survive.

        scene2["video"] = {
            "status": "generated",
            "file":
                "output/test/videos/"
                "scene_002.mp4",
        }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        self.assertEqual(
            status[
                "video_semantic_qc"
            ]["state"],
            "pending",
        )

        self.assertEqual(
            status[
                "video_semantic_qc"
            ]["failed"],
            0,
        )


    def test_one_semantic_pass_is_partial(
        self,
    ):

        job = make_job()

        scene2 = (
            job["visuals"]["scenes"][1]
        )

        scene2["video"] = {
            "status": "generated",

            "file":
                "output/test/videos/"
                "scene_002.mp4",

            "semantic_qc": {
                "status": "passed",
            },
        }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        summary = status[
            "video_semantic_qc"
        ]

        self.assertEqual(
            summary["state"],
            "partial",
        )

        self.assertEqual(
            summary["ready"],
            1,
        )

        self.assertEqual(
            summary["failed"],
            0,
        )

        self.assertEqual(
            summary["pending"],
            2,
        )


    def test_one_failed_semantic_qc_marks_stage_failed(
        self,
    ):

        job = make_job()

        scene1 = (
            job["visuals"]["scenes"][0]
        )

        scene1["video"] = {
            "status": "generated",
            "file": "scene_001.mp4",

            "semantic_qc": {
                "status": "passed",
            },
        }

        scene2 = (
            job["visuals"]["scenes"][1]
        )

        scene2["video"] = {
            "status": "generated",
            "file": "scene_002.mp4",

            "semantic_qc": {
                "status": "failed",
            },
        }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        summary = status[
            "video_semantic_qc"
        ]

        self.assertEqual(
            summary["state"],
            "failed",
        )

        self.assertEqual(
            summary["ready"],
            1,
        )

        self.assertEqual(
            summary["failed"],
            1,
        )

        self.assertEqual(
            summary["pending"],
            1,
        )


    def test_all_semantic_qc_passed(
        self,
    ):

        job = make_job()

        for scene in (
            job["visuals"]["scenes"]
        ):

            scene_id = (
                scene["scene_id"]
            )

            scene["video"] = {
                "status": "generated",

                "file": (
                    f"scene_"
                    f"{scene_id:03d}.mp4"
                ),

                "semantic_qc": {
                    "status": "passed",
                },
            }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        summary = status[
            "video_semantic_qc"
        ]

        self.assertEqual(
            summary["state"],
            "completed",
        )

        self.assertEqual(
            summary["ready"],
            3,
        )

        self.assertEqual(
            summary["failed"],
            0,
        )

        self.assertEqual(
            summary["pending"],
            0,
        )


    def test_one_trimmed_scene_is_partial(
        self,
    ):

        job = make_job()

        scene2 = (
            job["visuals"]["scenes"][1]
        )

        scene2["video"] = {
            "status":
                "generated",

            "file":
                "scene_002.mp4",

            "trimmed": {
                "status":
                    "passed",

                "file":
                    "trimmed/scene_002.mp4",
            },
        }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        summary = status[
            "scene_trimmed"
        ]

        self.assertEqual(
            summary["state"],
            "partial",
        )

        self.assertEqual(
            summary["ready"],
            1,
        )

        self.assertEqual(
            summary["pending"],
            2,
        )


    def test_all_trimmed_scenes_complete(
        self,
    ):

        job = make_job()

        for scene in (
            job["visuals"]["scenes"]
        ):

            scene_id = scene[
                "scene_id"
            ]

            scene["video"] = {
                "status":
                    "generated",

                "file":
                    (
                        f"scene_"
                        f"{scene_id:03d}.mp4"
                    ),

                "trimmed": {
                    "status":
                        "passed",

                    "file":
                        (
                            "trimmed/"
                            f"scene_{scene_id:03d}.mp4"
                        ),
                },
            }

        legacy = (
            set_legacy_status_from_stage(
                job,
                "scene_trimmed",
            )
        )

        self.assertEqual(
            legacy,
            "scene_trimmed_passed",
        )

        self.assertEqual(
            job[
                "pipeline_status"
            ][
                "scene_trimmed"
            ][
                "state"
            ],
            "completed",
        )


    def test_legacy_status_updates_current_stage(
        self,
    ):

        job = make_job()

        scene2 = (
            job["visuals"]["scenes"][1]
        )

        scene2["video"] = {
            "status": "generated",
            "file": "scene_002.mp4",
        }

        legacy = (
            set_legacy_status_from_stage(
                job,
                "scene_videos",
            )
        )

        self.assertEqual(
            legacy,
            "scene_videos_partial",
        )

        self.assertEqual(
            job["status"],
            "scene_videos_partial",
        )

        # The stale previous value must be gone.

        self.assertNotEqual(
            job["status"],
            "old_stale_status",
        )


    def test_original_job_is_not_needed_for_comparison(
        self,
    ):

        job = make_job()

        original = copy.deepcopy(
            job
        )

        refresh_pipeline_status(
            job
        )

        self.assertNotIn(
            "pipeline_status",
            original,
        )

        self.assertIn(
            "pipeline_status",
            job,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )