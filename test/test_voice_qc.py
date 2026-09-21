import unittest

import voice_qc

from voice_qc import (
    evaluate_voice_qc,
    inspect_audio_probe,
)


class VoiceQCTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_min_size = (
            voice_qc.MIN_FILE_SIZE_BYTES
        )

        self.old_min_rate = (
            voice_qc.MIN_SAMPLE_RATE
        )

        voice_qc.MIN_FILE_SIZE_BYTES = 5000
        voice_qc.MIN_SAMPLE_RATE = 22050


    def tearDown(
        self,
    ):

        voice_qc.MIN_FILE_SIZE_BYTES = (
            self.old_min_size
        )

        voice_qc.MIN_SAMPLE_RATE = (
            self.old_min_rate
        )


    def make_actual(
        self,
        duration=5.0,
        sample_rate=24000,
        channels=1,
        file_size=100000,
        codec="pcm_s16le",
    ):

        return {
            "has_audio_stream":
                True,

            "codec":
                codec,

            "sample_rate":
                sample_rate,

            "channels":
                channels,

            "duration_sec":
                duration,

            "file_size_bytes":
                file_size,
        }


    def test_valid_voice_passes(
        self,
    ):

        passed, errors, warnings = (
            evaluate_voice_qc(
                6.0,
                self.make_actual(
                    duration=5.8,
                ),
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )


    def test_slightly_long_voice_passes(
        self,
    ):

        passed, errors, warnings = (
            evaluate_voice_qc(
                6.0,
                self.make_actual(
                    duration=6.20,
                ),
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )


    def test_too_long_voice_warns_but_passes(
        self,
    ):

        passed, errors, warnings = (
            evaluate_voice_qc(
                6.0,
                self.make_actual(
                    duration=7.0,
                ),
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )

        self.assertTrue(
            any(
                "longer"
                in warning
                for warning in warnings
            )
        )


    def test_missing_audio_stream_fails(
        self,
    ):

        passed, errors, warnings = (
            evaluate_voice_qc(
                6.0,
                {
                    "has_audio_stream":
                        False,

                    "file_size_bytes":
                        10000,
                },
            )
        )

        self.assertFalse(
            passed
        )


    def test_low_sample_rate_fails(
        self,
    ):

        passed, errors, warnings = (
            evaluate_voice_qc(
                6.0,
                self.make_actual(
                    sample_rate=16000,
                ),
            )
        )

        self.assertFalse(
            passed
        )

        self.assertTrue(
            any(
                "Sample rate"
                in error
                for error in errors
            )
        )


    def test_short_voice_generates_warning(
        self,
    ):

        passed, errors, warnings = (
            evaluate_voice_qc(
                7.0,
                self.make_actual(
                    duration=3.5,
                ),
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )

        self.assertTrue(
            any(
                "shorter"
                in warning
                for warning in warnings
            )
        )


    def test_probe_parser(
        self,
    ):

        probe = {
            "streams": [
                {
                    "codec_type":
                        "audio",

                    "codec_name":
                        "pcm_s16le",

                    "codec_long_name":
                        "PCM signed 16-bit little-endian",

                    "sample_rate":
                        "24000",

                    "channels":
                        1,

                    "channel_layout":
                        "mono",

                    "sample_fmt":
                        "s16",

                    "duration":
                        "5.125000",

                    "bit_rate":
                        "384000",
                },
            ],

            "format": {
                "duration":
                    "5.125000",
            },
        }

        actual = (
            inspect_audio_probe(
                probe,
                100000,
            )
        )

        self.assertTrue(
            actual[
                "has_audio_stream"
            ]
        )

        self.assertEqual(
            actual[
                "sample_rate"
            ],
            24000,
        )

        self.assertEqual(
            actual[
                "channels"
            ],
            1,
        )

        self.assertAlmostEqual(
            actual[
                "duration_sec"
            ],
            5.125,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )