import unittest

from pipeline_status import (
    refresh_pipeline_status,
    set_legacy_status_from_stage,
)


class AudioMixStatusTests(
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


    def test_audio_mix_pending_without_metadata(
        self,
    ):

        job = self.make_job()

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "audio_mix"
            ][
                "state"
            ],
            "pending",
        )


    def test_audio_mix_failed(
        self,
    ):

        job = self.make_job()

        job[
            "audio"
        ][
            "mix"
        ] = {
            "status":
                "failed",
        }

        status = refresh_pipeline_status(
            job
        )

        self.assertEqual(
            status[
                "audio_mix"
            ][
                "state"
            ],
            "failed",
        )


    def test_audio_mix_completed_and_legacy_status(
        self,
    ):

        job = self.make_job()

        job[
            "audio"
        ][
            "mix"
        ] = {
            "status":
                "passed",

            "file":
                "final_audio_mix.mp4",
        }

        legacy = set_legacy_status_from_stage(
            job,
            "audio_mix",
        )

        self.assertEqual(
            legacy,
            "audio_mix_passed",
        )

        self.assertEqual(
            job[
                "pipeline_status"
            ][
                "audio_mix"
            ][
                "state"
            ],
            "completed",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
