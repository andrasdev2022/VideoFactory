import unittest

from unittest.mock import patch

import pipeline_orchestrator

from pipeline_orchestrator import (
    STAGE_GLOBAL_TIMING,
    STAGE_ORDER,
    STAGE_VISUAL_PROMPTS,
    all_scene_generation_completed,
    all_voice_timing_completed,
    should_stop_after,
)


class MasterPipelineOrchestratorTests(
    unittest.TestCase
):

    def test_expensive_visuals_start_after_global_timing(
        self,
    ):

        self.assertLess(
            STAGE_ORDER.index(
                STAGE_GLOBAL_TIMING
            ),
            STAGE_ORDER.index(
                STAGE_VISUAL_PROMPTS
            ),
        )


    def test_stop_after_matches_only_current_stage(
        self,
    ):

        self.assertTrue(
            should_stop_after(
                "subtitles",
                "subtitles",
            )
        )

        self.assertFalse(
            should_stop_after(
                "subtitles",
                "audio_mix",
            )
        )


    @patch(
        "pipeline_orchestrator.current_pipeline_status"
    )
    def test_voice_timing_completion_requires_all_three_stages(
        self,
        status_mock,
    ):

        status_mock.return_value = {
            "voiceovers": {
                "state":
                    "completed",
            },

            "voice_qc": {
                "state":
                    "completed",
            },

            "scene_timing": {
                "state":
                    "pending",
            },
        }

        self.assertFalse(
            all_voice_timing_completed()
        )

        status_mock.return_value[
            "scene_timing"
        ][
            "state"
        ] = "completed"

        self.assertTrue(
            all_voice_timing_completed()
        )


    @patch(
        "pipeline_orchestrator.current_pipeline_status"
    )
    def test_scene_completion_requires_trim_and_both_qc_layers(
        self,
        status_mock,
    ):

        names = (
            "scene_images",
            "image_qc",
            "image_semantic_qc",
            "scene_videos",
            "video_qc",
            "video_semantic_qc",
            "scene_trimmed",
        )

        status_mock.return_value = {
            name: {
                "state":
                    "completed",
            }
            for name in names
        }

        self.assertTrue(
            all_scene_generation_completed()
        )

        status_mock.return_value[
            "video_semantic_qc"
        ][
            "state"
        ] = "failed"

        self.assertFalse(
            all_scene_generation_completed()
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
