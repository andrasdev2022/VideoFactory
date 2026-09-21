import unittest

from video_qc import (
    get_expected_duration,
    get_target_render_duration,
)


class VideoQCTimingTests(
    unittest.TestCase
):

    def test_expected_duration_uses_provider_duration(
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
            "visuals": {
                "scenes": [
                    {
                        "scene_id": 2,
                        "video": {
                            "provider_duration_sec": 9,
                            "target_render_duration_sec": 8.2,
                        },
                    },
                ],
            },
        }

        self.assertEqual(
            get_expected_duration(
                job,
                2,
            ),
            9.0,
        )


    def test_target_render_duration_uses_timing(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id": 2,
                        "timing": {
                            "status": "passed",
                            "render_duration_sec": 8.2,
                        },
                    },
                ],
            },
        }

        self.assertEqual(
            get_target_render_duration(
                job,
                2,
            ),
            8.2,
        )


    def test_legacy_expected_duration_falls_back_to_script(
        self,
    ):

        job = {
            "script": {
                "scenes": [
                    {
                        "scene_id": 2,
                        "duration_sec": 7.0,
                    },
                ],
            },
            "visuals": {
                "scenes": [
                    {
                        "scene_id": 2,
                        "video": {},
                    },
                ],
            },
        }

        self.assertEqual(
            get_expected_duration(
                job,
                2,
            ),
            7.0,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
