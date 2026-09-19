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
from video_qc import analyze_video


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


DURATION_TOLERANCE_SEC = float(
    os.getenv(
        "SCENE_TRIM_DURATION_TOLERANCE_SEC",
        "0.08",
    )
)

CRF = int(
    os.getenv(
        "SCENE_TRIM_CRF",
        "18",
    )
)

PRESET = os.getenv(
    "SCENE_TRIM_PRESET",
    "medium",
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Create exact-duration scene clips from "
            "approved raw scene videos."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Trim one scene only. "
            "If omitted, process all scenes."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Recreate the trimmed clip even when current "
            "metadata and output already match."
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


def get_target_render_duration(
    job: dict,
    scene_id: int,
) -> float | None:

    script_scene = find_script_scene(
        job,
        scene_id,
    )

    if script_scene is None:

        return None

    timing = script_scene.get(
        "timing",
        {},
    )

    if timing.get(
        "status"
    ) != "passed":

        return None

    value = timing.get(
        "render_duration_sec"
    )

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


def get_trimmed_output_path(
    job: dict,
    scene_id: int,
) -> Path:

    return (
        PROJECT_ROOT
        / "output"
        / job[
            "job_id"
        ]
        / "videos"
        / "trimmed"
        / (
            f"scene_"
            f"{scene_id:03d}.mp4"
        )
    )


def validate_trim_preconditions(
    job: dict,
    scene: dict,
) -> list[str]:

    errors: list[str] = []

    scene_id = scene.get(
        "scene_id"
    )

    video = scene.get(
        "video",
        {},
    )

    if video.get(
        "qc",
        {},
    ).get(
        "status"
    ) != "passed":

        errors.append(
            "Raw video technical QC has not passed."
        )

    if video.get(
        "semantic_qc",
        {},
    ).get(
        "status"
    ) != "passed":

        errors.append(
            "Raw video semantic QC has not passed."
        )

    source_file = video.get(
        "file"
    )

    if not source_file:

        errors.append(
            "Raw video file metadata is missing."
        )

    else:

        source_path = (
            PROJECT_ROOT
            / source_file
        )

        if not source_path.exists():

            errors.append(
                f"Raw video file does not exist: "
                f"{source_file}"
            )

    target_duration = (
        get_target_render_duration(
            job,
            scene_id,
        )
    )

    if target_duration is None:

        errors.append(
            "Approved render duration is unavailable."
        )

    elif target_duration <= 0:

        errors.append(
            "Approved render duration must be positive."
        )

    return errors


def trimmed_metadata_matches_current_request(
    scene: dict,
    output_file: Path,
    target_duration_sec: float,
) -> bool:

    video = scene.get(
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

        return False

    expected_file = str(
        output_file.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    if trimmed.get(
        "file"
    ) != expected_file:

        return False

    if trimmed.get(
        "source_video"
    ) != video.get(
        "file"
    ):

        return False

    if trimmed.get(
        "source_task_id"
    ) != video.get(
        "task_id"
    ):

        return False

    try:

        stored_target = float(
            trimmed.get(
                "target_duration_sec"
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        return False

    if abs(
        stored_target
        - float(
            target_duration_sec
        )
    ) > 0.001:

        return False

    return output_file.exists()


def build_ffmpeg_command(
    source_file: Path,
    output_file: Path,
    target_duration_sec: float,
) -> list[str]:

    return [
        "ffmpeg",
        "-y",
        "-v",
        "error",

        "-i",
        str(
            source_file
        ),

        "-t",
        f"{target_duration_sec:.3f}",

        "-map",
        "0:v:0",

        "-an",

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

        "-movflags",
        "+faststart",

        str(
            output_file
        ),
    ]


def evaluate_trimmed_video(
    actual: dict[str, Any],
    target_duration_sec: float,
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
            "Unable to determine trimmed video duration."
        )

    else:

        difference = abs(
            float(
                duration
            )
            - float(
                target_duration_sec
            )
        )

        if (
            difference
            > DURATION_TOLERANCE_SEC
        ):

            errors.append(
                f"Trimmed duration differs from target "
                f"by {difference:.3f}s; tolerance is "
                f"{DURATION_TOLERANCE_SEC:.3f}s."
            )

    if actual.get(
        "video_stream_count"
    ) != 1:

        errors.append(
            "Trimmed artifact must contain exactly "
            "one video stream."
        )

    if actual.get(
        "audio_stream_count"
    ) != 0:

        errors.append(
            "Trimmed scene clip must not contain audio."
        )

    codec = actual.get(
        "codec"
    )

    if codec != "h264":

        warnings.append(
            f"Trimmed video codec is '{codec}', "
            f"expected H.264."
        )

    if (
        actual.get(
            "width",
            0,
        )
        <= 0
        or actual.get(
            "height",
            0,
        )
        <= 0
    ):

        errors.append(
            "Trimmed video resolution is invalid."
        )

    return (
        not errors,
        errors,
        warnings,
    )


def trim_scene_video(
    job: dict,
    scene: dict,
    force: bool,
) -> bool:

    scene_id = scene[
        "scene_id"
    ]

    errors = validate_trim_preconditions(
        job,
        scene,
    )

    if errors:

        raise RuntimeError(
            "\n".join(
                f"Scene {scene_id}: {error}"
                for error in errors
            )
        )

    video = scene[
        "video"
    ]

    source_file = video[
        "file"
    ]

    source_path = (
        PROJECT_ROOT
        / source_file
    )

    target_duration = (
        get_target_render_duration(
            job,
            scene_id,
        )
    )

    if target_duration is None:

        raise RuntimeError(
            f"Scene {scene_id}: target render "
            f"duration is unavailable."
        )

    output_file = get_trimmed_output_path(
        job,
        scene_id,
    )

    if (
        not force
        and trimmed_metadata_matches_current_request(
            scene=scene,
            output_file=output_file,
            target_duration_sec=target_duration,
        )
    ):

        print(
            f"  SKIP: Scene {scene_id} trimmed "
            f"clip already matches current timing."
        )

        return False

    if shutil.which(
        "ffmpeg"
    ) is None:

        raise RuntimeError(
            "ffmpeg is not available on PATH."
        )

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

    raw_actual = analyze_video(
        source_path
    )

    raw_duration = raw_actual.get(
        "duration_sec"
    )

    if raw_duration is None:

        raise RuntimeError(
            f"Scene {scene_id}: unable to determine "
            f"raw video duration."
        )

    if (
        float(
            raw_duration
        )
        + DURATION_TOLERANCE_SEC
        < target_duration
    ):

        raise RuntimeError(
            f"Scene {scene_id}: raw video is only "
            f"{float(raw_duration):.3f}s but target "
            f"duration is {target_duration:.3f}s."
        )

    command = build_ffmpeg_command(
        source_file=source_path,
        output_file=temporary_file,
        target_duration_sec=
            target_duration,
    )

    print(
        f"\nTrimming scene {scene_id}"
    )

    print(
        f"  Source: "
        f"{source_file}"
    )

    print(
        f"  Raw duration: "
        f"{float(raw_duration):.3f}s"
    )

    print(
        f"  Target: "
        f"{target_duration:.3f}s"
    )

    print(
        f"  Output: "
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
            "ffmpeg trim failed:\n"
            + result.stderr.strip()
        )

    if (
        not temporary_file.exists()
        or temporary_file.stat().st_size
        <= 0
    ):

        raise RuntimeError(
            "ffmpeg did not create a valid "
            "temporary trimmed video."
        )

    trimmed_actual = analyze_video(
        temporary_file
    )

    (
        passed,
        qc_errors,
        qc_warnings,
    ) = evaluate_trimmed_video(
        actual=trimmed_actual,
        target_duration_sec=
            target_duration,
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

        video[
            "trimmed"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "source_video":
                source_file,

            "source_task_id":
                video.get(
                    "task_id"
                ),

            "target_duration_sec":
                round(
                    target_duration,
                    3,
                ),

            "actual":
                trimmed_actual,

            "errors":
                qc_errors,

            "warnings":
                qc_warnings,
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

    video[
        "trimmed"
    ] = {
        "status":
            "passed",

        "checked_at":
            checked_at,

        "file":
            relative_output,

        "source_video":
            source_file,

        "source_task_id":
            video.get(
                "task_id"
            ),

        "target_duration_sec":
            round(
                target_duration,
                3,
            ),

        "duration_tolerance_sec":
            DURATION_TOLERANCE_SEC,

        "encoder":
            "libx264",

        "crf":
            CRF,

        "preset":
            PRESET,

        "actual":
            trimmed_actual,

        "errors":
            [],

        "warnings":
            qc_warnings,
    }

    print(
        f"  Actual: "
        f"{trimmed_actual.get('duration_sec')}s"
    )

    print(
        "  PASS"
    )

    return True


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SCENE VIDEO TRIMMER v1")
    print("=" * 60)

    args = parse_args()

    try:

        job = load_json(
            JOB_FILE
        )

    except Exception as exc:

        print(
            f"\nERROR loading job:\n"
            f"{exc}"
        )

        return 1

    visual_scenes = (
        job
        .get(
            "visuals",
            {},
        )
        .get(
            "scenes",
            [],
        )
    )

    if args.scene is not None:

        scene = find_visual_scene(
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

        selected_scenes = (
            visual_scenes
        )

    passed_count = 0
    failed_count = 0
    skipped_count = 0

    for scene in selected_scenes:

        scene_id = scene.get(
            "scene_id"
        )

        try:

            changed = trim_scene_video(
                job=job,
                scene=scene,
                force=args.force,
            )

        except Exception as exc:

            failed_count += 1

            scene.setdefault(
                "video",
                {},
            )[
                "trimmed"
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

            print(
                f"\nScene {scene_id}: FAIL"
            )

            print(
                f"  {exc}"
            )

            continue

        status = (
            scene
            .get(
                "video",
                {},
            )
            .get(
                "trimmed",
                {},
            )
            .get(
                "status"
            )
        )

        if status == "passed":

            passed_count += 1

            if not changed:

                skipped_count += 1

        else:

            failed_count += 1

    set_legacy_status_from_stage(
        job,
        "scene_trimmed",
    )

    save_job_atomic(
        job
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "SCENE VIDEO TRIM COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nPassed:  "
        f"{passed_count}"
    )

    print(
        f"Skipped: "
        f"{skipped_count}"
    )

    print(
        f"Failed:  "
        f"{failed_count}"
    )

    return (
        1
        if failed_count > 0
        else 0
    )


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
