from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess

from datetime import datetime, timezone
from pathlib import Path

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


FALLBACK_WIDTH = int(
    os.getenv(
        "LOCAL_VIDEO_FALLBACK_WIDTH",
        "720",
    )
)

FALLBACK_HEIGHT = int(
    os.getenv(
        "LOCAL_VIDEO_FALLBACK_HEIGHT",
        "1280",
    )
)

FALLBACK_FPS = float(
    os.getenv(
        "LOCAL_VIDEO_FALLBACK_FPS",
        "24",
    )
)

FALLBACK_CRF = int(
    os.getenv(
        "LOCAL_VIDEO_FALLBACK_CRF",
        "18",
    )
)

FALLBACK_PRESET = os.getenv(
    "LOCAL_VIDEO_FALLBACK_PRESET",
    "medium",
)

FALLBACK_MAX_ZOOM = float(
    os.getenv(
        "LOCAL_VIDEO_FALLBACK_MAX_ZOOM",
        "1.025",
    )
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Create a deterministic local scene video from the "
            "approved source image after repeated provider failures."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--force",
        action="store_true",
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


def get_target_duration(
    job: dict,
    scene_id: int,
) -> float:

    script_scene = find_script_scene(
        job,
        scene_id,
    )

    if script_scene is None:

        raise RuntimeError(
            f"Scene {scene_id}: script scene is missing."
        )

    timing = script_scene.get(
        "timing",
        {},
    )

    if timing.get(
        "status"
    ) != "passed":

        raise RuntimeError(
            f"Scene {scene_id}: timing has not passed."
        )

    value = timing.get(
        "render_duration_sec"
    )

    if value is None:

        raise RuntimeError(
            f"Scene {scene_id}: render duration is missing."
        )

    value = float(
        value
    )

    if value <= 0:

        raise RuntimeError(
            f"Scene {scene_id}: invalid render duration."
        )

    return value


def get_output_path(
    job: dict,
    scene_id: int,
) -> Path:

    return (
        PROJECT_ROOT
        / "output"
        / str(
            job[
                "job_id"
            ]
        )
        / "videos"
        / (
            f"scene_"
            f"{scene_id:03d}"
            f"_fallback.mp4"
        )
    )


def build_ffmpeg_command(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
) -> list[str]:

    frame_count = max(
        1,
        math.ceil(
            duration_sec
            * FALLBACK_FPS
        ),
    )

    zoom_increment = (
        max(
            0.0,
            FALLBACK_MAX_ZOOM
            - 1.0
        )
        / max(
            1,
            frame_count - 1,
        )
    )

    zoom_filter = (
        f"zoompan="
        f"z='min(zoom+{zoom_increment:.8f},{FALLBACK_MAX_ZOOM:.5f})':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d=1:"
        f"s={FALLBACK_WIDTH}x{FALLBACK_HEIGHT}:"
        f"fps={FALLBACK_FPS:.3f},"
        f"setsar=1,"
        f"format=yuv420p"
    )

    return [
        "ffmpeg",
        "-y",
        "-v",
        "error",

        "-loop",
        "1",

        "-i",
        str(
            image_path
        ),

        "-vf",
        zoom_filter,

        "-frames:v",
        str(
            frame_count
        ),

        "-an",

        "-c:v",
        "libx264",

        "-preset",
        FALLBACK_PRESET,

        "-crf",
        str(
            FALLBACK_CRF
        ),

        "-pix_fmt",
        "yuv420p",

        "-movflags",
        "+faststart",

        str(
            output_path
        ),
    ]


def generate_fallback(
    job: dict,
    scene: dict,
    force: bool,
) -> bool:

    scene_id = int(
        scene[
            "scene_id"
        ]
    )

    image = scene.get(
        "image",
        {},
    )

    if (
        image.get(
            "status"
        )
        not in {
            "generated",
            "completed",
            "passed",
        }
        or image.get(
            "qc",
            {},
        ).get(
            "status"
        )
        != "passed"
        or image.get(
            "semantic_qc",
            {},
        ).get(
            "status"
        )
        != "passed"
    ):

        raise RuntimeError(
            f"Scene {scene_id}: approved source image "
            f"and both image QCs are required."
        )

    image_file = image.get(
        "file"
    )

    if not image_file:

        raise RuntimeError(
            f"Scene {scene_id}: image file metadata is missing."
        )

    image_path = (
        PROJECT_ROOT
        / image_file
    )

    if not image_path.exists():

        raise RuntimeError(
            f"Scene {scene_id}: image file does not exist."
        )

    if shutil.which(
        "ffmpeg"
    ) is None:

        raise RuntimeError(
            "ffmpeg is not available on PATH."
        )

    duration = get_target_duration(
        job,
        scene_id,
    )

    output_file = get_output_path(
        job,
        scene_id,
    )

    if (
        output_file.exists()
        and not force
        and scene.get(
            "video",
            {},
        ).get(
            "provider"
        )
        == "local_ffmpeg"
        and scene.get(
            "motion_strategy"
        )
        == "still_image_fallback_v1"
    ):

        print(
            f"  SKIP: Scene {scene_id} local fallback "
            f"already exists."
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
            + ".fallback.tmp"
            + output_file.suffix
        )
    )

    if temporary_file.exists():

        temporary_file.unlink()

    command = build_ffmpeg_command(
        image_path=image_path,
        output_path=temporary_file,
        duration_sec=duration,
    )

    print(
        f"\nCreating deterministic fallback for scene {scene_id}"
    )

    print(
        f"  Source image: {image_file}"
    )

    print(
        f"  Target:       {duration:.3f}s"
    )

    print(
        f"  Resolution:   {FALLBACK_WIDTH}x{FALLBACK_HEIGHT}"
    )

    print(
        f"  FPS:          {FALLBACK_FPS:.3f}"
    )

    print(
        f"  Max zoom:     {FALLBACK_MAX_ZOOM:.3f}x"
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
            "ffmpeg fallback generation failed:\n"
            + result.stderr.strip()
        )

    if (
        not temporary_file.exists()
        or temporary_file.stat().st_size
        <= 0
    ):

        raise RuntimeError(
            "ffmpeg did not create a valid fallback video."
        )

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

    scene[
        "motion_prompt"
    ] = (
        "Deterministic static hold on the approved source image. "
        "No independent character or object motion is required. "
        "An imperceptible or extremely subtle camera push-in is "
        "acceptable but not required to be visually detectable. "
        "All characters, props, clothing, anatomy, background, "
        "and composition remain stable. No character duplication, "
        "no scene change, and no morphing."
    )

    scene[
        "motion_strategy"
    ] = "still_image_fallback_v1"

    scene[
        "semantic_qc_policy"
    ] = {
        "version":
            "still_image_fallback_v2",

        "motion_mode":
            "static_hold",

        "allowed_exit_character_ids":
            [],
    }

    now = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    scene[
        "video"
    ] = {
        "status":
            "generated",

        "file":
            relative_output,

        "provider":
            "local_ffmpeg",

        "model":
            "deterministic_still_push_in_v1",

        "ratio":
            (
                f"{FALLBACK_WIDTH}:"
                f"{FALLBACK_HEIGHT}"
            ),

        "duration_sec":
            round(
                duration,
                3,
            ),

        "provider_duration_sec":
            round(
                duration,
                3,
            ),

        "target_render_duration_sec":
            round(
                duration,
                3,
            ),

        "trim_required":
            True,

        "timing_policy":
            "natural_voice_driven_v1",

        "source_image":
            image_file,

        "task_id":
            (
                "local-still-"
                + now
            ),

        "file_size_bytes":
            output_file
            .stat()
            .st_size,

        "qc": {
            "status":
                "pending",
        },

        "semantic_qc": {
            "status":
                "pending",
        },
    }

    job.pop(
        "assembly",
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
            "base_video_file"
        ] = None

    print(
        f"  Saved:        {relative_output}"
    )

    print(
        f"  Bytes:        "
        f"{output_file.stat().st_size:,}"
    )

    return True


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - LOCAL SCENE VIDEO FALLBACK v1")
    print("=" * 60)

    args = parse_args()

    try:

        job = load_json(
            JOB_FILE
        )

        scene = find_visual_scene(
            job,
            args.scene,
        )

        if scene is None:

            raise RuntimeError(
                f"Scene {args.scene} not found."
            )

        generate_fallback(
            job=job,
            scene=scene,
            force=args.force,
        )

        set_legacy_status_from_stage(
            job,
            "scene_videos",
        )

        save_job_atomic(
            job
        )

    except Exception as exc:

        print(
            f"\nERROR: {exc}"
        )

        return 1

    print(
        "\n" + "=" * 60
    )

    print(
        "LOCAL FALLBACK VIDEO COMPLETE"
    )

    print(
        "=" * 60
    )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
