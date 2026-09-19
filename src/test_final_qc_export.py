import tempfile
import unittest

from pathlib import Path

import final_qc_export

from final_qc_export import (
    build_export_metadata,
    build_source_signature,
    evaluate_technical_media,
    export_final_package,
    export_matches_current_request,
    get_export_paths,
    validate_metadata,
)


class FinalQCExportTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_root = (
            final_qc_export
            .PROJECT_ROOT
        )


    def tearDown(
        self,
    ):

        final_qc_export.PROJECT_ROOT = (
            self.old_root
        )


    def make_spec(
        self,
    ) -> dict:

        return {
            "video": {
                "target_duration_sec":
                    30,

                "min_duration_sec":
                    20,

                "max_duration_sec":
                    45,

                "resolution":
                    "1080x1920",

                "fps":
                    30,
            },

            "quality": {
                "technical": {
                    "resolution_required":
                        "1080x1920",

                    "audio_required":
                        True,

                    "max_file_size_mb":
                        100,
                },
            },

            "output": {
                "video_codec":
                    "h264",

                "audio_codec":
                    "aac",
            },

            "metadata": {
                "title": {
                    "max_length":
                        100,
                },

                "hashtags": {
                    "min":
                        3,

                    "max":
                        8,
                },
            },
        }


    def test_technical_qc_passes_expected_final_media(
        self,
    ):

        actual = {
            "duration_sec":
                30.767,

            "file_size_bytes":
                10_000_000,

            "video_stream_count":
                1,

            "audio_stream_count":
                1,

            "video_codec":
                "h264",

            "audio_codec":
                "aac",

            "width":
                1080,

            "height":
                1920,

            "fps":
                30.0,

            "audio_sample_rate":
                48000,
        }

        passed, errors, warnings = (
            evaluate_technical_media(
                actual,
                self.make_spec(),
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )

        self.assertEqual(
            warnings,
            [],
        )


    def test_technical_qc_rejects_wrong_resolution(
        self,
    ):

        actual = {
            "duration_sec":
                30.0,

            "file_size_bytes":
                10_000_000,

            "video_stream_count":
                1,

            "audio_stream_count":
                1,

            "video_codec":
                "h264",

            "audio_codec":
                "aac",

            "width":
                720,

            "height":
                1280,

            "fps":
                30.0,

            "audio_sample_rate":
                48000,
        }

        passed, errors, warnings = (
            evaluate_technical_media(
                actual,
                self.make_spec(),
            )
        )

        self.assertFalse(
            passed
        )

        self.assertTrue(
            any(
                "width"
                in error
                for error in errors
            )
        )

        self.assertTrue(
            any(
                "height"
                in error
                for error in errors
            )
        )


    def test_technical_qc_warns_outside_target_tolerance(
        self,
    ):

        actual = {
            "duration_sec":
                35.0,

            "file_size_bytes":
                10_000_000,

            "video_stream_count":
                1,

            "audio_stream_count":
                1,

            "video_codec":
                "h264",

            "audio_codec":
                "aac",

            "width":
                1080,

            "height":
                1920,

            "fps":
                30.0,

            "audio_sample_rate":
                48000,
        }

        passed, errors, warnings = (
            evaluate_technical_media(
                actual,
                self.make_spec(),
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
                "differs from target"
                in warning
                for warning in warnings
            )
        )


    def test_metadata_validation(
        self,
    ):

        job = {
            "metadata": {
                "title":
                    "My Cat Just Fired Me",

                "description":
                    "A comedy short.",

                "hashtags": [
                    "#funny",
                    "#cat",
                    "#shorts",
                ],
            },
        }

        errors, warnings = validate_metadata(
            job,
            self.make_spec(),
        )

        self.assertEqual(
            errors,
            [],
        )


    def test_metadata_validation_rejects_missing_description(
        self,
    ):

        job = {
            "metadata": {
                "title":
                    "My Cat Just Fired Me",

                "description":
                    "",

                "hashtags": [
                    "#funny",
                    "#cat",
                    "#shorts",
                ],
            },
        }

        errors, warnings = validate_metadata(
            job,
            self.make_spec(),
        )

        self.assertTrue(
            any(
                "description"
                in error.lower()
                for error in errors
            )
        )


    def test_export_package_copies_without_reencoding(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            root = Path(
                directory
            )

            final_qc_export.PROJECT_ROOT = (
                root
            )

            source = (
                root
                / "mix.mp4"
            )

            source.write_bytes(
                b"final-video-bytes"
            )

            subtitle_source = (
                root
                / "subtitles.srt"
            )

            subtitle_source.write_text(
                "subtitle",
                encoding="utf-8",
            )

            job = {
                "job_id":
                    "job-1",

                "script": {
                    "scenes":
                        [],
                },

                "subtitles": {
                    "subtitle_file":
                        "subtitles.srt",
                },

                "metadata": {
                    "title":
                        "Title",

                    "description":
                        "Description",

                    "hashtags": [
                        "#one",
                        "#two",
                        "#three",
                    ],
                },

                "publishing": {
                    "youtube_shorts": {
                        "enabled":
                            True,
                    },
                },
            }

            paths = get_export_paths(
                job
            )

            actual = {
                "duration_sec":
                    30.0,
            }

            export = export_final_package(
                job=job,
                source_video=source,
                actual=actual,
                warnings=[],
                paths=paths,
            )

            self.assertEqual(
                paths[
                    "video"
                ].read_bytes(),
                b"final-video-bytes",
            )

            self.assertTrue(
                paths[
                    "metadata"
                ].exists()
            )

            self.assertTrue(
                paths[
                    "script"
                ].exists()
            )

            self.assertTrue(
                paths[
                    "subtitles"
                ].exists()
            )

            self.assertEqual(
                export[
                    "video_file"
                ],
                "output/job-1/final/video.mp4",
            )


    def test_stale_export_signature_does_not_match(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            root = Path(
                directory
            )

            final_qc_export.PROJECT_ROOT = (
                root
            )

            source = (
                root
                / "mix.mp4"
            )

            source.write_bytes(
                b"video"
            )

            job = {
                "job_id":
                    "job-1",

                "script": {
                    "voiceover":
                        "Current script.",
                },

                "subtitles": {
                    "subtitle_file":
                        None,
                },

                "metadata": {
                    "title":
                        "Current title",

                    "description":
                        "Description",

                    "hashtags": [
                        "#one",
                        "#two",
                        "#three",
                    ],
                },
            }

            paths = get_export_paths(
                job
            )

            for key in (
                "video",
                "metadata",
                "script",
            ):

                paths[
                    key
                ].parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                paths[
                    key
                ].write_bytes(
                    b"x"
                )

            signature = build_source_signature(
                job,
                source,
            )

            job[
                "final_qc"
            ] = {
                "status":
                    "passed",

                "source_signature": {
                    **signature,
                    "script_voiceover":
                        "Old script.",
                },

                "export": {
                    "video_file":
                        "output/job-1/final/video.mp4",

                    "metadata_file":
                        "output/job-1/final/metadata.json",

                    "script_file":
                        "output/job-1/final/script.json",
                },
            }

            self.assertFalse(
                export_matches_current_request(
                    job,
                    signature,
                    paths,
                )
            )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
