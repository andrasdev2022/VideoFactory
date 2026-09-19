import unittest

from voice_orchestrator import (
    ACTION_COMPLETE,
    ACTION_GENERATE,
    ACTION_QC,
    ACTION_STOP,
    ACTION_TIMING,
    choose_next_action,
    voice_is_natural_speed,
)


class VoiceOrchestratorTests(
    unittest.TestCase
):

    def test_missing_voice_generates(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    None,

                "voice_file":
                    None,

                "voice_speed":
                    None,

                "voice_qc_status":
                    None,

                "timing_status":
                    None,
            },
            attempts=0,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_GENERATE,
        )


    def test_old_fast_voice_is_regenerated(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    "generated",

                "voice_file":
                    "voice.wav",

                "voice_speed":
                    1.35,

                "voice_qc_status":
                    "passed",

                "timing_status":
                    "passed",
            },
            attempts=1,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_GENERATE,
        )


    def test_speed_108_is_not_natural(
        self,
    ):

        self.assertFalse(
            voice_is_natural_speed(
                {
                    "voice_speed":
                        1.08,
                }
            )
        )


    def test_speed_100_is_natural(
        self,
    ):

        self.assertTrue(
            voice_is_natural_speed(
                {
                    "voice_speed":
                        1.0,
                }
            )
        )


    def test_natural_voice_runs_qc(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    "generated",

                "voice_file":
                    "voice.wav",

                "voice_speed":
                    1.0,

                "voice_qc_status":
                    "pending",

                "timing_status":
                    None,
            },
            attempts=1,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_QC,
        )


    def test_voice_qc_pass_runs_timing(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    "generated",

                "voice_file":
                    "voice.wav",

                "voice_speed":
                    1.0,

                "voice_qc_status":
                    "passed",

                "timing_status":
                    None,
            },
            attempts=1,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_TIMING,
        )


    def test_timing_pass_completes(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    "generated",

                "voice_file":
                    "voice.wav",

                "voice_speed":
                    1.0,

                "voice_qc_status":
                    "passed",

                "timing_status":
                    "passed",
            },
            attempts=1,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_COMPLETE,
        )


    def test_timing_failure_stops(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    "generated",

                "voice_file":
                    "voice.wav",

                "voice_speed":
                    1.0,

                "voice_qc_status":
                    "passed",

                "timing_status":
                    "failed",

                "script_revision_required":
                    True,
            },
            attempts=1,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_STOP,
        )


    def test_voice_qc_failure_stops(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    "generated",

                "voice_file":
                    "voice.wav",

                "voice_speed":
                    1.0,

                "voice_qc_status":
                    "failed",

                "timing_status":
                    None,
            },
            attempts=1,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_STOP,
        )


    def test_attempt_limit_stops_old_speed_voice(
        self,
    ):

        action = choose_next_action(
            {
                "voice_status":
                    "generated",

                "voice_file":
                    "voice.wav",

                "voice_speed":
                    1.35,

                "voice_qc_status":
                    "passed",

                "timing_status":
                    "passed",
            },
            attempts=3,
            max_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_STOP,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )