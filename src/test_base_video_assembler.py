import tempfile
import unittest

from pathlib import Path

import base_video_assembler

from base_video_assembler import (
    assembly_metadata_matches_current_request,
    build_filter_complex,
    build_timeline,
    collect_assembly_inputs,
    evaluate_assembled_media,
    get_output_settings,
    parse_resolution,
)


class BaseVideoAssemblerTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_root = (
            base_video_assembler
            .PROJECT_ROOT
        )

        self.old_tolerance = (
            base_video_assembler
            .DURATION_TOLERANCE_SEC
        )

        base_video_assembler.DURATION_TOLERANCE_SEC = (
            0.15
        )


    def tearDown(
        self,
    ):

        base_video_assembler.PROJECT_ROOT = (
            self.old_root
        )

        base_video_assembler.DURATION_TOLERANCE_SEC = (
            self.old_tolerance
        )


    def test_parse_resolution(
        self,
    ):

        self.assertEqual(
            parse_resolution(
                "1080x1920"
            ),
            (
                1080,
                1920,
            ),
        )


    def test_timeline_preserves_scene_headroom(
        self,
    ):

        timeline = build_timeline(
            [
                {
                    "scene_id": 1,
                    "target_duration_sec": 2.9,
                    "voice_duration_sec": 2.6,
                },
                {
                    "scene_id": 2,
                    "target_duration_sec": 6.55,
                    "voice_duration_sec": 6.25,
                },
            ]
        )

        self.assertEqual(
            timeline[0][
                "start_sec"
            ],
            0.0,
        )

        self.assertEqual(
            timeline[0][
                "end_sec"
            ],
            2.9,
        )

        self.assertEqual(
            timeline[0][
                "trailing_silence_sec"
            ],
            0.3,
        )

        self.assertEqual(
            timeline[1][
                "start_sec"
            ],
            2.9,
        )

        self.assertEqual(
            timeline[1][
                "voice_end_sec"
            ],
            9.15,
        )


    def test_filter_pads_voice_to_scene_duration(
        self,
    ):

        filter_complex = build_filter_complex(
            assembly_inputs=[
                {
                    "scene_id": 1,
                    "target_duration_sec": 2.9,
                },
                {
                    "scene_id": 2,
                    "target_duration_sec": 6.55,
                },
            ],
            width=1080,
            height=1920,
            fps=30.0,
            audio_sample_rate=48000,
        )

        self.assertIn(
            "scale=1080:1920",
            filter_complex,
        )

        self.assertIn(
            "atrim=duration=2.900",
            filter_complex,
        )

        self.assertIn(
            "atrim=duration=6.550",
            filter_complex,
        )

        self.assertIn(
            "concat=n=2:v=1:a=1",
            filter_complex,
        )


    def test_assembly_qc_passes_expected_media(
        self,
    ):

        settings = {
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "audio_sample_rate": 48000,
        }

        passed, errors, warnings = (
            evaluate_assembled_media(
                actual={
                    "duration_sec": 30.767,
                    "video_stream_count": 1,
                    "audio_stream_count": 1,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "width": 1080,
                    "height": 1920,
                    "fps": 30.0,
                    "audio_sample_rate": 48000,
                    "audio_channels": 2,
                },
                expected_duration_sec=30.75,
                settings=settings,
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )


    def test_assembly_qc_rejects_wrong_duration(
        self,
    ):

        settings = {
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "audio_sample_rate": 48000,
        }

        passed, errors, warnings = (
            evaluate_assembled_media(
                actual={
                    "duration_sec": 31.5,
                    "video_stream_count": 1,
                    "audio_stream_count": 1,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "width": 1080,
                    "height": 1920,
                    "fps": 30.0,
                    "audio_sample_rate": 48000,
                    "audio_channels": 2,
                },
                expected_duration_sec=30.75,
                settings=settings,
            )
        )

        self.assertFalse(
            passed
        )

        self.assertTrue(
            any(
                "differs from target"
                in error
                for error in errors
            )
        )


    def test_collect_inputs_requires_current_files(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            root = Path(
                directory
            )

            base_video_assembler.PROJECT_ROOT = (
                root
            )

            voice_file = (
                root
                / "voice.wav"
            )

            video_file = (
                root
                / "trimmed.mp4"
            )

            voice_file.write_bytes(
                b"voice"
            )

            video_file.write_bytes(
                b"video"
            )

            job = {
                "timing_summary": {
                    "status": "complete",
                    "script_revision_recommended": False,
                },
                "script": {
                    "scenes": [
                        {
                            "scene_id": 1,
                            "timing": {
                                "status": "passed",
                                "render_duration_sec": 2.9,
                            },
                            "voice": {
                                "file": "voice.wav",
                                "model": "tts",
                                "voice": "marin",
                                "speed": 1.0,
                                "input_text": "Hello.",
                                "qc": {
                                    "status": "passed",
                                    "checked_at": "now",
                                    "actual": {
                                        "duration_sec": 2.6,
                                    },
                                },
                            },
                        },
                    ],
                },
                "visuals": {
                    "scenes": [
                        {
                            "scene_id": 1,
                            "video": {
                                "task_id": "task-1",
                                "trimmed": {
                                    "status": "passed",
                                    "file": "trimmed.mp4",
                                    "checked_at": "now",
                                },
                            },
                        },
                    ],
                },
            }

            inputs = collect_assembly_inputs(
                job
            )

            self.assertEqual(
                len(
                    inputs
                ),
                1,
            )

            self.assertEqual(
                inputs[0][
                    "target_duration_sec"
                ],
                2.9,
            )


    def test_stale_source_signature_does_not_match(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            root = Path(
                directory
            )

            base_video_assembler.PROJECT_ROOT = (
                root
            )

            output_file = (
                root
                / "output"
                / "job"
                / "assembly"
                / "base_with_voice.mp4"
            )

            output_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_file.write_bytes(
                b"video"
            )

            signature = [
                {
                    "scene_id": 1,
                    "voice_qc_checked_at": "new",
                },
            ]

            job = {
                "assembly": {
                    "status": "passed",
                    "file": (
                        "output/job/assembly/"
                        "base_with_voice.mp4"
                    ),
                    "source_signature": [
                        {
                            "scene_id": 1,
                            "voice_qc_checked_at": "old",
                        },
                    ],
                    "expected": {
                        "duration_sec": 2.9,
                        "resolution": "1080x1920",
                        "fps": 30.0,
                    },
                },
            }

            settings = {
                "resolution": "1080x1920",
                "fps": 30.0,
            }

            self.assertFalse(
                assembly_metadata_matches_current_request(
                    job=job,
                    output_file=output_file,
                    source_signature=signature,
                    settings=settings,
                    expected_duration_sec=2.9,
                )
            )


    def test_output_settings_come_from_spec(
        self,
    ):

        settings = get_output_settings(
            {
                "video": {
                    "resolution": "1080x1920",
                    "fps": 30,
                },
            }
        )

        self.assertEqual(
            settings[
                "width"
            ],
            1080,
        )

        self.assertEqual(
            settings[
                "height"
            ],
            1920,
        )

        self.assertEqual(
            settings[
                "fps"
            ],
            30.0,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
