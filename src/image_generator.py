from __future__ import annotations

from pathlib import Path
import argparse
import base64
import copy
import json
import os
import sys

from openai import OpenAI

from validator import load_json

from contextlib import ExitStack


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

IMAGE_MODEL = os.getenv(
    "OPENAI_IMAGE_MODEL",
    "gpt-image-2.5-flare",
)

IMAGE_QUALITY = os.getenv(
    "OPENAI_IMAGE_QUALITY",
    "low",
)

SCENE_IMAGE_SIZE = os.getenv(
    "OPENAI_SCENE_IMAGE_SIZE",
    "1008x1792",
)

CHARACTER_REFERENCE_SIZE = os.getenv(
    "OPENAI_CHARACTER_REFERENCE_SIZE",
    "1024x1536",
)


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Video Factory image generator"
    )

    parser.add_argument(
        "--mode",
        choices=[
            "character_reference",
            "scene_image",
        ],
        default="character_reference",
        help="Image generation mode",
    )

    parser.add_argument(
        "--character",
        type=str,
        default=None,
        help=(
            "Generate only one character ID, "
            "for example char-002"
        ),
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Generate only one scene ID, "
            "for example --scene 3"
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate images even if they already exist",
    )

    return parser.parse_args()


# ---------------------------------------------------------
# SAVE JOB ATOMICALLY
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

    temp_file.replace(JOB_FILE)


# ---------------------------------------------------------
# CHARACTER LOOKUP
# ---------------------------------------------------------

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

def get_scene_output_path(
    job: dict,
    scene: dict,
) -> Path:

    job_id = job["job_id"]
    scene_id = scene["scene_id"]

    return (
        PROJECT_ROOT
        / "output"
        / job_id
        / "images"
        / f"scene_{scene_id:03d}.png"
    )

def get_scene_character_references(
    job: dict,
    scene: dict,
) -> list[tuple[dict, Path]]:

    result = []

    character_ids = scene.get(
        "characters",
        [],
    )

    for character_id in character_ids:

        character = find_character(
            job,
            character_id,
        )

        if character is None:

            raise RuntimeError(
                f"Scene {scene['scene_id']}: "
                f"character '{character_id}' not found."
            )

        reference = character.get(
            "reference",
            {},
        )

        image_file = reference.get(
            "image_file"
        )

        if not image_file:

            raise RuntimeError(
                f"Scene {scene['scene_id']}: "
                f"character '{character_id}' has no "
                f"reference image."
            )

        image_path = (
            PROJECT_ROOT
            / image_file
        )

        if not image_path.exists():

            raise RuntimeError(
                f"Scene {scene['scene_id']}: "
                f"reference image does not exist: "
                f"{image_path}"
            )

        result.append(
            (
                character,
                image_path,
            )
        )

    return result

def build_scene_prompt(
    job: dict,
    scene: dict,
    character_references: list[tuple[dict, Path]],
) -> str:

    image_prompt = scene.get(
        "image_prompt",
        "",
    )

    negative_prompt = scene.get(
        "negative_prompt",
        "",
    )

    continuity_notes = scene.get(
        "continuity_notes",
        "",
    )

    global_prompt = job.get(
        "visuals",
        {},
    ).get(
        "global_prompt",
        "",
    )

    style = job.get(
        "style",
        {},
    )

    # -----------------------------------------------------
    # Reference mapping
    # -----------------------------------------------------

    reference_description = []

    for index, (
        character,
        _,
    ) in enumerate(
        character_references,
        start=1,
    ):

        reference = character.get(
            "reference",
            {},
        )

        signature = reference.get(
            "visual_signature",
            "",
        )

        reference_description.append(
            f"""
REFERENCE IMAGE {index}:
Character ID: {character["character_id"]}
Name: {character.get("name", "")}
Visual identity: {signature}

Preserve this character's visual identity closely.
""".strip()
        )

    reference_text = "\n\n".join(
        reference_description
    )

    style_text = json.dumps(
        style,
        ensure_ascii=False,
    )

    prompt = f"""
Create a single vertical 9:16 frame for a short-form video.

SCENE ID:
{scene["scene_id"]}

SCENE DESCRIPTION:
{image_prompt}

GLOBAL VISUAL STYLE:
{global_prompt}

JOB STYLE:
{style_text}

CHARACTER REFERENCES:

{reference_text}

CONTINUITY REQUIREMENTS:
{continuity_notes}

IMPORTANT CHARACTER RULES:

- The supplied reference images define the identity and appearance
  of the characters.
- Preserve facial features, species, fur, hair, clothing, colors,
  accessories and overall identity.
- Do not merge character identities.
- Do not swap clothing between characters.
- Do not invent additional main characters.
- Characters must remain recognizable as the same characters
  shown in their reference images.

COMPOSITION RULES:

- Vertical 9:16 composition.
- Designed for viewing on a mobile phone.
- Main subjects must be immediately readable.
- Keep important subjects away from the extreme top and bottom,
  where social media UI may cover them.
- Use one clearly readable visual idea.
- Do not generate subtitles or captions.
- Do not generate watermarks.
- Do not generate logos unless explicitly required.
- Do not render the later text_overlay into the image.

AVOID:

{negative_prompt}

Generate only the scene image.
""".strip()

    return prompt

# ---------------------------------------------------------
# BUILD FINAL CHARACTER PROMPT
# ---------------------------------------------------------

def build_character_prompt(
    character: dict,
    job: dict,
) -> str:

    reference = character["reference"]

    positive_prompt = reference["prompt"]
    negative_prompt = reference.get(
        "negative_prompt",
        "",
    )

    visual_signature = reference.get(
        "visual_signature",
        "",
    )

    job_style = job.get(
        "style",
        {},
    )

    style_text = json.dumps(
        job_style,
        ensure_ascii=False,
    )

    prompt = f"""
Create a canonical reusable character reference image.

CHARACTER ID:
{character["character_id"]}

CHARACTER NAME:
{character.get("name", "")}

VISUAL SIGNATURE:
{visual_signature}

REFERENCE DESCRIPTION:
{positive_prompt}

GLOBAL VISUAL STYLE:
{style_text}

REFERENCE IMAGE REQUIREMENTS:

- Show exactly one character.
- Full body or near-full-body view.
- Three-quarter standing pose.
- Neutral simple background.
- Clean studio-style lighting.
- Character clearly separated from the background.
- Entire identity-defining clothing and accessories visible.
- Neutral or characteristic resting facial expression.
- No dramatic action.
- No other characters.
- No captions.
- No subtitles.
- No logos.
- No watermark.
- No UI elements.
- This image will be reused as a visual identity reference
  in later AI-generated scenes.

AVOID:

{negative_prompt}

The result must prioritize clear, reproducible character identity
over artistic complexity.
""".strip()

    return prompt


# ---------------------------------------------------------
# IMAGE API
# ---------------------------------------------------------

def generate_image(
    client: OpenAI,
    prompt: str,
    output_file: Path,
    size: str,
) -> None:

    result = client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size=size,
        quality=IMAGE_QUALITY,
        output_format="png",
        background="opaque",
        n=1,
    )

    if not result.data:
        raise RuntimeError(
            "Image API returned no image data."
        )

    image_base64 = result.data[0].b64_json

    if not image_base64:
        raise RuntimeError(
            "Image API returned empty base64 image data."
        )

    image_bytes = base64.b64decode(
        image_base64
    )

    if not image_bytes:
        raise RuntimeError(
            "Decoded image contains no data."
        )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = output_file.with_suffix(
        output_file.suffix + ".tmp"
    )

    with temp_file.open(
        "wb"
    ) as file:

        file.write(
            image_bytes
        )

    temp_file.replace(
        output_file
    )


# ---------------------------------------------------------
# OUTPUT PATH
# ---------------------------------------------------------

def get_character_output_path(
    job: dict,
    character: dict,
) -> Path:

    job_id = job["job_id"]

    character_id = character[
        "character_id"
    ]

    return (
        PROJECT_ROOT
        / "output"
        / job_id
        / "characters"
        / character_id
        / "reference.png"
    )


# ---------------------------------------------------------
# GENERATE ONE CHARACTER
# ---------------------------------------------------------

def generate_character_reference(
    client: OpenAI,
    job: dict,
    character: dict,
    force: bool,
) -> bool:

    character_id = character[
        "character_id"
    ]

    reference = character.get(
        "reference"
    )

    if not reference:

        raise RuntimeError(
            f"{character_id}: no reference section. "
            "Run character_reference_generator.py first."
        )

    if not reference.get(
        "prompt"
    ):

        raise RuntimeError(
            f"{character_id}: reference prompt is missing."
        )

    output_file = get_character_output_path(
        job,
        character,
    )

    # -----------------------------------------------------
    # Skip existing image
    # -----------------------------------------------------

    if (
        output_file.exists()
        and not force
    ):

        print(
            f"  SKIP: {output_file} already exists."
        )

        reference["status"] = "generated"

        reference["image_file"] = str(
            output_file.relative_to(
                PROJECT_ROOT
            )
        ).replace(
            "\\",
            "/",
        )

        return False

    # -----------------------------------------------------
    # Build prompt
    # -----------------------------------------------------

    prompt = build_character_prompt(
        character,
        job,
    )

    print(
        f"\nGenerating {character_id} "
        f"- {character.get('name', '')}"
    )

    print(
        f"  Model:   {IMAGE_MODEL}"
    )

    print(
        f"  Quality: {IMAGE_QUALITY}"
    )

    print(
        f"  Size:    {CHARACTER_REFERENCE_SIZE}"
    )

    # -----------------------------------------------------
    # Generate
    # -----------------------------------------------------

    generate_image(
        client=client,
        prompt=prompt,
        output_file=output_file,
        size=CHARACTER_REFERENCE_SIZE,
    )

    # -----------------------------------------------------
    # Validate filesystem result
    # -----------------------------------------------------

    if not output_file.exists():

        raise RuntimeError(
            f"{character_id}: generated image file "
            "does not exist."
        )

    file_size = output_file.stat().st_size

    if file_size == 0:

        raise RuntimeError(
            f"{character_id}: generated image is empty."
        )

    # -----------------------------------------------------
    # Update VideoJob
    # -----------------------------------------------------

    relative_path = str(
        output_file.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    reference["status"] = "generated"
    reference["image_file"] = relative_path
    reference["model"] = IMAGE_MODEL
    reference["quality"] = IMAGE_QUALITY
    reference["size"] = CHARACTER_REFERENCE_SIZE

    print(
        f"  Saved:   {relative_path}"
    )

    print(
        f"  Bytes:   {file_size:,}"
    )

    return True


# ---------------------------------------------------------
# CHECK OVERALL STATUS
# ---------------------------------------------------------

def all_character_references_generated(
    job: dict,
) -> bool:

    characters = job.get(
        "characters",
        [],
    )

    if not characters:
        return False

    for character in characters:

        reference = character.get(
            "reference",
            {},
        )

        if (
            reference.get("status")
            != "generated"
        ):
            return False

        image_file = reference.get(
            "image_file"
        )

        if not image_file:
            return False

        absolute_path = (
            PROJECT_ROOT
            / image_file
        )

        if not absolute_path.exists():
            return False

    return True


# ---------------------------------------------------------
# CHARACTER REFERENCE MODE
# ---------------------------------------------------------

def run_character_reference_mode(
    client: OpenAI,
    job: dict,
    selected_character: str | None,
    force: bool,
) -> int:

    characters = job.get(
        "characters",
        [],
    )

    if not characters:

        print(
            "\nERROR: video_job.json contains "
            "no characters."
        )

        return 1

    # -----------------------------------------------------
    # Select characters
    # -----------------------------------------------------

    if selected_character:

        character = find_character(
            job,
            selected_character,
        )

        if character is None:

            print(
                f"\nERROR: character "
                f"'{selected_character}' not found."
            )

            return 1

        selected = [
            character
        ]

    else:

        selected = characters

    # -----------------------------------------------------
    # Generate
    # -----------------------------------------------------

    generated_count = 0

    for character in selected:

        try:

            generated = (
                generate_character_reference(
                    client=client,
                    job=job,
                    character=character,
                    force=force,
                )
            )

            if generated:
                generated_count += 1

            # Save after every successful character.
            # If character 2 fails, character 1 is not lost.
            save_job(
                job
            )

        except Exception as exc:

            character_id = character.get(
                "character_id",
                "?",
            )

            print(
                f"\nERROR generating "
                f"{character_id}:\n{exc}"
            )

            save_job(
                job
            )

            return 1

    # -----------------------------------------------------
    # Overall status
    # -----------------------------------------------------

    if all_character_references_generated(
        job
    ):

        job["status"] = (
            "character_references_generated"
        )

    save_job(
        job
    )

    print(
        "\nCHARACTER IMAGE GENERATION COMPLETE"
    )

    print(
        f"\nNew images generated: "
        f"{generated_count}"
    )

    print(
        f"Job status: "
        f"{job.get('status')}"
    )

    return 0

def generate_scene_image_with_references(
    client: OpenAI,
    prompt: str,
    reference_paths: list[Path],
    output_file: Path,
) -> None:

    with ExitStack() as stack:

        image_files = [
            stack.enter_context(
                path.open("rb")
            )
            for path in reference_paths
        ]

        result = client.images.edit(
            model=IMAGE_MODEL,
            image=image_files,
            prompt=prompt,
            size=SCENE_IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            output_format="png",
        )

    if not result.data:

        raise RuntimeError(
            "Image API returned no image data."
        )

    image_base64 = result.data[0].b64_json

    if not image_base64:

        raise RuntimeError(
            "Image API returned empty base64 image data."
        )

    image_bytes = base64.b64decode(
        image_base64
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = output_file.with_suffix(
        output_file.suffix + ".tmp"
    )

    with temp_file.open(
        "wb"
    ) as file:

        file.write(
            image_bytes
        )

    temp_file.replace(
        output_file
    )

def generate_scene_image(
    client: OpenAI,
    job: dict,
    scene: dict,
    force: bool,
) -> bool:

    scene_id = scene["scene_id"]

    output_file = get_scene_output_path(
        job,
        scene,
    )

    # -----------------------------------------------------
    # Existing image
    # -----------------------------------------------------

    if (
        output_file.exists()
        and not force
    ):

        print(
            f"  SKIP: Scene {scene_id} already exists."
        )

        scene.setdefault(
            "image",
            {},
        )

        scene["image"]["status"] = "generated"

        scene["image"]["file"] = str(
            output_file.relative_to(
                PROJECT_ROOT
            )
        ).replace(
            "\\",
            "/",
        )

        return False

    # -----------------------------------------------------
    # Character references
    # -----------------------------------------------------

    character_references = (
        get_scene_character_references(
            job,
            scene,
        )
    )

    prompt = build_scene_prompt(
        job,
        scene,
        character_references,
    )

    print(
        f"\nGenerating scene {scene_id}"
    )

    print(
        f"  Characters: "
        f"{len(character_references)}"
    )

    print(
        f"  Model:      {IMAGE_MODEL}"
    )

    print(
        f"  Quality:    {IMAGE_QUALITY}"
    )

    print(
        f"  Size:       {SCENE_IMAGE_SIZE}"
    )

    # -----------------------------------------------------
    # Generate
    # -----------------------------------------------------

    if character_references:

        reference_paths = [
            path
            for _, path
            in character_references
        ]

        generate_scene_image_with_references(
            client=client,
            prompt=prompt,
            reference_paths=reference_paths,
            output_file=output_file,
        )

    else:

        generate_image(
            client=client,
            prompt=prompt,
            output_file=output_file,
            size=SCENE_IMAGE_SIZE,
        )

    # -----------------------------------------------------
    # File verification
    # -----------------------------------------------------

    if not output_file.exists():

        raise RuntimeError(
            f"Scene {scene_id}: generated file "
            "does not exist."
        )

    file_size = output_file.stat().st_size

    if file_size == 0:

        raise RuntimeError(
            f"Scene {scene_id}: generated image "
            "is empty."
        )

    relative_path = str(
        output_file.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    # -----------------------------------------------------
    # Job state
    # -----------------------------------------------------

    scene["image"] = {
        "status": "generated",
        "file": relative_path,
        "model": IMAGE_MODEL,
        "quality": IMAGE_QUALITY,
        "size": SCENE_IMAGE_SIZE,

        "reference_images": [
            str(
                path.relative_to(
                    PROJECT_ROOT
                )
            ).replace(
                "\\",
                "/",
            )
            for _, path
            in character_references
        ],
    }

    print(
        f"  Saved:      {relative_path}"
    )

    print(
        f"  Bytes:      {file_size:,}"
    )

    return True

def all_scene_images_generated(
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

        image = scene.get(
            "image",
            {},
        )

        if image.get(
            "status"
        ) != "generated":

            return False

        image_file = image.get(
            "file"
        )

        if not image_file:
            return False

        path = (
            PROJECT_ROOT
            / image_file
        )

        if not path.exists():
            return False

    return True

def run_scene_image_mode(
    client: OpenAI,
    job: dict,
    selected_scene: int | None,
    force: bool,
) -> int:

    scenes = job.get(
        "visuals",
        {},
    ).get(
        "scenes",
        [],
    )

    if not scenes:

        print(
            "\nERROR: no visual scene prompts found."
        )

        print(
            "Run visual_prompt_generator.py first."
        )

        return 1

    # -----------------------------------------------------
    # Select scenes
    # -----------------------------------------------------

    if selected_scene is not None:

        scene = find_scene(
            job,
            selected_scene,
        )

        if scene is None:

            print(
                f"\nERROR: scene "
                f"{selected_scene} not found."
            )

            return 1

        selected = [
            scene
        ]

    else:

        selected = scenes

    generated_count = 0

    # -----------------------------------------------------
    # Generate
    # -----------------------------------------------------

    for scene in selected:

        try:

            generated = generate_scene_image(
                client=client,
                job=job,
                scene=scene,
                force=force,
            )

            if generated:
                generated_count += 1

            # checkpoint after every scene
            save_job(
                job
            )

        except Exception as exc:

            print(
                f"\nERROR generating "
                f"scene {scene.get('scene_id')}:\n"
                f"{exc}"
            )

            save_job(
                job
            )

            return 1

    # -----------------------------------------------------
    # Overall state
    # -----------------------------------------------------

    if all_scene_images_generated(
        job
    ):

        job["status"] = (
            "scene_images_generated"
        )

    save_job(
        job
    )

    print(
        "\nSCENE IMAGE GENERATION COMPLETE"
    )

    print(
        f"\nNew images generated: "
        f"{generated_count}"
    )

    print(
        f"Job status: "
        f"{job.get('status')}"
    )

    return 0

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - IMAGE GENERATOR v1")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # API KEY
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
    # LOAD JOB
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

    print(
        f"\nJob ID:  {job.get('job_id')}"
    )

    print(
        f"Mode:    {args.mode}"
    )

    print(
        f"Model:   {IMAGE_MODEL}"
    )

    print(
        f"Quality: {IMAGE_QUALITY}"
    )

    # -----------------------------------------------------
    # CLIENT
    # -----------------------------------------------------

    client = OpenAI()

    # -----------------------------------------------------
    # MODES
    # -----------------------------------------------------

    if (
        args.mode
        == "character_reference"
    ):

        return run_character_reference_mode(
            client=client,
            job=job,
            selected_character=args.character,
            force=args.force,
        )

    if (
        args.mode
        == "scene_image"
    ):

        return run_scene_image_mode(
            client=client,
            job=job,
            selected_scene=args.scene,
            force=args.force,
        )

    print(
        f"\nERROR: Unsupported mode: "
        f"{args.mode}"
    )

    return 1


if __name__ == "__main__":
    sys.exit(
        main()
    )