from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import argparse
import base64
import json
import os
import sys

from openai import OpenAI
from pydantic import BaseModel, Field

from validator import load_json


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

VISION_MODEL = os.getenv(
    "OPENAI_VISION_MODEL",
    "gpt-5.6-luna",
)

VISION_DETAIL = os.getenv(
    "OPENAI_VISION_DETAIL",
    "high",
)

LOW_CONFIDENCE_WARNING = float(
    os.getenv(
        "IMAGE_SEMANTIC_QC_LOW_CONFIDENCE",
        "0.70",
    )
)


# ---------------------------------------------------------
# STRUCTURED OUTPUT
# ---------------------------------------------------------

class CharacterQC(BaseModel):

    character_id: str

    present: bool

    identity_match: bool

    appearance_match: bool

    clothing_match: bool

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    notes: str


class SemanticQCOutput(BaseModel):

    scene_matches_prompt: bool

    composition_ok: bool

    anatomy_ok: bool

    unwanted_text_or_logo: bool

    extra_main_characters: bool

    character_checks: list[CharacterQC]

    overall_notes: str


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

SYSTEM_PROMPT = """
You are the SEMANTIC IMAGE QUALITY CONTROL worker inside an
automated short-form video production system.

You will receive:

1. One generated SCENE IMAGE.
2. Zero or more CHARACTER REFERENCE images.
3. A textual description of the intended scene.
4. Character IDs and visual identity descriptions.

Your job is NOT to creatively reinterpret the image.

Your job is to inspect whether the generated scene is suitable
for continuing into expensive image-to-video generation.

Evaluate the following:

SCENE MATCH
- Does the image substantially depict the intended scene?
- Are the important subjects, environment and situation correct?

COMPOSITION
- Is the scene clearly readable in vertical short-form format?
- Are important subjects visible?
- Is the composition usable for animation?

ANATOMY / VISUAL DEFECTS
- Look for obvious malformed anatomy.
- Extra limbs.
- Merged bodies.
- Severely distorted faces.
- Impossible body structure.
- Broken or duplicated major objects.
- Visually obvious AI-generation defects.

CHARACTER CONSISTENCY
For every expected character:
- Is the character actually present?
- Does the character match the supplied reference identity?
- Are important physical traits preserved?
- Is defining clothing/accessory information preserved?

Do not require pixel-perfect identity.
Judge whether a normal viewer would reasonably perceive the
character as the same established character.

TEXT / LOGOS
- The scene should not contain generated captions, subtitles,
  watermarks, logos or random readable text unless explicitly
  required by the intended scene.
- Text overlays are added later by another pipeline stage.

EXTRA CHARACTERS
- Background extras may be acceptable when appropriate.
- Flag extra_main_characters only when the model has invented
  a prominent unintended character or duplicated a main character.

CONFIDENCE
- confidence is your confidence in the character consistency
  assessment from 0.0 to 1.0.
- Do not use confidence as a quality score.

Be conservative about major failures, but do not fail images for
minor harmless stylistic differences.

Return only the required structured result.
""".strip()


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Video Factory semantic image quality control"
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Check only one scene. "
            "Example: --scene 2"
        ),
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
        ".gif": "image/gif",
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

    image = scene.get(
        "image",
        {},
    )

    # -----------------------------------------------------
    # Technical QC
    # -----------------------------------------------------

    technical_qc = image.get(
        "qc",
        {},
    )

    if (
        technical_qc.get("status")
        != "passed"
    ):

        errors.append(
            f"Scene {scene_id}: technical image QC "
            "has not passed."
        )

    # -----------------------------------------------------
    # Scene image
    # -----------------------------------------------------

    image_file = image.get(
        "file"
    )

    if not image_file:

        errors.append(
            f"Scene {scene_id}: image.file is missing."
        )

    else:

        image_path = (
            PROJECT_ROOT
            / image_file
        )

        if not image_path.exists():

            errors.append(
                f"Scene {scene_id}: scene image "
                f"does not exist: {image_file}"
            )

    # -----------------------------------------------------
    # Character references
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

            errors.append(
                f"Scene {scene_id}: unknown character "
                f"{character_id}."
            )

            continue

        reference = character.get(
            "reference",
            {},
        )

        reference_file = reference.get(
            "image_file"
        )

        if not reference_file:

            errors.append(
                f"Scene {scene_id}: character "
                f"{character_id} has no reference image."
            )

            continue

        reference_path = (
            PROJECT_ROOT
            / reference_file
        )

        if not reference_path.exists():

            errors.append(
                f"Scene {scene_id}: reference image "
                f"does not exist for {character_id}: "
                f"{reference_file}"
            )

    return errors


# ---------------------------------------------------------
# BUILD TEXT CONTEXT
# ---------------------------------------------------------

def build_text_context(
    job: dict,
    scene: dict,
) -> str:

    character_descriptions = []

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

        character_descriptions.append(
            {
                "character_id":
                    character_id,

                "name":
                    character.get("name"),

                "description":
                    character.get("description"),

                "visual_signature":
                    reference.get(
                        "visual_signature"
                    ),
            }
        )

    context = {
        "scene_id":
            scene["scene_id"],

        "intended_scene_prompt":
            scene.get(
                "image_prompt",
                ""
            ),

        "continuity_notes":
            scene.get(
                "continuity_notes",
                ""
            ),

        "expected_characters":
            character_descriptions,

        "global_style":
            job.get(
                "style",
                {},
            ),

        "important_note":
            (
                "The first supplied image is the generated "
                "scene being inspected. Images after that are "
                "character references in the same order as "
                "expected_characters."
            ),
    }

    return json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------
# BUILD MULTIMODAL CONTENT
# ---------------------------------------------------------

def build_request_content(
    job: dict,
    scene: dict,
) -> list[dict]:

    image_file = scene[
        "image"
    ][
        "file"
    ]

    scene_path = (
        PROJECT_ROOT
        / image_file
    )

    content: list[dict] = []

    # -----------------------------------------------------
    # Text instructions/context
    # -----------------------------------------------------

    content.append(
        {
            "type": "input_text",
            "text": (
                "Inspect this generated scene against the "
                "provided specification and character "
                "references.\n\n"
                + build_text_context(
                    job,
                    scene,
                )
            ),
        }
    )

    # -----------------------------------------------------
    # Scene image
    # -----------------------------------------------------

    content.append(
        {
            "type": "input_text",
            "text": (
                "GENERATED SCENE IMAGE TO INSPECT:"
            ),
        }
    )

    content.append(
        {
            "type": "input_image",
            "image_url":
                image_to_data_url(
                    scene_path
                ),
            "detail":
                VISION_DETAIL,
        }
    )

    # -----------------------------------------------------
    # Character references
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
                    f"REFERENCE IMAGE FOR "
                    f"{character_id} "
                    f"({character.get('name', '')}):"
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

    return content


# ---------------------------------------------------------
# CALL VISION MODEL
# ---------------------------------------------------------

def analyze_scene_semantics(
    client: OpenAI,
    job: dict,
    scene: dict,
) -> SemanticQCOutput:

    content = build_request_content(
        job,
        scene,
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

        text_format=SemanticQCOutput,
    )

    result = response.output_parsed

    if result is None:

        raise RuntimeError(
            "Vision model returned no parsed QC result."
        )

    return result


# ---------------------------------------------------------
# DETERMINISTIC EVALUATION OF AI RESULT
# ---------------------------------------------------------

def evaluate_result(
    scene: dict,
    result: SemanticQCOutput,
) -> tuple[
    bool,
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    scene_id = scene[
        "scene_id"
    ]

    # -----------------------------------------------------
    # Scene-level checks
    # -----------------------------------------------------

    if not result.scene_matches_prompt:

        errors.append(
            "Generated image does not sufficiently "
            "match the intended scene."
        )

    if not result.composition_ok:

        errors.append(
            "Composition is not suitable for the "
            "short-form scene."
        )

    if not result.anatomy_ok:

        errors.append(
            "Obvious anatomy or AI visual defects "
            "were detected."
        )

    if result.unwanted_text_or_logo:

        errors.append(
            "Unwanted text, logo, watermark or "
            "caption was detected."
        )

    if result.extra_main_characters:

        errors.append(
            "Unexpected or duplicated main character "
            "was detected."
        )

    # -----------------------------------------------------
    # Expected character IDs
    # -----------------------------------------------------

    expected_ids = set(
        scene.get(
            "characters",
            [],
        )
    )

    actual_ids = {
        check.character_id
        for check in result.character_checks
    }

    if actual_ids != expected_ids:

        errors.append(
            f"Character QC IDs do not match. "
            f"Expected {sorted(expected_ids)}, "
            f"got {sorted(actual_ids)}."
        )

    # -----------------------------------------------------
    # Character-level checks
    # -----------------------------------------------------

    for check in result.character_checks:

        prefix = (
            f"{check.character_id}: "
        )

        if check.character_id not in expected_ids:

            continue

        if not check.present:

            errors.append(
                prefix
                + "expected character is missing."
            )

        if not check.identity_match:

            errors.append(
                prefix
                + "character identity does not match "
                "the reference."
            )

        if not check.appearance_match:

            errors.append(
                prefix
                + "important appearance features "
                "do not match the reference."
            )

        if not check.clothing_match:

            errors.append(
                prefix
                + "defining clothing/accessories "
                "do not match the reference."
            )

        if (
            check.confidence
            < LOW_CONFIDENCE_WARNING
        ):

            warnings.append(
                prefix
                + f"low QC confidence "
                f"({check.confidence:.2f})."
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
# STORE QC RESULT
# ---------------------------------------------------------

def apply_semantic_qc_result(
    scene: dict,
    result: SemanticQCOutput,
    passed: bool,
    errors: list[str],
    warnings: list[str],
) -> None:

    image = scene.setdefault(
        "image",
        {},
    )

    image[
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

        "model":
            VISION_MODEL,

        "detail":
            VISION_DETAIL,

        "scene_matches_prompt":
            result.scene_matches_prompt,

        "composition_ok":
            result.composition_ok,

        "anatomy_ok":
            result.anatomy_ok,

        "unwanted_text_or_logo":
            result.unwanted_text_or_logo,

        "extra_main_characters":
            result.extra_main_characters,

        "characters": [
            character.model_dump()
            for character
            in result.character_checks
        ],

        "overall_notes":
            result.overall_notes,

        "errors":
            errors,

        "warnings":
            warnings,
    }


# ---------------------------------------------------------
# GLOBAL STATE
# ---------------------------------------------------------

def all_semantic_qc_passed(
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
            scene.get(
                "image",
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


def any_semantic_qc_failed(
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
            scene.get(
                "image",
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
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SEMANTIC IMAGE QC v1")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # Config
    # -----------------------------------------------------

    if not os.getenv(
        "OPENAI_API_KEY"
    ):

        print(
            "\nERROR: OPENAI_API_KEY "
            "environment variable is not set."
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

    scenes = job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
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
        f"\nJob ID:  {job.get('job_id')}"
    )

    print(
        f"Model:   {VISION_MODEL}"
    )

    print(
        f"Detail:  {VISION_DETAIL}"
    )

    print(
        f"Scenes:  {len(selected_scenes)}"
    )

    # -----------------------------------------------------
    # Client
    # -----------------------------------------------------

    client = OpenAI()

    passed_count = 0
    failed_count = 0

    # -----------------------------------------------------
    # Analyze
    # -----------------------------------------------------

    for scene in selected_scenes:

        scene_id = scene[
            "scene_id"
        ]

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

            print(
                "  PRECONDITION FAILED"
            )

            for error in precondition_errors:

                print(
                    f"  [ERROR] {error}"
                )

            continue

        # -------------------------------------------------
        # AI vision
        # -------------------------------------------------

        try:

            result = analyze_scene_semantics(
                client=client,
                job=job,
                scene=scene,
            )

        except Exception as exc:

            print(
                f"\n  ERROR during vision QC:\n"
                f"  {exc}"
            )

            save_job(
                job
            )

            return 1

        # -------------------------------------------------
        # Deterministic evaluation
        # -------------------------------------------------

        (
            passed,
            errors,
            warnings,
        ) = evaluate_result(
            scene,
            result,
        )

        apply_semantic_qc_result(
            scene=scene,
            result=result,
            passed=passed,
            errors=errors,
            warnings=warnings,
        )

        # -------------------------------------------------
        # Output
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
            f"  Scene match:  "
            f"{result.scene_matches_prompt}"
        )

        print(
            f"  Composition:  "
            f"{result.composition_ok}"
        )

        print(
            f"  Anatomy:      "
            f"{result.anatomy_ok}"
        )

        print(
            f"  Bad text:     "
            f"{result.unwanted_text_or_logo}"
        )

        print(
            f"  Extra chars:  "
            f"{result.extra_main_characters}"
        )

        for character in result.character_checks:

            print(
                f"\n  {character.character_id}"
            )

            print(
                f"    present:     "
                f"{character.present}"
            )

            print(
                f"    identity:    "
                f"{character.identity_match}"
            )

            print(
                f"    appearance:  "
                f"{character.appearance_match}"
            )

            print(
                f"    clothing:    "
                f"{character.clothing_match}"
            )

            print(
                f"    confidence:  "
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

        # checkpoint
        save_job(
            job
        )

    # -----------------------------------------------------
    # Job status
    # -----------------------------------------------------

    if all_semantic_qc_passed(
        job
    ):

        job["status"] = (
            "scene_images_semantic_qc_passed"
        )

    elif any_semantic_qc_failed(
        job
    ):

        job["status"] = (
            "scene_images_semantic_qc_failed"
        )

    save_job(
        job
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print(
        "\n" + "=" * 60
    )

    print(
        "SEMANTIC IMAGE QC COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nPassed: {passed_count}"
    )

    print(
        f"Failed: {failed_count}"
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