import copy
import unittest

from visual_prompt_generator import (
    MotionPromptOutput,
    MotionPromptScene,
    apply_motion_only_output,
    validate_motion_only_output,
)


def make_job() -> dict:

    return {
        "script": {
            "scenes": [
                {
                    "scene_id": 2,
                    "duration_sec": 7,
                },
            ],
        },

        "visuals": {
            "scenes": [
                {
                    "scene_id": 2,

                    "image_prompt":
                        "Approved image prompt.",

                    "motion_prompt":
                        "Old motion prompt.",

                    "continuity_notes":
                        "Keep both characters visible.",

                    "image": {
                        "status":
                            "generated",

                        "file":
                            "output/test/"
                            "images/scene_002.png",

                        "qc": {
                            "status":
                                "passed",
                        },

                        "semantic_qc": {
                            "status":
                                "passed",
                        },
                    },

                    "video": {
                        "status":
                            "generated",

                        "file":
                            "output/test/"
                            "videos/scene_002.mp4",

                        "qc": {
                            "status":
                                "passed",
                        },

                        "semantic_qc": {
                            "status":
                                "failed",
                        },
                    },
                },
            ],
        },
    }


class MotionOnlyTests(
    unittest.TestCase
):

    def test_changed_motion_invalidates_video_only(
        self,
    ):

        job = make_job()

        original_image = copy.deepcopy(
            job[
                "visuals"
            ][
                "scenes"
            ][0][
                "image"
            ]
        )

        output = MotionPromptOutput(
            scenes=[
                MotionPromptScene(
                    scene_id=2,
                    motion_prompt=(
                        "Mike remains visible while "
                        "the camera stays locked."
                    ),
                ),
            ],
        )

        invalidated = (
            apply_motion_only_output(
                job,
                output,
            )
        )

        scene = (
            job[
                "visuals"
            ][
                "scenes"
            ][0]
        )

        self.assertEqual(
            invalidated,
            [2],
        )

        self.assertEqual(
            scene["image"],
            original_image,
        )

        self.assertNotIn(
            "video",
            scene,
        )

        self.assertEqual(
            scene["image_prompt"],
            "Approved image prompt.",
        )


    def test_identical_motion_preserves_video(
        self,
    ):

        job = make_job()

        original_video = copy.deepcopy(
            job[
                "visuals"
            ][
                "scenes"
            ][0][
                "video"
            ]
        )

        output = MotionPromptOutput(
            scenes=[
                MotionPromptScene(
                    scene_id=2,
                    motion_prompt=(
                        "Old motion prompt."
                    ),
                ),
            ],
        )

        invalidated = (
            apply_motion_only_output(
                job,
                output,
            )
        )

        scene = (
            job[
                "visuals"
            ][
                "scenes"
            ][0]
        )

        self.assertEqual(
            invalidated,
            [],
        )

        self.assertEqual(
            scene["video"],
            original_video,
        )


    def test_simple_motion_passes_validation(
        self,
    ):

        script_scene = {
            "scene_id": 2,
        }

        output = MotionPromptOutput(
            scenes=[
                MotionPromptScene(
                    scene_id=2,
                    motion_prompt=(
                        "Mike remains visible. "
                        "The locked-off camera "
                        "remains still."
                    ),
                ),
            ],
        )

        errors = (
            validate_motion_only_output(
                script_scene,
                output,
            )
        )

        self.assertEqual(
            errors,
            [],
        )


    def test_wrong_scene_id_fails(
        self,
    ):

        script_scene = {
            "scene_id": 2,
        }

        output = MotionPromptOutput(
            scenes=[
                MotionPromptScene(
                    scene_id=3,
                    motion_prompt=(
                        "Simple motion."
                    ),
                ),
            ],
        )

        errors = (
            validate_motion_only_output(
                script_scene,
                output,
            )
        )

        self.assertTrue(
            errors
        )


    def test_complex_motion_fails(
        self,
    ):

        script_scene = {
            "scene_id": 2,
        }

        output = MotionPromptOutput(
            scenes=[
                MotionPromptScene(
                    scene_id=2,
                    motion_prompt=(
                        "Mike walks across the room "
                        "then turns around and after that "
                        "leaves the frame."
                    ),
                ),
            ],
        )

        errors = (
            validate_motion_only_output(
                script_scene,
                output,
            )
        )

        self.assertTrue(
            any(
                "too complex"
                in error
                for error in errors
            )
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )