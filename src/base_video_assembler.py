from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline_status import (
    set_legacy_status_from_stage,
)

from validator import (
    load_json,
)

from video_qc import (
    parse_fps,
    run_ffprobe,
)


from genre_policy import runtime_spec as load_yaml

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

JOB_FILE = (
    PROJECT_ROOT
    / "jobs"
    / "video_job.json"
)

SPEC_FILE = (
    PROJECT_ROOT
    / "config"
    / "video_spec_v1.yaml"
)


DURATION_TOLERANCE_SEC = float(
    os.getenv(
        "BASE_ASSEMBLY_DURATION_TOLERANCE_SEC",
        "0.15",
    )
)

CRF = int(
    os.getenv(
        "BASE_ASSEMBLY_CRF",
        "16",
    )
)

PRESET = os.getenv(
    "BASE_ASSEMBLY_PRESET",
    "medium",
)

AUDIO_SAMPLE_RATE = int(
    os.getenv(
        "BASE_ASSEMBLY_AUDIO_SAMPLE_RATE",
        "48000",
    )
)

AUDIO_BITRATE = os.getenv(
    "BASE_ASSEMBLY_AUDIO_BITRATE",
    "192k",
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Assemble exact-duration scene clips and "
            "natural voice WAVs into one base video."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rebuild the base assembly even when "
            "current metadata and output already match."
        ),
    )

    return parser.parse_args()


def save_job_atomic(
    job: dict,
) -> None:

    temporary_file = (
        JOB_FILE.with_name(
            JOB_FILE.name
            + ".tmp"
        )
    )

    temporary_file.write_text(
        json.dumps(
            job,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary_file,
        JOB_FILE,
    )


def parse_resolution(
    value: str,
) -> tuple[int, int]:

    parts = value.lower().split(
        "x",
        1,
    )

    if len(
        parts
    ) != 2:

        raise RuntimeError(
            f"Invalid resolution: {value}"
        )

    try:

        width = int(
            parts[0]
        )

        height = int(
            parts[1]
        )

    except ValueError as exc:

        raise RuntimeError(
            f"Invalid resolution: {value}"
        ) from exc

    if (
        width <= 0
        or height <= 0
    ):

        raise RuntimeError(
            f"Invalid resolution: {value}"
        )

    return (
        width,
        height,
    )


def find_script_scene(
    job: dict,
    scene_id: int,
) -> dict | None:

    for scene in (
        job
        .get(
            "script",
            {},
        )
        .get(
            "scenes",
            [],
        )
    ):

        if scene.get(
            "scene_id"
        ) == scene_id:

            return scene

    return None


def find_visual_scene(
    job: dict,
    scene_id: int,
) -> dict | None:

    for scene in (
        job
        .get(
            "visuals",
            {},
        )
        .get(
            "scenes",
            [],
        )
    ):

        if scene.get(
            "scene_id"
        ) == scene_id:

            return scene

    return None


def get_base_output_path(
    job: dict,
) -> Path:

    return (
        PROJECT_ROOT
        / "output"
        / str(
            job[
                "job_id"
            ]
        )
        / "assembly"
        / "base_with_voice.mp4"
    )


def get_output_settings(
    spec: dict,
) -> dict[str, Any]:

    resolution_text = (
        spec
        .get(
            "video",
            {},
        )
        .get(
            "resolution",
            "1080x1920",
        )
    )

    fps = float(
        spec
        .get(
            "video",
            {},
        )
        .get(
            "fps",
            30,
        )
    )

    width, height = parse_resolution(
        resolution_text
    )

    if fps <= 0:

        raise RuntimeError(
            "Output FPS must be positive."
        )

    return {
        "resolution":
            resolution_text,

        "width":
            width,

        "height":
            height,

        "fps":
            fps,

        "audio_sample_rate":
            AUDIO_SAMPLE_RATE,

        "audio_bitrate":
            AUDIO_BITRATE,
    }


def collect_assembly_inputs(
    job: dict,
) -> list[dict[str, Any]]:

    summary = job.get(
        "timing_summary",
        {},
    )

    if (
        summary.get(
            "status"
        )
        != "complete"
    ):

        raise RuntimeError(
            "Global timing summary is not complete."
        )

    if summary.get(
        "script_revision_recommended"
    ):

        raise RuntimeError(
            "Global timing still recommends "
            "script revision."
        )

    script_scenes = (
        job
        .get(
            "script",
            {},
        )
        .get(
            "scenes",
            [],
        )
    )

    if not script_scenes:

        raise RuntimeError(
            "Script contains no scenes."
        )

    result: list[
        dict[str, Any]
    ] = []

    for script_scene in script_scenes:

        scene_id = script_scene.get(
            "scene_id"
        )

        if scene_id is None:

            raise RuntimeError(
                "Script scene is missing scene_id."
            )

        visual_scene = find_visual_scene(
            job,
            scene_id,
        )

        if visual_scene is None:

            raise RuntimeError(
                f"Scene {scene_id}: visual scene "
                f"is missing."
            )

        timing = script_scene.get(
            "timing",
            {},
        )

        if timing.get(
            "status"
        ) != "passed":

            raise RuntimeError(
                f"Scene {scene_id}: timing "
                f"has not passed."
            )

        target_duration = timing.get(
            "render_duration_sec"
        )

        if target_duration is None:

            raise RuntimeError(
                f"Scene {scene_id}: render "
                f"duration is missing."
            )

        target_duration = float(
            target_duration
        )

        voice = script_scene.get(
            "voice",
            {},
        )

        if voice.get(
            "qc",
            {},
        ).get(
            "status"
        ) != "passed":

            raise RuntimeError(
                f"Scene {scene_id}: voice QC "
                f"has not passed."
            )

        voice_file = voice.get(
            "file"
        )

        if not voice_file:

            raise RuntimeError(
                f"Scene {scene_id}: voice file "
                f"metadata is missing."
            )

        voice_path = (
            PROJECT_ROOT
            / voice_file
        )

        if not voice_path.exists():

            raise RuntimeError(
                f"Scene {scene_id}: voice file "
                f"does not exist: {voice_file}"
            )

        voice_duration = (
            voice
            .get(
                "qc",
                {},
            )
            .get(
                "actual",
                {},
            )
            .get(
                "duration_sec"
            )
        )

        if voice_duration is None:

            raise RuntimeError(
                f"Scene {scene_id}: measured "
                f"voice duration is missing."
            )

        voice_duration = float(
            voice_duration
        )

        if (
            voice_duration
            > target_duration
            + 0.001
        ):

            raise RuntimeError(
                f"Scene {scene_id}: voice duration "
                f"{voice_duration:.3f}s exceeds "
                f"render duration "
                f"{target_duration:.3f}s."
            )

        video = visual_scene.get(
            "video",
            {},
        )

        trimmed = video.get(
            "trimmed",
            {},
        )

        if trimmed.get(
            "status"
        ) != "passed":

            raise RuntimeError(
                f"Scene {scene_id}: exact "
                f"video trim has not passed."
            )

        trimmed_file = trimmed.get(
            "file"
        )

        if not trimmed_file:

            raise RuntimeError(
                f"Scene {scene_id}: trimmed "
                f"video file metadata is missing."
            )

        trimmed_path = (
            PROJECT_ROOT
            / trimmed_file
        )

        if not trimmed_path.exists():

            raise RuntimeError(
                f"Scene {scene_id}: trimmed video "
                f"does not exist: {trimmed_file}"
            )

        result.append(
            {
                "scene_id":
                    int(
                        scene_id
                    ),

                "target_duration_sec":
                    round(
                        target_duration,
                        3,
                    ),

                "voice_duration_sec":
                    round(
                        voice_duration,
                        3,
                    ),

                "video_file":
                    trimmed_file,

                "video_path":
                    trimmed_path,

                "voice_file":
                    voice_file,

                "voice_path":
                    voice_path,

                "source_task_id":
                    video.get(
                        "task_id"
                    ),

                "trim_checked_at":
                    trimmed.get(
                        "checked_at"
                    ),

                "voice_qc_checked_at":
                    voice
                    .get(
                        "qc",
                        {},
                    )
                    .get(
                        "checked_at"
                    ),

                "voice_model":
                    voice.get(
                        "model"
                    ),

                "voice_name":
                    voice.get(
                        "voice"
                    ),

                "voice_speed":
                    voice.get(
                        "speed"
                    ),

                "voice_text":
                    voice.get(
                        "input_text"
                    ),
            }
        )

    return result


def build_timeline(
    assembly_inputs: list[
        dict[str, Any]
    ],
) -> list[dict[str, Any]]:

    timeline: list[
        dict[str, Any]
    ] = []

    cursor = 0.0

    for item in assembly_inputs:

        render_duration = float(
            item[
                "target_duration_sec"
            ]
        )

        voice_duration = float(
            item[
                "voice_duration_sec"
            ]
        )

        start = cursor
        end = start + render_duration
        voice_end = start + voice_duration

        timeline.append(
            {
                "scene_id":
                    item[
                        "scene_id"
                    ],

                "start_sec":
                    round(
                        start,
                        3,
                    ),

                "end_sec":
                    round(
                        end,
                        3,
                    ),

                "render_duration_sec":
                    round(
                        render_duration,
                        3,
                    ),

                "voice_start_sec":
                    round(
                        start,
                        3,
                    ),

                "voice_end_sec":
                    round(
                        voice_end,
                        3,
                    ),

                "voice_duration_sec":
                    round(
                        voice_duration,
                        3,
                    ),

                "trailing_silence_sec":
                    round(
                        max(
                            0.0,
                            render_duration
                            - voice_duration,
                        ),
                        3,
                    ),
            }
        )

        cursor = end

    return timeline


def build_source_signature(
    assembly_inputs: list[
        dict[str, Any]
    ],
) -> list[dict[str, Any]]:

    return [
        {
            "scene_id":
                item[
                    "scene_id"
                ],

            "video_file":
                item[
                    "video_file"
                ],

            "source_task_id":
                item[
                    "source_task_id"
                ],

            "trim_checked_at":
                item[
                    "trim_checked_at"
                ],

            "target_duration_sec":
                item[
                    "target_duration_sec"
                ],

            "voice_file":
                item[
                    "voice_file"
                ],

            "voice_qc_checked_at":
                item[
                    "voice_qc_checked_at"
                ],

            "voice_duration_sec":
                item[
                    "voice_duration_sec"
                ],

            "voice_model":
                item[
                    "voice_model"
                ],

            "voice_name":
                item[
                    "voice_name"
                ],

            "voice_speed":
                item[
                    "voice_speed"
                ],

            "voice_text":
                item[
                    "voice_text"
                ],
        }
        for item in assembly_inputs
    ]


def build_filter_complex(
    assembly_inputs: list[
        dict[str, Any]
    ],
    width: int,
    height: int,
    fps: float,
    audio_sample_rate: int,
) -> str:

    filters: list[str] = []

    concat_parts: list[str] = []

    for index, item in enumerate(
        assembly_inputs
    ):

        video_input = (
            index
            * 2
        )

        audio_input = (
            video_input
            + 1
        )

        duration = float(
            item[
                "target_duration_sec"
            ]
        )

        filters.append(
            (
                f"[{video_input}:v]"
                f"scale={width}:{height}:"
                f"flags=lanczos,"
                f"setsar=1,"
                f"fps={fps:.3f},"
                f"trim=duration={duration:.3f},"
                f"setpts=PTS-STARTPTS"
                f"[v{index}]"
            )
        )

        filters.append(
            (
                f"[{audio_input}:a]"
                f"aresample={audio_sample_rate},"
                f"aformat=sample_fmts=fltp:"
                f"sample_rates={audio_sample_rate}:"
                f"channel_layouts=stereo,"
                f"apad,"
                f"atrim=duration={duration:.3f},"
                f"asetpts=PTS-STARTPTS"
                f"[a{index}]"
            )
        )

        concat_parts.append(
            f"[v{index}]"
            f"[a{index}]"
        )

    filters.append(
        (
            "".join(
                concat_parts
            )
            + (
                f"concat=n="
                f"{len(assembly_inputs)}:"
                f"v=1:a=1"
                f"[vout][aout]"
            )
        )
    )

    return ";".join(
        filters
    )


def build_ffmpeg_command(
    assembly_inputs: list[
        dict[str, Any]
    ],
    output_file: Path,
    settings: dict[str, Any],
) -> list[str]:

    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
    ]

    for item in assembly_inputs:

        command.extend(
            [
                "-i",
                str(
                    item[
                        "video_path"
                    ]
                ),

                "-i",
                str(
                    item[
                        "voice_path"
                    ]
                ),
            ]
        )

    filter_complex = build_filter_complex(
        assembly_inputs=
            assembly_inputs,
        width=settings[
            "width"
        ],
        height=settings[
            "height"
        ],
        fps=settings[
            "fps"
        ],
        audio_sample_rate=
            settings[
                "audio_sample_rate"
            ],
    )

    command.extend(
        [
            "-filter_complex",
            filter_complex,

            "-map",
            "[vout]",

            "-map",
            "[aout]",

            "-c:v",
            "libx264",

            "-preset",
            PRESET,

            "-crf",
            str(
                CRF
            ),

            "-pix_fmt",
            "yuv420p",

            "-c:a",
            "aac",

            "-b:a",
            settings[
                "audio_bitrate"
            ],

            "-ar",
            str(
                settings[
                    "audio_sample_rate"
                ]
            ),

            "-movflags",
            "+faststart",

            str(
                output_file
            ),
        ]
    )

    return command


def analyze_assembled_media(
    media_path: Path,
) -> dict[str, Any]:

    probe = run_ffprobe(
        media_path
    )

    streams = probe.get(
        "streams",
        [],
    )

    format_data = probe.get(
        "format",
        {},
    )

    video_streams = [
        stream
        for stream in streams
        if stream.get(
            "codec_type"
        ) == "video"
    ]

    audio_streams = [
        stream
        for stream in streams
        if stream.get(
            "codec_type"
        ) == "audio"
    ]

    video_stream = (
        video_streams[0]
        if video_streams
        else {}
    )

    audio_stream = (
        audio_streams[0]
        if audio_streams
        else {}
    )

    duration = None

    duration_text = format_data.get(
        "duration"
    )

    if duration_text is not None:

        try:

            duration = float(
                duration_text
            )

        except ValueError:

            pass

    fps = parse_fps(
        video_stream.get(
            "avg_frame_rate"
        )
    )

    if fps is None:

        fps = parse_fps(
            video_stream.get(
                "r_frame_rate"
            )
        )

    sample_rate = None

    sample_rate_text = (
        audio_stream.get(
            "sample_rate"
        )
    )

    if sample_rate_text is not None:

        try:

            sample_rate = int(
                sample_rate_text
            )

        except ValueError:

            pass

    channels = (
        audio_stream.get(
            "channels"
        )
    )

    return {
        "file_size_bytes":
            media_path
            .stat()
            .st_size,

        "duration_sec":
            (
                round(
                    duration,
                    3,
                )
                if duration
                is not None
                else None
            ),

        "video_stream_count":
            len(
                video_streams
            ),

        "audio_stream_count":
            len(
                audio_streams
            ),

        "video_codec":
            video_stream.get(
                "codec_name"
            ),

        "pixel_format":
            video_stream.get(
                "pix_fmt"
            ),

        "width":
            video_stream.get(
                "width"
            ),

        "height":
            video_stream.get(
                "height"
            ),

        "fps":
            (
                round(
                    fps,
                    3,
                )
                if fps is not None
                else None
            ),

        "audio_codec":
            audio_stream.get(
                "codec_name"
            ),

        "audio_sample_rate":
            sample_rate,

        "audio_channels":
            channels,

        "format_name":
            format_data.get(
                "format_name"
            ),
    }


def evaluate_assembled_media(
    actual: dict[str, Any],
    expected_duration_sec: float,
    settings: dict[str, Any],
) -> tuple[
    bool,
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    duration = actual.get(
        "duration_sec"
    )

    if duration is None:

        errors.append(
            "Unable to determine assembly duration."
        )

    else:

        difference = abs(
            float(
                duration
            )
            - float(
                expected_duration_sec
            )
        )

        if (
            difference
            > DURATION_TOLERANCE_SEC
        ):

            errors.append(
                f"Assembly duration differs from target "
                f"by {difference:.3f}s; tolerance is "
                f"{DURATION_TOLERANCE_SEC:.3f}s."
            )

    if actual.get(
        "video_stream_count"
    ) != 1:

        errors.append(
            "Assembly must contain exactly "
            "one video stream."
        )

    if actual.get(
        "audio_stream_count"
    ) != 1:

        errors.append(
            "Assembly must contain exactly "
            "one audio stream."
        )

    if actual.get(
        "video_codec"
    ) != "h264":

        errors.append(
            f"Assembly video codec is "
            f"'{actual.get('video_codec')}', "
            f"expected H.264."
        )

    if actual.get(
        "audio_codec"
    ) != "aac":

        errors.append(
            f"Assembly audio codec is "
            f"'{actual.get('audio_codec')}', "
            f"expected AAC."
        )

    if (
        actual.get(
            "width"
        )
        != settings[
            "width"
        ]
        or actual.get(
            "height"
        )
        != settings[
            "height"
        ]
    ):

        errors.append(
            f"Assembly resolution is "
            f"{actual.get('width')}x"
            f"{actual.get('height')}; "
            f"expected "
            f"{settings['width']}x"
            f"{settings['height']}."
        )

    fps = actual.get(
        "fps"
    )

    if fps is None:

        errors.append(
            "Unable to determine assembly FPS."
        )

    elif abs(
        float(
            fps
        )
        - float(
            settings[
                "fps"
            ]
        )
    ) > 0.05:

        errors.append(
            f"Assembly FPS is {fps}; expected "
            f"{settings['fps']}."
        )

    if (
        actual.get(
            "audio_sample_rate"
        )
        != settings[
            "audio_sample_rate"
        ]
    ):

        errors.append(
            f"Assembly audio sample rate is "
            f"{actual.get('audio_sample_rate')}; "
            f"expected "
            f"{settings['audio_sample_rate']}."
        )

    if actual.get(
        "audio_channels"
    ) != 2:

        warnings.append(
            f"Assembly audio channel count is "
            f"{actual.get('audio_channels')}; "
            f"expected stereo."
        )

    return (
        not errors,
        errors,
        warnings,
    )


def assembly_metadata_matches_current_request(
    job: dict,
    output_file: Path,
    source_signature: list[
        dict[str, Any]
    ],
    settings: dict[str, Any],
    expected_duration_sec: float,
) -> bool:

    assembly = job.get(
        "assembly",
        {},
    )

    if assembly.get(
        "status"
    ) != "passed":

        return False

    expected_file = str(
        output_file.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    if assembly.get(
        "file"
    ) != expected_file:

        return False

    if assembly.get(
        "source_signature"
    ) != source_signature:

        return False

    expected = assembly.get(
        "expected",
        {},
    )

    try:

        stored_duration = float(
            expected.get(
                "duration_sec"
            )
        )

        stored_fps = float(
            expected.get(
                "fps"
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        return False

    if abs(
        stored_duration
        - float(
            expected_duration_sec
        )
    ) > 0.001:

        return False

    if expected.get(
        "resolution"
    ) != settings[
        "resolution"
    ]:

        return False

    if abs(
        stored_fps
        - float(
            settings[
                "fps"
            ]
        )
    ) > 0.001:

        return False

    return output_file.exists()


def invalidate_downstream_outputs(
    job: dict,
) -> None:

    output = job.get(
        "output"
    )

    if isinstance(
        output,
        dict,
    ):

        output[
            "video_file"
        ] = None

    subtitles = job.get(
        "subtitles"
    )

    if isinstance(
        subtitles,
        dict,
    ):

        subtitles.pop(
            "generation",
            None,
        )

        subtitles.pop(
            "render",
            None,
        )

        subtitles[
            "subtitle_file"
        ] = None

    if isinstance(
        output,
        dict,
    ):

        output[
            "subtitled_video_file"
        ] = None

    job.pop(
        "subtitles_render",
        None,
    )

    audio = job.get(
        "audio"
    )

    if isinstance(
        audio,
        dict,
    ):

        audio.pop(
            "mix",
            None,
        )

    if isinstance(
        output,
        dict,
    ):

        output[
            "mixed_video_file"
        ] = None

    job.pop(
        "final_mix",
        None,
    )

    job.pop(
        "final_qc",
        None,
    )


def assemble_base_video(
    job: dict,
    spec: dict,
    force: bool,
) -> bool:

    if shutil.which(
        "ffmpeg"
    ) is None:

        raise RuntimeError(
            "ffmpeg is not available on PATH."
        )

    if shutil.which(
        "ffprobe"
    ) is None:

        raise RuntimeError(
            "ffprobe is not available on PATH."
        )

    settings = get_output_settings(
        spec
    )

    assembly_inputs = (
        collect_assembly_inputs(
            job
        )
    )

    source_signature = (
        build_source_signature(
            assembly_inputs
        )
    )

    timeline = build_timeline(
        assembly_inputs
    )

    expected_duration = round(
        sum(
            float(
                item[
                    "target_duration_sec"
                ]
            )
            for item in assembly_inputs
        ),
        3,
    )

    output_file = get_base_output_path(
        job
    )

    if (
        not force
        and assembly_metadata_matches_current_request(
            job=job,
            output_file=output_file,
            source_signature=
                source_signature,
            settings=settings,
            expected_duration_sec=
                expected_duration,
        )
    ):

        print(
            "Base assembly already matches "
            "current scene/video/voice inputs."
        )

        return False

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        output_file
        .with_name(
            output_file.stem
            + ".tmp"
            + output_file.suffix
        )
    )

    if temporary_file.exists():

        temporary_file.unlink()

    invalidate_downstream_outputs(
        job
    )

    command = build_ffmpeg_command(
        assembly_inputs=
            assembly_inputs,
        output_file=
            temporary_file,
        settings=
            settings,
    )

    print(
        f"\nScenes:       "
        f"{len(assembly_inputs)}"
    )

    print(
        f"Duration:     "
        f"{expected_duration:.3f}s"
    )

    print(
        f"Resolution:   "
        f"{settings['resolution']}"
    )

    print(
        f"FPS:          "
        f"{settings['fps']:.3f}"
    )

    print(
        f"Audio:        "
        f"AAC "
        f"{settings['audio_sample_rate']} Hz "
        f"{settings['audio_bitrate']}"
    )

    print(
        f"Output:       "
        f"{output_file.relative_to(PROJECT_ROOT)}"
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:

        if temporary_file.exists():

            temporary_file.unlink()

        raise RuntimeError(
            "ffmpeg base assembly failed:\n"
            + result.stderr.strip()
        )

    if (
        not temporary_file.exists()
        or temporary_file.stat().st_size
        <= 0
    ):

        raise RuntimeError(
            "ffmpeg did not create a valid "
            "base assembly file."
        )

    actual = analyze_assembled_media(
        temporary_file
    )

    (
        passed,
        errors,
        warnings,
    ) = evaluate_assembled_media(
        actual=actual,
        expected_duration_sec=
            expected_duration,
        settings=settings,
    )

    checked_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    if not passed:

        if temporary_file.exists():

            temporary_file.unlink()

        job[
            "assembly"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "expected": {
                "duration_sec":
                    expected_duration,

                "resolution":
                    settings[
                        "resolution"
                    ],

                "fps":
                    settings[
                        "fps"
                    ],
            },

            "source_signature":
                source_signature,

            "timeline":
                timeline,

            "actual":
                actual,

            "errors":
                errors,

            "warnings":
                warnings,
        }

        return False

    os.replace(
        temporary_file,
        output_file,
    )

    relative_output = str(
        output_file.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    job[
        "assembly"
    ] = {
        "status":
            "passed",

        "checked_at":
            checked_at,

        "type":
            "base_with_voice",

        "file":
            relative_output,

        "expected": {
            "duration_sec":
                expected_duration,

            "resolution":
                settings[
                    "resolution"
                ],

            "width":
                settings[
                    "width"
                ],

            "height":
                settings[
                    "height"
                ],

            "fps":
                settings[
                    "fps"
                ],

            "audio_sample_rate":
                settings[
                    "audio_sample_rate"
                ],

            "audio_bitrate":
                settings[
                    "audio_bitrate"
                ],
        },

        "encoder": {
            "video_codec":
                "libx264",

            "video_crf":
                CRF,

            "video_preset":
                PRESET,

            "audio_codec":
                "aac",
        },

        "source_signature":
            source_signature,

        "timeline":
            timeline,

        "actual":
            actual,

        "errors":
            [],

        "warnings":
            warnings,
    }

    output = job.setdefault(
        "output",
        {},
    )

    output[
        "base_video_file"
    ] = relative_output

    print(
        f"Actual duration: "
        f"{actual.get('duration_sec')}s"
    )

    print(
        "PASS"
    )

    return True


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - BASE VIDEO ASSEMBLER v1")
    print("=" * 60)

    args = parse_args()

    try:

        job = load_json(
            JOB_FILE
        )

        spec = load_yaml(
            SPEC_FILE
        )

    except Exception as exc:

        print(
            f"\nERROR loading input files:\n"
            f"{exc}"
        )

        return 1

    try:

        assemble_base_video(
            job=job,
            spec=spec,
            force=args.force,
        )

    except Exception as exc:

        job[
            "assembly"
        ] = {
            "status":
                "failed",

            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "errors": [
                str(
                    exc
                )
            ],

            "warnings":
                [],
        }

        set_legacy_status_from_stage(
            job,
            "base_assembly",
        )

        save_job_atomic(
            job
        )

        print(
            f"\nERROR: {exc}"
        )

        return 1

    set_legacy_status_from_stage(
        job,
        "base_assembly",
    )

    save_job_atomic(
        job
    )

    assembly = job.get(
        "assembly",
        {},
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "BASE VIDEO ASSEMBLY COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nStatus:   "
        f"{assembly.get('status')}"
    )

    print(
        f"File:     "
        f"{assembly.get('file')}"
    )

    print(
        f"Duration: "
        f"{assembly.get('actual', {}).get('duration_sec')}"
    )

    return (
        0
        if assembly.get(
            "status"
        )
        == "passed"
        else 1
    )


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
