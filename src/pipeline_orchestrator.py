from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline_status import refresh_pipeline_status
from service_budget_preflight import (
    blocking as blocking_service_checks,
    check_elevenlabs,
    check_runway,
    enabled as service_preflight_enabled,
    estimate_elevenlabs_audio_credits,
    estimate_runway_budget,
    print_checks as print_service_checks,
    startup_checks as service_startup_checks,
)
from validator import load_json


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"


STAGE_SCRIPT = "script"
STAGE_VOICE_TIMING = "voice_timing"
STAGE_GLOBAL_TIMING = "global_timing"
STAGE_VISUAL_PROMPTS = "visual_prompts"
STAGE_CHARACTER_PROMPTS = "character_reference_prompts"
STAGE_CHARACTER_IMAGES = "character_references"
STAGE_SCENES = "scene_generation"
STAGE_ASSEMBLY = "base_assembly"
STAGE_SUBTITLES = "subtitles"
STAGE_AUDIO_PLAN = "audio_plan"
STAGE_AUDIO_ASSETS = "audio_assets"
STAGE_AUDIO_MIX = "audio_mix"
STAGE_THUMBNAIL = "thumbnail"
STAGE_FINAL_QC = "final_qc"

STAGE_ORDER = (
    STAGE_SCRIPT,
    STAGE_VOICE_TIMING,
    STAGE_GLOBAL_TIMING,
    STAGE_VISUAL_PROMPTS,
    STAGE_CHARACTER_PROMPTS,
    STAGE_CHARACTER_IMAGES,
    STAGE_SCENES,
    STAGE_ASSEMBLY,
    STAGE_SUBTITLES,
    STAGE_AUDIO_PLAN,
    STAGE_AUDIO_ASSETS,
    STAGE_AUDIO_MIX,
    STAGE_THUMBNAIL,
    STAGE_FINAL_QC,
)


class PipelineError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Run Video Factory end-to-end from a rough idea, "
            "or resume the active job."
        )
    )

    parser.add_argument(
        "--idea",
        default=None,
        help=(
            "Create a new job from this rough idea before "
            "running the pipeline. Omit to resume the active job."
        ),
    )

    parser.add_argument(
        "--job-id",
        default=None,
        help="Optional job ID used with --idea.",
    )

    parser.add_argument(
        "--max-local-rewrites",
        type=int,
        default=3,
        help=(
            "Maximum scene-level timing rewrites per scene. "
            "Default: 3"
        ),
    )

    parser.add_argument(
        "--max-global-iterations",
        type=int,
        default=3,
        help=(
            "Maximum total-duration rewrite iterations. "
            "Default: 3"
        ),
    )

    parser.add_argument(
        "--max-image-attempts",
        type=int,
        default=2,
        help="Maximum image generations per scene. Default: 2",
    )

    parser.add_argument(
        "--max-video-attempts",
        type=int,
        default=4,
        help="Maximum video generations per scene. Default: 4",
    )

    parser.add_argument(
        "--stop-after",
        choices=STAGE_ORDER,
        default=None,
        help=(
            "Stop successfully after the selected stage. "
            "Useful for integration debugging."
        ),
    )

    args = parser.parse_args()

    for name in (
        "max_local_rewrites",
        "max_global_iterations",
        "max_image_attempts",
        "max_video_attempts",
    ):
        if getattr(
            args,
            name,
        ) < 1:
            parser.error(
                f"--{name.replace('_', '-')} must be at least 1."
            )

    return args


def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def save_job_atomic(
    job: dict,
) -> None:

    temporary = JOB_FILE.with_name(
        JOB_FILE.name + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            job,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        JOB_FILE,
    )


def load_job() -> dict:
    return load_json(
        JOB_FILE
    )


def master_state(
    job: dict,
) -> dict[str, Any]:

    orchestration = job.setdefault(
        "orchestration",
        {},
    )

    state = orchestration.setdefault(
        "master",
        {},
    )

    state.setdefault(
        "state",
        "in_progress",
    )

    state.setdefault(
        "current_stage",
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


def record_master_event(
    *,
    stage: str,
    result: str,
    details: dict[str, Any] | None = None,
    state_value: str | None = None,
) -> None:

    job = load_job()

    state = master_state(
        job
    )

    state[
        "current_stage"
    ] = stage

    if state_value is not None:
        state[
            "state"
        ] = state_value

    event = {
        "timestamp":
            utc_now_iso(),

        "stage":
            stage,

        "result":
            result,
    }

    if details:
        event[
            "details"
        ] = details

    state[
        "history"
    ].append(
        event
    )

    save_job_atomic(
        job
    )


def current_pipeline_status() -> dict[str, Any]:
    return refresh_pipeline_status(
        load_job()
    )


def stage_completed(
    stage: str,
) -> bool:

    mapping = {
        STAGE_SCRIPT:
            "script",

        STAGE_GLOBAL_TIMING:
            "global_timing",

        STAGE_VISUAL_PROMPTS:
            "visual_prompts",

        STAGE_CHARACTER_PROMPTS:
            "character_reference_prompts",

        STAGE_CHARACTER_IMAGES:
            "character_references",

        STAGE_ASSEMBLY:
            "base_assembly",

        STAGE_SUBTITLES:
            "subtitles",

        STAGE_AUDIO_ASSETS:
            "audio_assets",

        STAGE_AUDIO_MIX:
            "audio_mix",

        STAGE_FINAL_QC:
            "final_qc",
    }

    pipeline_stage = mapping.get(
        stage
    )

    if pipeline_stage is None:
        return False

    status = current_pipeline_status()

    return (
        status
        .get(
            pipeline_stage,
            {},
        )
        .get(
            "state"
        )
        == "completed"
    )


def audio_plan_completed() -> bool:

    return (
        load_job()
        .get(
            "audio",
            {},
        )
        .get(
            "plan",
            {},
        )
        .get(
            "status"
        )
        == "passed"
    )


def all_scene_generation_completed() -> bool:

    status = current_pipeline_status()

    stages = (
        "scene_images",
        "image_qc",
        "image_semantic_qc",
        "scene_videos",
        "video_qc",
        "video_semantic_qc",
        "scene_trimmed",
    )

    return all(
        status
        .get(
            stage,
            {},
        )
        .get(
            "state"
        )
        == "completed"
        for stage in stages
    )


def all_voice_timing_completed() -> bool:

    status = current_pipeline_status()

    return all(
        status
        .get(
            stage,
            {},
        )
        .get(
            "state"
        )
        == "completed"
        for stage in (
            "voiceovers",
            "voice_qc",
            "scene_timing",
        )
    )


def run_worker(
    stage: str,
    script_name: str,
    arguments: list[str] | None = None,
    *,
    allow_failure: bool = False,
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
        "\n" + "=" * 72
    )

    print(
        f"MASTER STAGE: {stage}"
    )

    print(
        "RUN: "
        + subprocess.list2cmdline(
            command
        )
    )

    print(
        "=" * 72
    )

    if JOB_FILE.exists():
        record_master_event(
            stage=stage,
            result="started",
            state_value="running",
        )

    # When stdout is piped through Tee-Object, Python may
    # otherwise block-buffer the parent while child output appears
    # immediately. Flush here and force unbuffered child Python so
    # the combined pipeline log preserves chronological order.
    sys.stdout.flush()
    sys.stderr.flush()

    child_env = os.environ.copy()

    child_env[
        "PYTHONUNBUFFERED"
    ] = "1"

    child_env[
        "PYTHONUTF8"
    ] = "1"

    child_env[
        "PYTHONIOENCODING"
    ] = "utf-8"

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        env=child_env,
    )

    if completed.returncode == 0:

        if JOB_FILE.exists():
            record_master_event(
                stage=stage,
                result="completed",
                details={
                    "worker":
                        script_name,

                    "return_code":
                        0,
                },
                state_value="in_progress",
            )

        return 0

    if JOB_FILE.exists():
        record_master_event(
            stage=stage,
            result="failed",
            details={
                "worker":
                    script_name,

                "return_code":
                    completed.returncode,
            },
            state_value="failed",
        )

    if allow_failure:
        return completed.returncode

    raise PipelineError(
        (
            f"Stage '{stage}' failed in "
            f"{script_name} with return code "
            f"{completed.returncode}."
        )
    )


def preflight() -> None:

    missing: list[str] = []

    for name in (
        "OPENAI_API_KEY",
        "ELEVENLABS_API_KEY",
    ):
        if not os.getenv(
            name
        ):
            missing.append(
                name
            )

    video_provider = os.getenv(
        "VIDEO_PROVIDER",
        "local_ltx",
    ).strip().lower()

    if video_provider == "runway":

        if not os.getenv(
            "RUNWAYML_API_SECRET"
        ):

            missing.append(
                "RUNWAYML_API_SECRET"
            )

    elif video_provider == "still_motion":
        from still_motion_provider import load_config
        load_config()

    elif video_provider == "local_ltx":

        local_ltx_python = Path(
            os.getenv(
                "LOCAL_LTX_PYTHON",
                str(
                    PROJECT_ROOT
                    / ".venv-ltx"
                    / "Scripts"
                    / "python.exe"
                ),
            )
        )

        local_ltx_worker = Path(
            os.getenv(
                "LOCAL_LTX_WORKER",
                str(
                    SRC_DIR
                    / "local_ltx_worker.py"
                ),
            )
        )

        local_ltx_service = Path(
            os.getenv(
                "LOCAL_LTX_SERVICE",
                str(
                    SRC_DIR
                    / "local_ltx_service.py"
                ),
            )
        )

        if not local_ltx_python.exists():

            missing.append(
                (
                    "Local LTX environment "
                    f"({local_ltx_python})"
                )
            )

        if not local_ltx_worker.exists():

            missing.append(
                (
                    "Local LTX worker "
                    f"({local_ltx_worker})"
                )
            )

        if not local_ltx_service.exists():

            missing.append(
                (
                    "Local LTX service "
                    f"({local_ltx_service})"
                )
            )

    else:

        raise PipelineError(
            (
                "Unsupported VIDEO_PROVIDER: "
                f"{video_provider}. "
                "Expected 'local_ltx', 'still_motion' or 'runway'."
            )
        )

    for command in (
        "ffmpeg",
        "ffprobe",
    ):
        if shutil.which(
            command
        ) is None:
            missing.append(
                command
            )

    if missing:
        raise PipelineError(
            (
                "Preflight failed. Missing: "
                + ", ".join(
                    missing
                )
            )
        )


    if service_preflight_enabled():

        runway_model = os.getenv(
            "RUNWAY_VIDEO_MODEL",
            "gen4_turbo",
        )

        checks = service_startup_checks(
            video_provider=video_provider,
            runway_model=runway_model,
        )

        print_service_checks(
            "SERVICE ACCOUNT / QUOTA PREFLIGHT",
            checks,
        )

        blockers = blocking_service_checks(
            checks
        )

        if blockers:

            raise PipelineError(
                (
                    "Service preflight blocked: "
                    + "; ".join(
                        (
                            f"{check.service}: "
                            f"{check.message}"
                        )
                        for check in blockers
                    )
                )
            )


def run_runway_budget_preflight(
    max_video_attempts: int,
) -> None:

    if not service_preflight_enabled():
        return

    video_provider = os.getenv(
        "VIDEO_PROVIDER",
        "local_ltx",
    ).strip().lower()

    if video_provider != "runway":
        return

    model = os.getenv(
        "RUNWAY_VIDEO_MODEL",
        "gen4_turbo",
    )

    budget = estimate_runway_budget(
        job=load_job(),
        model=model,
        max_video_attempts=
            max_video_attempts,
    )

    check = check_runway(
        model=model,
        budget=budget,
    )

    print_service_checks(
        "RUNWAY SCENE BUDGET PREFLIGHT",
        [
            check,
        ],
    )

    blockers = blocking_service_checks(
        [
            check,
        ]
    )

    if blockers:

        raise PipelineError(
            (
                "Runway scene-generation "
                "budget preflight blocked: "
                + check.message
            )
        )


def run_elevenlabs_audio_budget_preflight() -> None:

    if not service_preflight_enabled():
        return

    estimate = (
        estimate_elevenlabs_audio_credits(
            load_job()
        )
    )

    required = float(
        estimate.get(
            "estimated_total_credits",
            0.0,
        )
    )

    check = check_elevenlabs(
        required_credits=required,
    )

    merged_details = {
        **check.details,
        **estimate,
    }

    check = type(check)(
        service=check.service,
        status=check.status,
        message=check.message,
        details=merged_details,
    )

    print_service_checks(
        "ELEVENLABS AUDIO BUDGET PREFLIGHT",
        [
            check,
        ],
    )

    blockers = blocking_service_checks(
        [
            check,
        ]
    )

    if blockers:

        raise PipelineError(
            (
                "ElevenLabs audio budget "
                "preflight blocked: "
                + check.message
            )
        )


def get_scene_ids() -> list[int]:

    job = load_job()

    result: list[int] = []

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

        scene_id = scene.get(
            "scene_id"
        )

        if scene_id is not None:
            result.append(
                int(
                    scene_id
                )
            )

    if not result:
        raise PipelineError(
            "Script contains no scene IDs."
        )

    return result


def get_script_scene(
    scene_id: int,
) -> dict:

    for scene in (
        load_job()
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

    raise PipelineError(
        f"Scene {scene_id} disappeared from the active job."
    )


def run_voice_timing_for_scene(
    scene_id: int,
    max_local_rewrites: int,
) -> None:

    rewrite_count = 0
    reset_attempts = False

    while True:

        scene = get_script_scene(
            scene_id
        )

        timing = scene.get(
            "timing",
            {},
        )

        if (
            timing.get(
                "status"
            )
            == "passed"
            and not timing.get(
                "script_revision_required",
                False,
            )
        ):
            print(
                f"Scene {scene_id}: voice/timing already passed."
            )
            return

        arguments = [
            "--scene",
            str(
                scene_id
            ),
        ]

        if reset_attempts:
            arguments.append(
                "--reset-attempts"
            )

        rc = run_worker(
            STAGE_VOICE_TIMING,
            "voice_orchestrator.py",
            arguments,
            allow_failure=True,
        )

        scene = get_script_scene(
            scene_id
        )

        timing = scene.get(
            "timing",
            {},
        )

        if (
            rc == 0
            and timing.get(
                "status"
            )
            == "passed"
        ):
            return

        if not timing.get(
            "script_revision_required",
            False,
        ):
            raise PipelineError(
                (
                    f"Scene {scene_id} voice/timing failed "
                    "without a recoverable script timing rewrite."
                )
            )

        if rewrite_count >= max_local_rewrites:
            raise PipelineError(
                (
                    f"Scene {scene_id} exceeded the maximum "
                    f"{max_local_rewrites} local script rewrites."
                )
            )

        rewrite_count += 1

        print(
            (
                f"\nScene {scene_id}: natural voice is too long. "
                f"Running local script rewrite "
                f"{rewrite_count}/{max_local_rewrites}."
            )
        )

        run_worker(
            STAGE_VOICE_TIMING,
            "script_timing_rewriter.py",
            [
                "--scene",
                str(
                    scene_id
                ),
            ],
        )

        reset_attempts = True


def run_voice_timing(
    max_local_rewrites: int,
) -> None:

    if all_voice_timing_completed():
        print(
            "\nVoice/timing stages already complete."
        )
        return

    for scene_id in get_scene_ids():
        run_voice_timing_for_scene(
            scene_id,
            max_local_rewrites,
        )

    run_worker(
        STAGE_VOICE_TIMING,
        "scene_timing.py",
    )

    if not all_voice_timing_completed():
        raise PipelineError(
            "Voice/timing did not reach a completed state."
        )


def reserve_local_port() -> int:

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as listener:

        listener.bind(
            (
                "127.0.0.1",
                0,
            )
        )

        return int(
            listener
            .getsockname()[
                1
            ]
        )


def ping_local_ltx_service(
    host: str,
    port: int,
    timeout_sec: float = 1.0,
) -> bool:

    request = (
        json.dumps(
            {
                "action":
                    "ping",
            }
        )
        + "\n"
    ).encode(
        "utf-8"
    )

    try:

        with socket.create_connection(
            (
                host,
                port,
            ),
            timeout=timeout_sec,
        ) as connection:

            connection.settimeout(
                timeout_sec
            )

            connection.sendall(
                request
            )

            line = (
                connection
                .makefile(
                    "rb"
                )
                .readline()
            )

    except OSError:

        return False

    if not line:

        return False

    try:

        response = json.loads(
            line.decode(
                "utf-8"
            )
        )

    except Exception:

        return False

    return bool(
        response.get(
            "ok"
        )
        and response.get(
            "status"
        )
        == "ready"
    )


def start_local_ltx_service():

    if os.getenv(
        "VIDEO_PROVIDER",
        "local_ltx",
    ).strip().lower() != "local_ltx":

        return None

    python_exe = Path(
        os.getenv(
            "LOCAL_LTX_PYTHON",
            str(
                PROJECT_ROOT
                / ".venv-ltx"
                / "Scripts"
                / "python.exe"
            ),
        )
    )

    service_file = Path(
        os.getenv(
            "LOCAL_LTX_SERVICE",
            str(
                SRC_DIR
                / "local_ltx_service.py"
            ),
        )
    )

    model_id = os.getenv(
        "LOCAL_LTX_MODEL_ID",
        "Lightricks/LTX-Video",
    )

    offload_mode = os.getenv(
        "LOCAL_LTX_OFFLOAD_MODE",
        "sequential",
    )

    host = "127.0.0.1"
    port = reserve_local_port()

    command = [
        str(
            python_exe
        ),
        str(
            service_file
        ),
        "--host",
        host,
        "--port",
        str(
            port
        ),
        "--model-id",
        model_id,
        "--offload",
        offload_mode,
    ]

    environment = os.environ.copy()

    environment[
        "PYTHONUNBUFFERED"
    ] = "1"

    environment[
        "PYTHONUTF8"
    ] = "1"

    environment[
        "PYTHONIOENCODING"
    ] = "utf-8"

    print(
        "\n" + "=" * 60
    )

    print(
        "STARTING PERSISTENT LOCAL LTX SERVICE"
    )

    print(
        "=" * 60
    )

    print(
        subprocess.list2cmdline(
            command
        )
    )

    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
    )

    start_timeout = float(
        os.getenv(
            "LOCAL_LTX_SERVER_START_TIMEOUT_SEC",
            "300",
        )
    )

    deadline = (
        time.monotonic()
        + start_timeout
    )

    while time.monotonic() < deadline:

        return_code = process.poll()

        if return_code is not None:

            raise PipelineError(
                (
                    "Persistent Local LTX service exited during "
                    f"startup with return code {return_code}."
                )
            )

        if ping_local_ltx_service(
            host,
            port,
        ):

            os.environ[
                "LOCAL_LTX_SERVER_HOST"
            ] = host

            os.environ[
                "LOCAL_LTX_SERVER_PORT"
            ] = str(
                port
            )

            print(
                (
                    "Persistent Local LTX service ready at "
                    f"{host}:{port}"
                )
            )

            return process

        time.sleep(
            0.5
        )

    process.terminate()

    raise PipelineError(
        (
            "Persistent Local LTX service did not become ready "
            f"within {start_timeout:.0f}s."
        )
    )


def stop_local_ltx_service(
    process,
) -> None:

    if process is None:

        return

    host = os.getenv(
        "LOCAL_LTX_SERVER_HOST",
        "127.0.0.1",
    )

    raw_port = os.getenv(
        "LOCAL_LTX_SERVER_PORT"
    )

    if (
        raw_port
        and process.poll()
        is None
    ):

        request = (
            json.dumps(
                {
                    "action":
                        "shutdown",
                }
            )
            + "\n"
        ).encode(
            "utf-8"
        )

        try:

            with socket.create_connection(
                (
                    host,
                    int(
                        raw_port
                    ),
                ),
                timeout=2.0,
            ) as connection:

                connection.sendall(
                    request
                )

                connection.settimeout(
                    2.0
                )

                connection.recv(
                    4096
                )

        except OSError:

            pass

    try:

        process.wait(
            timeout=15
        )

    except subprocess.TimeoutExpired:

        process.terminate()

        try:

            process.wait(
                timeout=5
            )

        except subprocess.TimeoutExpired:

            process.kill()

            process.wait()

    os.environ.pop(
        "LOCAL_LTX_SERVER_HOST",
        None,
    )

    os.environ.pop(
        "LOCAL_LTX_SERVER_PORT",
        None,
    )

    print(
        "Persistent Local LTX service stopped."
    )


def run_scene_generation(
    max_image_attempts: int,
    max_video_attempts: int,
) -> None:

    if all_scene_generation_completed():
        print(
            "\nAll scene image/video stages already complete."
        )
        return

    ltx_service = None

    try:

        ltx_service = (
            start_local_ltx_service()
        )

        for scene_id in get_scene_ids():

            run_worker(
                STAGE_SCENES,
                "scene_orchestrator.py",
                [
                    "--scene",
                    str(
                        scene_id
                    ),

                    "--max-image-attempts",
                    str(
                        max_image_attempts
                    ),

                    "--max-video-attempts",
                    str(
                        max_video_attempts
                    ),
                ],
            )

        if not all_scene_generation_completed():

            raise PipelineError(
                (
                    "One or more scene-generation stages "
                    "remain incomplete."
                )
            )

    finally:

        stop_local_ltx_service(
            ltx_service
        )


def should_stop_after(
    current_stage: str,
    requested_stage: str | None,
) -> bool:

    return (
        requested_stage
        == current_stage
    )


def run_standard_stage(
    stage: str,
    script_name: str,
    arguments: list[str] | None = None,
) -> None:

    if stage_completed(
        stage
    ):
        print(
            f"\nSKIP {stage}: already completed."
        )
        return

    run_worker(
        stage,
        script_name,
        arguments,
    )

    if not stage_completed(
        stage
    ):
        raise PipelineError(
            (
                f"Stage '{stage}' returned success but "
                "pipeline status is not completed."
            )
        )


def run_pipeline(
    args: argparse.Namespace,
) -> None:

    if args.idea is not None:

        new_job_args = [
            "--idea",
            args.idea,
        ]

        if args.job_id:
            new_job_args.extend(
                [
                    "--job-id",
                    args.job_id,
                ]
            )

        run_worker(
            "new_job",
            "new_job.py",
            new_job_args,
        )

    elif not JOB_FILE.exists():

        raise PipelineError(
            (
                "No active jobs/video_job.json exists. "
                "Provide --idea to create a new job."
            )
        )

    job = load_job()

    print(
        f"\nACTIVE JOB: {job.get('job_id')}"
    )

    print(
        f"TITLE:      {job.get('idea', {}).get('title')}"
    )

    # -----------------------------------------------------
    # Script
    # -----------------------------------------------------

    run_standard_stage(
        STAGE_SCRIPT,
        "script_generator.py",
    )

    if should_stop_after(
        STAGE_SCRIPT,
        args.stop_after,
    ):
        return

    # -----------------------------------------------------
    # Natural voice + local timing
    # -----------------------------------------------------

    run_voice_timing(
        args.max_local_rewrites
    )

    if should_stop_after(
        STAGE_VOICE_TIMING,
        args.stop_after,
    ):
        return

    # -----------------------------------------------------
    # Global timing normalization
    # -----------------------------------------------------

    global_timing_runner = (
        run_worker if os.getenv("VIDEO_PROVIDER", "runway").strip().lower() == "still_motion"
        else run_standard_stage
    )
    global_timing_runner(
        STAGE_GLOBAL_TIMING,
        "script_duration_orchestrator.py",
        [
            "--max-iterations",
            str(
                args.max_global_iterations
            ),
        ],
    )

    if should_stop_after(
        STAGE_GLOBAL_TIMING,
        args.stop_after,
    ):
        return

    # -----------------------------------------------------
    # Visual and reusable character planning
    # -----------------------------------------------------

    run_standard_stage(
        STAGE_VISUAL_PROMPTS,
        "visual_prompt_generator.py",
    )

    if should_stop_after(
        STAGE_VISUAL_PROMPTS,
        args.stop_after,
    ):
        return

    run_standard_stage(
        STAGE_CHARACTER_PROMPTS,
        "character_reference_generator.py",
    )

    if should_stop_after(
        STAGE_CHARACTER_PROMPTS,
        args.stop_after,
    ):
        return

    run_standard_stage(
        STAGE_CHARACTER_IMAGES,
        "image_generator.py",
        [
            "--mode",
            "character_reference",
        ],
    )

    if should_stop_after(
        STAGE_CHARACTER_IMAGES,
        args.stop_after,
    ):
        return

    # -----------------------------------------------------
    # Per-scene image/video + QC + trim
    # -----------------------------------------------------

    run_runway_budget_preflight(
        args.max_video_attempts
    )

    run_scene_generation(
        max_image_attempts=
            args.max_image_attempts,
        max_video_attempts=
            args.max_video_attempts,
    )

    if should_stop_after(
        STAGE_SCENES,
        args.stop_after,
    ):
        return

    # -----------------------------------------------------
    # Assembly + subtitles
    # -----------------------------------------------------

    run_standard_stage(
        STAGE_ASSEMBLY,
        "base_video_assembler.py",
    )

    if should_stop_after(
        STAGE_ASSEMBLY,
        args.stop_after,
    ):
        return

    run_standard_stage(
        STAGE_SUBTITLES,
        "subtitle_pipeline.py",
    )

    if should_stop_after(
        STAGE_SUBTITLES,
        args.stop_after,
    ):
        return

    # -----------------------------------------------------
    # Audio planning + generation + mix
    # -----------------------------------------------------

    if audio_plan_completed():
        print(
            "\nSKIP audio_plan: already completed."
        )
    else:
        run_worker(
            STAGE_AUDIO_PLAN,
            "audio_plan_generator.py",
        )

        if not audio_plan_completed():
            raise PipelineError(
                "Audio planner did not reach passed state."
            )

    if should_stop_after(
        STAGE_AUDIO_PLAN,
        args.stop_after,
    ):
        return

    run_elevenlabs_audio_budget_preflight()

    run_standard_stage(
        STAGE_AUDIO_ASSETS,
        "audio_asset_generator.py",
    )

    if should_stop_after(
        STAGE_AUDIO_ASSETS,
        args.stop_after,
    ):
        return

    run_standard_stage(
        STAGE_AUDIO_MIX,
        "final_audio_mix.py",
    )

    if should_stop_after(
        STAGE_AUDIO_MIX,
        args.stop_after,
    ):
        return

    # -----------------------------------------------------
    # Final QC + export
    # -----------------------------------------------------

    run_worker(STAGE_THUMBNAIL, "thumbnail_generator.py")
    if should_stop_after(STAGE_THUMBNAIL, args.stop_after):
        return

    # Let final export validate its own file/signature cache on resume.
    run_worker(
        STAGE_FINAL_QC,
        "final_qc_export.py",
    )

    if should_stop_after(
        STAGE_FINAL_QC,
        args.stop_after,
    ):
        return


def main() -> int:

    try:

        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )

        sys.stderr.reconfigure(
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )

    except (
        AttributeError,
        ValueError,
    ):

        pass

    print("=" * 72)
    print("VIDEO FACTORY - MASTER PIPELINE ORCHESTRATOR v1")
    print("=" * 72)

    args = parse_args()

    try:
        preflight()

        run_pipeline(
            args
        )

        job = load_job()

        state = master_state(
            job
        )

        state[
            "state"
        ] = "completed"

        state[
            "current_stage"
        ] = (
            args.stop_after
            or STAGE_FINAL_QC
        )

        state[
            "completed_at"
        ] = utc_now_iso()

        save_job_atomic(
            job
        )

    except Exception as exc:

        if JOB_FILE.exists():
            try:
                job = load_job()

                state = master_state(
                    job
                )

                state[
                    "state"
                ] = "failed"

                state[
                    "error"
                ] = str(
                    exc
                )

                state[
                    "updated_at"
                ] = utc_now_iso()

                save_job_atomic(
                    job
                )

            except Exception:
                pass

        print(
            "\n" + "=" * 72
        )

        print(
            "MASTER PIPELINE FAILED"
        )

        print(
            "=" * 72
        )

        print(
            f"\nERROR: {exc}"
        )

        print(
            "\nFix the problem, then resume with:"
        )

        print(
            "python src\\pipeline_orchestrator.py"
        )

        return 1

    job = load_job()

    print(
        "\n" + "=" * 72
    )

    if args.stop_after:
        print(
            (
                "MASTER PIPELINE STOPPED SUCCESSFULLY AFTER "
                + args.stop_after.upper()
            )
        )
    else:
        print(
            "MASTER PIPELINE COMPLETE"
        )

    print(
        "=" * 72
    )

    print(
        f"\nJob ID: {job.get('job_id')}"
    )

    final_file = (
        job
        .get(
            "output",
            {},
        )
        .get(
            "video_file"
        )
    )

    if final_file:
        print(
            f"Final video: {final_file}"
        )

    publish_ready = (
        job
        .get(
            "final_qc",
            {},
        )
        .get(
            "publish_ready"
        )
    )

    if publish_ready is not None:
        print(
            f"Publish ready: {publish_ready}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
