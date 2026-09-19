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


MIN_DURATION_SEC = float(
    os.getenv(
        "VOICE_QC_MIN_DURATION_SEC",
        "0.20",
    )
)

MIN_FILE_SIZE_BYTES = int(
    os.getenv(
        "VOICE_QC_MIN_FILE_SIZE_BYTES",
        "5000",
    )
)

MIN_SAMPLE_RATE = int(
    os.getenv(
        "VOICE_QC_MIN_SAMPLE_RATE",
        "22050",
    )
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Technical QC for per-scene voiceover audio."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Check only one scene. "
            "Example: --scene 1"
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

        if (
            scene.get(
                "scene_id"
            )
            == scene_id
        ):

            return scene

    return None


def run_ffprobe(
    audio_path: Path,
) -> dict[str, Any]:

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(audio_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "ffprobe failed:\n"
            + result.stderr.strip()
        )

    try:

        return json.loads(
            result.stdout
        )

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            "ffprobe returned invalid JSON."
        ) from exc


def parse_float(
    value: Any,
) -> float | None:

    if value is None:
        return None

    try:

        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


def parse_int(
    value: Any,
) -> int | None:

    if value is None:
        return None

    try:

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


def inspect_audio_probe(
    probe: dict,
    file_size_bytes: int,
) -> dict[str, Any]:

    streams = probe.get(
        "streams",
        [],
    )

    audio_stream = None

    for stream in streams:

        if (
            stream.get(
                "codec_type"
            )
            == "audio"
        ):

            audio_stream = stream
            break

    if audio_stream is None:

        return {
            "has_audio_stream":
                False,

            "file_size_bytes":
                file_size_bytes,
        }

    format_info = probe.get(
        "format",
        {},
    )

    duration = parse_float(
        audio_stream.get(
            "duration"
        )
    )

    if duration is None:

        duration = parse_float(
            format_info.get(
                "duration"
            )
        )

    return {
        "has_audio_stream":
            True,

        "codec":
            audio_stream.get(
                "codec_name"
            ),

        "codec_long_name":
            audio_stream.get(
                "codec_long_name"
            ),

        "sample_rate":
            parse_int(
                audio_stream.get(
                    "sample_rate"
                )
            ),

        "channels":
            parse_int(
                audio_stream.get(
                    "channels"
                )
            ),

        "channel_layout":
            audio_stream.get(
                "channel_layout"
            ),

        "sample_fmt":
            audio_stream.get(
                "sample_fmt"
            ),

        "duration_sec":
            duration,

        "bit_rate":
            parse_int(
                audio_stream.get(
                    "bit_rate"
                )
            ),

        "file_size_bytes":
            file_size_bytes,
    }


def evaluate_voice_qc(
    target_duration_sec: float,
    actual: dict[str, Any],
) -> tuple[
    bool,
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    if not actual.get(
        "has_audio_stream"
    ):

        errors.append(
            "No audio stream found."
        )

        return (
            False,
            errors,
            warnings,
        )

    file_size = (
        actual.get(
            "file_size_bytes"
        )
        or 0
    )

    if (
        file_size
        < MIN_FILE_SIZE_BYTES
    ):

        errors.append(
            f"Voice file is too small "
            f"({file_size} bytes). "
            f"Minimum: "
            f"{MIN_FILE_SIZE_BYTES}."
        )

    duration = actual.get(
        "duration_sec"
    )

    if duration is None:

        errors.append(
            "Audio duration could not "
            "be determined."
        )

    else:

        if (
            duration
            < MIN_DURATION_SEC
        ):

            errors.append(
                f"Voice duration is too short "
                f"({duration:.3f}s)."
            )

        difference = (
            duration
            - target_duration_sec
        )

        # Important:
        # This is informational only.
        # The video timing will adapt to the voice.
        if difference > 0.25:

            warnings.append(
                f"Natural voice is "
                f"{difference:.3f}s longer than "
                f"the originally planned scene. "
                f"Scene timing must adapt."
            )

        elif difference < -2.0:

            warnings.append(
                f"Natural voice is "
                f"{abs(difference):.3f}s shorter than "
                f"the originally planned scene. "
                f"Global timing should be reviewed."
            )

    sample_rate = actual.get(
        "sample_rate"
    )

    if sample_rate is None:

        errors.append(
            "Sample rate could not "
            "be determined."
        )

    elif (
        sample_rate
        < MIN_SAMPLE_RATE
    ):

        errors.append(
            f"Sample rate is too low "
            f"({sample_rate} Hz). "
            f"Minimum: "
            f"{MIN_SAMPLE_RATE} Hz."
        )

    channels = actual.get(
        "channels"
    )

    if channels is None:

        errors.append(
            "Channel count could not "
            "be determined."
        )

    elif channels not in {
        1,
        2,
    }:

        warnings.append(
            f"Unexpected channel count: "
            f"{channels}."
        )

    codec = actual.get(
        "codec"
    )

    if codec not in {
        "pcm_s16le",
        "pcm_s24le",
        "pcm_s32le",
        "pcm_f32le",
    }:

        warnings.append(
            f"Unexpected WAV codec: "
            f"{codec}."
        )

    return (
        len(errors) == 0,
        errors,
        warnings,
    )


def check_scene_voice(
    job: dict,
    scene: dict,
) -> bool:

    scene_id = scene.get(
        "scene_id"
    )

    if scene_id is None:

        raise RuntimeError(
            "Script scene has no scene_id."
        )

    voice = scene.get(
        "voice",
        {},
    )

    voice_file = voice.get(
        "file"
    )

    planned_duration = (
        scene.get(
            "planned_duration_sec",
            scene.get(
                "duration_sec"
            ),
        )
    )

    errors: list[str] = []
    warnings: list[str] = []

    actual: dict[str, Any] = {}

    if not voice_file:

        errors.append(
            f"Scene {scene_id}: "
            f"voice.file is missing."
        )

    if planned_duration is None:

        errors.append(
            f"Scene {scene_id}: "
            f"planned duration is missing."
        )

    audio_path = None

    if voice_file:

        audio_path = (
            PROJECT_ROOT
            / voice_file
        )

        if not audio_path.exists():

            errors.append(
                f"Scene {scene_id}: "
                f"voice file does not exist: "
                f"{voice_file}"
            )

    if not errors:

        probe = run_ffprobe(
            audio_path
        )

        actual = (
            inspect_audio_probe(
                probe,
                audio_path
                .stat()
                .st_size,
            )
        )

        (
            passed,
            qc_errors,
            qc_warnings,
        ) = evaluate_voice_qc(
            float(
                planned_duration
            ),
            actual,
        )

        errors.extend(
            qc_errors
        )

        warnings.extend(
            qc_warnings
        )

    else:

        passed = False

    voice["qc"] = {

        "status":
            (
                "passed"
                if passed
                else "failed"
            ),

        "checked_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "expected": {

            "planned_scene_duration_sec":
                (
                    float(
                        planned_duration
                    )
                    if planned_duration
                    is not None
                    else None
                ),

            "min_duration_sec":
                MIN_DURATION_SEC,

            "min_file_size_bytes":
                MIN_FILE_SIZE_BYTES,

            "min_sample_rate":
                MIN_SAMPLE_RATE,

            "timing_policy":
                (
                    "Voice duration does not fail QC "
                    "for exceeding planned scene duration. "
                    "Video timing adapts to natural voice."
                ),
        },

        "actual":
            actual,

        "errors":
            errors,

        "warnings":
            warnings,
    }

    scene["voice"] = voice

    return passed


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - VOICE QC v2")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # ffprobe
    # -----------------------------------------------------

    ffprobe_path = shutil.which(
        "ffprobe"
    )

    if not ffprobe_path:

        print(
            "\nERROR: ffprobe not found in PATH."
        )

        return 1

    # -----------------------------------------------------
    # Load job
    # -----------------------------------------------------

    try:

        job = load_json(
            JOB_FILE
        )

    except Exception as exc:

        print(
            f"\nERROR loading video_job.json:\n"
            f"{exc}"
        )

        return 1

    scenes = (
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

    if not scenes:

        print(
            "\nERROR: script contains no scenes."
        )

        return 1

    # -----------------------------------------------------
    # Select scenes
    # -----------------------------------------------------

    if args.scene is not None:

        scene = find_script_scene(
            job,
            args.scene,
        )

        if scene is None:

            print(
                f"\nERROR: scene "
                f"{args.scene} not found."
            )

            return 1

        selected_scenes = [
            scene
        ]

    else:

        selected_scenes = scenes

    print(
        f"\nJob ID: "
        f"{job.get('job_id')}"
    )

    print(
        f"Scenes: "
        f"{len(selected_scenes)}"
    )

    passed_count = 0
    failed_count = 0

    # -----------------------------------------------------
    # QC loop
    # -----------------------------------------------------

    for scene in selected_scenes:

        scene_id = scene.get(
            "scene_id"
        )

        print(
            f"\nChecking scene "
            f"{scene_id}..."
        )

        try:

            passed = (
                check_scene_voice(
                    job,
                    scene,
                )
            )

        except Exception as exc:

            passed = False

            scene.setdefault(
                "voice",
                {},
            )

            scene["voice"][
                "qc"
            ] = {

                "status":
                    "failed",

                "checked_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "expected":
                    {},

                "actual":
                    {},

                "errors": [
                    str(exc)
                ],

                "warnings":
                    [],
            }

        qc = (
            scene
            .get(
                "voice",
                {},
            )
            .get(
                "qc",
                {},
            )
        )

        if passed:

            passed_count += 1

            print(
                "  PASS"
            )

        else:

            failed_count += 1

            print(
                "  FAIL"
            )

        actual = qc.get(
            "actual",
            {},
        )

        if actual:

            print(
                f"  Codec:       "
                f"{actual.get('codec')}"
            )

            print(
                f"  Sample rate: "
                f"{actual.get('sample_rate')} Hz"
            )

            print(
                f"  Channels:    "
                f"{actual.get('channels')}"
            )

            print(
                f"  Duration:    "
                f"{actual.get('duration_sec')}s"
            )

            print(
                f"  File size:   "
                f"{actual.get('file_size_bytes', 0):,} bytes"
            )

        for error in qc.get(
            "errors",
            [],
        ):

            print(
                f"  [ERROR] {error}"
            )

        for warning in qc.get(
            "warnings",
            [],
        ):

            print(
                f"  [WARNING] {warning}"
            )

        set_legacy_status_from_stage(
            job,
            "voice_qc",
        )

        save_job_atomic(
            job
        )

    # -----------------------------------------------------
    # Final status
    # -----------------------------------------------------

    set_legacy_status_from_stage(
        job,
        "voice_qc",
    )

    save_job_atomic(
        job
    )

    stage = (
        job[
            "pipeline_status"
        ][
            "voice_qc"
        ]
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "VOICE QC COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nPassed this run: "
        f"{passed_count}"
    )

    print(
        f"Failed this run: "
        f"{failed_count}"
    )

    print(
        f"Stage state: "
        f"{stage['state']}"
    )

    print(
        f"Ready: "
        f"{stage['ready']}/"
        f"{stage['total']}"
    )

    print(
        f"Failed overall: "
        f"{stage['failed']}"
    )

    print(
        f"Pending: "
        f"{stage['pending']}"
    )

    print(
        f"Job status: "
        f"{job.get('status')}"
    )

    if failed_count > 0:

        return 1

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )