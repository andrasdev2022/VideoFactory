from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from pathlib import Path
from typing import Any

from validator import load_json


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


NATURAL_TTS_SPEED = 1.0
SPEED_TOLERANCE = 0.001


ACTION_GENERATE = "generate"
ACTION_QC = "qc"
ACTION_TIMING = "timing"
ACTION_COMPLETE = "complete"
ACTION_STOP = "stop"


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Run natural-speed voice generation, "
            "voice QC, and scene timing for one scene."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        required=True,
        help=(
            "Scene ID to process."
        ),
    )

    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help=(
            "Maximum natural-speed TTS generations. "
            "Default: 3"
        ),
    )

    parser.add_argument(
        "--reset-attempts",
        action="store_true",
        help=(
            "Reset the persistent voice generation "
            "counter for this scene."
        ),
    )

    args = parser.parse_args()

    if args.max_attempts < 1:

        parser.error(
            "--max-attempts must be "
            "at least 1."
        )

    return args


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


def inspect_voice_state(
    scene: dict,
) -> dict[str, Any]:

    voice = scene.get(
        "voice",
        {},
    )

    voice_qc = voice.get(
        "qc",
        {},
    )

    timing = scene.get(
        "timing",
        {},
    )

    return {

        "voice_status":
            voice.get(
                "status"
            ),

        "voice_file":
            voice.get(
                "file"
            ),

        "voice_speed":
            voice.get(
                "speed"
            ),

        "voice_qc_status":
            voice_qc.get(
                "status"
            ),

        "timing_status":
            timing.get(
                "status"
            ),

        "render_duration_sec":
            timing.get(
                "render_duration_sec"
            ),

        "script_revision_required":
            timing.get(
                "script_revision_required",
                False,
            ),
    }


def voice_is_generated(
    state: dict[str, Any],
) -> bool:

    return (
        state.get(
            "voice_status"
        )
        in {
            "generated",
            "completed",
            "passed",
        }
        and bool(
            state.get(
                "voice_file"
            )
        )
    )


def voice_is_natural_speed(
    state: dict[str, Any],
) -> bool:

    speed = state.get(
        "voice_speed"
    )

    if speed is None:

        return False

    try:

        numeric_speed = float(
            speed
        )

    except (
        TypeError,
        ValueError,
    ):

        return False

    return (
        abs(
            numeric_speed
            - NATURAL_TTS_SPEED
        )
        <= SPEED_TOLERANCE
    )


def choose_next_action(
    state: dict[str, Any],
    attempts: int,
    max_attempts: int,
) -> str:

    # -----------------------------------------------------
    # Voice must exist at natural speed.
    # -----------------------------------------------------

    if (
        not voice_is_generated(
            state
        )
        or not voice_is_natural_speed(
            state
        )
    ):

        if attempts >= max_attempts:

            return ACTION_STOP

        return ACTION_GENERATE

    # -----------------------------------------------------
    # Technical voice QC
    # -----------------------------------------------------

    voice_qc_status = (
        state.get(
            "voice_qc_status"
        )
    )

    if voice_qc_status == "failed":

        return ACTION_STOP

    if voice_qc_status != "passed":

        return ACTION_QC

    # -----------------------------------------------------
    # Scene timing
    # -----------------------------------------------------

    timing_status = state.get(
        "timing_status"
    )

    if timing_status == "passed":

        return ACTION_COMPLETE

    if timing_status == "failed":

        return ACTION_STOP

    return ACTION_TIMING


def get_or_create_state(
    job: dict,
    scene_id: int,
    observed_state: dict[str, Any],
) -> dict:

    orchestration = (
        job.setdefault(
            "orchestration",
            {},
        )
    )

    voice_scenes = (
        orchestration.setdefault(
            "voice_scenes",
            {},
        )
    )

    key = str(
        scene_id
    )

    state = voice_scenes.get(
        key
    )

    if state is not None:

        state.setdefault(
            "attempts",
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

        state[
            "policy"
        ] = "natural_voice_timing_v1"

        return state

    inferred_attempts = (
        1
        if voice_is_generated(
            observed_state
        )
        else 0
    )

    state = {

        "attempts":
            inferred_attempts,

        "state":
            "in_progress",

        "last_action":
            None,

        "policy":
            "natural_voice_timing_v1",
    }

    voice_scenes[
        key
    ] = state

    return state


def start_voice_attempt(
    job: dict,
    scene_id: int,
    observed_state: dict[str, Any],
) -> int:

    state = get_or_create_state(
        job,
        scene_id,
        observed_state,
    )

    state[
        "attempts"
    ] = (
        int(
            state.get(
                "attempts",
                0,
            )
        )
        + 1
    )

    state[
        "last_action"
    ] = ACTION_GENERATE

    state[
        "state"
    ] = "running"

    return int(
        state[
            "attempts"
        ]
    )


def run_worker(
    script_name: str,
    arguments: list[str],
) -> int:

    command = [
        sys.executable,
        str(
            SRC_DIR
            / script_name
        ),
        *arguments,
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


def print_state(
    state: dict[str, Any],
) -> None:

    print(
        f"  voice status:     "
        f"{state.get('voice_status')}"
    )

    print(
        f"  voice speed:      "
        f"{state.get('voice_speed')}"
    )

    print(
        f"  voice QC:         "
        f"{state.get('voice_qc_status')}"
    )

    print(
        f"  timing:           "
        f"{state.get('timing_status')}"
    )

    print(
        f"  render duration:  "
        f"{state.get('render_duration_sec')}"
    )


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - VOICE ORCHESTRATOR v2")
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

    observed = (
        inspect_voice_state(
            scene
        )
    )

    orchestration_state = (
        get_or_create_state(
            job,
            args.scene,
            observed,
        )
    )

    if args.reset_attempts:

        orchestration_state[
            "attempts"
        ] = 0

        orchestration_state[
            "state"
        ] = "in_progress"

        orchestration_state[
            "last_action"
        ] = "reset_attempts"

        print(
            "\nPersistent voice attempt "
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

            scene = find_scene(
                job,
                args.scene,
            )

            if scene is None:

                print(
                    "\nERROR: scene disappeared "
                    "from job state."
                )

                return 1

            observed = (
                inspect_voice_state(
                    scene
                )
            )

            orchestration_state = (
                get_or_create_state(
                    job,
                    args.scene,
                    observed,
                )
            )

            attempts = int(
                orchestration_state.get(
                    "attempts",
                    0,
                )
            )

        except Exception as exc:

            print(
                f"\nERROR reading pipeline state:\n"
                f"{exc}"
            )

            return 1

        action = choose_next_action(
            observed,
            attempts,
            args.max_attempts,
        )

        print(
            f"\n[Step {step}] "
            f"Next action: {action}"
        )

        print(
            f"  attempts: "
            f"{attempts}/"
            f"{args.max_attempts}"
        )

        print_state(
            observed
        )

        # =================================================
        # COMPLETE
        # =================================================

        if action == ACTION_COMPLETE:

            orchestration_state[
                "state"
            ] = "completed"

            orchestration_state[
                "last_action"
            ] = ACTION_COMPLETE

            save_job_atomic(
                job
            )

            print(
                "\n" + "=" * 60
            )

            print(
                f"VOICE/TIMING SCENE "
                f"{args.scene} COMPLETE"
            )

            print(
                "=" * 60
            )

            return 0

        # =================================================
        # STOP
        # =================================================

        if action == ACTION_STOP:

            orchestration_state[
                "state"
            ] = "failed"

            orchestration_state[
                "last_action"
            ] = ACTION_STOP

            save_job_atomic(
                job
            )

            print(
                "\n" + "=" * 60
            )

            print(
                "VOICE/TIMING PIPELINE STOPPED"
            )

            print(
                "=" * 60
            )

            if observed.get(
                "script_revision_required"
            ):

                print(
                    "\nReason: natural voice does not fit "
                    "within the allowed scene video duration."
                )

                print(
                    "Script revision is required."
                )

            elif (
                observed.get(
                    "voice_qc_status"
                )
                == "failed"
            ):

                print(
                    "\nReason: technical voice QC failed."
                )

            elif (
                attempts
                >= args.max_attempts
            ):

                print(
                    "\nReason: maximum natural voice "
                    "generation attempts reached."
                )

            else:

                print(
                    "\nReason: pipeline state cannot "
                    "continue automatically."
                )

            return 1

        # =================================================
        # GENERATE NATURAL VOICE
        # =================================================

        if action == ACTION_GENERATE:

            attempt = start_voice_attempt(
                job,
                args.scene,
                observed,
            )

            save_job_atomic(
                job
            )

            print(
                f"\nStarting natural voice attempt "
                f"{attempt}/"
                f"{args.max_attempts}"
            )

            rc = run_worker(
                "voice_generator.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                    "--force",
                ],
            )

            if rc != 0:

                print(
                    "\nERROR: voice generator failed."
                )

                return 1

            continue

        # =================================================
        # VOICE TECHNICAL QC
        # =================================================

        if action == ACTION_QC:

            run_worker(
                "voice_qc.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                ],
            )

            # QC returning non-zero can be a valid pipeline
            # outcome. Reload state on next iteration.

            continue

        # =================================================
        # SCENE TIMING
        # =================================================

        if action == ACTION_TIMING:

            run_worker(
                "scene_timing.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                ],
            )

            # Timing failure may mean script revision is
            # required. The next iteration decides STOP.

            continue

        print(
            f"\nERROR: unknown action: "
            f"{action}"
        )

        return 1

    print(
        "\nERROR: voice orchestrator exceeded "
        "internal step limit."
    )

    return 1


if __name__ == "__main__":

    raise SystemExit(
        main()
    )