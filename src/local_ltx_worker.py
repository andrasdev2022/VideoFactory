from __future__ import annotations

import argparse
import os
import sys
import time

from pathlib import Path


DEFAULT_NEGATIVE_PROMPT = (
    "worst quality, inconsistent motion, blurry, jittery, "
    "distorted, morphing, duplicate characters, extra limbs"
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Isolated low-VRAM LTX image-to-video worker."
        )
    )

    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Check CUDA and Python dependencies only.",
    )

    parser.add_argument(
        "--image",
        default=None,
    )

    parser.add_argument(
        "--output",
        default=None,
    )

    parser.add_argument(
        "--prompt",
        default=None,
    )

    parser.add_argument(
        "--negative-prompt",
        default=DEFAULT_NEGATIVE_PROMPT,
    )

    parser.add_argument(
        "--model-id",
        default="Lightricks/LTX-Video",
    )

    parser.add_argument(
        "--width",
        type=int,
        default=512,
    )

    parser.add_argument(
        "--height",
        type=int,
        default=896,
    )

    parser.add_argument(
        "--fps",
        type=int,
        default=24,
    )

    parser.add_argument(
        "--num-frames",
        type=int,
        default=73,
    )

    parser.add_argument(
        "--steps",
        type=int,
        default=12,
    )

    parser.add_argument(
        "--guidance-scale",
        type=float,
        default=3.0,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=171198,
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


def import_runtime():

    try:

        import torch

    except Exception as exc:

        raise RuntimeError(
            (
                "PyTorch is not installed in the Local LTX "
                "environment. Run setup-local-ltx.ps1."
            )
        ) from exc

    try:

        from diffusers import (
            LTXImageToVideoPipeline,
        )

        from diffusers.utils import (
            export_to_video,
            load_image,
        )

    except Exception as exc:

        raise RuntimeError(
            (
                "Diffusers LTX dependencies are not installed. "
                "Run setup-local-ltx.ps1."
            )
        ) from exc

    return (
        torch,
        LTXImageToVideoPipeline,
        export_to_video,
        load_image,
    )


def print_cuda_info(
    torch,
) -> None:

    print(
        f"Python: {sys.version.split()[0]}"
    )

    print(
        f"PyTorch: {torch.__version__}"
    )

    print(
        f"CUDA available: {torch.cuda.is_available()}"
    )

    if torch.cuda.is_available():

        index = torch.cuda.current_device()

        properties = (
            torch.cuda.get_device_properties(
                index
            )
        )

        print(
            (
                "GPU: "
                + torch.cuda.get_device_name(
                    index
                )
            )
        )

        print(
            (
                "VRAM: "
                f"{properties.total_memory / 1024**3:.2f} GiB"
            )
        )

        print(
            f"CUDA runtime: {torch.version.cuda}"
        )


def validate_generation_args(
    args: argparse.Namespace,
) -> None:

    if not args.image:

        raise RuntimeError(
            "--image is required."
        )

    if not args.output:

        raise RuntimeError(
            "--output is required."
        )

    if not args.prompt:

        raise RuntimeError(
            "--prompt is required."
        )

    if (
        args.width % 32 != 0
        or args.height % 32 != 0
    ):

        raise RuntimeError(
            "LTX width/height must be divisible by 32."
        )

    if (
        args.num_frames < 9
        or (
            args.num_frames - 1
        )
        % 8
        != 0
    ):

        raise RuntimeError(
            "LTX num_frames must be N*8+1 and at least 9."
        )


def main() -> int:

    args = parse_args()

    print("=" * 60)
    print("VIDEO FACTORY - LOCAL LTX WORKER v1")
    print("=" * 60)

    try:

        (
            torch,
            LTXImageToVideoPipeline,
            export_to_video,
            load_image,
        ) = import_runtime()

        print_cuda_info(
            torch
        )

        if not torch.cuda.is_available():

            raise RuntimeError(
                (
                    "CUDA is not available in the Local LTX "
                    "environment. A CUDA-enabled PyTorch build "
                    "and NVIDIA driver are required."
                )
            )

        if args.preflight:

            print(
                "\nLOCAL LTX PREFLIGHT PASS"
            )

            return 0

        validate_generation_args(
            args
        )

        input_image = Path(
            args.image
        )

        output_file = Path(
            args.output
        )

        if not input_image.exists():

            raise RuntimeError(
                f"Input image does not exist: {input_image}"
            )

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        print(
            f"\nModel:      {args.model_id}"
        )

        print(
            f"Resolution: {args.width}x{args.height}"
        )

        print(
            f"Frames:     {args.num_frames}"
        )

        print(
            f"FPS:        {args.fps}"
        )

        print(
            f"Steps:      {args.steps}"
        )

        print(
            f"Guidance:   {args.guidance_scale}"
        )

        print(
            f"Seed:       {args.seed}"
        )

        print(
            f"Offload:    {args.offload}"
        )

        print(
            "\nLoading LTX pipeline..."
        )

        started = time.perf_counter()

        # RTX 20-series has no native BF16 tensor-core path.
        # FP16 is intentionally used for the Turing baseline.
        pipeline = (
            LTXImageToVideoPipeline
            .from_pretrained(
                args.model_id,
                dtype=
                    torch.float16,
            )
        )

        if hasattr(
            pipeline,
            "vae",
        ):

            pipeline.vae.enable_tiling()

        if args.offload == "sequential":

            pipeline.enable_sequential_cpu_offload()

        else:

            pipeline.enable_model_cpu_offload()

        image = load_image(
            str(
                input_image
            )
        )

        generator = (
            torch.Generator(
                device="cpu"
            )
            .manual_seed(
                args.seed
            )
        )

        print(
            "\nGenerating..."
        )

        result = pipeline(
            image=image,
            prompt=args.prompt,
            negative_prompt=
                args.negative_prompt,
            width=args.width,
            height=args.height,
            num_frames=args.num_frames,
            frame_rate=args.fps,
            num_inference_steps=
                args.steps,
            guidance_scale=
                args.guidance_scale,
            decode_timestep=0.05,
            decode_noise_scale=0.025,
            generator=generator,
        )

        frames = result.frames[
            0
        ]

        print(
            "\nEncoding MP4..."
        )

        export_to_video(
            frames,
            str(
                output_file
            ),
            fps=args.fps,
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

        print(
            "\nLOCAL LTX GENERATION COMPLETE"
        )

        print(
            f"Output:  {output_file}"
        )

        print(
            f"Bytes:   {output_file.stat().st_size:,}"
        )

        print(
            f"Elapsed: {elapsed:.1f}s"
        )

        peak = (
            torch.cuda
            .max_memory_allocated()
            / 1024**3
        )

        print(
            f"Peak CUDA allocated: {peak:.2f} GiB"
        )

        return 0

    except Exception as exc:

        print(
            f"\nERROR: {exc}"
        )

        print(
            (
                "Exception: "
                f"{type(exc).__name__}: {exc!r}"
            )
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
