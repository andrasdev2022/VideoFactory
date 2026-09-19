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
                {
                    "scene_id": 3,
                },
            ],
        },

        "characters": [],

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


class AudioPipelineStatusTests(
    unittest.TestCase
):

    def test_voiceovers_initially_pending(
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
                "voiceovers"
            ][
                "state"
            ],
            "pending",
        )


    def test_one_voice_is_partial(
        self,
    ):

        job = make_job()

        job[
            "script"
        ][
            "scenes"
        ][0][
            "voice"
        ] = {

            "status":
                "generated",

            "file":
                "scene_001.wav",
        }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        summary = status[
            "voiceovers"
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


    def test_all_voiceovers_completed(
        self,
    ):

        job = make_job()

        for scene in (
            job[
                "script"
            ][
                "scenes"
            ]
        ):

            scene[
                "voice"
            ] = {

                "status":
                    "generated",

                "file":
                    "voice.wav",
            }

        status = (
            refresh_pipeline_status(
                job
            )
        )

        self.assertEqual(
            status[
                "voiceovers"
            ][
                "state"
            ],
            "completed",
        )


    def test_voice_qc_and_legacy_status(
        self,
    ):

        job = make_job()

        for scene in (
            job[
                "script"
            ][
                "scenes"
            ]
        ):

            scene[
                "voice"
            ] = {

                "status":
                    "generated",

                "file":
                    "voice.wav",

                "qc": {
                    "status":
                        "passed",
                },
            }

        legacy = (
            set_legacy_status_from_stage(
                job,
                "voice_qc",
            )
        )

        self.assertEqual(
            legacy,
            "voice_qc_passed",
        )

        self.assertEqual(
            job["status"],
            "voice_qc_passed",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )