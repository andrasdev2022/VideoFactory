from __future__ import annotations

import argparse
import json
import os
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


AUDIO_SAMPLE_RATE = int(
    os.getenv(
        "FINAL_MIX_AUDIO_SAMPLE_RATE",
        "48000",
    )
)

AUDIO_BITRATE = os.getenv(
    "FINAL_MIX_AUDIO_BITRATE",
    "192k",
)

MUSIC_FADE_SEC = float(
    os.getenv(
        "FINAL_MIX_MUSIC_FADE_SEC",
        "0.50",
    )
)

MUSIC_DUCK_THRESHOLD = float(
    os.getenv(
        "FINAL_MIX_DUCK_THRESHOLD",
        "0.02",
    )
)

MUSIC_DUCK_RATIO = float(
    os.getenv(
        "FINAL_MIX_DUCK_RATIO",
        "8.0",
    )
)

MUSIC_DUCK_ATTACK_MS = int(
    os.getenv(
        "FINAL_MIX_DUCK_ATTACK_MS",
        "20",
    )
)

MUSIC_DUCK_RELEASE_MS = int(
    os.getenv(
        "FINAL_MIX_DUCK_RELEASE_MS",
        "250",
    )
)

DURATION_TOLERANCE_SEC = float(
    os.getenv(
        "FINAL_MIX_DURATION_TOLERANCE_SEC",
        "0.15",
    )
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Mix background music and scene-timed sound effects "
            "under the approved narration track."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild the audio mix even when metadata matches.",
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


def get_source_video(
    job: dict,
) -> tuple[
    Path,
    dict[str, Any],
    str,
]:

    subtitles = job.get(
        "subtitles",
        {},
    )

    if (
        subtitles.get(
            "enabled",
            True,
        )
        and subtitles.get(
            "burned_in",
            True,
        )
    ):

        render = subtitles.get(
            "render",
            {},
        )

        if render.get(
            "status"
        ) != "passed":

            raise RuntimeError(
                "Burned-in subtitles are required but "
                "the subtitle render has not passed."
            )

        file_value = render.get(
            "file"
        )

        if not file_value:

            raise RuntimeError(
                "Subtitle render file metadata is missing."
            )

        path = (
            PROJECT_ROOT
            / file_value
        )

        metadata = (
            render.get(
                "actual",
                {},
            )
        )

        source_kind = (
            "subtitled_video"
        )

    else:

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

        file_value = assembly.get(
            "file"
        )

        if not file_value:

            raise RuntimeError(
                "Base assembly file metadata is missing."
            )

        path = (
            PROJECT_ROOT
            / file_value
        )

        metadata = (
            assembly.get(
                "actual",
                {},
            )
        )

        source_kind = (
            "base_assembly"
        )

    if not path.exists():

        raise RuntimeError(
            f"Source video does not exist: "
            f"{relative_path(path)}"
        )

    if not metadata:

        metadata = (
            analyze_assembled_media(
                path
            )
        )

    return (
        path,
        metadata,
        source_kind,
    )


def get_timeline(
    job: dict,
) -> list[dict[str, Any]]:

    timeline = (
        job
        .get(
            "assembly",
            {},
        )
        .get(
            "timeline"
        )
    )

    if not isinstance(
        timeline,
        list,
    ) or not timeline:

        raise RuntimeError(
            "Assembly timeline is missing."
        )

    return timeline


def timeline_map(
    timeline: list[
        dict[str, Any]
    ],
) -> dict[int, dict[str, Any]]:

    result: dict[
        int,
        dict[str, Any]
    ] = {}

    for item in timeline:

        scene_id = item.get(
            "scene_id"
        )

        if scene_id is None:

            continue

        result[
            int(
                scene_id
            )
        ] = item

    return result


def get_total_duration(
    source_metadata: dict[str, Any],
    timeline: list[
        dict[str, Any]
    ],
) -> float:

    value = source_metadata.get(
        "duration_sec"
    )

    if value is not None:

        duration = float(
            value
        )

        if duration > 0:

            return duration

    last = timeline[
        -1
    ]

    value = last.get(
        "end_sec"
    )

    if value is None:

        raise RuntimeError(
            "Unable to determine final mix duration."
        )

    duration = float(
        value
    )

    if duration <= 0:

        raise RuntimeError(
            "Final mix duration must be positive."
        )

    return duration


def resolve_audio_file(
    value: Any,
) -> tuple[
    str,
    Path,
]:

    if not isinstance(
        value,
        str,
    ) or not value.strip():

        raise RuntimeError(
            "Audio file path is missing."
        )

    relative = (
        value
        .replace(
            "\\",
            "/",
        )
        .strip()
    )

    path = (
        PROJECT_ROOT
        / relative
    )

    if not path.exists():

        raise RuntimeError(
            f"Audio file does not exist: "
            f"{relative}"
        )

    return (
        relative,
        path,
    )


def collect_mix_inputs(
    job: dict,
    timeline: list[
        dict[str, Any]
    ],
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    list[str],
]:

    audio = job.get(
        "audio",
        {},
    )

    warnings: list[str] = []

    # -----------------------------------------------------
    # Background music
    # -----------------------------------------------------

    music_config = audio.get(
        "background_music",
        {},
    )

    music_required = bool(
        music_config.get(
            "required",
            False,
        )
    )

    music_file = music_config.get(
        "audio_file"
    )

    music: dict[str, Any] | None = None

    if music_file:

        (
            music_relative,
            music_path,
        ) = resolve_audio_file(
            music_file
        )

        music = {
            "file":
                music_relative,

            "path":
                music_path,

            "volume":
                float(
                    music_config.get(
                        "volume",
                        0.20,
                    )
                ),

            "style":
                music_config.get(
                    "style"
                ),
        }

    elif music_required:

        raise RuntimeError(
            "Background music is required but "
            "audio.background_music.audio_file is missing."
        )

    # -----------------------------------------------------
    # Sound effects
    # -----------------------------------------------------

    sound_effects = audio.get(
        "sound_effects",
        {},
    )

    effects_enabled = bool(
        sound_effects.get(
            "enabled",
            False,
        )
    )

    effects: list[
        dict[str, Any]
    ] = []

    scene_map = timeline_map(
        timeline
    )

    if effects_enabled:

        for index, effect in enumerate(
            sound_effects.get(
                "effects",
                [],
            ),
            start=1,
        ):

            scene_id = effect.get(
                "scene_id"
            )

            if scene_id is None:

                warnings.append(
                    f"SFX #{index} has no scene_id; skipped."
                )

                continue

            try:

                scene_id = int(
                    scene_id
                )

            except (
                TypeError,
                ValueError,
            ):

                warnings.append(
                    f"SFX #{index} has invalid scene_id; skipped."
                )

                continue

            timeline_item = (
                scene_map.get(
                    scene_id
                )
            )

            if timeline_item is None:

                warnings.append(
                    (
                        f"SFX #{index} references scene "
                        f"{scene_id}, which is not in the "
                        f"final assembly timeline; skipped."
                    )
                )

                continue

            file_value = effect.get(
                "audio_file"
            )

            if not file_value:

                warnings.append(
                    (
                        f"SFX #{index} for scene {scene_id} "
                        f"has no audio_file; skipped."
                    )
                )

                continue

            try:

                (
                    effect_relative,
                    effect_path,
                ) = resolve_audio_file(
                    file_value
                )

            except RuntimeError as exc:

                warnings.append(
                    str(
                        exc
                    )
                    + "; SFX skipped."
                )

                continue

            if effect.get(
                "start_sec"
            ) is not None:

                start_sec = float(
                    effect[
                        "start_sec"
                    ]
                )

                timing_source = (
                    "absolute"
                )

            else:

                offset_sec = float(
                    effect.get(
                        "offset_sec",
                        0.0,
                    )
                )

                start_sec = (
                    float(
                        timeline_item[
                            "start_sec"
                        ]
                    )
                    + offset_sec
                )

                timing_source = (
                    "scene_relative"
                )

            if start_sec < 0:

                warnings.append(
                    (
                        f"SFX #{index} start time is negative; "
                        f"clamped to 0."
                    )
                )

                start_sec = 0.0

            effects.append(
                {
                    "index":
                        index,

                    "scene_id":
                        scene_id,

                    "effect":
                        effect.get(
                            "effect",
                            f"sfx_{index}",
                        ),

                    "file":
                        effect_relative,

                    "path":
                        effect_path,

                    "start_sec":
                        round(
                            start_sec,
                            3,
                        ),

                    "volume":
                        float(
                            effect.get(
                                "volume",
                                1.0,
                            )
                        ),

                    "timing_source":
                        timing_source,
                }
            )

    from scene_music import mix_scene_music
    scene_tracks = mix_scene_music(job, timeline, resolve_audio_file)
    if music is not None:
        music['mute_intervals'] = [(t['start_sec'], t['start_sec'] + t['duration_sec']) for t in scene_tracks]
    effects.extend(scene_tracks)

    return (
        music,
        effects,
        warnings,
    )


def build_source_signature(
    source_video: Path,
    source_kind: str,
    music: dict[str, Any] | None,
    effects: list[dict[str, Any]],
    total_duration: float,
) -> dict[str, Any]:

    def file_signature(
        path: Path,
    ) -> dict[str, Any]:

        stat = path.stat()

        return {
            "file":
                relative_path(
                    path
                ),

            "size_bytes":
                stat.st_size,

            "mtime_ns":
                stat.st_mtime_ns,
        }

    return {
        "source_kind":
            source_kind,

        "source_video":
            file_signature(
                source_video
            ),

        "duration_sec":
            round(
                total_duration,
                3,
            ),

        "music":
            (
                {
                    "source":
                        file_signature(
                            music[
                                "path"
                            ]
                        ),

                    "volume":
                        music[
                            "volume"
                        ],

                    "mute_intervals": music.get("mute_intervals", []),
                    "style":
                        music.get(
                            "style"
                        ),
                }
                if music
                is not None
                else None
            ),

        "effects": [
            {
                "duration_sec": effect.get("duration_sec"),
                "kind": effect.get("kind"),
                "index":
                    effect[
                        "index"
                    ],

                "scene_id":
                    effect[
                        "scene_id"
                    ],

                "effect":
                    effect[
                        "effect"
                    ],

                "source":
                    file_signature(
                        effect[
                            "path"
                        ]
                    ),

                "start_sec":
                    effect[
                        "start_sec"
                    ],

                "volume":
                    effect[
                        "volume"
                    ],
            }
            for effect
            in effects
        ],

        "mix_config": {
            "sample_rate":
                AUDIO_SAMPLE_RATE,

            "audio_bitrate":
                AUDIO_BITRATE,

            "music_fade_sec":
                MUSIC_FADE_SEC,

            "duck_threshold":
                MUSIC_DUCK_THRESHOLD,

            "duck_ratio":
                MUSIC_DUCK_RATIO,

            "duck_attack_ms":
                MUSIC_DUCK_ATTACK_MS,

            "duck_release_ms":
                MUSIC_DUCK_RELEASE_MS,
        },
    }


def build_filter_complex(
    *,
    total_duration: float,
    music: dict[str, Any] | None,
    effects: list[dict[str, Any]],
) -> tuple[
    str,
    str,
]:

    filters: list[str] = []

    # Source-video audio is the narration authority.
    filters.append(
        (
            "[0:a:0]"
            f"aresample={AUDIO_SAMPLE_RATE},"
            "aformat=sample_fmts=fltp:"
            f"sample_rates={AUDIO_SAMPLE_RATE}:"
            "channel_layouts=stereo,"
            f"atrim=duration={total_duration:.3f},"
            "asetpts=PTS-STARTPTS"
            "[voice]"
        )
    )

    duck_labels = (["duck_main"] if music is not None else []) + [
        f"duck_scene{i}" for i, effect in enumerate(effects) if effect.get("kind") == "scene_music"]
    if duck_labels:
        filters[0] = filters[0].replace("[voice]", "[voice_raw]")
        filters.append("[voice_raw]asplit=" + str(1 + len(duck_labels)) +
                       "[voice]" + "".join(f"[{label}]" for label in duck_labels))

    mix_labels = [
        "[voice]"
    ]

    input_index = 1

    if music is not None:

        fade_duration = min(
            max(
                MUSIC_FADE_SEC,
                0.0,
            ),
            total_duration
            / 2.0,
        )

        fade_out_start = max(
            0.0,
            total_duration
            - fade_duration,
        )

        music_chain = (
            f"[{input_index}:a]"
            f"aresample={AUDIO_SAMPLE_RATE},"
            "aformat=sample_fmts=fltp:"
            f"sample_rates={AUDIO_SAMPLE_RATE}:"
            "channel_layouts=stereo,"
            f"atrim=duration={total_duration:.3f},"
            "asetpts=PTS-STARTPTS,"
            f"volume={music['volume']:.6f}"
        )

        for start, end in music.get("mute_intervals", []):
            music_chain += f",volume=0:enable='gte(t,{start:.6f})*lt(t,{end:.6f})'"

        if fade_duration > 0:

            music_chain += (
                f",afade=t=in:st=0:"
                f"d={fade_duration:.3f}"
                f",afade=t=out:"
                f"st={fade_out_start:.3f}:"
                f"d={fade_duration:.3f}"
            )

        music_chain += (
            "[music_preduck]"
        )

        filters.append(
            music_chain
        )

        filters.append(
            (
                "[music_preduck][duck_main]"
                "sidechaincompress="
                f"threshold={MUSIC_DUCK_THRESHOLD}:"
                f"ratio={MUSIC_DUCK_RATIO}:"
                f"attack={MUSIC_DUCK_ATTACK_MS}:"
                f"release={MUSIC_DUCK_RELEASE_MS}"
                "[music]"
            )
        )

        mix_labels.append(
            "[music]"
        )

        input_index += 1

    for effect_index, effect in enumerate(
        effects
    ):

        delay_ms = max(
            0,
            int(
                round(
                    float(
                        effect[
                            "start_sec"
                        ]
                    )
                    * 1000
                )
            ),
        )

        label = (
            f"sfx{effect_index}"
        )

        scene_music = effect.get("kind") == "scene_music"
        duration = float(effect.get("duration_sec", total_duration))
        local_filter = ""
        if scene_music:
            fade = min(0.15, duration / 2)
            local_filter = (f"apad,atrim=duration={duration:.6f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:d={fade:.6f},afade=t=out:st={duration-fade:.6f}:d={fade:.6f},")

        filters.append(
            (
                f"[{input_index}:a]"
                f"aresample={AUDIO_SAMPLE_RATE},"
                "aformat=sample_fmts=fltp:"
                f"sample_rates={AUDIO_SAMPLE_RATE}:"
                "channel_layouts=stereo,"
                f"{local_filter}"
                f"volume={effect['volume']:.6f},"
                f"adelay={delay_ms}|{delay_ms},"
                f"atrim=duration={total_duration:.3f},"
                "asetpts=PTS-STARTPTS"
                f"[{label}]"
            )
        )

        if scene_music:
            filters[-1] = filters[-1].replace(f"[{label}]", f"[{label}_raw]")
            filters.append(f"[{label}_raw][duck_scene{effect_index}]sidechaincompress="
                f"threshold={MUSIC_DUCK_THRESHOLD}:ratio={MUSIC_DUCK_RATIO}:"
                f"attack={MUSIC_DUCK_ATTACK_MS}:release={MUSIC_DUCK_RELEASE_MS}[{label}]")

        mix_labels.append(
            f"[{label}]"
        )

        input_index += 1

    if len(
        mix_labels
    ) == 1:

        filters.append(
            (
                "[voice]"
                "anull"
                "[mixout]"
            )
        )

    else:

        filters.append(
            (
                "".join(
                    mix_labels
                )
                + (
                    f"amix=inputs="
                    f"{len(mix_labels)}:"
                    "duration=first:"
                    "dropout_transition=0:"
                    "normalize=0,"
                    f"atrim=duration={total_duration:.3f}"
                    "[mixout]"
                )
            )
        )

    return (
        ";".join(
            filters
        ),
        "[mixout]",
    )


def build_ffmpeg_command(
    *,
    source_video: Path,
    music: dict[str, Any] | None,
    effects: list[dict[str, Any]],
    total_duration: float,
    output_path: Path,
) -> list[str]:

    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",

        "-i",
        str(
            source_video
        ),
    ]

    if music is not None:

        command.extend(
            [
                "-stream_loop",
                "-1",

                "-i",
                str(
                    music[
                        "path"
                    ]
                ),
            ]
        )

    for effect in effects:

        command.extend(
            [
                "-i",
                str(
                    effect[
                        "path"
                    ]
                ),
            ]
        )

    (
        filter_complex,
        audio_label,
    ) = build_filter_complex(
        total_duration=
            total_duration,
        music=
            music,
        effects=
            effects,
    )

    command.extend(
        [
            "-filter_complex",
            filter_complex,

            "-map",
            "0:v:0",

            "-map",
            audio_label,

            "-c:v",
            "copy",

            "-c:a",
            "aac",

            "-b:a",
            AUDIO_BITRATE,

            "-ar",
            str(
                AUDIO_SAMPLE_RATE
            ),

            "-movflags",
            "+faststart",

            "-t",
            f"{total_duration:.3f}",

            str(
                output_path
            ),
        ]
    )

    return command


def evaluate_mixed_video(
    actual: dict[str, Any],
    source_metadata: dict[str, Any],
) -> tuple[
    bool,
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    source_duration = (
        source_metadata.get(
            "duration_sec"
        )
    )

    actual_duration = actual.get(
        "duration_sec"
    )

    if (
        source_duration is None
        or actual_duration is None
    ):

        errors.append(
            "Unable to verify mixed video duration."
        )

    elif abs(
        float(
            actual_duration
        )
        - float(
            source_duration
        )
    ) > DURATION_TOLERANCE_SEC:

        errors.append(
            "Mixed video duration differs from source video."
        )

    for key in (
        "width",
        "height",
    ):

        if actual.get(
            key
        ) != source_metadata.get(
            key
        ):

            errors.append(
                f"Mixed video {key} changed."
            )

    if actual.get(
        "video_stream_count"
    ) != 1:

        errors.append(
            "Mixed video must contain one video stream."
        )

    if actual.get(
        "audio_stream_count"
    ) != 1:

        errors.append(
            "Mixed video must contain one audio stream."
        )

    if actual.get(
        "video_codec"
    ) != source_metadata.get(
        "video_codec"
    ):

        errors.append(
            "Mixed video codec changed."
        )

    if actual.get(
        "audio_codec"
    ) != "aac":

        errors.append(
            "Mixed audio codec must be AAC."
        )

    if (
        actual.get(
            "audio_sample_rate"
        )
        != AUDIO_SAMPLE_RATE
    ):

        errors.append(
            (
                "Mixed audio sample rate is "
                f"{actual.get('audio_sample_rate')}; "
                f"expected {AUDIO_SAMPLE_RATE}."
            )
        )

    if actual.get(
        "fps"
    ) != source_metadata.get(
        "fps"
    ):

        warnings.append(
            "Mixed video FPS metadata differs from source."
        )

    return (
        not errors,
        errors,
        warnings,
    )


def mix_metadata_matches(
    job: dict,
    output_path: Path,
    source_signature: dict[str, Any],
) -> bool:

    mix = (
        job
        .get(
            "audio",
            {},
        )
        .get(
            "mix",
            {},
        )
    )

    if mix.get(
        "status"
    ) != "passed":

        return False

    if mix.get(
        "file"
    ) != relative_path(
        output_path
    ):

        return False

    if mix.get(
        "source_signature"
    ) != source_signature:

        return False

    return output_path.exists()


def mix_audio(
    job: dict,
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

    (
        source_video,
        source_metadata,
        source_kind,
    ) = get_source_video(
        job
    )

    timeline = get_timeline(
        job
    )

    total_duration = get_total_duration(
        source_metadata,
        timeline,
    )

    (
        music,
        effects,
        warnings,
    ) = collect_mix_inputs(
        job,
        timeline,
    )

    source_signature = (
        build_source_signature(
            source_video=
                source_video,
            source_kind=
                source_kind,
            music=
                music,
            effects=
                effects,
            total_duration=
                total_duration,
        )
    )

    output_path = (
        PROJECT_ROOT
        / "output"
        / str(
            job[
                "job_id"
            ]
        )
        / "assembly"
        / "final_audio_mix.mp4"
    )

    if (
        not force
        and mix_metadata_matches(
            job=job,
            output_path=output_path,
            source_signature=
                source_signature,
        )
    ):

        print(
            "Final audio mix already matches "
            "current source and audio assets."
        )

        return False

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

    command = build_ffmpeg_command(
        source_video=
            source_video,
        music=
            music,
        effects=
            effects,
        total_duration=
            total_duration,
        output_path=
            temporary_file,
    )

    print(
        f"\nSource:       "
        f"{relative_path(source_video)}"
    )

    print(
        f"Duration:     "
        f"{total_duration:.3f}s"
    )

    print(
        f"Music:        "
        f"{music['file'] if music else 'none'}"
    )

    print(
        f"Sound effects:"
        f" {len(effects)}"
    )

    for effect in effects:

        print(
            (
                f"  scene {effect['scene_id']} "
                f"@ {effect['start_sec']:.3f}s: "
                f"{effect['effect']}"
            )
        )

    for warning in warnings:

        print(
            f"  [WARNING] {warning}"
        )

    result = subprocess.run(
        command,
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

    audio = job.setdefault(
        "audio",
        {},
    )

    if result.returncode != 0:

        if temporary_file.exists():

            temporary_file.unlink()

        audio[
            "mix"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "errors": [
                (
                    "ffmpeg final audio mix failed: "
                    + result.stderr.strip()
                )
            ],

            "warnings":
                warnings,
        }

        return False

    if (
        not temporary_file.exists()
        or temporary_file.stat().st_size
        <= 0
    ):

        audio[
            "mix"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "errors": [
                "ffmpeg created no valid mixed video."
            ],

            "warnings":
                warnings,
        }

        return False

    actual = analyze_assembled_media(
        temporary_file
    )

    (
        passed,
        errors,
        qc_warnings,
    ) = evaluate_mixed_video(
        actual=actual,
        source_metadata=
            source_metadata,
    )

    warnings.extend(
        qc_warnings
    )

    if not passed:

        temporary_file.unlink(
            missing_ok=True
        )

        audio[
            "mix"
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

    audio[
        "mix"
    ] = {
        "status":
            "passed",

        "checked_at":
            checked_at,

        "file":
            relative_output,

        "source_video":
            relative_path(
                source_video
            ),

        "source_kind":
            source_kind,

        "music":
            (
                {
                    "file":
                        music[
                            "file"
                        ],

                    "volume":
                        music[
                            "volume"
                        ],
                }
                if music
                is not None
                else None
            ),

        "effects":
            [
                {
                    key:
                        effect[
                            key
                        ]
                    for key in (
                        "scene_id",
                        "effect",
                        "file",
                        "start_sec",
                        "volume",
                        "timing_source",
                    )
                }
                for effect
                in effects
            ],

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
        "mixed_video_file"
    ] = relative_output

    output[
        "video_file"
    ] = None

    job.pop(
        "final_qc",
        None,
    )

    print(
        f"Output:       "
        f"{relative_output}"
    )

    print(
        "PASS"
    )

    return True


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - FINAL AUDIO MIX v1")
    print("=" * 60)

    args = parse_args()

    try:

        job = load_json(
            JOB_FILE
        )

        mix_audio(
            job=job,
            force=args.force,
        )

        set_legacy_status_from_stage(
            job,
            "audio_mix",
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

        audio = job.setdefault(
            "audio",
            {},
        )

        audio[
            "mix"
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
            "audio_mix",
        )

        save_job_atomic(
            job
        )

        print(
            f"\nERROR: {exc}"
        )

        return 1

    mix = (
        job
        .get(
            "audio",
            {},
        )
        .get(
            "mix",
            {},
        )
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "FINAL AUDIO MIX COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nStatus: "
        f"{mix.get('status')}"
    )

    print(
        f"File:   "
        f"{mix.get('file')}"
    )

    return (
        0
        if mix.get(
            "status"
        )
        == "passed"
        else 1
    )


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
