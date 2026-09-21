import unittest

from pipeline_status import (
    refresh_pipeline_status,
    set_legacy_status_from_stage,
)


class BaseAssemblyStatusTests(
    unittest.TestCase
):

    def make_job(
        self,
    ) -> dict:

        return {
            "script": {
                "scenes": [
                    {
                        "scene_id": 1,
                    },
                ],
            },
            "visuals": {
                "scenes": [
                    {
                        "scene_id": 1,
                    },
                ],
            },
            "characters": [],
        }


    def test_base_assembly_pending_without_metadata(
        self,
    ):

        job = self.make_job()

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "base_assembly"
            ][
                "state"
            ],
            "pending",
        )


    def test_base_assembly_failed(
        self,
    ):

        job = self.make_job()

        job[
            "assembly"
        ] = {
            "status":
                "failed",
        }

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "base_assembly"
            ][
                "state"
            ],
            "failed",
        )


    def test_base_assembly_completed_and_legacy_status(
        self,
    ):

        job = self.make_job()

        job[
            "assembly"
        ] = {
            "status":
                "passed",

            "file":
                (
                    "output/job/assembly/"
                    "base_with_voice.mp4"
                ),
        }

        legacy = set_legacy_status_from_stage(
            job,
            "base_assembly",
        )

        self.assertEqual(
            legacy,
            "base_assembly_passed",
        )

        self.assertEqual(
            job[
                "pipeline_status"
            ][
                "base_assembly"
            ][
                "state"
            ],
            "completed",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
