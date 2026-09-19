import unittest

from scene_orchestrator import (
    append_orchestration_history,
    get_or_create_scene_orchestration,
    load_persistent_attempts,
    record_orchestration_result,
    reset_scene_attempts,
    start_generation_attempt,
)


def make_observed_state(
    *,
    image_status=None,
    image_file=None,
    video_status=None,
    video_file=None,
    video_semantic_qc=None,
):

    return {
        "image_status":
            image_status,

        "image_file":
            image_file,

        "image_qc":
            None,

        "image_semantic_qc":
            None,

        "video_status":
            video_status,

        "video_file":
            video_file,

        "video_qc":
            None,

        "video_semantic_qc":
            video_semantic_qc,
    }


class PersistentOrchestratorTests(
    unittest.TestCase
):

    def test_new_scene_starts_at_zero(
        self,
    ):

        job = {}

        observed = (
            make_observed_state()
        )

        scene_state = (
            get_or_create_scene_orchestration(
                job,
                1,
                observed,
            )
        )

        self.assertEqual(
            scene_state[
                "image_attempts"
            ],
            0,
        )

        self.assertEqual(
            scene_state[
                "video_attempts"
            ],
            0,
        )

        self.assertIn(
            "1",
            job[
                "orchestration"
            ][
                "scenes"
            ],
        )


    def test_existing_artifact_is_migrated_as_one_attempt(
        self,
    ):

        job = {}

        observed = (
            make_observed_state(
                image_status=
                    "generated",
                image_file=
                    "scene.png",
                video_status=
                    "generated",
                video_file=
                    "scene.mp4",
            )
        )

        scene_state = (
            get_or_create_scene_orchestration(
                job,
                2,
                observed,
            )
        )

        self.assertEqual(
            scene_state[
                "image_attempts"
            ],
            1,
        )

        self.assertEqual(
            scene_state[
                "video_attempts"
            ],
            1,
        )


    def test_generation_attempt_increments_before_worker(
        self,
    ):

        job = {}

        observed = (
            make_observed_state()
        )

        attempt = (
            start_generation_attempt(
                job,
                scene_id=1,
                observed_state=
                    observed,
                counter_name=
                    "video_attempts",
                action=
                    "generate_video",
            )
        )

        self.assertEqual(
            attempt,
            1,
        )

        scene_state = (
            job[
                "orchestration"
            ][
                "scenes"
            ][
                "1"
            ]
        )

        self.assertEqual(
            scene_state[
                "video_attempts"
            ],
            1,
        )

        self.assertEqual(
            scene_state[
                "state"
            ],
            "running",
        )


    def test_attempts_survive_second_lookup(
        self,
    ):

        job = {}

        observed = (
            make_observed_state()
        )

        start_generation_attempt(
            job,
            scene_id=1,
            observed_state=
                observed,
            counter_name=
                "video_attempts",
            action=
                "generate_video",
        )

        image_attempts, video_attempts = (
            load_persistent_attempts(
                job,
                1,
                observed,
            )
        )

        self.assertEqual(
            image_attempts,
            0,
        )

        self.assertEqual(
            video_attempts,
            1,
        )

        # Simulate another orchestrator run using
        # the same persisted job structure.

        image_attempts, video_attempts = (
            load_persistent_attempts(
                job,
                1,
                observed,
            )
        )

        self.assertEqual(
            video_attempts,
            1,
        )


    def test_reset_attempts(
        self,
    ):

        job = {}

        observed = (
            make_observed_state()
        )

        start_generation_attempt(
            job,
            scene_id=1,
            observed_state=
                observed,
            counter_name=
                "image_attempts",
            action=
                "generate_image",
        )

        start_generation_attempt(
            job,
            scene_id=1,
            observed_state=
                observed,
            counter_name=
                "video_attempts",
            action=
                "generate_video",
        )

        reset_scene_attempts(
            job,
            1,
            observed,
        )

        image_attempts, video_attempts = (
            load_persistent_attempts(
                job,
                1,
                observed,
            )
        )

        self.assertEqual(
            image_attempts,
            0,
        )

        self.assertEqual(
            video_attempts,
            0,
        )


    def test_completed_state_is_persisted(
        self,
    ):

        job = {}

        observed = (
            make_observed_state(
                image_status=
                    "generated",
                image_file=
                    "scene.png",
                video_status=
                    "generated",
                video_file=
                    "scene.mp4",
                video_semantic_qc=
                    "passed",
            )
        )

        record_orchestration_result(
            job,
            scene_id=1,
            observed_state=
                observed,
            action=
                "complete",
            result=
                "passed",
            orchestration_state=
                "completed",
        )

        scene_state = (
            job[
                "orchestration"
            ][
                "scenes"
            ][
                "1"
            ]
        )

        self.assertEqual(
            scene_state[
                "state"
            ],
            "completed",
        )

        self.assertEqual(
            scene_state[
                "last_action"
            ],
            "complete",
        )


    def test_history_records_attempts(
        self,
    ):

        job = {}

        observed = (
            make_observed_state()
        )

        start_generation_attempt(
            job,
            scene_id=1,
            observed_state=
                observed,
            counter_name=
                "video_attempts",
            action=
                "generate_video",
        )

        scene_state = (
            job[
                "orchestration"
            ][
                "scenes"
            ][
                "1"
            ]
        )

        latest = (
            scene_state[
                "history"
            ][-1]
        )

        self.assertEqual(
            latest[
                "action"
            ],
            "generate_video",
        )

        self.assertEqual(
            latest[
                "result"
            ],
            "started",
        )

        self.assertEqual(
            latest[
                "video_attempts"
            ],
            1,
        )


    def test_history_is_bounded(
        self,
    ):

        scene_state = {
            "image_attempts": 0,
            "video_attempts": 0,
            "history": [],
        }

        for index in range(
            150
        ):

            append_orchestration_history(
                scene_state,
                action=
                    "test",
                result=
                    str(index),
            )

        self.assertEqual(
            len(
                scene_state[
                    "history"
                ]
            ),
            100,
        )

        self.assertEqual(
            scene_state[
                "history"
            ][0][
                "result"
            ],
            "50",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )