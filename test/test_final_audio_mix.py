import tempfile
import unittest

from pathlib import Path

import final_audio_mix

from final_audio_mix import (
    build_ffmpeg_command,
    build_filter_complex,
    collect_mix_inputs,
    evaluate_mixed_video,
    get_total_duration,
    timeline_map,
)


class FinalAudioMixTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_root = (
            final_audio_mix
            .PROJECT_ROOT
        )


    def tearDown(
        self,
    ):

        final_audio_mix.PROJECT_ROOT = (
            self.old_root
        )


    def make_timeline(
        self,
    ):

        return [
            {
                "scene_id":
                    1,

                "start_sec":
                    0.0,

                "end_sec":
                    2.9,
            },
            {
                "scene_id":
                    2,

                "start_sec":
                    2.9,

                "end_sec":
                    9.45,
            },
        ]


    def test_timeline_map(
        self,
    ):

        mapping = timeline_map(
            self.make_timeline()
        )

        self.assertEqual(
            mapping[
                2
            ][
                "start_sec"
            ],
            2.9,
        )


    def test_total_duration_prefers_source_metadata(
        self,
    ):

        duration = get_total_duration(
            source_metadata={
                "duration_sec":
                    30.767,
            },
            timeline=[
                {
                    "end_sec":
                        30.75,
                },
            ],
        )

        self.assertEqual(
            duration,
            30.767,
        )


    def test_required_music_missing_fails(
        self,
    ):

        job = {
            "audio": {
                "background_music": {
                    "required":
                        True,

                    "audio_file":
                        None,
                },

                "sound_effects": {
                    "enabled":
                        False,
                },
            },
        }

        with self.assertRaises(
            RuntimeError
        ):

            collect_mix_inputs(
                job,
                self.make_timeline(),
            )


    def test_scene_relative_sfx_timing(
        self,
    ):

        with tempfile.TemporaryDirectory() as directory:

            root = Path(
                directory
            )

            final_audio_mix.PROJECT_ROOT = (
                root
            )

            music = (
                root
                / "music.wav"
            )

            sfx = (
                root
                / "door.wav"
            )

            music.write_bytes(
                b"music"
            )

            sfx.write_bytes(
                b"sfx"
            )

            job = {
                "audio": {
                    "background_music": {
                        "required":
                            True,

                        "audio_file":
                            "music.wav",

                        "volume":
                            0.2,
                    },

                    "sound_effects": {
                        "enabled":
                            True,

                        "effects": [
                            {
                                "scene_id":
                                    2,

                                "effect":
                                    "door slam",

                                "audio_file":
                                    "door.wav",

                                "offset_sec":
                                    1.25,

                                "volume":
                                    0.8,
                            },
                        ],
                    },
                },
            }

            music_data, effects, warnings = (
                collect_mix_inputs(
                    job,
                    self.make_timeline(),
                )
            )

            self.assertIsNotNone(
                music_data
            )

            self.assertEqual(
                effects[0][
                    "start_sec"
                ],
                4.15,
            )

            self.assertEqual(
                effects[0][
                    "timing_source"
                ],
                "scene_relative",
            )

            self.assertEqual(
                warnings,
                [],
            )


    def test_invalid_scene_sfx_is_skipped(
        self,
    ):

        job = {
            "audio": {
                "background_music": {
                    "required":
                        False,
                },

                "sound_effects": {
                    "enabled":
                        True,

                    "effects": [
                        {
                            "scene_id":
                                6,

                            "effect":
                                "notification",
                        },
                    ],
                },
            },
        }

        music, effects, warnings = (
            collect_mix_inputs(
                job,
                self.make_timeline(),
            )
        )

        self.assertIsNone(
            music
        )

        self.assertEqual(
            effects,
            [],
        )

        self.assertTrue(
            any(
                "not in the final assembly timeline"
                in warning
                for warning in warnings
            )
        )


    def test_filter_ducks_music_under_voice_and_delays_sfx(
        self,
    ):

        music = {
            "volume":
                0.2,
        }

        effects = [
            {
                "start_sec":
                    4.15,

                "volume":
                    0.8,
            },
        ]

        filter_complex, label = (
            build_filter_complex(
                total_duration=30.75,
                music=music,
                effects=effects,
            )
        )

        self.assertEqual(
            label,
            "[mixout]",
        )

        self.assertIn(
            "sidechaincompress=",
            filter_complex,
        )

        self.assertIn(
            "adelay=4150|4150",
            filter_complex,
        )

        self.assertIn(
            "amix=inputs=3",
            filter_complex,
        )


    def test_ffmpeg_command_copies_video_and_encodes_aac(
        self,
    ):

        command = build_ffmpeg_command(
            source_video=
                Path(
                    "with_subtitles.mp4"
                ),

            music=None,
            effects=[],
            total_duration=30.75,

            output_path=
                Path(
                    "final_audio_mix.mp4"
                ),
        )

        self.assertIn(
            "-c:v",
            command,
        )

        self.assertEqual(
            command[
                command.index(
                    "-c:v"
                )
                + 1
            ],
            "copy",
        )

        self.assertEqual(
            command[
                command.index(
                    "-c:a"
                )
                + 1
            ],
            "aac",
        )


    def test_mixed_video_qc_passes_matching_media(
        self,
    ):

        source = {
            "duration_sec":
                30.767,

            "width":
                1080,

            "height":
                1920,

            "fps":
                30.0,

            "video_codec":
                "h264",
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

            "audio_sample_rate":
                48000,
        }

        passed, errors, warnings = (
            evaluate_mixed_video(
                actual=actual,
                source_metadata=source,
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
