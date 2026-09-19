import unittest

from pipeline_status import (
    refresh_pipeline_status,
    set_legacy_status_from_stage,
)


class SubtitleStatusTests(
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
            "subtitles": {
                "enabled":
                    True,
                "burned_in":
                    True,
            },
        }


    def test_subtitles_pending_without_generation(
        self,
    ):

        job = self.make_job()

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "subtitles"
            ][
                "state"
            ],
            "pending",
        )


    def test_subtitles_failed_when_generation_fails(
        self,
    ):

        job = self.make_job()

        job[
            "subtitles"
        ][
            "generation"
        ] = {
            "status":
                "failed",
        }

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "subtitles"
            ][
                "state"
            ],
            "failed",
        )


    def test_subtitles_wait_for_burn_when_required(
        self,
    ):

        job = self.make_job()

        job[
            "subtitles"
        ][
            "generation"
        ] = {
            "status":
                "passed",
        }

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "subtitles"
            ][
                "state"
            ],
            "pending",
        )


    def test_subtitles_complete_after_burn(
        self,
    ):

        job = self.make_job()

        job[
            "subtitles"
        ][
            "generation"
        ] = {
            "status":
                "passed",
        }

        job[
            "subtitles"
        ][
            "render"
        ] = {
            "status":
                "passed",

            "file":
                "with_subtitles.mp4",
        }

        legacy = set_legacy_status_from_stage(
            job,
            "subtitles",
        )

        self.assertEqual(
            legacy,
            "subtitles_passed",
        )

        self.assertEqual(
            job[
                "pipeline_status"
            ][
                "subtitles"
            ][
                "state"
            ],
            "completed",
        )


    def test_disabled_subtitles_are_complete(
        self,
    ):

        job = self.make_job()

        job[
            "subtitles"
        ][
            "enabled"
        ] = False

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "subtitles"
            ][
                "state"
            ],
            "completed",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
