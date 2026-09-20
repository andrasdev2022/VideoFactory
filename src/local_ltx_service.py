from __future__ import annotations

import argparse
import gc
import json
import os
import socket
import sys
import time

from pathlib import Path

from local_ltx_worker import (
    DEFAULT_NEGATIVE_PROMPT,
    fit_prompt_to_token_budget,
    import_runtime,
    print_cuda_info,
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Persistent localhost service for Local LTX generation."
        )
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )

    parser.add_argument(
        "--port",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--model-id",
        default="Lightricks/LTX-Video",
    )

    parser.add_argument(
        "--offload",
        choices=[
            "sequential",
            "model",
        ],
        default="sequential",
    )

    return parser.parse_args()


def load_pipeline(
    *,
    model_id: str,
    offload_mode: str,
    torch,
    pipeline_class,
):

    print(
        "\nLoading persistent LTX pipeline..."
    )

    started = time.perf_counter()

    pipeline = (
        pipeline_class
        .from_pretrained(
            model_id,
            dtype=
                torch.float16,
        )
    )

    if hasattr(
        pipeline,
        "vae",
    ):

        pipeline.vae.enable_tiling()

    if offload_mode == "sequential":

        pipeline.enable_sequential_cpu_offload()

    else:

        pipeline.enable_model_cpu_offload()

    elapsed = (
        time.perf_counter()
        - started
    )

    print(
        (
            "Persistent LTX pipeline ready "
            f"in {elapsed:.1f}s."
        ),
        flush=True,
    )

    return pipeline


def validate_request(
    request: dict,
) -> None:

    required = (
        "image",
        "output",
        "prompt",
        "width",
        "height",
        "fps",
        "num_frames",
        "steps",
        "guidance_scale",
        "seed",
    )

    for name in required:

        if name not in request:

            raise RuntimeError(
                f"Missing request field: {name}"
            )

    width = int(
        request["width"]
    )

    height = int(
        request["height"]
    )

    num_frames = int(
        request["num_frames"]
    )

    if (
        width <= 0
        or height <= 0
        or width % 32 != 0
        or height % 32 != 0
    ):

        raise RuntimeError(
            (
                "LTX width/height must be positive "
                "and divisible by 32."
            )
        )

    if (
        num_frames < 9
        or (
            num_frames
            - 1
        )
        % 8
        != 0
    ):

        raise RuntimeError(
            "LTX num_frames must be N*8+1 and at least 9."
        )


def generate(
    *,
    request: dict,
    pipeline,
    torch,
    export_to_video,
    load_image,
) -> dict:

    validate_request(
        request
    )

    input_image = Path(
        request["image"]
    )

    output_file = Path(
        request["output"]
    )

    if not input_image.exists():

        raise RuntimeError(
            f"Input image does not exist: {input_image}"
        )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file.unlink(
        missing_ok=True,
    )

    image = load_image(
        str(
            input_image
        )
    )

    seed = int(
        request["seed"]
    )

    (
        prompt_text,
        original_prompt_tokens,
        used_prompt_tokens,
    ) = fit_prompt_to_token_budget(
        str(
            request["prompt"]
        ),
        pipeline.tokenizer,
    )

    print(
        (
            "Prompt tokens: "
            f"{original_prompt_tokens} -> "
            f"{used_prompt_tokens}"
        ),
        flush=True,
    )

    if (
        original_prompt_tokens
        > used_prompt_tokens
    ):

        print(
            (
                "Prompt compacted before Diffusers "
                "to preserve the LTX 128-token limit."
            ),
            flush=True,
        )

    generator = (
        torch.Generator(
            device="cpu"
        )
        .manual_seed(
            seed
        )
    )

    torch.cuda.reset_peak_memory_stats()

    started = time.perf_counter()

    result = pipeline(
        image=image,
        prompt=prompt_text,
        negative_prompt=str(
            request.get(
                "negative_prompt",
                DEFAULT_NEGATIVE_PROMPT,
            )
        ),
        width=int(
            request["width"]
        ),
        height=int(
            request["height"]
        ),
        num_frames=int(
            request["num_frames"]
        ),
        frame_rate=int(
            request["fps"]
        ),
        num_inference_steps=int(
            request["steps"]
        ),
        guidance_scale=float(
            request["guidance_scale"]
        ),
        decode_timestep=0.05,
        decode_noise_scale=0.025,
        generator=generator,
    )

    frames = result.frames[
        0
    ]

    export_to_video(
        frames,
        str(
            output_file
        ),
        fps=int(
            request["fps"]
        ),
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    if (
        not output_file.exists()
        or output_file.stat().st_size
        == 0
    ):

        raise RuntimeError(
            "LTX export produced an empty output file."
        )

    peak = (
        torch.cuda
        .max_memory_allocated()
        / 1024**3
    )

    response = {
        "ok":
            True,

        "elapsed_sec":
            round(
                elapsed,
                3,
            ),

        "bytes":
            output_file
            .stat()
            .st_size,

        "peak_cuda_gib":
            round(
                peak,
                3,
            ),
    }

    del frames
    del result
    del generator
    del image

    gc.collect()

    if torch.cuda.is_available():

        torch.cuda.empty_cache()

    return response


def send_response(
    connection: socket.socket,
    response: dict,
) -> None:

    payload = (
        json.dumps(
            response,
            ensure_ascii=False,
        )
        + "\n"
    )

    connection.sendall(
        payload.encode(
            "utf-8"
        )
    )


def run_server(
    args: argparse.Namespace,
) -> int:

    (
        torch,
        pipeline_class,
        export_to_video,
        load_image,
    ) = import_runtime()

    print("=" * 60)
    print("VIDEO FACTORY - LOCAL LTX SERVICE v1")
    print("=" * 60)

    print_cuda_info(
        torch
    )

    if not torch.cuda.is_available():

        raise RuntimeError(
            "CUDA is not available for the Local LTX service."
        )

    print(
        f"Model:   {args.model_id}"
    )

    print(
        f"Offload: {args.offload}"
    )

    pipeline = load_pipeline(
        model_id=args.model_id,
        offload_mode=args.offload,
        torch=torch,
        pipeline_class=
            pipeline_class,
    )

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as server:

        server.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )

        server.bind(
            (
                args.host,
                args.port,
            )
        )

        server.listen(
            4
        )

        print(
            (
                "LOCAL LTX SERVICE READY "
                f"{args.host}:{args.port}"
            ),
            flush=True,
        )

        while True:

            connection, address = (
                server.accept()
            )

            with connection:

                file = connection.makefile(
                    "rb"
                )

                line = file.readline()

                if not line:

                    continue

                try:

                    request = json.loads(
                        line.decode(
                            "utf-8"
                        )
                    )

                    action = request.get(
                        "action",
                        "generate",
                    )

                    if action == "ping":

                        send_response(
                            connection,
                            {
                                "ok":
                                    True,

                                "status":
                                    "ready",
                            },
                        )

                        continue

                    if action == "shutdown":

                        send_response(
                            connection,
                            {
                                "ok":
                                    True,

                                "status":
                                    "shutting_down",
                            },
                        )

                        return 0

                    if action != "generate":

                        raise RuntimeError(
                            (
                                "Unsupported Local LTX service action: "
                                f"{action}"
                            )
                        )

                    print(
                        (
                            "\nPersistent LTX request: "
                            f"{Path(request['image']).name} -> "
                            f"{Path(request['output']).name}"
                        ),
                        flush=True,
                    )

                    response = generate(
                        request=request,
                        pipeline=pipeline,
                        torch=torch,
                        export_to_video=
                            export_to_video,
                        load_image=
                            load_image,
                    )

                    print(
                        (
                            "Persistent LTX generation complete: "
                            f"{response['elapsed_sec']:.1f}s, "
                            f"peak CUDA "
                            f"{response['peak_cuda_gib']:.2f} GiB"
                        ),
                        flush=True,
                    )

                    send_response(
                        connection,
                        response,
                    )

                except Exception as exc:

                    print(
                        (
                            "Persistent LTX request failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                        flush=True,
                    )

                    send_response(
                        connection,
                        {
                            "ok":
                                False,

                            "error":
                                str(
                                    exc
                                ),

                            "error_type":
                                type(
                                    exc
                                ).__name__,
                        },
                    )

    return 0


def main() -> int:

    args = parse_args()

    try:

        return run_server(
            args
        )

    except Exception as exc:

        print(
            f"\nERROR: {exc}",
            flush=True,
        )

        print(
            (
                "Exception: "
                f"{type(exc).__name__}: {exc!r}"
            ),
            flush=True,
        )

        return 1


if __name__ == "__main__":

    os.environ.setdefault(
        "PYTHONUTF8",
        "1",
    )

    sys.exit(
        main()
    )
