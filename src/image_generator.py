from __future__ import annotations

from visual_styles import style_instruction
from visual_supervisor import require_approval, contract_text, reference_text

from pathlib import Path
import argparse
import base64
import copy
import json
import os
import hashlib
import shutil
from datetime import datetime, timezone
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

        if character.get("library_asset"):
            from character_library import verify_locked
            verify_locked(character, PROJECT_ROOT)

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
    *, repair: bool = False,
) -> str:

    approved = contract_text(job, scene)
    mapping = '\n'.join(f"Reference {i}: {c['character_id']} ({c.get('name', '')})"
                        for i, (c, _) in enumerate(character_references, 2 if repair else 1))
    feedback = repair_metadata(scene).get('semantic_qc', {})
    correction = ''
    if feedback.get('status') == 'failed':
        correction = ('\nPrevious QC observations (repair only deviations from the approved '
                      'contract; never add new requirements):\n' +
                      str(feedback.get('overall_notes', ''))[:3000])
    action = ('Edit IMAGE 1, the failed scene image. Correct ONLY the deviations described '
              'by QC against the approved contract. Preserve the composition, lighting, '
              'identities and all already-correct objects. Remaining images are identity '
              'references, NOT edit targets. Do not recreate the whole scene from them.\n'
              if repair else '')
    return (action + 'Generate one scene image using this approved contract. Reference images '
            'define identity, not framing.\n' + approved + '\n' + mapping +
            '\n' + style_instruction(job) + correction)


# ---------------------------------------------------------
# BUILD FINAL CHARACTER PROMPT
# ---------------------------------------------------------

def build_character_prompt(
    character: dict,
    job: dict,
) -> str:

    return reference_text(job, character) + '\n' + style_instruction(job)


# ---------------------------------------------------------
# IMAGE API
# ---------------------------------------------------------

def generate_image(
    client: OpenAI,
    prompt: str,
    output_file: Path,
    size: str,
    *, job: dict,
) -> None:

    require_approval(job)
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

    require_approval(job)
    if character.get("library_asset"):
        from character_library import verify_locked
        verify_locked(character, PROJECT_ROOT)
        if force:
            raise ValueError("Cannot force-regenerate a locked library character; create a new variant instead.")
        character['reference']['supervisor_hash'] = job['visual_supervisor']['plan_hash']
        print(f"  SKIP: immutable library reference {character['library_asset']['asset_id']}")
        return False

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
        and reference.get("supervisor_hash") == job["visual_supervisor"]["plan_hash"]
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
        job=job,
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

    reference["supervisor_hash"] = job["visual_supervisor"]["plan_hash"]
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
    *, job: dict, repair_source: Path | None = None,
) -> None:

    require_approval(job)
    input_paths = ([repair_source] if repair_source is not None else []) + reference_paths
    with ExitStack() as stack:

        image_files = [
            stack.enter_context(
                path.open("rb")
            )
            for path in input_paths
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

    if not image_bytes:
        raise RuntimeError("Image edit returned empty image data.")

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

def repair_metadata(scene):
    current = scene.get('image', {})
    if current:
        return current if current.get('semantic_qc', {}).get('status') == 'failed' else {}
    return scene.get('image_repair_source', {})


def archive_repair_source(scene, output_file, prompt):
    metadata = repair_metadata(scene)
    if not metadata:
        return None, None
    if metadata.get('qc', {}).get('status') != 'passed':
        return None, None  # corrupt/technically invalid images need a fresh generation
    name = metadata.get('file')
    if not name:
        raise RuntimeError('Failed scene has no edit-source filename; refusing blind regeneration.')
    source_path = PROJECT_ROOT / name
    if not source_path.is_file():
        raise RuntimeError(f'Failed scene edit source missing: {source_path}')
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    folder = output_file.parent / 'history'
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f'{output_file.stem}-before-repair-{stamp}{source_path.suffix}'
    shutil.copy2(source_path, archive)
    audit = {'mode': 'targeted_edit', 'source_file': name, 'source_sha256': source_hash,
             'backup_file': archive.relative_to(PROJECT_ROOT).as_posix(),
             'qc': metadata.get('semantic_qc'), 'prompt': prompt,
             'created_at': datetime.now(timezone.utc).isoformat()}
    audit_file = archive.with_suffix('.json')
    audit_file.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'  Targeted image repair; original preserved: {archive}')
    return archive, audit


def generate_scene_image(
    client: OpenAI,
    job: dict,
    scene: dict,
    force: bool,
) -> bool:

    require_approval(job)

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
        and not repair_metadata(scene)
        and scene.get("image", {}).get("supervisor_hash") == job["visual_supervisor"]["plan_hash"]
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
        repair=bool(repair_metadata(scene).get("qc", {}).get("status") == "passed"),
    )
    repair_source, repair_audit = archive_repair_source(scene, output_file, prompt)

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

    if character_references or repair_source is not None:

        reference_paths = [
            path
            for _, path
            in character_references
        ]

        generate_scene_image_with_references(
            client=client,
            prompt=prompt,
            reference_paths=reference_paths,
            repair_source=repair_source,
            output_file=output_file,
            job=job,
        )

    else:

        generate_image(
            client=client,
            prompt=prompt,
            output_file=output_file,
            size=SCENE_IMAGE_SIZE,
            job=job,
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

    scene.pop("image_repair_source", None)
    scene["image"] = {
        "repair": repair_audit,
        "supervisor_hash": job["visual_supervisor"]["plan_hash"],
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

    try:
        require_approval(job)
    except RuntimeError as exc:
        print(str(exc))
        return 1

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