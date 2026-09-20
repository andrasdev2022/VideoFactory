from __future__ import annotations

import json
import math
import os
import socket
import subprocess

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DEFAULT_LTX_PYTHON = (
    PROJECT_ROOT
    / ".venv-ltx"
    / "Scripts"
    / "python.exe"
)

DEFAULT_LTX_WORKER = (
    PROJECT_ROOT
    / "src"
    / "local_ltx_worker.py"
)


@dataclass(
    frozen=True,
)
class LocalLTXConfig:

    python_exe: Path
    worker_file: Path
    model_id: str
    width: int
    height: int
    fps: int
    inference_steps: int
    guidance_scale: float
    seed_base: int
    timeout_sec: int
    offload_mode: str


@dataclass(
    frozen=True,
)
class LocalLTXResult:

    file: Path
    model_id: str
    width: int
    height: int
    fps: int
    num_frames: int
    duration_sec: float
    inference_steps: int
    guidance_scale: float
    seed: int
    offload_mode: str


def load_config() -> LocalLTXConfig:

    return LocalLTXConfig(
        python_exe=Path(
            os.getenv(
                "LOCAL_LTX_PYTHON",
                str(
                    DEFAULT_LTX_PYTHON
                ),
            )
        ),
        worker_file=Path(
            os.getenv(
                "LOCAL_LTX_WORKER",
                str(
                    DEFAULT_LTX_WORKER
                ),
            )
        ),
        model_id=os.getenv(
            "LOCAL_LTX_MODEL_ID",
            "Lightricks/LTX-Video",
        ),
        width=int(
            os.getenv(
                "LOCAL_LTX_WIDTH",
                "512",
            )
        ),
        height=int(
            os.getenv(
                "LOCAL_LTX_HEIGHT",
                "896",
            )
        ),
        fps=int(
            os.getenv(
                "LOCAL_LTX_FPS",
                "24",
            )
        ),
        inference_steps=int(
            os.getenv(
                "LOCAL_LTX_INFERENCE_STEPS",
                "12",
            )
        ),
        guidance_scale=float(
            os.getenv(
                "LOCAL_LTX_GUIDANCE_SCALE",
                "3.0",
            )
        ),
        seed_base=int(
            os.getenv(
                "LOCAL_LTX_SEED_BASE",
                "171198",
            )
        ),
        timeout_sec=int(
            os.getenv(
                "LOCAL_LTX_TIMEOUT_SEC",
                "7200",
            )
        ),
        offload_mode=os.getenv(
            "LOCAL_LTX_OFFLOAD_MODE",
            "sequential",
        ),
    )


def validate_config(
    config: LocalLTXConfig,
) -> list[str]:

    errors: list[str] = []

    if not config.python_exe.exists():

        errors.append(
            (
                "Local LTX Python environment was not found: "
                f"{config.python_exe}"
            )
        )

    if not config.worker_file.exists():

        errors.append(
            (
                "Local LTX worker was not found: "
                f"{config.worker_file}"
            )
        )

    if (
        config.width <= 0
        or config.height <= 0
    ):

        errors.append(
            "LOCAL_LTX_WIDTH/HEIGHT must be positive."
        )

    if (
        config.width % 32 != 0
        or config.height % 32 != 0
    ):

        errors.append(
            (
                "LOCAL_LTX_WIDTH and LOCAL_LTX_HEIGHT must "
                "both be divisible by 32."
            )
        )

    if config.height <= config.width:

        errors.append(
            "Local LTX baseline must be portrait."
        )

    if config.fps <= 0:

        errors.append(
            "LOCAL_LTX_FPS must be positive."
        )

    if config.inference_steps < 1:

        errors.append(
            "LOCAL_LTX_INFERENCE_STEPS must be at least 1."
        )

    if config.timeout_sec < 60:

        errors.append(
            "LOCAL_LTX_TIMEOUT_SEC must be at least 60."
        )

    if config.offload_mode not in {
        "sequential",
        "model",
    }:

        errors.append(
            (
                "LOCAL_LTX_OFFLOAD_MODE must be "
                "'sequential' or 'model'."
            )
        )

    return errors


def calculate_num_frames(
    duration_sec: float,
    fps: int,
) -> int:

    if duration_sec <= 0:

        raise ValueError(
            "duration_sec must be positive."
        )

    if fps <= 0:

        raise ValueError(
            "fps must be positive."
        )

    minimum_frames = math.ceil(
        duration_sec
        * fps
        - 1e-9
    )

    # LTX works best with N*8+1 frame counts.
    groups = math.ceil(
        max(
            minimum_frames - 1,
            8,
        )
        / 8
    )

    return (
        groups
        * 8
        + 1
    )


def calculate_seed(
    *,
    config: LocalLTXConfig,
    scene_id: int,
    previous_seed: int | None = None,
) -> int:

    if previous_seed is not None:

        return (
            int(
                previous_seed
            )
            + 1
        )

    return (
        config.seed_base
        + int(
            scene_id
        )
    )


def build_command(
    *,
    config: LocalLTXConfig,
    input_image: Path,
    output_file: Path,
    prompt: str,
    num_frames: int,
    seed: int,
) -> list[str]:

    return [
        str(
            config.python_exe
        ),
        str(
            config.worker_file
        ),
        "--image",
        str(
            input_image
        ),
        "--output",
        str(
            output_file
        ),
        "--prompt",
        prompt,
        "--model-id",
        config.model_id,
        "--width",
        str(
            config.width
        ),
        "--height",
        str(
            config.height
        ),
        "--fps",
        str(
            config.fps
        ),
        "--num-frames",
        str(
            num_frames
        ),
        "--steps",
        str(
            config.inference_steps
        ),
        "--guidance-scale",
        str(
            config.guidance_scale
        ),
        "--seed",
        str(
            seed
        ),
        "--offload",
        config.offload_mode,
    ]


def server_endpoint() -> tuple[str, int] | None:

    raw_port = os.getenv(
        "LOCAL_LTX_SERVER_PORT"
    )

    if not raw_port:

        return None

    return (
        os.getenv(
            "LOCAL_LTX_SERVER_HOST",
            "127.0.0.1",
        ),
        int(
            raw_port
        ),
    )


def generate_via_server(
    *,
    config: LocalLTXConfig,
    input_image: Path,
    output_file: Path,
    prompt: str,
    num_frames: int,
    seed: int,
) -> dict:

    endpoint = server_endpoint()

    if endpoint is None:

        raise RuntimeError(
            "Local LTX server endpoint is not configured."
        )

    host, port = endpoint

    request = {
        "action":
            "generate",

        "image":
            str(
                input_image
            ),

        "output":
            str(
                output_file
            ),

        "prompt":
            prompt,

        "width":
            config.width,

        "height":
            config.height,

        "fps":
            config.fps,

        "num_frames":
            num_frames,

        "steps":
            config.inference_steps,

        "guidance_scale":
            config.guidance_scale,

        "seed":
            seed,
    }

    payload = (
        json.dumps(
            request,
            ensure_ascii=False,
        )
        + "\n"
    ).encode(
        "utf-8"
    )

    print(
        (
            "\nLocal LTX service: "
            f"{host}:{port}"
        )
    )

    try:

        with socket.create_connection(
            (
                host,
                port,
            ),
            timeout=config.timeout_sec,
        ) as connection:

            connection.settimeout(
                config.timeout_sec
            )

            connection.sendall(
                payload
            )

            response_file = (
                connection
                .makefile(
                    "rb"
                )
            )

            line = (
                response_file
                .readline()
            )

    except OSError as exc:

        raise RuntimeError(
            (
                "Local LTX persistent service is unavailable at "
                f"{host}:{port}: {exc}"
            )
        ) from exc

    if not line:

        raise RuntimeError(
            "Local LTX persistent service returned no response."
        )

    response = json.loads(
        line.decode(
            "utf-8"
        )
    )

    if not response.get(
        "ok"
    ):

        raise RuntimeError(
            (
                "Local LTX persistent service failed: "
                + str(
                    response.get(
                        "error",
                        "unknown error",
                    )
                )
            )
        )

    return response


def run_preflight(
    config: LocalLTXConfig | None = None,
) -> None:

    config = (
        config
        or load_config()
    )

    errors = validate_config(
        config
    )

    if errors:

        raise RuntimeError(
            "\n".join(
                errors
            )
        )

    completed = subprocess.run(
        [
            str(
                config.python_exe
            ),
            str(
                config.worker_file
            ),
            "--preflight",
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )

    if completed.returncode != 0:

        raise RuntimeError(
            (
                "Local LTX worker preflight failed with "
                f"return code {completed.returncode}."
            )
        )


def generate(
    *,
    input_image: Path,
    output_file: Path,
    prompt: str,
    duration_sec: float,
    scene_id: int,
    previous_seed: int | None = None,
    config: LocalLTXConfig | None = None,
) -> LocalLTXResult:

    config = (
        config
        or load_config()
    )

    errors = validate_config(
        config
    )

    if errors:

        raise RuntimeError(
            "\n".join(
                errors
            )
        )

    if not input_image.exists():

        raise RuntimeError(
            f"Local LTX input image does not exist: {input_image}"
        )

    if not prompt.strip():

        raise RuntimeError(
            "Local LTX prompt is empty."
        )

    num_frames = calculate_num_frames(
        duration_sec,
        config.fps,
    )

    seed = calculate_seed(
        config=config,
        scene_id=scene_id,
        previous_seed=previous_seed,
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        output_file
        .with_name(
            output_file.stem
            + ".ltx.tmp"
            + output_file.suffix
        )
    )

    temporary_file.unlink(
        missing_ok=True,
    )

    endpoint = server_endpoint()

    if endpoint is not None:

        try:

            generate_via_server(
                config=config,
                input_image=input_image,
                output_file=temporary_file,
                prompt=prompt,
                num_frames=num_frames,
                seed=seed,
            )

        except Exception:

            temporary_file.unlink(
                missing_ok=True,
            )

            raise

    else:

        command = build_command(
            config=config,
            input_image=input_image,
            output_file=temporary_file,
            prompt=prompt,
            num_frames=num_frames,
            seed=seed,
        )

        print(
            "\nLocal LTX command:"
        )

        print(
            subprocess.list2cmdline(
                command
            )
        )

        environment = os.environ.copy()

        environment[
            "PYTHONUTF8"
        ] = "1"

        environment[
            "PYTHONIOENCODING"
        ] = "utf-8"

        try:

            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=environment,
                check=False,
                timeout=config.timeout_sec,
            )

        except subprocess.TimeoutExpired as exc:

            temporary_file.unlink(
                missing_ok=True,
            )

            raise RuntimeError(
                (
                    "Local LTX generation timed out after "
                    f"{config.timeout_sec}s."
                )
            ) from exc

        if completed.returncode != 0:

            temporary_file.unlink(
                missing_ok=True,
            )

            raise RuntimeError(
                (
                    "Local LTX worker failed with return code "
                    f"{completed.returncode}."
                )
            )

    if (
        not temporary_file.exists()
        or temporary_file.stat().st_size == 0
    ):

        raise RuntimeError(
            "Local LTX worker produced no video file."
        )

    temporary_file.replace(
        output_file
    )

    duration = (
        float(
            num_frames
        )
        / float(
            config.fps
        )
    )

    return LocalLTXResult(
        file=output_file,
        model_id=config.model_id,
        width=config.width,
        height=config.height,
        fps=config.fps,
        num_frames=num_frames,
        duration_sec=duration,
        inference_steps=config.inference_steps,
        guidance_scale=config.guidance_scale,
        seed=seed,
        offload_mode=config.offload_mode,
    )
