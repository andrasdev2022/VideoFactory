import unittest

from pipeline_status import (
    refresh_pipeline_status,
    set_legacy_status_from_stage,
)


class AudioAssetsStatusTests(
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

            "audio":
                {},
        }


    def test_audio_assets_pending_without_metadata(
        self,
    ):

        job = self.make_job()

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "audio_assets"
            ][
                "state"
            ],
            "pending",
        )


    def test_audio_assets_failed(
        self,
    ):

        job = self.make_job()

        job[
            "audio"
        ][
            "assets"
        ] = {
            "status":
                "failed",
        }

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "audio_assets"
            ][
                "state"
            ],
            "failed",
        )


    def test_audio_assets_complete_and_legacy_status(
        self,
    ):

        job = self.make_job()

        job[
            "audio"
        ][
            "assets"
        ] = {
            "status":
                "passed",
        }

        legacy = set_legacy_status_from_stage(
            job,
            "audio_assets",
        )

        self.assertEqual(
            legacy,
            "audio_assets_passed",
        )

        self.assertEqual(
            job[
                "pipeline_status"
            ][
                "audio_assets"
            ][
                "state"
            ],
            "completed",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
