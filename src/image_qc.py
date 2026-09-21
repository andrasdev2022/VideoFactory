from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import os
import sys

from PIL import Image, ImageStat, UnidentifiedImageError

from validator import load_json


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

from genre_policy import runtime_spec as load_yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SPEC_FILE = PROJECT_ROOT / "config" / "video_spec_v1.yaml"
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

MIN_FILE_SIZE_BYTES = int(
    os.getenv(
        "IMAGE_QC_MIN_FILE_SIZE_BYTES",
        "20000",
    )
)

ASPECT_RATIO_TOLERANCE = float(
    os.getenv(
        "IMAGE_QC_ASPECT_RATIO_TOLERANCE",
        "0.02",
    )
)

MIN_LUMINANCE_STDDEV = float(
    os.getenv(
        "IMAGE_QC_MIN_LUMINANCE_STDDEV",
        "2.0",
    )
)


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Video Factory image quality control"
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Check only one scene ID. "
            "Example: --scene 2"
        ),
    )

    return parser.parse_args()


# ---------------------------------------------------------
# SAVE JOB ATOMICALLY
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
# HELPERS
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


def parse_size(
    value: str | None,
) -> tuple[int, int] | None:

    if not value:
        return None

    try:

        width_text, height_text = (
            value.lower().split("x")
        )

        return (
            int(width_text),
            int(height_text),
        )

    except (
        ValueError,
        AttributeError,
    ):

        return None


def parse_aspect_ratio(
    value: str | None,
) -> float | None:

    if not value:
        return None

    try:

        width_text, height_text = (
            value.split(":")
        )

        width = float(width_text)
        height = float(height_text)

        if height == 0:
            return None

        return width / height

    except (
        ValueError,
        AttributeError,
    ):

        return None


def relative_path(
    path: Path,
) -> str:

    return str(
        path.relative_to(PROJECT_ROOT)
    ).replace(
        "\\",
        "/",
    )


# ---------------------------------------------------------
# IMAGE ANALYSIS
# ---------------------------------------------------------

def analyze_image(
    image_path: Path,
) -> dict:

    file_size = image_path.stat().st_size

    try:

        with Image.open(
            image_path
        ) as image:

            # Force Pillow to actually decode the file.
            image.load()

            width, height = image.size

            image_format = image.format
            image_mode = image.mode

            frame_count = getattr(
                image,
                "n_frames",
                1,
            )

            # ---------------------------------------------
            # Basic visual variance check
            # ---------------------------------------------

            grayscale = image.convert(
                "L"
            )

            grayscale.thumbnail(
                (128, 128)
            )

            statistics = ImageStat.Stat(
                grayscale
            )

            luminance_mean = (
                statistics.mean[0]
            )

            luminance_stddev = (
                statistics.stddev[0]
            )

            # ---------------------------------------------
            # Alpha analysis
            # ---------------------------------------------

            alpha_mean = None
            alpha_min = None
            alpha_max = None

            if "A" in image.getbands():

                alpha = image.getchannel(
                    "A"
                )

                alpha_stats = ImageStat.Stat(
                    alpha
                )

                alpha_mean = (
                    alpha_stats.mean[0]
                )

                extrema = alpha.getextrema()

                alpha_min = extrema[0]
                alpha_max = extrema[1]

    except UnidentifiedImageError:

        raise RuntimeError(
            "File is not a recognized image."
        )

    except Exception as exc:

        raise RuntimeError(
            f"Image could not be decoded: {exc}"
        )

    return {
        "file_size_bytes": file_size,

        "width": width,
        "height": height,

        "aspect_ratio": (
            width / height
            if height
            else None
        ),

        "format": image_format,
        "mode": image_mode,

        "frames": frame_count,

        "luminance_mean":
            round(
                luminance_mean,
                3,
            ),

        "luminance_stddev":
            round(
                luminance_stddev,
                3,
            ),

        "alpha_mean": (
            round(alpha_mean, 3)
            if alpha_mean is not None
            else None
        ),

        "alpha_min": alpha_min,
        "alpha_max": alpha_max,
    }


# ---------------------------------------------------------
# QC ONE SCENE
# ---------------------------------------------------------

def check_scene_image(
    spec: dict,
    job: dict,
    scene: dict,
) -> bool:

    scene_id = scene["scene_id"]

    errors: list[str] = []
    warnings: list[str] = []

    image_info = scene.get(
        "image",
        {},
    )

    image_file = image_info.get(
        "file"
    )

    # -----------------------------------------------------
    # Does job contain image metadata?
    # -----------------------------------------------------

    if not image_file:

        errors.append(
            "Scene has no image.file value."
        )

        scene["image"] = image_info

        image_info["qc"] = {
            "status": "failed",
            "checked_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "errors": errors,
            "warnings": warnings,
        }

        return False

    image_path = (
        PROJECT_ROOT
        / image_file
    )

    # -----------------------------------------------------
    # File exists?
    # -----------------------------------------------------

    if not image_path.exists():

        errors.append(
            f"Image file does not exist: "
            f"{image_file}"
        )

        image_info["qc"] = {
            "status": "failed",
            "checked_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "errors": errors,
            "warnings": warnings,
        }

        return False

    # -----------------------------------------------------
    # Analyze
    # -----------------------------------------------------

    try:

        actual = analyze_image(
            image_path
        )

    except Exception as exc:

        errors.append(
            str(exc)
        )

        image_info["qc"] = {
            "status": "failed",
            "checked_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "errors": errors,
            "warnings": warnings,
        }

        return False

    # -----------------------------------------------------
    # Expected values
    # -----------------------------------------------------

    expected_size_text = image_info.get(
        "size"
    )

    expected_size = parse_size(
        expected_size_text
    )

    expected_aspect_text = (
        spec["video"]["aspect_ratio"]
    )

    expected_aspect = parse_aspect_ratio(
        expected_aspect_text
    )

    # -----------------------------------------------------
    # File size
    # -----------------------------------------------------

    if (
        actual["file_size_bytes"]
        < MIN_FILE_SIZE_BYTES
    ):

        errors.append(
            f"File is suspiciously small: "
            f"{actual['file_size_bytes']:,} bytes. "
            f"Minimum expected: "
            f"{MIN_FILE_SIZE_BYTES:,} bytes."
        )

    # -----------------------------------------------------
    # Format
    # -----------------------------------------------------

    if actual["format"] != "PNG":

        errors.append(
            f"Unexpected image format: "
            f"{actual['format']}. "
            f"Expected PNG."
        )

    # -----------------------------------------------------
    # Exact expected size
    # -----------------------------------------------------

    if expected_size is not None:

        expected_width, expected_height = (
            expected_size
        )

        if (
            actual["width"]
            != expected_width
            or
            actual["height"]
            != expected_height
        ):

            errors.append(
                f"Unexpected resolution: "
                f"{actual['width']}x"
                f"{actual['height']}. "
                f"Expected "
                f"{expected_width}x"
                f"{expected_height}."
            )

    else:

        warnings.append(
            "No valid expected image size "
            "stored in video_job.json."
        )

    # -----------------------------------------------------
    # Aspect ratio
    # -----------------------------------------------------

    actual_aspect = actual[
        "aspect_ratio"
    ]

    if (
        expected_aspect is not None
        and
        actual_aspect is not None
    ):

        relative_difference = abs(
            actual_aspect
            - expected_aspect
        ) / expected_aspect

        if (
            relative_difference
            > ASPECT_RATIO_TOLERANCE
        ):

            errors.append(
                f"Invalid aspect ratio: "
                f"{actual['width']}:"
                f"{actual['height']}. "
                f"Expected approximately "
                f"{expected_aspect_text}."
            )

    # -----------------------------------------------------
    # Portrait orientation
    # -----------------------------------------------------

    if (
        actual["height"]
        <= actual["width"]
    ):

        errors.append(
            "Image is not portrait orientation."
        )

    # -----------------------------------------------------
    # Static image
    # -----------------------------------------------------

    if actual["frames"] != 1:

        warnings.append(
            f"Image contains "
            f"{actual['frames']} frames."
        )

    # -----------------------------------------------------
    # Color mode
    # -----------------------------------------------------

    if actual["mode"] not in (
        "RGB",
        "RGBA",
    ):

        warnings.append(
            f"Unusual image mode: "
            f"{actual['mode']}."
        )

    # -----------------------------------------------------
    # Nearly blank image
    # -----------------------------------------------------

    if (
        actual["luminance_stddev"]
        < MIN_LUMINANCE_STDDEV
    ):

        errors.append(
            f"Image appears nearly uniform or blank. "
            f"Luminance stddev: "
            f"{actual['luminance_stddev']}."
        )

    # -----------------------------------------------------
    # Fully transparent
    # -----------------------------------------------------

    if (
        actual["alpha_max"] is not None
        and
        actual["alpha_max"] == 0
    ):

        errors.append(
            "Image is fully transparent."
        )

    # -----------------------------------------------------
    # Result
    # -----------------------------------------------------

    passed = len(errors) == 0

    qc_result = {
        "status": (
            "passed"
            if passed
            else "failed"
        ),

        "checked_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),

        "expected": {
            "format": "PNG",

            "size":
                expected_size_text,

            "aspect_ratio":
                expected_aspect_text,

            "min_file_size_bytes":
                MIN_FILE_SIZE_BYTES,
        },

        "actual": actual,

        "errors": errors,
        "warnings": warnings,
    }

    image_info["qc"] = qc_result

    return passed


# ---------------------------------------------------------
# GLOBAL QC STATE
# ---------------------------------------------------------

def all_scene_images_qc_passed(
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

        qc = scene.get(
            "image",
            {},
        ).get(
            "qc",
            {},
        )

        if qc.get("status") != "passed":
            return False

    return True


def any_scene_image_qc_failed(
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

        qc = scene.get(
            "image",
            {},
        ).get(
            "qc",
            {},
        )

        if qc.get("status") == "failed":
            return True

    return False


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - IMAGE QC v1")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # Load
    # -----------------------------------------------------

    try:

        spec = load_yaml(
            SPEC_FILE
        )

        job = load_json(
            JOB_FILE
        )

    except Exception as exc:

        print(
            f"\nERROR loading input files:\n"
            f"{exc}"
        )

        return 1

    scenes = job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
    )

    if not scenes:

        print(
            "\nERROR: No visual scenes found."
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
                f"\nERROR: Scene "
                f"{args.scene} not found."
            )

            return 1

        selected_scenes = [
            scene
        ]

    else:

        selected_scenes = scenes

    print(
        f"\nJob ID: {job.get('job_id')}"
    )

    print(
        f"Scenes to check: "
        f"{len(selected_scenes)}"
    )

    # -----------------------------------------------------
    # QC
    # -----------------------------------------------------

    passed_count = 0
    failed_count = 0

    for scene in selected_scenes:

        scene_id = scene["scene_id"]

        print(
            f"\nChecking scene {scene_id}..."
        )

        passed = check_scene_image(
            spec=spec,
            job=job,
            scene=scene,
        )

        qc = scene.get(
            "image",
            {},
        ).get(
            "qc",
            {},
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
                f"  Format:     "
                f"{actual.get('format')}"
            )

            print(
                f"  File size:  "
                f"{actual.get('file_size_bytes', 0):,} bytes"
            )

            for warning in qc.get(
                "warnings",
                [],
            ):

                print(
                    f"  [WARNING] {warning}"
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

        # Checkpoint after every scene.
        save_job(
            job
        )

    # -----------------------------------------------------
    # Job state
    # -----------------------------------------------------

    if all_scene_images_qc_passed(
        job
    ):

        job["status"] = (
            "scene_images_qc_passed"
        )

    elif any_scene_image_qc_failed(
        job
    ):

        job["status"] = (
            "scene_images_qc_failed"
        )

    save_job(
        job
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print(
        "\n" + "=" * 60
    )

    print(
        "IMAGE QC COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nPassed: {passed_count}"
    )

    print(
        f"Failed: {failed_count}"
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