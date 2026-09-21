from __future__ import annotations

from pathlib import Path
import argparse
import base64
import json
import math
import os
import sys
import urllib.request

from runwayml import RunwayML
import still_motion_provider
from dataclasses import asdict
from local_ltx_motion_policy import build_motion_plan, previous_seed as previous_ltx_seed
from local_ltx_provider import (
    calculate_num_frames as calculate_ltx_num_frames,
    generate as generate_local_ltx,
    load_config as load_local_ltx_config,
    validate_config as validate_local_ltx_config,
)
from validator import load_json
from pipeline_status import set_legacy_status_from_stage

# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

VIDEO_PROVIDER = os.getenv(
    "VIDEO_PROVIDER",
    "local_ltx",
).strip().lower()

VIDEO_MODEL = os.getenv(
    "RUNWAY_VIDEO_MODEL",
    "gen4_turbo",
)

VIDEO_RATIO = os.getenv(
    "RUNWAY_VIDEO_RATIO",
    "720:1280",
)

TASK_TIMEOUT_SEC = int(
    os.getenv(
        "RUNWAY_TASK_TIMEOUT_SEC",
        "600",
    )
)

MIN_DURATION_SEC = 2
MAX_DURATION_SEC = 10


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Video Factory image-to-video generator"
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Generate only one scene. "
            "Example: --scene 2"
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Regenerate video even if "
            "the MP4 already exists."
        ),
    )

    parser.add_argument(
        "--retry-from-qc",
        action="store_true",
        help=(
            "Regenerate a failed video using feedback "
            "from semantic video QC."
        ),
    )

    return parser.parse_args()


# ---------------------------------------------------------
# JSON SAVE
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
# LOOKUPS
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


# ---------------------------------------------------------
# DATA URI
# ---------------------------------------------------------

def image_to_data_uri(
    image_path: Path,
) -> str:

    suffix = image_path.suffix.lower()

    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }

    mime_type = mime_types.get(
        suffix
    )

    if mime_type is None:

        raise RuntimeError(
            f"Unsupported image format: {suffix}"
        )

    with image_path.open(
        "rb"
    ) as file:

        encoded = base64.b64encode(
            file.read()
        ).decode(
            "ascii"
        )

    return (
        f"data:{mime_type};base64,"
        f"{encoded}"
    )


# ---------------------------------------------------------
# OUTPUT PATH
# ---------------------------------------------------------

def get_video_output_path(
    job: dict,
    scene: dict,
) -> Path:

    job_id = job["job_id"]
    scene_id = scene["scene_id"]

    return (
        PROJECT_ROOT
        / "output"
        / job_id
        / "videos"
        / f"scene_{scene_id:03d}.mp4"
    )


# ---------------------------------------------------------
# PRECONDITIONS
# ---------------------------------------------------------

def validate_scene_preconditions(
    job: dict,
    scene: dict,
) -> list[str]:

    errors: list[str] = []

    scene_id = scene["scene_id"]

    image = scene.get(
        "image",
        {},
    )

    # -----------------------------------------------------
    # Technical QC
    # -----------------------------------------------------

    technical_qc_status = (
        image
        .get(
            "qc",
            {},
        )
        .get(
            "status"
        )
    )

    if technical_qc_status != "passed":

        errors.append(
            f"Scene {scene_id}: technical "
            f"image QC has not passed."
        )

    # -----------------------------------------------------
    # Semantic QC
    # -----------------------------------------------------

    semantic_qc_status = (
        image
        .get(
            "semantic_qc",
            {},
        )
        .get(
            "status"
        )
    )

    if semantic_qc_status != "passed":

        errors.append(
            f"Scene {scene_id}: semantic "
            f"image QC has not passed."
        )

    # -----------------------------------------------------
    # Image file
    # -----------------------------------------------------

    if not image.get(
        "file"
    ):

        errors.append(
            f"Scene {scene_id}: "
            f"image.file is missing."
        )

    # -----------------------------------------------------
    # Motion prompt
    # -----------------------------------------------------

    if not scene.get(
        "motion_prompt"
    ):

        errors.append(
            f"Scene {scene_id}: "
            f"motion_prompt is missing."
        )

    # -----------------------------------------------------
    # Audio-driven timing
    # -----------------------------------------------------

    render_duration = get_render_duration(
        job,
        scene_id,
    )

    if render_duration is None:

        errors.append(
            f"Scene {scene_id}: "
            f"scene timing has not passed or "
            f"render_duration_sec is missing."
        )

    elif not (
        MIN_DURATION_SEC
        <= render_duration
        <= MAX_DURATION_SEC
    ):

        errors.append(
            f"Scene {scene_id}: "
            f"render duration {render_duration}s is outside "
            f"supported range "
            f"{MIN_DURATION_SEC}-"
            f"{MAX_DURATION_SEC}s."
        )

    return errors


# ---------------------------------------------------------
# BUILD MOTION PROMPT
# ---------------------------------------------------------

MAX_RUNWAY_PROMPT_CHARS = 1000
SAFE_RUNWAY_PROMPT_CHARS = 900


def build_video_prompt(
    job: dict,
    scene: dict,
    use_qc_feedback: bool = False,
) -> str:

    if VIDEO_PROVIDER == "still_motion":
        return still_motion_provider.motion_prompt(still_motion_provider.load_config(scene.get("still_motion")))

    if VIDEO_PROVIDER == "local_ltx":
        return build_motion_plan(job, scene, retry=use_qc_feedback)["prompt"]

    motion_prompt = (
        scene.get(
            "motion_prompt",
            ""
        )
        .strip()
    )

    continuity_notes = (
        scene.get(
            "continuity_notes",
            ""
        )
        .strip()
    )

    parts: list[str] = []

    # -----------------------------------------------------
    # Main requested motion
    # -----------------------------------------------------

    if motion_prompt:

        parts.append(
            motion_prompt
        )

    # -----------------------------------------------------
    # Previous QC correction
    # -----------------------------------------------------

    if use_qc_feedback:

        correction = build_qc_correction(
            job,
            scene,
        )

        if correction:

            parts.append(
                "Correction from previous attempt: "
                + correction
            )

    # -----------------------------------------------------
    # Continuity
    # -----------------------------------------------------

    if continuity_notes:

        parts.append(
            f"Continuity: {continuity_notes}"
        )

    parts.append(
        "Maintain character identity and appearance. "
        "Natural controlled motion. "
        "One continuous shot."
    )

    prompt = " ".join(
        parts
    )

    # -----------------------------------------------------
    # Runway safety limit
    # -----------------------------------------------------

    if len(prompt) > SAFE_RUNWAY_PROMPT_CHARS:

        prompt = (
            prompt[
                :SAFE_RUNWAY_PROMPT_CHARS
            ]
            .rsplit(
                " ",
                1,
            )[0]
            .rstrip(
                " ,.;:"
            )
            + "."
        )

    if len(prompt) > MAX_RUNWAY_PROMPT_CHARS:

        raise RuntimeError(
            f"Runway prompt too long: "
            f"{len(prompt)} chars."
        )

    return prompt


# ---------------------------------------------------------
# DOWNLOAD VIDEO
# ---------------------------------------------------------

def download_file(
    url: str,
    output_file: Path,
) -> None:

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = output_file.with_suffix(
        output_file.suffix + ".tmp"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "VideoFactory/1.0"
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:

        with temp_file.open(
            "wb"
        ) as file:

            while True:

                chunk = response.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                file.write(
                    chunk
                )

    if (
        not temp_file.exists()
        or temp_file.stat().st_size == 0
    ):

        raise RuntimeError(
            "Downloaded video file is empty."
        )

    temp_file.replace(
        output_file
    )


# ---------------------------------------------------------
# GENERATE ONE VIDEO
# ---------------------------------------------------------

def generate_scene_video(
    client: RunwayML | None,
    job: dict,
    scene: dict,
    force: bool,
    retry_from_qc: bool,
) -> bool:

    scene_id = scene[
        "scene_id"
    ]

    # -----------------------------------------------------
    # QC RETRY
    # -----------------------------------------------------

    if retry_from_qc:

        semantic_qc_status = (
            scene
            .get(
                "video",
                {},
            )
            .get(
                "semantic_qc",
                {},
            )
            .get(
                "status"
            )
        )

        if semantic_qc_status != "failed":

            raise RuntimeError(
                f"Scene {scene_id}: --retry-from-qc requested, "
                f"but semantic QC status is "
                f"'{semantic_qc_status}'."
            )

        # A QC retry always creates a new artifact.
        force = True

    # -----------------------------------------------------
    # Preconditions
    # -----------------------------------------------------

    errors = (
        validate_scene_preconditions(
            job,
            scene,
        )
    )

    if errors:

        raise RuntimeError(
            "\n".join(
                errors
            )
        )

    # -----------------------------------------------------
    # Input image
    # -----------------------------------------------------

    image_file = (
        scene["image"]["file"]
    )

    image_path = (
        PROJECT_ROOT
        / image_file
    )

    if not image_path.exists():

        raise RuntimeError(
            f"Scene {scene_id}: "
            f"input image does not exist: "
            f"{image_file}"
        )

    # -----------------------------------------------------
    # Output video
    # -----------------------------------------------------

    output_file = (
        get_video_output_path(
            job,
            scene,
        )
    )

    # -----------------------------------------------------
    # Current timing request
    # -----------------------------------------------------

    render_duration = get_render_duration(
        job,
        scene_id,
    )

    if render_duration is None:

        raise RuntimeError(
            f"Scene {scene_id}: approved render timing "
            f"is not available."
        )

    if VIDEO_PROVIDER == "runway":

        provider_duration = float(
            get_provider_duration(
                render_duration
            )
        )

    elif VIDEO_PROVIDER == "still_motion":
        still_config = still_motion_provider.load_config(scene.get("still_motion"))
        provider_duration = still_motion_provider.frame_count(render_duration, still_config) / still_config.fps

    elif VIDEO_PROVIDER == "local_ltx":

        ltx_config = load_local_ltx_config()

        ltx_errors = validate_local_ltx_config(
            ltx_config
        )

        if ltx_errors:

            raise RuntimeError(
                "\n".join(
                    ltx_errors
                )
            )

        ltx_num_frames = calculate_ltx_num_frames(
            render_duration,
            ltx_config.fps,
        )

        provider_duration = (
            float(
                ltx_num_frames
            )
            / float(
                ltx_config.fps
            )
        )

    else:

        raise RuntimeError(
            (
                "Unsupported VIDEO_PROVIDER: "
                f"{VIDEO_PROVIDER}. "
                "Expected 'local_ltx', 'still_motion' or 'runway'."
            )
        )

    # -----------------------------------------------------
    # Existing artifact
    # -----------------------------------------------------

    if (
        output_file.exists()
        and not force
    ):

        if video_metadata_matches_current_request(
            scene=scene,
            output_file=output_file,
            render_duration_sec=render_duration,
            provider_duration_sec=provider_duration,
            source_image=image_file,
            provider=VIDEO_PROVIDER,
        ):

            print(
                f"  SKIP: Scene {scene_id} "
                f"video already matches current timing."
            )

            return False

        print(
            f"  STALE: Scene {scene_id} has an existing "
            f"MP4, but its metadata does not match "
            f"the current timing. Regenerating."
        )

    # -----------------------------------------------------
    # Provider request
    # -----------------------------------------------------

    prompt_text = (
        build_video_prompt(
            job=job,
            scene=scene,
            use_qc_feedback=retry_from_qc,
        )
    )

    print(
        f"\nGenerating scene {scene_id}"
    )

    print(
        f"  Provider:     {VIDEO_PROVIDER}"
    )

    print(
        f"  Target render:{render_duration:.3f}s"
    )

    print(
        f"  Provider dur: {provider_duration:.3f}s"
    )

    print(
        f"  Input:        {image_file}"
    )

    print(
        f"  Prompt chars: "
        f"{len(prompt_text)}"
    )

    if retry_from_qc:

        correction = (
            build_motion_plan(job, scene, retry=True)["stage"]
            if VIDEO_PROVIDER == "local_ltx"
            else build_qc_correction(
                job,
                scene,
            )
        )

        print(
            "  QC retry:     YES"
        )

        print(
            f"  Correction:   "
            f"{correction}"
        )

    provider_metadata: dict[str, Any]

    if VIDEO_PROVIDER == "runway":

        if client is None:

            raise RuntimeError(
                "Runway client is not initialized."
            )

        prompt_image = image_to_data_uri(
            image_path
        )

        print(
            f"  Model:        {VIDEO_MODEL}"
        )

        print(
            f"  Ratio:        {VIDEO_RATIO}"
        )

        task = (
            client
            .image_to_video
            .create(
                model=VIDEO_MODEL,
                prompt_image=prompt_image,
                prompt_text=prompt_text,
                ratio=VIDEO_RATIO,
                duration=int(
                    round(
                        provider_duration
                    )
                ),
            )
            .wait_for_task_output(
                timeout=TASK_TIMEOUT_SEC,
            )
        )

        if not task.output:

            raise RuntimeError(
                f"Scene {scene_id}: "
                f"Runway task returned no output."
            )

        video_url = task.output[
            0
        ]

        if not video_url:

            raise RuntimeError(
                f"Scene {scene_id}: "
                f"Runway returned empty video URL."
            )

        download_file(
            video_url,
            output_file,
        )

        provider_metadata = {
            "provider":
                "runway",

            "model":
                VIDEO_MODEL,

            "ratio":
                VIDEO_RATIO,

            "task_id":
                str(
                    task.id
                ),
        }

    elif VIDEO_PROVIDER == "still_motion":
        provider_metadata = still_motion_provider.generate(
            input_image=image_path, output_file=output_file,
            duration_sec=render_duration, config=still_config,
        )
        scene["motion_strategy"] = "still_motion_v1"
        scene["semantic_qc_policy"] = {
            "version": "still_motion_v1",
            "motion_mode": "static_hold" if still_config.mode == "hold" or still_config.max_zoom == 1 else "camera_only",
            "allowed_exit_character_ids": [],
        }

    else:

        previous_seed = previous_ltx_seed(scene)
        motion_plan = build_motion_plan(job, scene, retry=retry_from_qc)

        result = generate_local_ltx(
            input_image=image_path,
            output_file=output_file,
            prompt=prompt_text,
            duration_sec=render_duration,
            scene_id=scene_id,
            previous_seed=previous_seed,
        )

        provider_duration = (
            result.duration_sec
        )

        scene["local_ltx_last_seed"] = result.seed

        provider_metadata = {
            "motion_policy_version": motion_plan["version"],
            "motion_policy_stage": motion_plan["stage"],
            "effective_motion_prompt": motion_plan["motion_prompt"],
            "requested_prompt": prompt_text,

            "provider":
                "local_ltx",

            "model":
                result.model_id,

            "ratio":
                (
                    f"{result.width}:"
                    f"{result.height}"
                ),

            "task_id":
                (
                    f"local-ltx-"
                    f"{scene_id}-"
                    f"{result.seed}"
                ),

            "width":
                result.width,

            "height":
                result.height,

            "fps":
                result.fps,

            "num_frames":
                result.num_frames,

            "inference_steps":
                result.inference_steps,

            "guidance_scale":
                result.guidance_scale,

            "seed":
                result.seed,

            "offload_mode":
                result.offload_mode,
        }

    if not output_file.exists():

        raise RuntimeError(
            f"Scene {scene_id}: "
            f"provider video does not exist."
        )

    file_size = (
        output_file
        .stat()
        .st_size
    )

    relative_video_path = str(
        output_file.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    # -----------------------------------------------------
    # IMPORTANT:
    #
    # Replace the complete video metadata block.
    #
    # This intentionally destroys QC results belonging
    # to the previous video artifact.
    # -----------------------------------------------------

    scene["video"] = {

        "status":
            "generated",

        "file":
            relative_video_path,

        **provider_metadata,

        "duration_sec":
            round(
                provider_duration,
                6,
            ),

        "provider_duration_sec":
            round(
                provider_duration,
                6,
            ),

        "target_render_duration_sec":
            round(
                render_duration,
                3,
            ),

        "trim_required":
            (
                provider_duration
                - render_duration
                > 0.001
            ),

        "timing_policy":
            "natural_voice_driven_v1",

        "source_image":
            image_file,

        "file_size_bytes":
            file_size,

        # The NEW artifact has not been checked yet.
        "qc": {
            "status": "pending",
        },

        "semantic_qc": {
            "status": "pending",
        },
    }

    # A new raw scene video invalidates any previous
    # trimmed/assembled downstream artifact chain.

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
        f"  Saved:        "
        f"{relative_video_path}"
    )

    print(
        f"  Bytes:        "
        f"{file_size:,}"
    )

    return True

# ---------------------------------------------------------
# ALL GENERATED?
# ---------------------------------------------------------

def all_scene_videos_generated(
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

        video = scene.get(
            "video",
            {},
        )

        if (
            video.get("status")
            != "generated"
        ):

            return False

        video_file = video.get(
            "file"
        )

        if not video_file:
            return False

        path = (
            PROJECT_ROOT
            / video_file
        )

        if not path.exists():
            return False

    return True


def find_script_scene(
    job: dict,
    scene_id: int,
) -> dict | None:

    for script_scene in job.get(
        "script",
        {},
    ).get(
        "scenes",
        [],
    ):

        if script_scene.get(
            "scene_id"
        ) == scene_id:

            return script_scene

    return None


def get_render_duration(
    job: dict,
    scene_id: int,
) -> float | None:

    script_scene = find_script_scene(
        job,
        scene_id,
    )

    if script_scene is None:
        return None

    timing = script_scene.get(
        "timing",
        {},
    )

    if timing.get(
        "status"
    ) != "passed":

        return None

    duration = timing.get(
        "render_duration_sec"
    )

    if duration is None:
        return None

    try:

        return float(
            duration
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


def get_provider_duration(
    render_duration_sec: float,
) -> int:

    provider_duration = math.ceil(
        float(
            render_duration_sec
        )
        - 1e-9
    )

    if not (
        MIN_DURATION_SEC
        <= provider_duration
        <= MAX_DURATION_SEC
    ):

        raise RuntimeError(
            f"Provider duration {provider_duration}s "
            f"is outside supported range "
            f"{MIN_DURATION_SEC}-"
            f"{MAX_DURATION_SEC}s."
        )

    return provider_duration


def video_metadata_matches_current_request(
    scene: dict,
    output_file: Path,
    render_duration_sec: float,
    provider_duration_sec: float,
    source_image: str,
    provider: str | None = None,
) -> bool:

    video = scene.get(
        "video",
        {},
    )

    if provider == "still_motion" and video.get("still_motion_config") != asdict(still_motion_provider.load_config(scene.get("still_motion"))):
        return False

    if video.get(
        "status"
    ) not in {
        "generated",
        "completed",
        "passed",
    }:

        return False

    video_file = video.get(
        "file"
    )

    if not video_file:

        return False

    expected_file = str(
        output_file.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    if video_file != expected_file:
        return False

    try:

        stored_render_duration = float(
            video.get(
                "target_render_duration_sec"
            )
        )

        stored_provider_duration = float(
            video.get(
                "provider_duration_sec"
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        return False

    if abs(
        stored_render_duration
        - float(
            render_duration_sec
        )
    ) > 0.001:

        return False

    if abs(
        stored_provider_duration
        - float(
            provider_duration_sec
        )
    ) > 0.001:

        return False

    if (
        provider is not None
        and video.get(
            "provider"
        )
        != provider
    ):

        return False

    if video.get(
        "source_image"
    ) != source_image:

        return False

    return output_file.exists()

def compact_qc_observation(
    value: Any,
    max_chars: int = 320,
) -> str:

    if not value:

        return ""

    text = " ".join(
        str(
            value
        )
        .replace(
            "\n",
            " ",
        )
        .split()
    )

    if not text:

        return ""

    lower = text.lower()

    however_index = lower.find(
        "however"
    )

    if however_index >= 0:

        text = text[
            however_index:
        ]

    if len(
        text
    ) <= max_chars:

        return text

    candidate = text[
        :max_chars - 1
    ].rstrip()

    last_space = candidate.rfind(
        " "
    )

    if last_space >= max_chars // 2:

        candidate = candidate[
            :last_space
        ].rstrip()

    return (
        candidate
        + "…"
    )


def build_qc_correction(
    job: dict,
    scene: dict,
    include_observation: bool = True,
) -> str:

    qc = (
        scene
        .get("video", {})
        .get("semantic_qc", {})
    )

    if qc.get("status") != "failed":
        return ""

    corrections: list[str] = []

    if not qc.get(
        "motion_matches_prompt",
        True,
    ):
        corrections.append(
            "Follow the requested motion exactly."
        )

    if not qc.get(
        "temporal_progression_coherent",
        True,
    ):
        corrections.append(
            "Maintain continuous chronological motion; "
            "no teleporting, disappearing, or reappearing."
        )

    if not qc.get(
        "source_frame_continuity_ok",
        True,
    ):
        corrections.append(
            "Remain visually close to the supplied opening frame."
        )

    if qc.get(
        "morphing_or_shape_drift",
        False,
    ):
        corrections.append(
            "Keep body shape and identity stable."
        )

    if qc.get(
        "unexpected_scene_cut",
        False,
    ):
        corrections.append(
            "Use one continuous shot with no scene cuts."
        )

    # -----------------------------------------------------
    # Character-specific corrections
    # -----------------------------------------------------

    for check in qc.get(
        "characters",
        [],
    ):

        character_id = check.get(
            "character_id"
        )

        character_name = character_id

        for character in job.get(
            "characters",
            [],
        ):

            if (
                character.get("character_id")
                == character_id
            ):

                character_name = character.get(
                    "name",
                    character_id,
                )

                break

        if not check.get(
            "present_throughout",
            True,
        ):
            corrections.append(
                f"{character_name} must remain continuously visible "
                f"in approximately the same screen position for the "
                f"entire shot. Do not move {character_name} out of frame."
            )

        if not check.get(
            "identity_stable",
            True,
        ):

            corrections.append(
                f"Keep {character_name}'s identity stable."
            )

        if not check.get(
            "appearance_stable",
            True,
        ):

            corrections.append(
                f"Keep {character_name}'s appearance unchanged."
            )

        if not check.get(
            "clothing_stable",
            True,
        ):

            corrections.append(
                f"Keep {character_name}'s clothing unchanged."
            )

    if include_observation:

        observation = compact_qc_observation(
            qc.get(
                "overall_notes"
            )
        )

        if observation:

            corrections.append(
                (
                    "Previous QC observation: "
                    + observation
                )
            )

    if not corrections:
        return ""

    return " ".join(
        corrections
    )

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - IMAGE TO VIDEO GENERATOR v2")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # API secret
    # -----------------------------------------------------

    if (
        VIDEO_PROVIDER
        == "runway"
        and not os.getenv(
            "RUNWAYML_API_SECRET"
        )
    ):

        print(
            "\nERROR: RUNWAYML_API_SECRET "
            "environment variable is not set."
        )

        return 1

    if VIDEO_PROVIDER not in {
        "still_motion",
        "local_ltx",
        "runway",
    }:

        print(
            (
                "\nERROR: unsupported VIDEO_PROVIDER "
                f"'{VIDEO_PROVIDER}'."
            )
        )

        return 1

    # -----------------------------------------------------
    # Load job
    # -----------------------------------------------------

    try:

        job = load_json(
            JOB_FILE
        )

    except Exception as exc:

        print(
            f"\nERROR loading video_job.json:\n"
            f"{exc}"
        )

        return 1

    scenes = (
        job
        .get(
            "visuals",
            {},
        )
        .get(
            "scenes",
            [],
        )
    )

    if not scenes:

        print(
            "\nERROR: no visual scenes found."
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
                f"\nERROR: scene "
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
        f"Provider: {VIDEO_PROVIDER}"
    )

    if VIDEO_PROVIDER == "runway":

        print(
            f"Model:    {VIDEO_MODEL}"
        )

    elif VIDEO_PROVIDER == "still_motion":
        print("Model:    ffmpeg_still_motion_v1")
    else:

        print(
            (
                "Model:    "
                + load_local_ltx_config().model_id
            )
        )

    print(
        f"Scenes: {len(selected_scenes)}"
    )

    # -----------------------------------------------------
    # Client
    # -----------------------------------------------------

    client = (
        RunwayML()
        if VIDEO_PROVIDER
        == "runway"
        else None
    )

    generated_count = 0
    failed_count = 0

    # -----------------------------------------------------
    # Generate
    # -----------------------------------------------------

    for scene in selected_scenes:

        scene_id = (
            scene["scene_id"]
        )

        try:

            generated = (
                generate_scene_video(
                    client=client,
                    job=job,
                    scene=scene,
                    force=args.force,
                    retry_from_qc=
                        args.retry_from_qc,
                )
            )

            if generated:

                generated_count += 1

            # ---------------------------------------------
            # Current pipeline stage becomes authoritative.
            # ---------------------------------------------

            set_legacy_status_from_stage(
                job,
                "scene_videos",
            )

            save_job(
                job
            )

        except Exception as exc:

            failed_count += 1

            print(
                f"\nERROR generating "
                f"scene {scene_id}:\n"
                f"{exc}"
            )

            print(
                f"  Exception type: "
                f"{type(exc).__name__}"
            )

            print(
                f"  Exception repr: "
                f"{exc!r}"
            )

            # ---------------------------------------------
            # Replace old artifact metadata.
            #
            # We must NOT preserve QC results belonging
            # to an older MP4.
            # ---------------------------------------------

            scene["video"] = {

                "status":
                    "failed",

                "error":
                    str(exc),

                "error_type":
                    type(exc).__name__,

                "error_repr":
                    repr(exc),

                "qc": {
                    "status":
                        "pending",
                },

                "semantic_qc": {
                    "status":
                        "pending",
                },
            }

            set_legacy_status_from_stage(
                job,
                "scene_videos",
            )

            save_job(
                job
            )

            # Video generation is expensive.
            # Stop on first provider/generation error.

            return 1

    # -----------------------------------------------------
    # Final pipeline status
    # -----------------------------------------------------

    set_legacy_status_from_stage(
        job,
        "scene_videos",
    )

    save_job(
        job
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    stage = (
        job["pipeline_status"]
        ["scene_videos"]
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "IMAGE TO VIDEO GENERATION COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nNew videos generated: "
        f"{generated_count}"
    )

    print(
        f"Failed: "
        f"{failed_count}"
    )

    print(
        f"Stage state: "
        f"{stage['state']}"
    )

    print(
        f"Ready: "
        f"{stage['ready']}/"
        f"{stage['total']}"
    )

    print(
        f"Pending: "
        f"{stage['pending']}"
    )

    print(
        f"Job status: "
        f"{job.get('status')}"
    )

    return 0

if __name__ == "__main__":

    sys.exit(
        main()
    )
