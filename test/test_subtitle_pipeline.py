import tempfile
import unittest

from pathlib import Path

import subtitle_pipeline

from subtitle_pipeline import (
    allocate_word_timings,
    build_burn_command,
    build_subtitle_cues,
    chunk_word_timings,
    evaluate_burned_video,
    get_subtitle_settings,
    render_ass,
    render_srt,
)


class SubtitlePipelineTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_root = (
            subtitle_pipeline
            .PROJECT_ROOT
        )


    def tearDown(
        self,
    ):

        subtitle_pipeline.PROJECT_ROOT = (
            self.old_root
        )


    def test_word_timing_fills_exact_voice_window(
        self,
    ):

        words = allocate_word_timings(
            text="Hello strange world!",
            start_sec=2.9,
            end_sec=5.9,
        )

        self.assertEqual(
            words[0][
                "start_sec"
            ],
            2.9,
        )

        self.assertEqual(
            words[-1][
                "end_sec"
            ],
            5.9,
        )

        for previous, current in zip(
            words,
            words[
                1:
            ],
        ):

            self.assertLessEqual(
                previous[
                    "end_sec"
                ],
                current[
                    "start_sec"
                ],
            )


    def test_chunking_respects_two_line_limit(
        self,
    ):

        words = allocate_word_timings(
            text=(
                "This is a deliberately longer subtitle "
                "sentence that needs multiple caption chunks."
            ),
            start_sec=0.0,
            end_sec=6.0,
        )

        chunks = chunk_word_timings(
            words=words,
            max_chars_per_line=20,
            max_lines=2,
        )

        self.assertGreater(
            len(
                chunks
            ),
            1,
        )

        for chunk in chunks:

            self.assertLessEqual(
                len(
                    chunk[
                        "lines"
                    ]
                ),
                2,
            )

            for line in chunk[
                "text"
            ].split(
                "\n"
            ):

                self.assertLessEqual(
                    len(
                        line
                    ),
                    20,
                )


    def test_cues_stop_at_voice_end_not_scene_end(
        self,
    ):

        job = {
            "subtitles": {
                "enabled":
                    True,
                "max_lines":
                    2,
                "max_chars_per_line":
                    32,
            },
            "script": {
                "scenes": [
                    {
                        "scene_id":
                            1,

                        "voice": {
                            "input_text":
                                "Hello from the narrator.",
                        },
                    },
                ],
            },
        }

        settings = get_subtitle_settings(
            job
        )

        cues = build_subtitle_cues(
            job=job,
            timeline=[
                {
                    "scene_id":
                        1,

                    "voice_start_sec":
                        0.0,

                    "voice_end_sec":
                        2.6,

                    "end_sec":
                        2.9,
                },
            ],
            settings=settings,
        )

        self.assertEqual(
            cues[-1][
                "end_sec"
            ],
            2.6,
        )


    def test_srt_render_contains_standard_timestamp(
        self,
    ):

        content = render_srt(
            [
                {
                    "index":
                        1,

                    "start_sec":
                        1.25,

                    "end_sec":
                        2.5,

                    "text":
                        "Hello world",
                },
            ]
        )

        self.assertIn(
            "00:00:01,250 --> 00:00:02,500",
            content,
        )

        self.assertIn(
            "Hello world",
            content,
        )


    def test_ass_render_contains_karaoke_word_tags(
        self,
    ):

        word1 = {
            "text":
                "Hello",

            "start_sec":
                0.0,

            "end_sec":
                0.5,
        }

        word2 = {
            "text":
                "world",

            "start_sec":
                0.5,

            "end_sec":
                1.0,
        }

        content = render_ass(
            cues=[
                {
                    "start_sec":
                        0.0,

                    "end_sec":
                        1.0,

                    "words": [
                        word1,
                        word2,
                    ],

                    "lines": [
                        [
                            word1,
                            word2,
                        ],
                    ],
                },
            ],
            settings={
                "font":
                    "Arial Bold",

                "font_size":
                    72,

                "margin_v":
                    320,

                "outline":
                    4,

                "shadow":
                    1,
            },
            width=1080,
            height=1920,
        )

        self.assertIn(
            "{\\k50}Hello",
            content,
        )

        self.assertIn(
            "{\\k50}world",
            content,
        )

        self.assertIn(
            "PlayResX: 1080",
            content,
        )

        self.assertIn(
            "PlayResY: 1920",
            content,
        )


    def test_burn_command_uses_relative_ass_filter(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            root = Path(
                directory
            )

            subtitle_pipeline.PROJECT_ROOT = (
                root
            )

            ass_path = (
                root
                / "output"
                / "job"
                / "subtitles"
                / "subtitles.ass"
            )

            command = build_burn_command(
                base_video=
                    root
                    / "base.mp4",

                ass_path=
                    ass_path,

                output_path=
                    root
                    / "with_subtitles.mp4",
            )

            filter_index = (
                command.index(
                    "-vf"
                )
            )

            filter_value = command[
                filter_index
                + 1
            ]

            self.assertIn(
                (
                    "output/job/subtitles/"
                    "subtitles.ass"
                ),
                filter_value,
            )

            self.assertNotIn(
                str(
                    root
                ),
                filter_value,
            )


    def test_burned_video_qc_matches_base(
        self,
    ):

        expected = {
            "duration_sec":
                30.75,

            "width":
                1080,

            "height":
                1920,

            "fps":
                30.0,

            "audio_codec":
                "aac",
        }

        actual = {
            "duration_sec":
                30.767,

            "width":
                1080,

            "height":
                1920,

            "fps":
                30.0,

            "video_stream_count":
                1,

            "audio_stream_count":
                1,

            "video_codec":
                "h264",

            "audio_codec":
                "aac",
        }

        passed, errors, warnings = (
            evaluate_burned_video(
                actual=actual,
                expected=expected,
            )
        )

        self.assertTrue(
            passed
        )

        self.assertEqual(
            errors,
            [],
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
