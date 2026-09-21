from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validator import load_json, load_yaml
from still_motion_timing import extend_visual_holds


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

SRC_DIR = (
    PROJECT_ROOT
    / "src"
)

JOB_FILE = (
    PROJECT_ROOT
    / "jobs"
    / "video_job.json"
)


ACTION_REWRITE = "rewrite"
ACTION_REMEASURE = "remeasure"
ACTION_COMPLETE = "complete"
ACTION_STOP_LOCAL_TIMING = "stop_local_timing"
ACTION_STOP_INCOMPLETE = "stop_incomplete"
ACTION_STOP_ATTEMPTS = "stop_attempts"


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Normalize total script duration by iterating "
            "global voiceover rewrites and natural-speed "
            "TTS remeasurement."
        )
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help=(
            "Maximum global rewrite iterations. "
            "Default: 3"
        ),
    )

    parser.add_argument(
        "--reset-attempts",
        action="store_true",
        help=(
            "Reset the persistent global rewrite "
            "iteration counter."
        ),
    )

    args = parser.parse_args()

    if args.max_iterations < 1:

        parser.error(
            "--max-iterations must be at least 1."
        )

    return args


def utc_now_iso() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


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


def inspect_global_state(
    job: dict,
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

    failed_local_scene_ids = []
    incomplete_scene_ids = []

    for scene in scenes:

        scene_id = scene.get(
            "scene_id"
        )

        timing = scene.get(
            "timing",
            {},
        )

        status = timing.get(
            "status"
        )

        if status == "failed":

            failed_local_scene_ids.append(
                scene_id
            )

        elif status != "passed":

            incomplete_scene_ids.append(
                scene_id
            )

    summary = job.get(
        "timing_summary",
        {},
    )

    normalization = (
        job
        .get(
            "script",
            {},
        )
        .get(
            "duration_normalization",
            {},
        )
    )

    normalization_status = normalization.get(
        "status"
    )

    pending_scene_ids = list(
        normalization.get(
            "changed_scene_ids",
            [],
        )
        or []
    )

    return {
        "scene_count":
            len(
                scenes
            ),

        "failed_local_scene_ids":
            failed_local_scene_ids,

        "incomplete_scene_ids":
            incomplete_scene_ids,

        "summary_status":
            summary.get(
                "status"
            ),

        "total_render_duration_sec":
            summary.get(
                "total_render_duration_sec"
            ),

        "target_duration_sec":
            summary.get(
                "target_duration_sec"
            ),

        "difference_from_target_sec":
            summary.get(
                "difference_from_target_sec"
            ),

        "script_revision_recommended":
            summary.get(
                "script_revision_recommended"
            ),

        "normalization_status":
            normalization_status,

        "pending_scene_ids":
            pending_scene_ids,
    }


def choose_next_action(
    state: dict[str, Any],
    iterations: int,
    max_iterations: int,
) -> str:

    if state.get(
        "failed_local_scene_ids"
    ):

        return ACTION_STOP_LOCAL_TIMING

    if (
        state.get(
            "normalization_status"
        )
        == "pending_remeasure"
    ):

        return ACTION_REMEASURE

    if (
        state.get(
            "summary_status"
        )
        != "complete"
        or state.get(
            "incomplete_scene_ids"
        )
    ):

        return ACTION_STOP_INCOMPLETE

    if not state.get(
        "script_revision_recommended"
    ):

        return ACTION_COMPLETE

    if iterations >= max_iterations:

        return ACTION_STOP_ATTEMPTS

    return ACTION_REWRITE


def get_or_create_orchestration_state(
    job: dict,
) -> dict[str, Any]:

    orchestration = job.setdefault(
        "orchestration",
        {},
    )

    state = orchestration.setdefault(
        "script_duration",
        {},
    )

    state.setdefault(
        "iterations",
        0,
    )

    state.setdefault(
        "state",
        "in_progress",
    )

    state.setdefault(
        "last_action",
        None,
    )

    state.setdefault(
        "history",
        [],
    )

    state.setdefault(
        "created_at",
        utc_now_iso(),
    )

    state[
        "updated_at"
    ] = utc_now_iso()

    return state


def append_history(
    orchestration_state: dict,
    action: str,
    result: str,
    details: dict[str, Any] | None = None,
) -> None:

    history = orchestration_state.setdefault(
        "history",
        [],
    )

    entry = {
        "timestamp":
            utc_now_iso(),

        "action":
            action,

        "result":
            result,

        "iterations":
            orchestration_state.get(
                "iterations",
                0,
            ),
    }

    if details:

        entry[
            "details"
        ] = details

    history.append(
        entry
    )

    if len(
        history
    ) > 100:

        del history[:-100]


def record_state(
    job: dict,
    action: str,
    result: str,
    state_value: str,
    details: dict[str, Any] | None = None,
) -> None:

    state = get_or_create_orchestration_state(
        job
    )

    state[
        "last_action"
    ] = action

    state[
        "state"
    ] = state_value

    state[
        "updated_at"
    ] = utc_now_iso()

    append_history(
        state,
        action=action,
        result=result,
        details=details,
    )


def start_rewrite_iteration(
    job: dict,
) -> int:

    state = get_or_create_orchestration_state(
        job
    )

    state[
        "iterations"
    ] = (
        int(
            state.get(
                "iterations",
                0,
            )
        )
        + 1
    )

    state[
        "last_action"
    ] = ACTION_REWRITE

    state[
        "state"
    ] = "running"

    state[
        "updated_at"
    ] = utc_now_iso()

    append_history(
        state,
        action=ACTION_REWRITE,
        result="started",
    )

    return int(
        state[
            "iterations"
        ]
    )


def run_worker(
    script_name: str,
    arguments: list[str] | None = None,
) -> int:

    command = [
        sys.executable,
        str(
            SRC_DIR
            / script_name
        ),
        *(
            arguments
            or []
        ),
    ]

    print(
        "\n" + "-" * 60
    )

    print(
        "RUN:"
    )

    print(
        " ".join(
            command
        )
    )

    print(
        "-" * 60
    )

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
    )

    return result.returncode


def print_global_state(
    state: dict[str, Any],
) -> None:

    print(
        f"  summary:          "
        f"{state.get('summary_status')}"
    )

    print(
        f"  total render:     "
        f"{state.get('total_render_duration_sec')}"
    )

    print(
        f"  target:           "
        f"{state.get('target_duration_sec')}"
    )

    print(
        f"  difference:       "
        f"{state.get('difference_from_target_sec')}"
    )

    print(
        f"  revision needed:  "
        f"{state.get('script_revision_recommended')}"
    )

    print(
        f"  normalization:    "
        f"{state.get('normalization_status')}"
    )

    print(
        f"  pending scenes:   "
        f"{state.get('pending_scene_ids')}"
    )


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SCRIPT DURATION ORCHESTRATOR v1")
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

    orchestration_state = (
        get_or_create_orchestration_state(
            job
        )
    )

    if args.reset_attempts:

        orchestration_state[
            "iterations"
        ] = 0

        orchestration_state[
            "state"
        ] = "in_progress"

        orchestration_state[
            "last_action"
        ] = "reset_attempts"

        append_history(
            orchestration_state,
            action="reset_attempts",
            result="completed",
        )

        print(
            "\nPersistent global rewrite "
            "counter reset."
        )

    save_job_atomic(
        job
    )

    max_steps = 12

    for step in range(
        1,
        max_steps + 1,
    ):

        try:

            job = load_json(
                JOB_FILE
            )

            spec = load_yaml(PROJECT_ROOT / "config" / "video_spec_v1.yaml")
            from scene_timing import calculate_job_timing_summary
            job["timing_summary"] = calculate_job_timing_summary(job, spec)
            extend_visual_holds(job, spec)
            save_job_atomic(job)

            state = inspect_global_state(
                job
            )

            orchestration_state = (
                get_or_create_orchestration_state(
                    job
                )
            )

            iterations = int(
                orchestration_state.get(
                    "iterations",
                    0,
                )
            )

        except Exception as exc:

            print(
                f"\nERROR reading global state:\n"
                f"{exc}"
            )

            return 1

        action = choose_next_action(
            state,
            iterations,
            args.max_iterations,
        )

        print(
            f"\n[Step {step}] "
            f"Next action: {action}"
        )

        print(
            f"  iterations: "
            f"{iterations}/"
            f"{args.max_iterations}"
        )

        print_global_state(
            state
        )

        if action == ACTION_COMPLETE:

            script = job.setdefault(
                "script",
                {},
            )

            normalization = script.get(
                "duration_normalization"
            )

            if isinstance(
                normalization,
                dict,
            ):

                normalization[
                    "status"
                ] = "completed"

                normalization[
                    "completed_at"
                ] = utc_now_iso()

            record_state(
                job,
                action=ACTION_COMPLETE,
                result="passed",
                state_value="completed",
                details={
                    "total_render_duration_sec":
                        state.get(
                            "total_render_duration_sec"
                        ),
                    "target_duration_sec":
                        state.get(
                            "target_duration_sec"
                        ),
                },
            )

            save_job_atomic(
                job
            )

            print(
                "\n" + "=" * 60
            )

            print(
                "GLOBAL SCRIPT TIMING COMPLETE"
            )

            print(
                "=" * 60
            )

            return 0

        if action == ACTION_STOP_LOCAL_TIMING:

            record_state(
                job,
                action=ACTION_STOP_LOCAL_TIMING,
                result="local_timing_failed",
                state_value="failed",
                details={
                    "scene_ids":
                        state.get(
                            "failed_local_scene_ids"
                        ),
                },
            )

            save_job_atomic(
                job
            )

            print(
                "\nERROR: One or more scenes fail "
                "their individual timing limit."
            )

            print(
                "Run the scene-level timing rewriter "
                "for those scenes before global normalization."
            )

            return 1

        if action == ACTION_STOP_INCOMPLETE:

            record_state(
                job,
                action=ACTION_STOP_INCOMPLETE,
                result="timing_incomplete",
                state_value="failed",
                details={
                    "scene_ids":
                        state.get(
                            "incomplete_scene_ids"
                        ),
                },
            )

            save_job_atomic(
                job
            )

            print(
                "\nERROR: Global timing cannot be normalized "
                "until all scene voice QC and scene timing "
                "results are complete."
            )

            return 1

        if action == ACTION_STOP_ATTEMPTS:

            record_state(
                job,
                action=ACTION_STOP_ATTEMPTS,
                result="iteration_limit_reached",
                state_value="failed",
                details={
                    "max_iterations":
                        args.max_iterations,
                },
            )

            save_job_atomic(
                job
            )

            print(
                "\nERROR: Maximum global duration rewrite "
                "iterations reached."
            )

            return 1

        if action == ACTION_REWRITE:

            iteration = start_rewrite_iteration(
                job
            )

            save_job_atomic(
                job
            )

            print(
                f"\nStarting global rewrite iteration "
                f"{iteration}/"
                f"{args.max_iterations}"
            )

            rc = run_worker(
                "script_duration_rewriter.py"
            )

            job = load_json(
                JOB_FILE
            )

            if rc != 0:

                record_state(
                    job,
                    action=ACTION_REWRITE,
                    result="worker_failed",
                    state_value="failed",
                    details={
                        "return_code":
                            rc,
                        "iteration":
                            iteration,
                    },
                )

                save_job_atomic(
                    job
                )

                print(
                    "\nERROR: global script duration "
                    "rewriter failed."
                )

                return 1

            new_state = inspect_global_state(
                job
            )

            record_state(
                job,
                action=ACTION_REWRITE,
                result="completed",
                state_value="in_progress",
                details={
                    "iteration":
                        iteration,
                    "changed_scene_ids":
                        new_state.get(
                            "pending_scene_ids"
                        ),
                },
            )

            save_job_atomic(
                job
            )

            continue

        if action == ACTION_REMEASURE:

            pending_scene_ids = list(
                state.get(
                    "pending_scene_ids"
                )
                or []
            )

            if not pending_scene_ids:

                print(
                    "\nERROR: duration normalization is "
                    "pending remeasurement but contains "
                    "no changed scene IDs."
                )

                return 1

            record_state(
                job,
                action=ACTION_REMEASURE,
                result="started",
                state_value="running",
                details={
                    "scene_ids":
                        pending_scene_ids,
                },
            )

            save_job_atomic(
                job
            )

            for scene_id in pending_scene_ids:

                print(
                    f"\nRegenerating natural voice "
                    f"for scene {scene_id}"
                )

                rc = run_worker(
                    "voice_orchestrator.py",
                    [
                        "--scene",
                        str(
                            scene_id
                        ),
                        "--reset-attempts",
                    ],
                )

                if rc != 0:

                    job = load_json(
                        JOB_FILE
                    )

                    record_state(
                        job,
                        action=ACTION_REMEASURE,
                        result="voice_worker_failed",
                        state_value="failed",
                        details={
                            "scene_id":
                                scene_id,
                            "return_code":
                                rc,
                        },
                    )

                    save_job_atomic(
                        job
                    )

                    return 1

            rc = run_worker(
                "scene_timing.py"
            )

            job = load_json(
                JOB_FILE
            )

            if rc != 0:

                record_state(
                    job,
                    action=ACTION_REMEASURE,
                    result="timing_worker_failed",
                    state_value="failed",
                    details={
                        "return_code":
                            rc,
                    },
                )

                save_job_atomic(
                    job
                )

                return 1

            normalization = (
                job
                .setdefault(
                    "script",
                    {},
                )
                .get(
                    "duration_normalization"
                )
            )

            if isinstance(
                normalization,
                dict,
            ):

                normalization[
                    "status"
                ] = "remeasured"

                normalization[
                    "remeasured_at"
                ] = utc_now_iso()

            measured_state = inspect_global_state(
                job
            )

            record_state(
                job,
                action=ACTION_REMEASURE,
                result="completed",
                state_value="in_progress",
                details={
                    "total_render_duration_sec":
                        measured_state.get(
                            "total_render_duration_sec"
                        ),
                    "difference_from_target_sec":
                        measured_state.get(
                            "difference_from_target_sec"
                        ),
                },
            )

            save_job_atomic(
                job
            )

            continue

        print(
            f"\nERROR: unknown action "
            f"{action}"
        )

        return 1

    job = load_json(
        JOB_FILE
    )

    record_state(
        job,
        action="step_limit",
        result="step_limit_reached",
        state_value="failed",
    )

    save_job_atomic(
        job
    )

    print(
        "\nERROR: global duration orchestrator "
        "exceeded its internal step limit."
    )

    return 1


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
