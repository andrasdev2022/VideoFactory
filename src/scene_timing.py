from __future__ import annotations

import argparse
import json
import os

from pathlib import Path
from typing import Any

from pipeline_status import (
    set_legacy_status_from_stage,
)

from validator import (
    load_json,
    load_yaml,
)


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


HEADROOM_SEC = float(
    os.getenv(
        "SCENE_TIMING_HEADROOM_SEC",
        "0.30",
    )
)

MIN_VIDEO_SEC = float(
    os.getenv(
        "SCENE_TIMING_MIN_VIDEO_SEC",
        "2.0",
    )
)

MAX_VIDEO_SEC = float(
    os.getenv(
        "SCENE_TIMING_MAX_VIDEO_SEC",
        "10.0",
    )
)

TARGET_TOLERANCE_SEC = float(
    os.getenv(
        "SCENE_TIMING_TARGET_TOLERANCE_SEC",
        "4.0",
    )
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Calculate video render timing "
            "from natural voice duration."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Process only one scene."
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


def find_scene(
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


def calculate_scene_timing(
    voice_duration_sec: float,
    planned_duration_sec: float,
) -> dict[str, Any]:

    raw_render_duration = (
        voice_duration_sec
        + HEADROOM_SEC
    )

    render_duration = max(
        MIN_VIDEO_SEC,
        raw_render_duration,
    )

    errors: list[str] = []
    warnings: list[str] = []

    script_revision_required = False

    if (
        raw_render_duration
        > MAX_VIDEO_SEC
    ):

        script_revision_required = True

        errors.append(
            f"Natural voice plus headroom "
            f"requires {raw_render_duration:.3f}s, "
            f"which exceeds the maximum "
            f"video generation duration "
            f"of {MAX_VIDEO_SEC:.3f}s."
        )

    planned_delta = (
        render_duration
        - planned_duration_sec
    )

    if abs(
        planned_delta
    ) >= 1.0:

        warnings.append(
            f"Render duration differs from "
            f"the original scene plan by "
            f"{planned_delta:+.3f}s."
        )

    status = (
        "failed"
        if errors
        else "passed"
    )

    return {

        "status":
            status,

        "planned_duration_sec":
            round(
                planned_duration_sec,
                3,
            ),

        "voice_duration_sec":
            round(
                voice_duration_sec,
                3,
            ),

        "headroom_sec":
            round(
                HEADROOM_SEC,
                3,
            ),

        "raw_render_duration_sec":
            round(
                raw_render_duration,
                3,
            ),

        "render_duration_sec":
            (
                None
                if script_revision_required
                else round(
                    render_duration,
                    3,
                )
            ),

        "min_video_duration_sec":
            MIN_VIDEO_SEC,

        "max_video_duration_sec":
            MAX_VIDEO_SEC,

        "script_revision_required":
            script_revision_required,

        "errors":
            errors,

        "warnings":
            warnings,
    }


def calculate_job_timing_summary(
    job: dict,
    spec: dict,
) -> dict[str, Any]:

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

    target_duration = float(
        spec
        .get(
            "video",
            {},
        )
        .get(
            "target_duration_sec",
            30,
        )
    )

    minimum_duration = float(
        spec
        .get(
            "video",
            {},
        )
        .get(
            "min_duration_sec",
            20,
        )
    )

    maximum_duration = float(
        spec
        .get(
            "video",
            {},
        )
        .get(
            "max_duration_sec",
            45,
        )
    )

    completed = 0
    failed = 0
    total_render = 0.0

    revision_scene_ids: list[int] = []

    for scene in scenes:

        timing = scene.get(
            "timing",
            {},
        )

        status = timing.get(
            "status"
        )

        if status == "passed":

            render_duration = (
                timing.get(
                    "render_duration_sec"
                )
            )

            if render_duration is not None:

                total_render += float(
                    render_duration
                )

                completed += 1

        elif status == "failed":

            failed += 1

            revision_scene_ids.append(
                scene.get(
                    "scene_id"
                )
            )

    all_complete = (
        len(scenes) > 0
        and completed
        == len(scenes)
    )

    if all_complete:

        difference = (
            total_render
            - target_duration
        )

        within_spec_bounds = (
            minimum_duration
            <= total_render
            <= maximum_duration
        )

        target_deviation_too_large = (
            abs(
                difference
            )
            > TARGET_TOLERANCE_SEC
        )

        script_revision_recommended = (
            not within_spec_bounds
            or target_deviation_too_large
        )

    else:

        difference = None
        within_spec_bounds = None

        script_revision_recommended = (
            failed > 0
        )

    return {

        "status":
            (
                "complete"
                if all_complete
                else (
                    "failed"
                    if failed > 0
                    else "partial"
                )
            ),

        "scene_count":
            len(scenes),

        "completed_scenes":
            completed,

        "failed_scenes":
            failed,

        "target_duration_sec":
            target_duration,

        "target_tolerance_sec":
            TARGET_TOLERANCE_SEC,

        "minimum_total_duration_sec":
            minimum_duration,

        "maximum_total_duration_sec":
            maximum_duration,

        "total_render_duration_sec":
            (
                round(
                    total_render,
                    3,
                )
                if all_complete
                else None
            ),

        "difference_from_target_sec":
            (
                round(
                    difference,
                    3,
                )
                if difference
                is not None
                else None
            ),

        "within_spec_bounds":
            within_spec_bounds,

        "script_revision_recommended":
            script_revision_recommended,

        "revision_scene_ids":
            revision_scene_ids,
    }


def process_scene(
    scene: dict,
) -> bool:

    scene_id = scene.get(
        "scene_id"
    )

    voice = scene.get(
        "voice",
        {},
    )

    voice_qc = voice.get(
        "qc",
        {},
    )

    if (
        voice_qc.get(
            "status"
        )
        != "passed"
    ):

        raise RuntimeError(
            f"Scene {scene_id}: "
            f"voice QC has not passed."
        )

    actual = voice_qc.get(
        "actual",
        {},
    )

    voice_duration = actual.get(
        "duration_sec"
    )

    if voice_duration is None:

        raise RuntimeError(
            f"Scene {scene_id}: "
            f"voice QC contains no duration."
        )

    if (
        "planned_duration_sec"
        not in scene
    ):

        planned_duration = (
            scene.get(
                "duration_sec"
            )
        )

        if planned_duration is None:

            raise RuntimeError(
                f"Scene {scene_id}: "
                f"duration_sec is missing."
            )

        scene[
            "planned_duration_sec"
        ] = float(
            planned_duration
        )

    planned_duration = float(
        scene[
            "planned_duration_sec"
        ]
    )

    scene[
        "timing"
    ] = calculate_scene_timing(
        voice_duration_sec=
            float(
                voice_duration
            ),
        planned_duration_sec=
            planned_duration,
    )

    return (
        scene[
            "timing"
        ][
            "status"
        ]
        == "passed"
    )


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SCENE TIMING v2")
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

    passed_count = 0
    failed_count = 0

    for scene in selected_scenes:

        scene_id = scene.get(
            "scene_id"
        )

        print(
            f"\nScene {scene_id}"
        )

        try:

            passed = process_scene(
                scene
            )

        except Exception as exc:

            failed_count += 1

            scene[
                "timing"
            ] = {

                "status":
                    "failed",

                "script_revision_required":
                    False,

                "errors": [
                    str(exc)
                ],

                "warnings":
                    [],
            }

            print(
                f"  FAIL"
            )

            print(
                f"  [ERROR] {exc}"
            )

            continue

        timing = scene[
            "timing"
        ]

        print(
            f"  Planned:  "
            f"{timing['planned_duration_sec']:.3f}s"
        )

        print(
            f"  Voice:    "
            f"{timing['voice_duration_sec']:.3f}s"
        )

        print(
            f"  Headroom: "
            f"{timing['headroom_sec']:.3f}s"
        )

        if passed:

            passed_count += 1

            print(
                f"  Render:   "
                f"{timing['render_duration_sec']:.3f}s"
            )

            print(
                "  PASS"
            )

        else:

            failed_count += 1

            print(
                "  FAIL - SCRIPT REVISION REQUIRED"
            )

        for warning in timing.get(
            "warnings",
            [],
        ):

            print(
                f"  [WARNING] {warning}"
            )

        for error in timing.get(
            "errors",
            [],
        ):

            print(
                f"  [ERROR] {error}"
            )

    job[
        "timing_summary"
    ] = (
        calculate_job_timing_summary(
            job,
            spec,
        )
    )

    summary = job[
        "timing_summary"
    ]

    if (
        summary.get(
            "status"
        )
        == "complete"
    ):

        set_legacy_status_from_stage(
            job,
            "global_timing",
        )

    else:

        set_legacy_status_from_stage(
            job,
            "scene_timing",
        )

    save_job_atomic(
        job
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "TIMING SUMMARY"
    )

    print(
        "=" * 60
    )

    print(
        f"\nCompleted scenes: "
        f"{summary['completed_scenes']}/"
        f"{summary['scene_count']}"
    )

    if (
        summary[
            "total_render_duration_sec"
        ]
        is not None
    ):

        print(
            f"Total render duration: "
            f"{summary['total_render_duration_sec']:.3f}s"
        )

        print(
            f"Target duration:       "
            f"{summary['target_duration_sec']:.3f}s"
        )

        print(
            f"Difference:            "
            f"{summary['difference_from_target_sec']:+.3f}s"
        )

        print(
            f"Script revision recommended: "
            f"{summary['script_revision_recommended']}"
        )

    if failed_count > 0:

        return 1

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )