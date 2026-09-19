import unittest

from pipeline_status import (
    refresh_pipeline_status,
    set_legacy_status_from_stage,
)


def make_job() -> dict:

    return {
        "script": {
            "scenes": [
                {
                    "scene_id": 1,
                },
                {
                    "scene_id": 2,
                },
            ],
        },

        "characters":
            [],

        "visuals": {
            "scenes": [
                {
                    "scene_id": 1,
                },
                {
                    "scene_id": 2,
                },
            ],
        },
    }


class GlobalTimingStatusTests(
    unittest.TestCase
):

    def test_global_timing_pending_before_scene_timing(
        self,
    ):

        job = make_job()

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "global_timing"
            ][
                "state"
            ],
            "pending",
        )


    def test_global_timing_failed_when_revision_is_recommended(
        self,
    ):

        job = make_job()

        for scene in job[
            "script"
        ][
            "scenes"
        ]:

            scene[
                "timing"
            ] = {
                "status":
                    "passed",
            }

        job[
            "timing_summary"
        ] = {
            "status":
                "complete",

            "script_revision_recommended":
                True,
        }

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "global_timing"
            ][
                "state"
            ],
            "failed",
        )


    def test_global_timing_completed_and_legacy_status(
        self,
    ):

        job = make_job()

        for scene in job[
            "script"
        ][
            "scenes"
        ]:

            scene[
                "timing"
            ] = {
                "status":
                    "passed",
            }

        job[
            "timing_summary"
        ] = {
            "status":
                "complete",

            "script_revision_recommended":
                False,
        }

        legacy = set_legacy_status_from_stage(
            job,
            "global_timing",
        )

        self.assertEqual(
            legacy,
            "global_timing_passed",
        )

        self.assertEqual(
            job[
                "pipeline_status"
            ][
                "global_timing"
            ][
                "state"
            ],
            "completed",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
