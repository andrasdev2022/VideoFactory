from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from fractions import Fraction
import argparse
import json
import os
import shutil
import subprocess
import sys

from validator import load_json
from pipeline_status import set_legacy_status_from_stage

# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

MIN_FILE_SIZE_BYTES = int(
    os.getenv(
        "VIDEO_QC_MIN_FILE_SIZE_BYTES",
        "50000",
    )
)

DURATION_TOLERANCE_SEC = float(
    os.getenv(
        "VIDEO_QC_DURATION_TOLERANCE_SEC",
        "0.75",
    )
)

ASPECT_RATIO_TOLERANCE = float(
    os.getenv(
        "VIDEO_QC_ASPECT_RATIO_TOLERANCE",
        "0.02",
    )
)

MIN_FPS = float(
    os.getenv(
        "VIDEO_QC_MIN_FPS",
        "20",
    )
)

MAX_FPS = float(
    os.getenv(
        "VIDEO_QC_MAX_FPS",
        "60",
    )
)


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Video Factory technical video QC"
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help="Check one scene only, e.g. --scene 2",
    )

    return parser.parse_args()


# ---------------------------------------------------------
# SAVE JOB
# ---------------------------------------------------------

def save_job(job: dict) -> None:

    temp_file = JOB_FILE.with_name(
        JOB_FILE.name + ".tmp"
    )

    with temp_file.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            job,
            file,
            indent=2,
            ensure_ascii=False,
        )

        file.write("\n")

    temp_file.replace(
        JOB_FILE
    )


# ---------------------------------------------------------
# LOOKUPS
# ---------------------------------------------------------

def find_scene(
    job: dict,
    scene_id: int,
) -> dict | None:

    for scene in job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
    ):

        if scene.get("scene_id") == scene_id:
            return scene

    return None


def get_expected_duration(
    job: dict,
    scene_id: int,
) -> float | None:

    # The raw scene video is generated at the provider
    # duration, which may be the ceiling of the exact
    # audio-driven render target. Final assembly will trim
    # the clip to target_render_duration_sec.

    for scene in job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
    ):

        if scene.get(
            "scene_id"
        ) != scene_id:

            continue

        video = scene.get(
            "video",
            {},
        )

        duration = video.get(
            "provider_duration_sec",
            video.get(
                "duration_sec"
            ),
        )

        if duration is not None:

            return float(
                duration
            )

    # Legacy fallback for older artifacts.

    for scene in job.get(
        "script",
        {},
    ).get(
        "scenes",
        [],
    ):

        if scene.get(
            "scene_id"
        ) == scene_id:

            duration = scene.get(
                "duration_sec"
            )

            if duration is None:
                return None

            return float(
                duration
            )

    return None


def get_target_render_duration(
    job: dict,
    scene_id: int,
) -> float | None:

    for scene in job.get(
        "script",
        {},
    ).get(
        "scenes",
        [],
    ):

        if scene.get(
            "scene_id"
        ) != scene_id:

            continue

        timing = scene.get(
            "timing",
            {},
        )

        if timing.get(
            "status"
        ) != "passed":

            return None

        duration = timing.get(
            "render_duration_sec"
        )

        if duration is None:
            return None

        return float(
            duration
        )

    return None


# ---------------------------------------------------------
# PARSERS
# ---------------------------------------------------------

def parse_ratio(
    value: str | None,
) -> float | None:

    if not value:
        return None

    separator = (
        ":"
        if ":" in value
        else "x"
    )

    try:

        width_text, height_text = (
            value.split(
                separator,
                1,
            )
        )

        width = float(
            width_text
        )

        height = float(
            height_text
        )

        if height == 0:
            return None

        return width / height

    except ValueError:
        return None


def parse_fps(
    value: str | None,
) -> float | None:

    if not value:
        return None

    try:

        return float(
            Fraction(
                value
            )
        )

    except (
        ValueError,
        ZeroDivisionError,
    ):

        return None


# ---------------------------------------------------------
# FFPROBE
# ---------------------------------------------------------

def run_ffprobe(
    video_path: Path,
) -> dict:

    command = [
        "ffprobe",
        "-v",
        "error",

        "-show_streams",
        "-show_format",

        "-of",
        "json",

        str(video_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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
            f"Invalid ffprobe JSON: {exc}"
        )


# ---------------------------------------------------------
# ANALYSIS
# ---------------------------------------------------------

def analyze_video(
    video_path: Path,
) -> dict:

    probe = run_ffprobe(
        video_path
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
        if stream.get("codec_type") == "video"
    ]

    audio_streams = [
        stream
        for stream in streams
        if stream.get("codec_type") == "audio"
    ]

    if not video_streams:

        raise RuntimeError(
            "No video stream found."
        )

    video_stream = video_streams[0]

    width = int(
        video_stream.get(
            "width",
            0,
        )
    )

    height = int(
        video_stream.get(
            "height",
            0,
        )
    )

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

    # Prefer container duration.
    duration_text = format_data.get(
        "duration"
    )

    if not duration_text:

        duration_text = video_stream.get(
            "duration"
        )

    duration = None

    if duration_text:

        try:

            duration = float(
                duration_text
            )

        except ValueError:
            pass

    file_size = (
        video_path
        .stat()
        .st_size
    )

    return {
        "file_size_bytes":
            file_size,

        "video_stream_count":
            len(video_streams),

        "audio_stream_count":
            len(audio_streams),

        "codec":
            video_stream.get(
                "codec_name"
            ),

        "codec_long_name":
            video_stream.get(
                "codec_long_name"
            ),

        "pixel_format":
            video_stream.get(
                "pix_fmt"
            ),

        "width":
            width,

        "height":
            height,

        "aspect_ratio":
            (
                width / height
                if height
                else None
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

        "duration_sec":
            (
                round(
                    duration,
                    3,
                )
                if duration is not None
                else None
            ),

        "format_name":
            format_data.get(
                "format_name"
            ),

        "bit_rate":
            format_data.get(
                "bit_rate"
            ),
    }


# ---------------------------------------------------------
# CHECK ONE SCENE
# ---------------------------------------------------------

def check_scene_video(
    job: dict,
    scene: dict,
) -> bool:

    scene_id = scene[
        "scene_id"
    ]

    errors: list[str] = []
    warnings: list[str] = []

    video = scene.get(
        "video",
        {},
    )

    video_file = video.get(
        "file"
    )

    # -----------------------------------------------------
    # File metadata exists
    # -----------------------------------------------------

    if not video_file:

        errors.append(
            "Scene has no video.file value."
        )

        video.setdefault(
            "qc",
            {}
        )

        video["qc"] = {
            "status": "failed",
            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "errors": errors,
            "warnings": warnings,
        }

        return False

    video_path = (
        PROJECT_ROOT
        / video_file
    )

    # -----------------------------------------------------
    # File exists
    # -----------------------------------------------------

    if not video_path.exists():

        errors.append(
            f"Video file does not exist: "
            f"{video_file}"
        )

        video["qc"] = {
            "status": "failed",
            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "errors": errors,
            "warnings": warnings,
        }

        return False

    # -----------------------------------------------------
    # Analyze
    # -----------------------------------------------------

    try:

        actual = analyze_video(
            video_path
        )

    except Exception as exc:

        errors.append(
            str(exc)
        )

        video["qc"] = {
            "status": "failed",
            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "errors": errors,
            "warnings": warnings,
        }

        return False

    # -----------------------------------------------------
    # File size
    # -----------------------------------------------------

    if (
        actual["file_size_bytes"]
        < MIN_FILE_SIZE_BYTES
    ):

        errors.append(
            f"Video file is suspiciously small: "
            f"{actual['file_size_bytes']:,} bytes."
        )

    # -----------------------------------------------------
    # Codec
    # -----------------------------------------------------

    codec = actual.get(
        "codec"
    )

    if codec != "h264":

        warnings.append(
            f"Video codec is '{codec}', "
            f"expected H.264."
        )

    # -----------------------------------------------------
    # Resolution / orientation
    # -----------------------------------------------------

    width = actual[
        "width"
    ]

    height = actual[
        "height"
    ]

    if width <= 0 or height <= 0:

        errors.append(
            "Invalid video resolution."
        )

    elif height <= width:

        errors.append(
            f"Video is not portrait: "
            f"{width}x{height}."
        )

    # -----------------------------------------------------
    # Expected ratio
    # -----------------------------------------------------

    expected_ratio_text = video.get(
        "ratio",
        os.getenv(
            "RUNWAY_VIDEO_RATIO",
            "720:1280",
        ),
    )

    expected_ratio = parse_ratio(
        expected_ratio_text
    )

    actual_ratio = actual.get(
        "aspect_ratio"
    )

    if (
        expected_ratio is not None
        and
        actual_ratio is not None
    ):

        relative_difference = abs(
            actual_ratio
            - expected_ratio
        ) / expected_ratio

        if (
            relative_difference
            > ASPECT_RATIO_TOLERANCE
        ):

            errors.append(
                f"Unexpected aspect ratio: "
                f"{width}:{height}. "
                f"Expected approximately "
                f"{expected_ratio_text}."
            )

    # -----------------------------------------------------
    # FPS
    # -----------------------------------------------------

    fps = actual.get(
        "fps"
    )

    if fps is None:

        warnings.append(
            "Unable to determine FPS."
        )

    elif not (
        MIN_FPS
        <= fps
        <= MAX_FPS
    ):

        warnings.append(
            f"Unusual FPS: {fps}. "
            f"Expected approximately "
            f"{MIN_FPS}-{MAX_FPS}."
        )

    # -----------------------------------------------------
    # Duration
    # -----------------------------------------------------

    expected_duration = (
        get_expected_duration(
            job,
            scene_id,
        )
    )

    actual_duration = actual.get(
        "duration_sec"
    )

    if expected_duration is None:

        errors.append(
            "Expected duration not found "
            "in script.scenes."
        )

    elif actual_duration is None:

        errors.append(
            "Unable to determine actual video duration."
        )

    else:

        difference = abs(
            actual_duration
            - expected_duration
        )

        if (
            difference
            > DURATION_TOLERANCE_SEC
        ):

            errors.append(
                f"Unexpected duration: "
                f"{actual_duration:.3f}s. "
                f"Expected {expected_duration:.3f}s "
                f"(tolerance ±"
                f"{DURATION_TOLERANCE_SEC}s)."
            )

    # -----------------------------------------------------
    # Multiple streams
    # -----------------------------------------------------

    if (
        actual["video_stream_count"]
        > 1
    ):

        warnings.append(
            f"Video contains "
            f"{actual['video_stream_count']} "
            f"video streams."
        )

    # Audio isn't required yet.
    if (
        actual["audio_stream_count"]
        > 0
    ):

        warnings.append(
            "Scene video contains audio. "
            "Audio will later be replaced/mixed "
            "during assembly."
        )

    # -----------------------------------------------------
    # Result
    # -----------------------------------------------------

    passed = (
        len(errors) == 0
    )

    video["qc"] = {
        "status": (
            "passed"
            if passed
            else "failed"
        ),

        "checked_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "expected": {
            "provider_duration_sec":
                expected_duration,

            "target_render_duration_sec":
                get_target_render_duration(
                    job,
                    scene_id,
                ),

            "ratio":
                expected_ratio_text,

            "codec":
                "h264",

            "min_file_size_bytes":
                MIN_FILE_SIZE_BYTES,
        },

        "actual":
            actual,

        "errors":
            errors,

        "warnings":
            warnings,
    }

    return passed


# ---------------------------------------------------------
# GLOBAL STATUS
# ---------------------------------------------------------

def all_scene_video_qc_passed(
    job: dict,
) -> bool:

    scenes = job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
    )

    if not scenes:
        return False

    for scene in scenes:

        status = (
            scene
            .get(
                "video",
                {},
            )
            .get(
                "qc",
                {},
            )
            .get(
                "status"
            )
        )

        if status != "passed":
            return False

    return True


def any_scene_video_qc_failed(
    job: dict,
) -> bool:

    scenes = job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
    )

    for scene in scenes:

        status = (
            scene
            .get(
                "video",
                {},
            )
            .get(
                "qc",
                {},
            )
            .get(
                "status"
            )
        )

        if status == "failed":
            return True

    return False


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - VIDEO QC v2")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # ffprobe available?
    # -----------------------------------------------------

    ffprobe_path = shutil.which(
        "ffprobe"
    )

    if not ffprobe_path:

        print(
            "\nERROR: ffprobe not found in PATH."
        )

        return 1

    print(
        f"\nffprobe: {ffprobe_path}"
    )

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
            "visuals",
            {},
        )
        .get(
            "scenes",
            [],
        )
    )

    if not scenes:

        print(
            "\nERROR: no scenes found."
        )

        return 1

    # -----------------------------------------------------
    # Select scenes
    # -----------------------------------------------------

    if args.scene is not None:

        scene = find_scene(
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
        f"Job ID: {job.get('job_id')}"
    )

    print(
        f"Scenes: {len(selected_scenes)}"
    )

    passed_count = 0
    failed_count = 0

    # -----------------------------------------------------
    # QC
    # -----------------------------------------------------

    for scene in selected_scenes:

        scene_id = (
            scene["scene_id"]
        )

        print(
            f"\nChecking scene {scene_id}..."
        )

        passed = check_scene_video(
            job,
            scene,
        )

        qc = (
            scene
            .get(
                "video",
                {},
            )
            .get(
                "qc",
                {},
            )
        )

        if passed:

            passed_count += 1

            actual = qc.get(
                "actual",
                {},
            )

            print(
                "  PASS"
            )

            print(
                f"  Resolution: "
                f"{actual.get('width')}x"
                f"{actual.get('height')}"
            )

            print(
                f"  Codec:      "
                f"{actual.get('codec')}"
            )

            print(
                f"  FPS:        "
                f"{actual.get('fps')}"
            )

            print(
                f"  Duration:   "
                f"{actual.get('duration_sec')}s"
            )

            print(
                f"  File size:  "
                f"{actual.get('file_size_bytes', 0):,} bytes"
            )

        else:

            failed_count += 1

            print(
                "  FAIL"
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

        # ---------------------------------------------
        # Recalculate status after every processed scene.
        # ---------------------------------------------

        set_legacy_status_from_stage(
            job,
            "video_qc",
        )

        save_job(
            job
        )

    # -----------------------------------------------------
    # Final status
    # -----------------------------------------------------

    set_legacy_status_from_stage(
        job,
        "video_qc",
    )

    save_job(
        job
    )

    stage = (
        job["pipeline_status"]
        ["video_qc"]
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print(
        "\n" + "=" * 60
    )

    print(
        "VIDEO QC COMPLETE"
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

    sys.exit(
        main()
    )