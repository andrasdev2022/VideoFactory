import unittest

from pipeline_status import (
    refresh_pipeline_status,
    set_legacy_status_from_stage,
)


class FinalQCStatusTests(
    unittest.TestCase
):

    def make_job(
        self,
    ) -> dict:

        return {
            "script": {
                "scenes": [
                    {
                        "scene_id":
                            1,
                    },
                ],
            },

            "visuals": {
                "scenes": [
                    {
                        "scene_id":
                            1,
                    },
                ],
            },

            "characters":
                [],
        }


    def test_final_qc_pending_without_metadata(
        self,
    ):

        job = self.make_job()

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "final_qc"
            ][
                "state"
            ],
            "pending",
        )


    def test_final_qc_failed(
        self,
    ):

        job = self.make_job()

        job[
            "final_qc"
        ] = {
            "status":
                "failed",
        }

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "final_qc"
            ][
                "state"
            ],
            "failed",
        )


    def test_final_qc_completed_and_legacy_status(
        self,
    ):

        job = self.make_job()

        job[
            "final_qc"
        ] = {
            "status":
                "passed",

            "export": {
                "video_file":
                    "output/job/final/video.mp4",
            },
        }

        legacy = set_legacy_status_from_stage(
            job,
            "final_qc",
        )

        self.assertEqual(
            legacy,
            "final_qc_passed",
        )

        self.assertEqual(
            job[
                "pipeline_status"
            ][
                "final_qc"
            ][
                "state"
            ],
            "completed",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
