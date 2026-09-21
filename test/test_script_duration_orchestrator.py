import unittest

from script_duration_orchestrator import (
    ACTION_COMPLETE,
    ACTION_REMEASURE,
    ACTION_REWRITE,
    ACTION_STOP_ATTEMPTS,
    ACTION_STOP_INCOMPLETE,
    ACTION_STOP_LOCAL_TIMING,
    choose_next_action,
)


class ScriptDurationOrchestratorTests(
    unittest.TestCase
):

    def test_complete_when_global_timing_is_good(
        self,
    ):

        action = choose_next_action(
            {
                "failed_local_scene_ids":
                    [],

                "incomplete_scene_ids":
                    [],

                "summary_status":
                    "complete",

                "script_revision_recommended":
                    False,

                "normalization_status":
                    None,
            },
            iterations=0,
            max_iterations=3,
        )

        self.assertEqual(
            action,
            ACTION_COMPLETE,
        )


    def test_rewrite_when_global_timing_is_outside_target(
        self,
    ):

        action = choose_next_action(
            {
                "failed_local_scene_ids":
                    [],

                "incomplete_scene_ids":
                    [],

                "summary_status":
                    "complete",

                "script_revision_recommended":
                    True,

                "normalization_status":
                    None,
            },
            iterations=0,
            max_iterations=3,
        )

        self.assertEqual(
            action,
            ACTION_REWRITE,
        )


    def test_pending_normalization_remeasures_before_summary_check(
        self,
    ):

        action = choose_next_action(
            {
                "failed_local_scene_ids":
                    [],

                "incomplete_scene_ids":
                    [
                        2,
                        3,
                    ],

                "summary_status":
                    None,

                "script_revision_recommended":
                    None,

                "normalization_status":
                    "pending_remeasure",
            },
            iterations=1,
            max_iterations=3,
        )

        self.assertEqual(
            action,
            ACTION_REMEASURE,
        )


    def test_local_timing_failure_stops(
        self,
    ):

        action = choose_next_action(
            {
                "failed_local_scene_ids":
                    [
                        4,
                    ],

                "incomplete_scene_ids":
                    [],

                "summary_status":
                    "failed",

                "script_revision_recommended":
                    True,

                "normalization_status":
                    None,
            },
            iterations=0,
            max_iterations=3,
        )

        self.assertEqual(
            action,
            ACTION_STOP_LOCAL_TIMING,
        )


    def test_incomplete_timing_stops(
        self,
    ):

        action = choose_next_action(
            {
                "failed_local_scene_ids":
                    [],

                "incomplete_scene_ids":
                    [
                        2,
                    ],

                "summary_status":
                    "partial",

                "script_revision_recommended":
                    None,

                "normalization_status":
                    None,
            },
            iterations=0,
            max_iterations=3,
        )

        self.assertEqual(
            action,
            ACTION_STOP_INCOMPLETE,
        )


    def test_iteration_limit_stops(
        self,
    ):

        action = choose_next_action(
            {
                "failed_local_scene_ids":
                    [],

                "incomplete_scene_ids":
                    [],

                "summary_status":
                    "complete",

                "script_revision_recommended":
                    True,

                "normalization_status":
                    "remeasured",
            },
            iterations=3,
            max_iterations=3,
        )

        self.assertEqual(
            action,
            ACTION_STOP_ATTEMPTS,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
