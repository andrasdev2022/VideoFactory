from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys

from openai import OpenAI
from pydantic import BaseModel, Field
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

VISION_MODEL = os.getenv(
    "OPENAI_VIDEO_QC_MODEL",
    "gpt-5.6-luna",
)

VISION_DETAIL = os.getenv(
    "OPENAI_VIDEO_QC_DETAIL",
    "high",
)

FRAME_COUNT = int(
    os.getenv(
        "VIDEO_SEMANTIC_QC_FRAME_COUNT",
        "5",
    )
)

FRAME_WIDTH = int(
    os.getenv(
        "VIDEO_SEMANTIC_QC_FRAME_WIDTH",
        "512",
    )
)

LOW_CONFIDENCE_WARNING = float(
    os.getenv(
        "VIDEO_SEMANTIC_QC_LOW_CONFIDENCE",
        "0.70",
    )
)


QC_POLICY_VERSION = (
    "target_window_v3_dupcheck"
)


# ---------------------------------------------------------
# STRUCTURED OUTPUT
# ---------------------------------------------------------

class CharacterVideoQC(BaseModel):

    character_id: str

    present_throughout: bool

    max_visible_instances: int = Field(
        ge=0,
        le=10,
    )

    identity_stable: bool

    appearance_stable: bool

    clothing_stable: bool

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    notes: str


class VideoSemanticQCOutput(BaseModel):

    motion_matches_prompt: bool

    temporal_progression_coherent: bool

    source_frame_continuity_ok: bool

    anatomy_ok: bool

    morphing_or_shape_drift: bool

    unexpected_scene_cut: bool

    unwanted_text_or_logo: bool

    extra_main_characters: bool

    character_checks: list[CharacterVideoQC]

    problematic_sample_indices: list[int]

    overall_notes: str


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

SYSTEM_PROMPT = """
You are the VIDEO SEMANTIC QUALITY CONTROL worker inside an
automated short-form video production pipeline.

You are NOT receiving the original video directly.

Instead, you receive:

1. The original approved source image used to start the video.
2. Character reference images.
3. Several chronological sample frames extracted from the video.
4. The intended motion prompt and continuity requirements.

The video sample frames are explicitly numbered and ordered by time.

Your task is to determine whether the generated video is suitable
for continuing into final video production.

Evaluate:

MOTION
- Does the chronological frame sequence appear consistent with
  the requested motion?
- Does the action meaningfully progress in the intended direction?

TEMPORAL COHERENCE
- Do frames form one coherent continuous shot?
- Is there an unexplained change of environment or composition?
- Is there evidence of an unintended scene cut?

SOURCE FRAME CONTINUITY
- Does the video remain visually consistent with the approved
  source image?
- The first video frame should substantially preserve the original
  scene and character identities.

CHARACTER CONSISTENCY
For every expected character:
- Report max_visible_instances: the maximum number of simultaneously
  visible instances of that expected character in any supplied sample.
  A duplicated main character means max_visible_instances > 1.
  Do not treat a duplicate of an expected character as a harmless
  background extra.
- Is the character present when expected?
- If semantic_qc_policy.allowed_exit_character_ids contains a
  character, that character may leave frame naturally as part of the
  approved action and does not need to remain present through the final
  sample. Judge identity/appearance/clothing stability only while the
  character is visible.
- Does identity remain stable across the sampled frames?
- Do face, species, fur, hair and defining physical traits remain
  stable?
- Does defining clothing remain stable?
- Watch for identity drift and characters transforming into each other.

MORPHING
Look for:
- face drift
- body shape drift
- changing species
- changing clothing
- objects merging into bodies
- duplicated limbs
- disappearing or appearing body parts
- characters blending into backgrounds or each other

ANATOMY
Flag obvious malformed anatomy or major AI artifacts.

TEXT
Flag generated captions, subtitles, logos, watermarks or random
readable text that was not intentionally part of the approved scene.

EXTRA CHARACTERS
Background extras may be acceptable when appropriate.
Flag only prominent unintended or duplicated main characters.

IMPORTANT LIMITATION:
You only see sampled frames, not every moment of the video.
Do not claim certainty about events that cannot be established
from the supplied samples.

CONFIDENCE:
Character confidence represents confidence in your consistency
assessment, not an aesthetic quality score.

Return only the required structured output.
""".strip()


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Video Factory semantic video QC"
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help="Check one scene only, e.g. --scene 2",
    )

    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep extracted QC frames on disk",
    )

    return parser.parse_args()


# ---------------------------------------------------------
# SAVE JOB
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


def find_character(
    job: dict,
    character_id: str,
) -> dict | None:

    for character in job.get(
        "characters",
        [],
    ):

        if (
            character.get("character_id")
            == character_id
        ):

            return character

    return None


# ---------------------------------------------------------
# IMAGE -> DATA URL
# ---------------------------------------------------------

def image_to_data_url(
    path: Path,
) -> str:

    suffix = path.suffix.lower()

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

    with path.open(
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
# PRECONDITIONS
# ---------------------------------------------------------

def validate_preconditions(
    job: dict,
    scene: dict,
) -> list[str]:

    errors: list[str] = []

    scene_id = scene[
        "scene_id"
    ]

    video = scene.get(
        "video",
        {},
    )

    # Technical video QC must pass.
    video_qc = video.get(
        "qc",
        {},
    )

    if (
        video_qc.get("status")
        != "passed"
    ):

        errors.append(
            f"Scene {scene_id}: "
            f"technical video QC has not passed."
        )

    video_file = video.get(
        "file"
    )

    if not video_file:

        errors.append(
            f"Scene {scene_id}: "
            f"video.file is missing."
        )

    else:

        video_path = (
            PROJECT_ROOT
            / video_file
        )

        if not video_path.exists():

            errors.append(
                f"Scene {scene_id}: "
                f"video file does not exist: "
                f"{video_file}"
            )

    # Approved scene source image.
    image_file = (
        scene.get(
            "image",
            {},
        ).get(
            "file"
        )
    )

    if not image_file:

        errors.append(
            f"Scene {scene_id}: "
            f"source scene image is missing."
        )

    elif not (
        PROJECT_ROOT
        / image_file
    ).exists():

        errors.append(
            f"Scene {scene_id}: "
            f"source image does not exist: "
            f"{image_file}"
        )

    # Character references.
    for character_id in scene.get(
        "characters",
        [],
    ):

        character = find_character(
            job,
            character_id,
        )

        if character is None:

            errors.append(
                f"Scene {scene_id}: "
                f"unknown character "
                f"{character_id}."
            )

            continue

        reference_file = (
            character
            .get(
                "reference",
                {},
            )
            .get(
                "image_file"
            )
        )

        if not reference_file:

            errors.append(
                f"Scene {scene_id}: "
                f"{character_id} has no "
                f"reference image."
            )

            continue

        if not (
            PROJECT_ROOT
            / reference_file
        ).exists():

            errors.append(
                f"Scene {scene_id}: "
                f"reference file missing for "
                f"{character_id}."
            )

    if not scene.get(
        "motion_prompt"
    ):

        errors.append(
            f"Scene {scene_id}: "
            f"motion_prompt is missing."
        )

    return errors


# ---------------------------------------------------------
# GET VIDEO DURATION
# ---------------------------------------------------------

def get_actual_duration(
    scene: dict,
) -> float:

    duration = (
        scene
        .get(
            "video",
            {},
        )
        .get(
            "qc",
            {},
        )
        .get(
            "actual",
            {},
        )
        .get(
            "duration_sec"
        )
    )

    if duration is None:

        raise RuntimeError(
            "Video QC contains no actual duration."
        )

    return float(
        duration
    )


def get_evaluation_duration(
    scene: dict,
) -> float:

    actual_duration = (
        get_actual_duration(
            scene
        )
    )

    target_duration = (
        scene
        .get(
            "video",
            {},
        )
        .get(
            "target_render_duration_sec"
        )
    )

    if target_duration is None:

        return actual_duration

    try:

        target_duration = float(
            target_duration
        )

    except (
        TypeError,
        ValueError,
    ):

        return actual_duration

    if target_duration <= 0:

        return actual_duration

    # Semantic QC must evaluate only the time window that will
    # survive exact trimming. Provider tail frames are irrelevant
    # to the final video and must not fail the scene.

    return min(
        actual_duration,
        target_duration,
    )


# ---------------------------------------------------------
# FRAME TIMESTAMPS
# ---------------------------------------------------------

def calculate_sample_times(
    duration: float,
    count: int,
) -> list[float]:

    if count < 2:
        count = 2

    # Avoid requesting a frame beyond the actual final frame.
    last_time = max(
        0.0,
        duration - 0.10,
    )

    if last_time <= 0:
        return [
            0.0
        ]

    times = []

    for index in range(
        count
    ):

        fraction = (
            index
            / (count - 1)
        )

        timestamp = (
            last_time
            * fraction
        )

        times.append(
            round(
                timestamp,
                3,
            )
        )

    return times


# ---------------------------------------------------------
# EXTRACT VIDEO FRAMES
# ---------------------------------------------------------

def extract_frames(
    job: dict,
    scene: dict,
) -> list[dict]:

    scene_id = scene[
        "scene_id"
    ]

    video_file = scene[
        "video"
    ][
        "file"
    ]

    video_path = (
        PROJECT_ROOT
        / video_file
    )

    duration = get_evaluation_duration(
        scene
    )

    timestamps = calculate_sample_times(
        duration,
        FRAME_COUNT,
    )

    frame_dir = (
        PROJECT_ROOT
        / "output"
        / job["job_id"]
        / "qc"
        / "video"
        / f"scene_{scene_id:03d}"
    )

    frame_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    samples: list[dict] = []

    for index, timestamp in enumerate(
        timestamps,
        start=1,
    ):

        frame_file = (
            frame_dir
            / f"frame_{index:02d}.jpg"
        )

        command = [
            "ffmpeg",
            "-y",

            "-ss",
            f"{timestamp:.3f}",

            "-i",
            str(video_path),

            "-frames:v",
            "1",

            "-vf",
            f"scale={FRAME_WIDTH}:-2",

            "-q:v",
            "2",

            str(frame_file),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:

            raise RuntimeError(
                f"FFmpeg failed extracting "
                f"sample {index}:\n"
                f"{result.stderr}"
            )

        if (
            not frame_file.exists()
            or frame_file.stat().st_size == 0
        ):

            raise RuntimeError(
                f"Frame extraction produced "
                f"no image for sample {index}."
            )

        samples.append(
            {
                "index":
                    index,

                "timestamp_sec":
                    timestamp,

                "path":
                    frame_file,
            }
        )

    return samples


# ---------------------------------------------------------
# BUILD TEXT CONTEXT
# ---------------------------------------------------------

def build_context(
    job: dict,
    scene: dict,
    samples: list[dict],
) -> str:

    characters = []

    for character_id in scene.get(
        "characters",
        [],
    ):

        character = find_character(
            job,
            character_id,
        )

        if character is None:
            continue

        reference = character.get(
            "reference",
            {},
        )

        characters.append(
            {
                "character_id":
                    character_id,

                "name":
                    character.get(
                        "name"
                    ),

                "description":
                    character.get(
                        "description"
                    ),

                "visual_signature":
                    reference.get(
                        "visual_signature"
                    ),
            }
        )

    context = {
        "scene_id":
            scene["scene_id"],

        "motion_prompt":
            scene.get(
                "motion_prompt"
            ),

        "continuity_notes":
            scene.get(
                "continuity_notes"
            ),

        "image_prompt":
            scene.get(
                "image_prompt"
            ),

        "semantic_qc_policy":
            scene.get(
                "semantic_qc_policy",
                {},
            ),

        "expected_characters":
            characters,

        "samples": [
            {
                "sample_index":
                    sample["index"],

                "timestamp_sec":
                    sample["timestamp_sec"],
            }
            for sample in samples
        ],

        "instructions":
            (
                "The chronological VIDEO SAMPLE FRAME images "
                "must be interpreted in ascending sample_index."
            ),
    }

    return json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------
# BUILD MULTIMODAL REQUEST
# ---------------------------------------------------------

def build_request_content(
    job: dict,
    scene: dict,
    samples: list[dict],
) -> list[dict]:

    content: list[dict] = []

    content.append(
        {
            "type": "input_text",

            "text": (
                "Evaluate the generated video using "
                "the following context:\n\n"
                + build_context(
                    job,
                    scene,
                    samples,
                )
            ),
        }
    )

    # -----------------------------------------------------
    # Approved source scene image
    # -----------------------------------------------------

    source_image_file = (
        scene["image"]["file"]
    )

    source_image_path = (
        PROJECT_ROOT
        / source_image_file
    )

    content.append(
        {
            "type": "input_text",
            "text": (
                "APPROVED SOURCE IMAGE USED "
                "TO START THE VIDEO:"
            ),
        }
    )

    content.append(
        {
            "type": "input_image",

            "image_url":
                image_to_data_url(
                    source_image_path
                ),

            "detail":
                VISION_DETAIL,
        }
    )

    # -----------------------------------------------------
    # Character reference images
    # -----------------------------------------------------

    for character_id in scene.get(
        "characters",
        [],
    ):

        character = find_character(
            job,
            character_id,
        )

        if character is None:
            continue

        reference_file = (
            character
            .get(
                "reference",
                {},
            )
            .get(
                "image_file"
            )
        )

        if not reference_file:
            continue

        reference_path = (
            PROJECT_ROOT
            / reference_file
        )

        content.append(
            {
                "type": "input_text",

                "text": (
                    f"CHARACTER REFERENCE: "
                    f"{character_id} "
                    f"({character.get('name', '')})"
                ),
            }
        )

        content.append(
            {
                "type": "input_image",

                "image_url":
                    image_to_data_url(
                        reference_path
                    ),

                "detail":
                    VISION_DETAIL,
            }
        )

    # -----------------------------------------------------
    # Chronological video samples
    # -----------------------------------------------------

    for sample in samples:

        content.append(
            {
                "type": "input_text",

                "text": (
                    f"VIDEO SAMPLE FRAME "
                    f"{sample['index']} "
                    f"AT "
                    f"{sample['timestamp_sec']:.3f}s:"
                ),
            }
        )

        content.append(
            {
                "type": "input_image",

                "image_url":
                    image_to_data_url(
                        sample["path"]
                    ),

                "detail":
                    VISION_DETAIL,
            }
        )

    return content


# ---------------------------------------------------------
# CALL VISION MODEL
# ---------------------------------------------------------

def analyze_video_semantics(
    client: OpenAI,
    job: dict,
    scene: dict,
    samples: list[dict],
) -> VideoSemanticQCOutput:

    content = build_request_content(
        job,
        scene,
        samples,
    )

    response = client.responses.parse(
        model=VISION_MODEL,

        input=[
            {
                "role": "system",
                "content":
                    SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content":
                    content,
            },
        ],

        text_format=
            VideoSemanticQCOutput,
    )

    result = response.output_parsed

    if result is None:

        raise RuntimeError(
            "Vision model returned "
            "no parsed video QC result."
        )

    return result


# ---------------------------------------------------------
# DETERMINISTIC DECISION
# ---------------------------------------------------------

def evaluate_result(
    scene: dict,
    result: VideoSemanticQCOutput,
) -> tuple[
    bool,
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    if not result.motion_matches_prompt:

        errors.append(
            "Video motion does not sufficiently "
            "match motion_prompt."
        )

    if not result.temporal_progression_coherent:

        errors.append(
            "Video does not show coherent temporal progression."
        )

    if not result.source_frame_continuity_ok:

        errors.append(
            "Video drifts significantly from "
            "the approved source image."
        )

    if not result.anatomy_ok:

        errors.append(
            "Obvious anatomy or visual-generation "
            "defects were detected."
        )

    if result.morphing_or_shape_drift:

        errors.append(
            "Character/object morphing or shape drift "
            "was detected."
        )

    if result.unexpected_scene_cut:

        errors.append(
            "Unexpected scene cut or major visual "
            "discontinuity was detected."
        )

    if result.unwanted_text_or_logo:

        errors.append(
            "Unwanted text, logo, caption or watermark "
            "was detected."
        )

    if result.extra_main_characters:

        errors.append(
            "Unexpected or duplicated main character "
            "was detected."
        )

    # -----------------------------------------------------
    # Character IDs
    # -----------------------------------------------------

    expected_ids = set(
        scene.get(
            "characters",
            [],
        )
    )

    allowed_exit_ids = set(
        scene
        .get(
            "semantic_qc_policy",
            {},
        )
        .get(
            "allowed_exit_character_ids",
            [],
        )
        or []
    )

    actual_ids = {
        character.character_id
        for character
        in result.character_checks
    }

    if actual_ids != expected_ids:

        errors.append(
            f"Character QC IDs mismatch. "
            f"Expected {sorted(expected_ids)}, "
            f"got {sorted(actual_ids)}."
        )

    # -----------------------------------------------------
    # Character consistency
    # -----------------------------------------------------

    for character in result.character_checks:

        prefix = (
            f"{character.character_id}: "
        )

        if character.character_id not in expected_ids:
            continue

        if (
            character.max_visible_instances
            > 1
        ):

            errors.append(
                prefix
                + (
                    "duplicated main character detected "
                    f"({character.max_visible_instances} "
                    "simultaneous instances)."
                )
            )

        if not character.present_throughout:

            if (
                character.character_id
                in allowed_exit_ids
            ):

                warnings.append(
                    prefix
                    + "character leaves frame under "
                    "the approved scene-exit policy."
                )

            else:

                errors.append(
                    prefix
                    + "character is not consistently present."
                )

        if not character.identity_stable:

            errors.append(
                prefix
                + "identity drift detected."
            )

        if not character.appearance_stable:

            errors.append(
                prefix
                + "appearance changes during the shot."
            )

        if not character.clothing_stable:

            errors.append(
                prefix
                + "clothing/accessories change "
                "during the shot."
            )

        if (
            character.confidence
            < LOW_CONFIDENCE_WARNING
        ):

            warnings.append(
                prefix
                + f"low assessment confidence "
                f"({character.confidence:.2f})."
            )

    # Problematic samples by themselves do not automatically fail;
    # the semantic findings above determine failure.
    if result.problematic_sample_indices:

        warnings.append(
            "Potential problems observed around "
            f"sample(s): "
            f"{result.problematic_sample_indices}."
        )

    passed = (
        len(errors) == 0
    )

    return (
        passed,
        errors,
        warnings,
    )


# ---------------------------------------------------------
# STORE RESULT
# ---------------------------------------------------------

def apply_result(
    scene: dict,
    samples: list[dict],
    result: VideoSemanticQCOutput,
    passed: bool,
    errors: list[str],
    warnings: list[str],
) -> None:

    scene.setdefault(
        "video",
        {},
    )

    scene["video"][
        "semantic_qc"
    ] = {

        "status": (
            "passed"
            if passed
            else "failed"
        ),

        "checked_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "policy_version":
            QC_POLICY_VERSION,

        "raw_duration_sec":
            round(
                get_actual_duration(
                    scene
                ),
                3,
            ),

        "evaluation_duration_sec":
            round(
                get_evaluation_duration(
                    scene
                ),
                3,
            ),

        "model":
            VISION_MODEL,

        "detail":
            VISION_DETAIL,

        "frame_count":
            len(samples),

        "samples": [
            {
                "index":
                    sample["index"],

                "timestamp_sec":
                    sample["timestamp_sec"],
            }
            for sample in samples
        ],

        "motion_matches_prompt":
            result.motion_matches_prompt,

        "temporal_progression_coherent":
            result.temporal_progression_coherent,

        "source_frame_continuity_ok":
            result.source_frame_continuity_ok,

        "anatomy_ok":
            result.anatomy_ok,

        "morphing_or_shape_drift":
            result.morphing_or_shape_drift,

        "unexpected_scene_cut":
            result.unexpected_scene_cut,

        "unwanted_text_or_logo":
            result.unwanted_text_or_logo,

        "extra_main_characters":
            result.extra_main_characters,

        "characters": [
            character.model_dump()
            for character
            in result.character_checks
        ],

        "problematic_sample_indices":
            result.problematic_sample_indices,

        "overall_notes":
            result.overall_notes,

        "applied_policy":
            scene.get(
                "semantic_qc_policy",
                {},
            ),

        "errors":
            errors,

        "warnings":
            warnings,
    }


# ---------------------------------------------------------
# GLOBAL STATUS
# ---------------------------------------------------------

def all_video_semantic_qc_passed(
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

        status = (
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

        if status != "passed":
            return False

    return True


def any_video_semantic_qc_failed(
    job: dict,
) -> bool:

    scenes = job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
    )

    for scene in scenes:

        status = (
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

        if status == "failed":
            return True

    return False


# ---------------------------------------------------------
# CLEANUP
# ---------------------------------------------------------

def cleanup_frames(
    samples: list[dict],
) -> None:

    if not samples:
        return

    parent = samples[0][
        "path"
    ].parent

    shutil.rmtree(
        parent,
        ignore_errors=True,
    )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - VIDEO SEMANTIC QC v4")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # Environment
    # -----------------------------------------------------

    if not os.getenv(
        "OPENAI_API_KEY"
    ):

        print(
            "\nERROR: OPENAI_API_KEY is not set."
        )

        return 1

    if not shutil.which(
        "ffmpeg"
    ):

        print(
            "\nERROR: ffmpeg not found in PATH."
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
            "\nERROR: no scenes found."
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
        f"\nJob ID:       "
        f"{job.get('job_id')}"
    )

    print(
        f"Model:        "
        f"{VISION_MODEL}"
    )

    print(
        f"Detail:       "
        f"{VISION_DETAIL}"
    )

    print(
        f"Sample frames:"
        f"{FRAME_COUNT}"
    )

    print(
        f"Scenes:       "
        f"{len(selected_scenes)}"
    )

    client = OpenAI()

    passed_count = 0
    failed_count = 0

    # -----------------------------------------------------
    # Analyze scenes
    # -----------------------------------------------------

    for scene in selected_scenes:

        scene_id = (
            scene["scene_id"]
        )

        print(
            f"\nChecking scene {scene_id}..."
        )

        # -------------------------------------------------
        # Preconditions
        # -------------------------------------------------

        precondition_errors = (
            validate_preconditions(
                job,
                scene,
            )
        )

        if precondition_errors:

            failed_count += 1

            scene.setdefault(
                "video",
                {},
            )

            scene["video"][
                "semantic_qc"
            ] = {

                "status":
                    "failed",

                "checked_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "errors":
                    precondition_errors,

                "warnings":
                    [],
            }

            print(
                "  PRECONDITION FAILED"
            )

            for error in precondition_errors:

                print(
                    f"  [ERROR] {error}"
                )

            set_legacy_status_from_stage(
                job,
                "video_semantic_qc",
            )

            save_job(
                job
            )

            continue

        samples: list[dict] = []

        try:

            print(
                "  Extracting frames..."
            )

            samples = extract_frames(
                job,
                scene,
            )

            for sample in samples:

                print(
                    f"    #{sample['index']} "
                    f"{sample['timestamp_sec']:.3f}s"
                )

            print(
                "  Running vision analysis..."
            )

            result = (
                analyze_video_semantics(
                    client,
                    job,
                    scene,
                    samples,
                )
            )

            (
                passed,
                errors,
                warnings,
            ) = evaluate_result(
                scene,
                result,
            )

            apply_result(
                scene,
                samples,
                result,
                passed,
                errors,
                warnings,
            )

        except Exception as exc:

            failed_count += 1

            print(
                f"  ERROR: {exc}"
            )

            scene.setdefault(
                "video",
                {},
            )

            scene["video"][
                "semantic_qc"
            ] = {

                "status":
                    "failed",

                "checked_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "errors": [
                    str(exc)
                ],

                "warnings":
                    [],
            }

            set_legacy_status_from_stage(
                job,
                "video_semantic_qc",
            )

            save_job(
                job
            )

            if (
                samples
                and not args.keep_frames
            ):

                cleanup_frames(
                    samples
                )

            continue

        # -------------------------------------------------
        # Display result
        # -------------------------------------------------

        if passed:

            passed_count += 1

            print(
                "  PASS"
            )

        else:

            failed_count += 1

            print(
                "  FAIL"
            )

        print(
            f"  Motion match: "
            f"{result.motion_matches_prompt}"
        )

        print(
            f"  Temporal:     "
            f"{result.temporal_progression_coherent}"
        )

        print(
            f"  Source match: "
            f"{result.source_frame_continuity_ok}"
        )

        print(
            f"  Anatomy:      "
            f"{result.anatomy_ok}"
        )

        print(
            f"  Morphing:     "
            f"{result.morphing_or_shape_drift}"
        )

        print(
            f"  Scene cut:    "
            f"{result.unexpected_scene_cut}"
        )

        for character in result.character_checks:

            print(
                f"\n  {character.character_id}"
            )

            print(
                f"    present:    "
                f"{character.present_throughout}"
            )

            print(
                f"    instances:  "
                f"{character.max_visible_instances}"
            )

            print(
                f"    identity:   "
                f"{character.identity_stable}"
            )

            print(
                f"    appearance: "
                f"{character.appearance_stable}"
            )

            print(
                f"    clothing:   "
                f"{character.clothing_stable}"
            )

            print(
                f"    confidence: "
                f"{character.confidence:.2f}"
            )

        for error in errors:

            print(
                f"  [ERROR] {error}"
            )

        for warning in warnings:

            print(
                f"  [WARNING] {warning}"
            )

        print(
            f"  Notes: "
            f"{result.overall_notes}"
        )

        # -------------------------------------------------
        # Persist current stage state
        # -------------------------------------------------

        set_legacy_status_from_stage(
            job,
            "video_semantic_qc",
        )

        save_job(
            job
        )

        if not args.keep_frames:

            cleanup_frames(
                samples
            )

    # -----------------------------------------------------
    # Final global stage status
    # -----------------------------------------------------

    set_legacy_status_from_stage(
        job,
        "video_semantic_qc",
    )

    save_job(
        job
    )

    stage = (
        job["pipeline_status"]
        ["video_semantic_qc"]
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print(
        "\n" + "=" * 60
    )

    print(
        "VIDEO SEMANTIC QC COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nPassed this run: "
        f"{passed_count}"
    )

    print(
        f"Failed this run: "
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
        f"Failed overall: "
        f"{stage['failed']}"
    )

    print(
        f"Pending: "
        f"{stage['pending']}"
    )

    print(
        f"Job status: "
        f"{job.get('status')}"
    )

    if failed_count > 0:

        return 1

    return 0

if __name__ == "__main__":

    sys.exit(
        main()
    )