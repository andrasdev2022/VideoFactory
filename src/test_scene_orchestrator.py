import unittest

from scene_orchestrator import (
    ACTION_COMPLETE,
    ACTION_GENERATE_IMAGE,
    ACTION_GENERATE_VIDEO,
    ACTION_IMAGE_QC,
    ACTION_IMAGE_SEMANTIC_QC,
    ACTION_REGENERATE_MOTION,
    ACTION_RETRY_VIDEO_FROM_QC,
    ACTION_STOP_IMAGE,
    ACTION_STOP_TIMING,
    ACTION_STOP_VIDEO,
    ACTION_VIDEO_QC,
    ACTION_VIDEO_SEMANTIC_QC,
    choose_next_action,
)


def make_state(
    *,
    timing_status="passed",
    render_duration_sec=5.0,
    script_revision_required=False,
    image_status=None,
    image_file=None,
    image_qc=None,
    image_semantic_qc=None,
    video_status=None,
    video_file=None,
    video_qc=None,
    video_semantic_qc=None,
):

    return {
        "timing_status":
            timing_status,

        "render_duration_sec":
            render_duration_sec,

        "script_revision_required":
            script_revision_required,

        "image_status":
            image_status,

        "image_file":
            image_file,

        "image_qc":
            image_qc,

        "image_semantic_qc":
            image_semantic_qc,

        "video_status":
            video_status,

        "video_file":
            video_file,

        "video_qc":
            video_qc,

        "video_semantic_qc":
            video_semantic_qc,
    }


class SceneOrchestratorTests(
    unittest.TestCase
):

    def choose(
        self,
        state,
        image_attempts=0,
        video_attempts=0,
        max_image_attempts=2,
        max_video_attempts=3,
    ):

        return choose_next_action(
            state=state,
            image_attempts=
                image_attempts,
            video_attempts=
                video_attempts,
            max_image_attempts=
                max_image_attempts,
            max_video_attempts=
                max_video_attempts,
        )


    def test_missing_timing_stops_before_image_generation(
        self,
    ):

        action = self.choose(
            make_state(
                timing_status=None,
                render_duration_sec=None,
            )
        )

        self.assertEqual(
            action,
            ACTION_STOP_TIMING,
        )


    def test_failed_timing_stops_before_image_generation(
        self,
    ):

        action = self.choose(
            make_state(
                timing_status="failed",
                render_duration_sec=None,
                script_revision_required=True,
            )
        )

        self.assertEqual(
            action,
            ACTION_STOP_TIMING,
        )


    def test_missing_image_generates_image(
        self,
    ):

        action = self.choose(
            make_state()
        )

        self.assertEqual(
            action,
            ACTION_GENERATE_IMAGE,
        )


    def test_generated_image_needs_qc(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
            ),
            image_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_IMAGE_QC,
        )


    def test_image_needs_semantic_qc(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
            ),
            image_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_IMAGE_SEMANTIC_QC,
        )


    def test_failed_image_semantic_qc_regenerates(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="failed",
            ),
            image_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_GENERATE_IMAGE,
        )


    def test_image_attempt_limit_stops(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="failed",
            ),
            image_attempts=2,
        )

        self.assertEqual(
            action,
            ACTION_STOP_IMAGE,
        )


    def test_good_image_generates_video(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="passed",
            ),
            image_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_GENERATE_VIDEO,
        )


    def test_generated_video_needs_qc(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="passed",

                video_status="generated",
                video_file="scene.mp4",
            ),
            image_attempts=1,
            video_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_VIDEO_QC,
        )


    def test_video_needs_semantic_qc(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="passed",

                video_status="generated",
                video_file="scene.mp4",
                video_qc="passed",
            ),
            image_attempts=1,
            video_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_VIDEO_SEMANTIC_QC,
        )


    def test_first_semantic_failure_uses_qc_retry(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="passed",

                video_status="generated",
                video_file="scene.mp4",
                video_qc="passed",
                video_semantic_qc="failed",
            ),
            image_attempts=1,
            video_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_RETRY_VIDEO_FROM_QC,
        )


    def test_second_semantic_failure_changes_motion(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="passed",

                video_status="generated",
                video_file="scene.mp4",
                video_qc="passed",
                video_semantic_qc="failed",
            ),
            image_attempts=1,
            video_attempts=2,
        )

        self.assertEqual(
            action,
            ACTION_REGENERATE_MOTION,
        )


    def test_third_semantic_failure_stops(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="passed",

                video_status="generated",
                video_file="scene.mp4",
                video_qc="passed",
                video_semantic_qc="failed",
            ),
            image_attempts=1,
            video_attempts=3,
        )

        self.assertEqual(
            action,
            ACTION_STOP_VIDEO,
        )


    def test_fully_passed_scene_is_complete(
        self,
    ):

        action = self.choose(
            make_state(
                image_status="generated",
                image_file="scene.png",
                image_qc="passed",
                image_semantic_qc="passed",

                video_status="generated",
                video_file="scene.mp4",
                video_qc="passed",
                video_semantic_qc="passed",
            ),
            image_attempts=1,
            video_attempts=1,
        )

        self.assertEqual(
            action,
            ACTION_COMPLETE,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )