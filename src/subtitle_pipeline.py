from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from base_video_assembler import (
    analyze_assembled_media,
)

from pipeline_status import (
    set_legacy_status_from_stage,
)

from validator import load_json


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


SUBTITLE_FONT_SIZE = int(
    os.getenv(
        "SUBTITLE_FONT_SIZE",
        "72",
    )
)

SUBTITLE_MARGIN_V = int(
    os.getenv(
        "SUBTITLE_MARGIN_V",
        "320",
    )
)

SUBTITLE_OUTLINE = int(
    os.getenv(
        "SUBTITLE_OUTLINE",
        "4",
    )
)

SUBTITLE_SHADOW = int(
    os.getenv(
        "SUBTITLE_SHADOW",
        "1",
    )
)

SUBTITLE_VIDEO_CRF = int(
    os.getenv(
        "SUBTITLE_VIDEO_CRF",
        "16",
    )
)

SUBTITLE_VIDEO_PRESET = os.getenv(
    "SUBTITLE_VIDEO_PRESET",
    "medium",
)

DURATION_TOLERANCE_SEC = float(
    os.getenv(
        "SUBTITLE_DURATION_TOLERANCE_SEC",
        "0.15",
    )
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Generate SRT/ASS subtitles from the approved "
            "voice timeline and burn them into the base video."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Regenerate subtitle artifacts and rebuild "
            "the subtitled video."
        ),
    )

    parser.add_argument(
        "--files-only",
        action="store_true",
        help=(
            "Generate subtitle files but do not burn them "
            "into the base video."
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


def get_subtitle_settings(
    job: dict,
) -> dict[str, Any]:

    config = job.get(
        "subtitles",
        {},
    )

    style = config.get(
        "style",
        {},
    )

    return {
        "enabled":
            bool(
                config.get(
                    "enabled",
                    True,
                )
            ),

        "language":
            config.get(
                "language",
                "en",
            ),

        "burned_in":
            bool(
                config.get(
                    "burned_in",
                    True,
                )
            ),

        "max_lines":
            int(
                config.get(
                    "max_lines",
                    2,
                )
            ),

        "max_chars_per_line":
            int(
                config.get(
                    "max_chars_per_line",
                    32,
                )
            ),

        "font":
            style.get(
                "font",
                "Arial Bold",
            ),

        "position":
            style.get(
                "position",
                "lower_center",
            ),

        "animation":
            style.get(
                "animation",
                "word_highlight",
            ),

        "font_size":
            SUBTITLE_FONT_SIZE,

        "margin_v":
            SUBTITLE_MARGIN_V,

        "outline":
            SUBTITLE_OUTLINE,

        "shadow":
            SUBTITLE_SHADOW,
    }


def get_artifact_paths(
    job: dict,
) -> dict[str, Path]:

    root = (
        PROJECT_ROOT
        / "output"
        / str(
            job[
                "job_id"
            ]
        )
    )

    return {
        "srt":
            root
            / "subtitles"
            / "subtitles.srt",

        "ass":
            root
            / "subtitles"
            / "subtitles.ass",

        "video":
            root
            / "assembly"
            / "with_subtitles.mp4",
    }


def relative_path(
    path: Path,
) -> str:

    return str(
        path.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )


def validate_preconditions(
    job: dict,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
]:

    assembly = job.get(
        "assembly",
        {},
    )

    if assembly.get(
        "status"
    ) != "passed":

        raise RuntimeError(
            "Base assembly has not passed."
        )

    assembly_file = assembly.get(
        "file"
    )

    if not assembly_file:

        raise RuntimeError(
            "Base assembly file metadata is missing."
        )

    assembly_path = (
        PROJECT_ROOT
        / assembly_file
    )

    if not assembly_path.exists():

        raise RuntimeError(
            f"Base assembly file does not exist: "
            f"{assembly_file}"
        )

    timeline = assembly.get(
        "timeline"
    )

    if not isinstance(
        timeline,
        list,
    ) or not timeline:

        raise RuntimeError(
            "Base assembly timeline is missing."
        )

    return (
        assembly,
        timeline,
    )


def get_scene_voice_text(
    job: dict,
    scene_id: int,
) -> str:

    scene = find_script_scene(
        job,
        scene_id,
    )

    if scene is None:

        raise RuntimeError(
            f"Scene {scene_id}: script scene is missing."
        )

    voice = scene.get(
        "voice",
        {},
    )

    text = voice.get(
        "input_text"
    )

    if not isinstance(
        text,
        str,
    ) or not text.strip():

        raise RuntimeError(
            f"Scene {scene_id}: voice.input_text is missing."
        )

    return " ".join(
        text.split()
    )


def word_weight(
    token: str,
) -> float:

    spoken = re.sub(
        r"[^\w']+",
        "",
        token,
        flags=re.UNICODE,
    )

    base = max(
        len(
            spoken
        ),
        1,
    )

    punctuation_bonus = 0.0

    if token.endswith(
        (
            ".",
            "!",
            "?",
        )
    ):

        punctuation_bonus = 2.0

    elif token.endswith(
        (
            ",",
            ";",
            ":",
            "—",
            "-",
        )
    ):

        punctuation_bonus = 1.0

    return (
        float(
            base
        )
        + punctuation_bonus
    )


def allocate_word_timings(
    text: str,
    start_sec: float,
    end_sec: float,
) -> list[dict[str, Any]]:

    tokens = text.split()

    if not tokens:

        return []

    duration = (
        float(
            end_sec
        )
        - float(
            start_sec
        )
    )

    if duration <= 0:

        raise RuntimeError(
            "Voice timing duration must be positive."
        )

    weights = [
        word_weight(
            token
        )
        for token in tokens
    ]

    total_weight = sum(
        weights
    )

    result: list[
        dict[str, Any]
    ] = []

    cursor = float(
        start_sec
    )

    for index, (
        token,
        weight,
    ) in enumerate(
        zip(
            tokens,
            weights,
        )
    ):

        if (
            index
            == len(
                tokens
            )
            - 1
        ):

            token_end = float(
                end_sec
            )

        else:

            token_end = (
                cursor
                + duration
                * weight
                / total_weight
            )

            remaining_weight = sum(
                weights[
                    index + 1:
                ]
            )

            total_weight = (
                remaining_weight
            )

            duration = (
                float(
                    end_sec
                )
                - token_end
            )

        result.append(
            {
                "text":
                    token,

                "start_sec":
                    round(
                        cursor,
                        3,
                    ),

                "end_sec":
                    round(
                        token_end,
                        3,
                    ),
            }
        )

        cursor = token_end

    return result


def wrap_word_texts(
    words: list[str],
    max_chars_per_line: int,
) -> list[list[str]]:

    if max_chars_per_line < 1:

        raise RuntimeError(
            "max_chars_per_line must be positive."
        )

    lines: list[
        list[str]
    ] = []

    current: list[str] = []

    for word in words:

        candidate = (
            " ".join(
                current
                + [
                    word
                ]
            )
        )

        if (
            current
            and len(
                candidate
            )
            > max_chars_per_line
        ):

            lines.append(
                current
            )

            current = [
                word
            ]

        else:

            current.append(
                word
            )

    if current:

        lines.append(
            current
        )

    return lines


def chunk_word_timings(
    words: list[dict[str, Any]],
    max_chars_per_line: int,
    max_lines: int,
) -> list[dict[str, Any]]:

    if max_lines < 1:

        raise RuntimeError(
            "max_lines must be positive."
        )

    chunks: list[
        dict[str, Any]
    ] = []

    current: list[
        dict[str, Any]
    ] = []

    def line_count(
        items: list[
            dict[str, Any]
        ],
    ) -> int:

        return len(
            wrap_word_texts(
                [
                    item[
                        "text"
                    ]
                    for item
                    in items
                ],
                max_chars_per_line,
            )
        )

    for word in words:

        candidate = (
            current
            + [
                word
            ]
        )

        if (
            current
            and line_count(
                candidate
            )
            > max_lines
        ):

            chunks.append(
                make_caption_chunk(
                    current,
                    max_chars_per_line,
                )
            )

            current = [
                word
            ]

        else:

            current = candidate

    if current:

        chunks.append(
            make_caption_chunk(
                current,
                max_chars_per_line,
            )
        )

    return chunks


def make_caption_chunk(
    words: list[dict[str, Any]],
    max_chars_per_line: int,
) -> dict[str, Any]:

    wrapped = wrap_word_texts(
        [
            word[
                "text"
            ]
            for word
            in words
        ],
        max_chars_per_line,
    )

    lines: list[
        list[
            dict[str, Any]
        ]
    ] = []

    offset = 0

    for text_line in wrapped:

        count = len(
            text_line
        )

        lines.append(
            words[
                offset:
                offset + count
            ]
        )

        offset += count

    return {
        "start_sec":
            words[0][
                "start_sec"
            ],

        "end_sec":
            words[-1][
                "end_sec"
            ],

        "words":
            words,

        "lines":
            lines,

        "text":
            "\n".join(
                " ".join(
                    word[
                        "text"
                    ]
                    for word
                    in line
                )
                for line
                in lines
            ),
    }


def build_subtitle_cues(
    job: dict,
    timeline: list[
        dict[str, Any]
    ],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:

    cues: list[
        dict[str, Any]
    ] = []

    cue_index = 1

    for timeline_item in timeline:

        scene_id = int(
            timeline_item[
                "scene_id"
            ]
        )

        text = get_scene_voice_text(
            job,
            scene_id,
        )

        start_sec = float(
            timeline_item[
                "voice_start_sec"
            ]
        )

        end_sec = float(
            timeline_item[
                "voice_end_sec"
            ]
        )

        words = allocate_word_timings(
            text=text,
            start_sec=start_sec,
            end_sec=end_sec,
        )

        chunks = chunk_word_timings(
            words=words,
            max_chars_per_line=
                settings[
                    "max_chars_per_line"
                ],
            max_lines=
                settings[
                    "max_lines"
                ],
        )

        for chunk in chunks:

            chunk[
                "index"
            ] = cue_index

            chunk[
                "scene_id"
            ] = scene_id

            cues.append(
                chunk
            )

            cue_index += 1

    return cues


def srt_timestamp(
    seconds: float,
) -> str:

    milliseconds = int(
        round(
            float(
                seconds
            )
            * 1000
        )
    )

    hours = (
        milliseconds
        // 3_600_000
    )

    milliseconds %= (
        3_600_000
    )

    minutes = (
        milliseconds
        // 60_000
    )

    milliseconds %= (
        60_000
    )

    secs = (
        milliseconds
        // 1000
    )

    millis = (
        milliseconds
        % 1000
    )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{secs:02d},"
        f"{millis:03d}"
    )


def ass_timestamp(
    seconds: float,
) -> str:

    centiseconds = int(
        round(
            float(
                seconds
            )
            * 100
        )
    )

    hours = (
        centiseconds
        // 360_000
    )

    centiseconds %= (
        360_000
    )

    minutes = (
        centiseconds
        // 6_000
    )

    centiseconds %= (
        6_000
    )

    secs = (
        centiseconds
        // 100
    )

    centis = (
        centiseconds
        % 100
    )

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:02d}."
        f"{centis:02d}"
    )


def render_srt(
    cues: list[
        dict[str, Any]
    ],
) -> str:

    blocks: list[str] = []

    for cue in cues:

        blocks.append(
            (
                f"{cue['index']}\n"
                f"{srt_timestamp(cue['start_sec'])} "
                f"--> "
                f"{srt_timestamp(cue['end_sec'])}\n"
                f"{cue['text']}"
            )
        )

    return (
        "\n\n".join(
            blocks
        )
        + "\n"
    )


def ass_escape(
    text: str,
) -> str:

    return (
        text
        .replace(
            "\\",
            r"\\",
        )
        .replace(
            "{",
            r"\{",
        )
        .replace(
            "}",
            r"\}",
        )
    )


def ass_font_name(
    font: str,
) -> tuple[
    str,
    int,
]:

    normalized = (
        font.strip()
        or "Arial Bold"
    )

    bold = (
        -1
        if "bold"
        in normalized.lower()
        else 0
    )

    family = re.sub(
        r"\s+bold\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()

    if not family:

        family = "Arial"

    return (
        family,
        bold,
    )


def render_ass_text(
    cue: dict[str, Any],
) -> str:

    result_lines: list[str] = []

    for line in cue[
        "lines"
    ]:

        parts: list[str] = []

        for word in line:

            duration_cs = max(
                1,
                int(
                    round(
                        (
                            float(
                                word[
                                    "end_sec"
                                ]
                            )
                            - float(
                                word[
                                    "start_sec"
                                ]
                            )
                        )
                        * 100
                    )
                ),
            )

            parts.append(
                (
                    f"{{\\k{duration_cs}}}"
                    f"{ass_escape(word['text'])}"
                )
            )

        result_lines.append(
            " ".join(
                parts
            )
        )

    return r"\N".join(
        result_lines
    )


def render_ass(
    cues: list[
        dict[str, Any]
    ],
    settings: dict[str, Any],
    width: int,
    height: int,
) -> str:

    font_name, bold = ass_font_name(
        settings[
            "font"
        ]
    )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{settings['font_size']},&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,{bold},0,0,0,100,100,0,0,1,{settings['outline']},{settings['shadow']},2,60,60,{settings['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []

    for cue in cues:

        events.append(
            (
                "Dialogue: 0,"
                f"{ass_timestamp(cue['start_sec'])},"
                f"{ass_timestamp(cue['end_sec'])},"
                "Default,,0,0,0,,"
                f"{render_ass_text(cue)}"
            )
        )

    return (
        header
        + "\n".join(
            events
        )
        + "\n"
    )


def build_source_signature(
    job: dict,
    assembly: dict[str, Any],
    timeline: list[
        dict[str, Any]
    ],
    settings: dict[str, Any],
) -> dict[str, Any]:

    texts = []

    for item in timeline:

        scene_id = int(
            item[
                "scene_id"
            ]
        )

        texts.append(
            {
                "scene_id":
                    scene_id,

                "text":
                    get_scene_voice_text(
                        job,
                        scene_id,
                    ),

                "voice_start_sec":
                    item[
                        "voice_start_sec"
                    ],

                "voice_end_sec":
                    item[
                        "voice_end_sec"
                    ],
            }
        )

    return {
        "assembly_file":
            assembly.get(
                "file"
            ),

        "assembly_checked_at":
            assembly.get(
                "checked_at"
            ),

        "assembly_duration_sec":
            assembly
            .get(
                "actual",
                {},
            )
            .get(
                "duration_sec"
            ),

        "texts":
            texts,

        "settings": {
            key:
                settings[
                    key
                ]
            for key in (
                "language",
                "max_lines",
                "max_chars_per_line",
                "font",
                "position",
                "animation",
                "font_size",
                "margin_v",
                "outline",
                "shadow",
            )
        },
    }


def subtitle_files_match(
    job: dict,
    paths: dict[str, Path],
    source_signature: dict[str, Any],
) -> bool:

    generation = (
        job
        .get(
            "subtitles",
            {},
        )
        .get(
            "generation",
            {},
        )
    )

    if generation.get(
        "status"
    ) != "passed":

        return False

    if generation.get(
        "source_signature"
    ) != source_signature:

        return False

    if generation.get(
        "srt_file"
    ) != relative_path(
        paths[
            "srt"
        ]
    ):

        return False

    if generation.get(
        "ass_file"
    ) != relative_path(
        paths[
            "ass"
        ]
    ):

        return False

    return (
        paths[
            "srt"
        ].exists()
        and paths[
            "ass"
        ].exists()
    )


def burn_metadata_matches(
    job: dict,
    output_path: Path,
    source_signature: dict[str, Any],
) -> bool:

    render = (
        job
        .get(
            "subtitles",
            {},
        )
        .get(
            "render",
            {},
        )
    )

    if render.get(
        "status"
    ) != "passed":

        return False

    if render.get(
        "source_signature"
    ) != source_signature:

        return False

    if render.get(
        "file"
    ) != relative_path(
        output_path
    ):

        return False

    return output_path.exists()


def write_subtitle_files(
    job: dict,
    assembly: dict[str, Any],
    timeline: list[
        dict[str, Any]
    ],
    settings: dict[str, Any],
    paths: dict[str, Path],
    force: bool,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    bool,
]:

    actual = assembly.get(
        "actual",
        {},
    )

    width = int(
        actual.get(
            "width",
            1080,
        )
    )

    height = int(
        actual.get(
            "height",
            1920,
        )
    )

    source_signature = (
        build_source_signature(
            job=job,
            assembly=assembly,
            timeline=timeline,
            settings=settings,
        )
    )

    cues = build_subtitle_cues(
        job=job,
        timeline=timeline,
        settings=settings,
    )

    if (
        not force
        and subtitle_files_match(
            job=job,
            paths=paths,
            source_signature=
                source_signature,
        )
    ):

        print(
            "Subtitle files already match current "
            "assembly and voice text."
        )

        return (
            cues,
            source_signature,
            False,
        )

    paths[
        "srt"
    ].parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths[
        "srt"
    ].write_text(
        render_srt(
            cues
        ),
        encoding="utf-8",
    )

    paths[
        "ass"
    ].write_text(
        render_ass(
            cues=cues,
            settings=settings,
            width=width,
            height=height,
        ),
        encoding="utf-8-sig",
    )

    checked_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    subtitles = job.setdefault(
        "subtitles",
        {},
    )

    subtitles[
        "generation"
    ] = {
        "status":
            "passed",

        "checked_at":
            checked_at,

        "timing_policy":
            "known_tts_text_weighted_v1",

        "word_timing_source":
            "deterministic_weighted_estimate",

        "cue_count":
            len(
                cues
            ),

        "srt_file":
            relative_path(
                paths[
                    "srt"
                ]
            ),

        "ass_file":
            relative_path(
                paths[
                    "ass"
                ]
            ),

        "source_signature":
            source_signature,

        "errors":
            [],

        "warnings": [
            (
                "Word-highlight timing is estimated from "
                "known TTS text and measured scene voice "
                "duration; it is not forced-alignment timing."
            )
        ],
    }

    subtitles[
        "subtitle_file"
    ] = relative_path(
        paths[
            "srt"
        ]
    )

    subtitles.pop(
        "render",
        None,
    )

    output = job.get(
        "output"
    )

    if isinstance(
        output,
        dict,
    ):

        output[
            "subtitled_video_file"
        ] = None

        output[
            "video_file"
        ] = None

    job.pop(
        "final_mix",
        None,
    )

    job.pop(
        "final_qc",
        None,
    )

    return (
        cues,
        source_signature,
        True,
    )


def ffmpeg_ass_filter_path(
    ass_path: Path,
) -> str:

    value = relative_path(
        ass_path
    )

    value = (
        value
        .replace(
            "\\",
            "/",
        )
        .replace(
            "'",
            r"\'",
        )
        .replace(
            ":",
            r"\:",
        )
    )

    return (
        "ass="
        + "'"
        + value
        + "'"
    )


def build_burn_command(
    base_video: Path,
    ass_path: Path,
    output_path: Path,
) -> list[str]:

    return [
        "ffmpeg",
        "-y",
        "-v",
        "error",

        "-i",
        str(
            base_video
        ),

        "-vf",
        ffmpeg_ass_filter_path(
            ass_path
        ),

        "-map",
        "0:v:0",

        "-map",
        "0:a:0?",

        "-c:v",
        "libx264",

        "-preset",
        SUBTITLE_VIDEO_PRESET,

        "-crf",
        str(
            SUBTITLE_VIDEO_CRF
        ),

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "copy",

        "-movflags",
        "+faststart",

        str(
            output_path
        ),
    ]


def evaluate_burned_video(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[
    bool,
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    expected_duration = expected.get(
        "duration_sec"
    )

    actual_duration = actual.get(
        "duration_sec"
    )

    if (
        expected_duration is None
        or actual_duration is None
    ):

        errors.append(
            "Unable to verify subtitled video duration."
        )

    elif abs(
        float(
            actual_duration
        )
        - float(
            expected_duration
        )
    ) > DURATION_TOLERANCE_SEC:

        errors.append(
            (
                "Subtitled video duration differs from "
                "base assembly beyond tolerance."
            )
        )

    for key in (
        "width",
        "height",
    ):

        if actual.get(
            key
        ) != expected.get(
            key
        ):

            errors.append(
                f"Subtitled video {key} changed."
            )

    if actual.get(
        "video_stream_count"
    ) != 1:

        errors.append(
            "Subtitled video must contain one video stream."
        )

    if actual.get(
        "audio_stream_count"
    ) != 1:

        errors.append(
            "Subtitled video must contain one audio stream."
        )

    if actual.get(
        "video_codec"
    ) != "h264":

        errors.append(
            "Subtitled video must use H.264."
        )

    if actual.get(
        "audio_codec"
    ) != expected.get(
        "audio_codec"
    ):

        errors.append(
            "Subtitled video audio codec changed."
        )

    if actual.get(
        "fps"
    ) != expected.get(
        "fps"
    ):

        warnings.append(
            (
                f"Subtitled FPS is {actual.get('fps')}; "
                f"base FPS is {expected.get('fps')}."
            )
        )

    return (
        not errors,
        errors,
        warnings,
    )


def burn_subtitles(
    job: dict,
    assembly: dict[str, Any],
    paths: dict[str, Path],
    source_signature: dict[str, Any],
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

    output_path = paths[
        "video"
    ]

    if (
        not force
        and burn_metadata_matches(
            job=job,
            output_path=output_path,
            source_signature=
                source_signature,
        )
    ):

        print(
            "Subtitled video already matches current "
            "subtitle artifacts."
        )

        return False

    base_video = (
        PROJECT_ROOT
        / assembly[
            "file"
        ]
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        output_path
        .with_name(
            output_path.stem
            + ".tmp"
            + output_path.suffix
        )
    )

    if temporary_file.exists():

        temporary_file.unlink()

    command = build_burn_command(
        base_video=base_video,
        ass_path=paths[
            "ass"
        ],
        output_path=
            temporary_file,
    )

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    checked_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    subtitles = job.setdefault(
        "subtitles",
        {},
    )

    if result.returncode != 0:

        if temporary_file.exists():

            temporary_file.unlink()

        subtitles[
            "render"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "errors": [
                (
                    "ffmpeg subtitle burn failed: "
                    + result.stderr.strip()
                )
            ],

            "warnings":
                [],
        }

        return False

    if (
        not temporary_file.exists()
        or temporary_file.stat().st_size
        <= 0
    ):

        subtitles[
            "render"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "errors": [
                "ffmpeg created no valid subtitled video."
            ],

            "warnings":
                [],
        }

        return False

    actual = analyze_assembled_media(
        temporary_file
    )

    passed, errors, warnings = (
        evaluate_burned_video(
            actual=actual,
            expected=assembly[
                "actual"
            ],
        )
    )

    if not passed:

        if temporary_file.exists():

            temporary_file.unlink()

        subtitles[
            "render"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "source_signature":
                source_signature,

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
        output_path,
    )

    relative_output = relative_path(
        output_path
    )

    subtitles[
        "render"
    ] = {
        "status":
            "passed",

        "checked_at":
            checked_at,

        "file":
            relative_output,

        "source_base_file":
            assembly.get(
                "file"
            ),

        "ass_file":
            relative_path(
                paths[
                    "ass"
                ]
            ),

        "source_signature":
            source_signature,

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
        "subtitled_video_file"
    ] = relative_output

    return True


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SUBTITLE PIPELINE v1")
    print("=" * 60)

    args = parse_args()

    try:

        job = load_json(
            JOB_FILE
        )

        settings = (
            get_subtitle_settings(
                job
            )
        )

        if not settings[
            "enabled"
        ]:

            print(
                "\nSubtitles are disabled for this job."
            )

            return 0

        (
            assembly,
            timeline,
        ) = validate_preconditions(
            job
        )

        paths = get_artifact_paths(
            job
        )

        (
            cues,
            source_signature,
            generated,
        ) = write_subtitle_files(
            job=job,
            assembly=assembly,
            timeline=timeline,
            settings=settings,
            paths=paths,
            force=args.force,
        )

        print(
            f"\nSubtitle cues: {len(cues)}"
        )

        print(
            f"SRT: {relative_path(paths['srt'])}"
        )

        print(
            f"ASS: {relative_path(paths['ass'])}"
        )

        if (
            not args.files_only
            and settings[
                "burned_in"
            ]
        ):

            burned = burn_subtitles(
                job=job,
                assembly=assembly,
                paths=paths,
                source_signature=
                    source_signature,
                force=args.force,
            )

            render = (
                job
                .get(
                    "subtitles",
                    {},
                )
                .get(
                    "render",
                    {},
                )
            )

            if render.get(
                "status"
            ) != "passed":

                raise RuntimeError(
                    "\n".join(
                        render.get(
                            "errors",
                            [
                                "Subtitle render failed.",
                            ],
                        )
                    )
                )

            print(
                f"Video: "
                f"{render.get('file')}"
            )

        set_legacy_status_from_stage(
            job,
            "subtitles",
        )

        save_job_atomic(
            job
        )

    except Exception as exc:

        try:

            job

        except NameError:

            print(
                f"\nERROR: {exc}"
            )

            return 1

        subtitles = job.setdefault(
            "subtitles",
            {},
        )

        if not subtitles.get(
            "generation"
        ):

            subtitles[
                "generation"
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
            "subtitles",
        )

        save_job_atomic(
            job
        )

        print(
            f"\nERROR: {exc}"
        )

        return 1

    print(
        "\n" + "=" * 60
    )

    print(
        "SUBTITLE PIPELINE COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nStatus: "
        f"{job['pipeline_status']['subtitles']['state']}"
    )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
