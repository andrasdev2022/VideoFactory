from __future__ import annotations

import argparse
import sys

from pathlib import Path

from local_ltx_provider import (
    generate,
    load_config,
    run_preflight,
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


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Benchmark Local LTX on one existing scene without "
            "modifying video_job.json."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help=(
            "Optional benchmark duration override. "
            "Defaults to the scene render duration."
        ),
    )

    parser.add_argument(
        "--preflight",
        action="store_true",
    )

    return parser.parse_args()


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


def build_prompt(
    scene: dict,
) -> str:

    parts: list[str] = []

    motion = (
        scene.get(
            "motion_prompt"
        )
        or ""
    ).strip()

    continuity = (
        scene.get(
            "continuity_notes"
        )
        or ""
    ).strip()

    if motion:

        parts.append(
            motion
        )

    if continuity:

        parts.append(
            (
                "Continuity: "
                + continuity
            )
        )

    parts.append(
        (
            "Preserve the supplied opening image, character "
            "identity, clothing, anatomy, environment, and "
            "composition. Natural controlled motion. "
            "One continuous shot."
        )
    )

    return " ".join(
        parts
    )


def main() -> int:

    args = parse_args()

    print("=" * 60)
    print("VIDEO FACTORY - LOCAL LTX BENCHMARK v1")
    print("=" * 60)

    try:

        config = load_config()

        if args.preflight:

            run_preflight(
                config
            )

            print(
                "\nLOCAL LTX BENCHMARK PREFLIGHT PASS"
            )

            return 0

        job = load_json(
            JOB_FILE
        )

        visual_scene = find_visual_scene(
            job,
            args.scene,
        )

        script_scene = find_script_scene(
            job,
            args.scene,
        )

        if visual_scene is None:

            raise RuntimeError(
                f"Visual scene {args.scene} was not found."
            )

        if script_scene is None:

            raise RuntimeError(
                f"Script scene {args.scene} was not found."
            )

        image_file = (
            visual_scene
            .get(
                "image",
                {},
            )
            .get(
                "file"
            )
        )

        if not image_file:

            raise RuntimeError(
                (
                    f"Scene {args.scene} has no generated "
                    "source image."
                )
            )

        timing = script_scene.get(
            "timing",
            {},
        )

        duration = (
            args.duration
            if args.duration
            is not None
            else timing.get(
                "render_duration_sec"
            )
        )

        if duration is None:

            raise RuntimeError(
                (
                    f"Scene {args.scene} has no approved "
                    "render duration."
                )
            )

        input_image = (
            PROJECT_ROOT
            / image_file
        )

        output_file = (
            PROJECT_ROOT
            / "output"
            / job[
                "job_id"
            ]
            / "benchmarks"
            / (
                f"local_ltx_scene_"
                f"{args.scene:03d}.mp4"
            )
        )

        prompt = build_prompt(
            visual_scene
        )

        print(
            f"\nJob:      {job['job_id']}"
        )

        print(
            f"Scene:    {args.scene}"
        )

        print(
            f"Input:    {image_file}"
        )

        print(
            f"Duration: {float(duration):.3f}s"
        )

        print(
            f"Output:   {output_file}"
        )

        result = generate(
            input_image=input_image,
            output_file=output_file,
            prompt=prompt,
            duration_sec=float(
                duration
            ),
            scene_id=args.scene,
            config=config,
        )

        print(
            "\nLOCAL LTX BENCHMARK COMPLETE"
        )

        print(
            f"Model:      {result.model_id}"
        )

        print(
            (
                "Resolution: "
                f"{result.width}x{result.height}"
            )
        )

        print(
            f"Frames:     {result.num_frames}"
        )

        print(
            f"FPS:        {result.fps}"
        )

        print(
            (
                "Raw duration: "
                f"{result.duration_sec:.3f}s"
            )
        )

        print(
            f"Seed:       {result.seed}"
        )

        print(
            f"File:       {result.file}"
        )

        print(
            (
                "\nNOTE: benchmark mode does not modify "
                "jobs/video_job.json."
            )
        )

        return 0

    except Exception as exc:

        print(
            f"\nERROR: {exc}"
        )

        return 1


if __name__ == "__main__":

    sys.exit(
        main()
    )
