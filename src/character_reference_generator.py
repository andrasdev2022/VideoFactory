from __future__ import annotations

from pathlib import Path
import copy
import json
import os
import sys

from openai import OpenAI
from pydantic import BaseModel

from validator import load_json, load_yaml


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SPEC_FILE = PROJECT_ROOT / "config" / "video_spec_v1.yaml"
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"

MODEL = os.getenv("OPENAI_MODEL")


# ---------------------------------------------------------
# STRUCTURED OUTPUT MODELS
# ---------------------------------------------------------

class CharacterReferencePrompt(BaseModel):
    character_id: str

    prompt: str

    negative_prompt: str

    visual_signature: str


class CharacterReferenceOutput(BaseModel):
    characters: list[CharacterReferencePrompt]


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

SYSTEM_PROMPT = """
You are the CHARACTER REFERENCE DESIGNER inside an automated
AI video production system.

Your task is to create a canonical visual reference prompt
for every supplied character.

These reference images will later be used to maintain visual
character consistency across many different video scenes.

For every character produce:

1. character_id
   Preserve the supplied character ID exactly.

2. prompt
   A detailed prompt for generating a clean canonical
   reference image of the character.

3. negative_prompt
   Visual artifacts and character inconsistencies that must
   be avoided.

4. visual_signature
   A short, stable description of the character's essential
   visual identity. This will later be inserted into scene
   prompts.

REFERENCE IMAGE RULES:

- Preserve the supplied character description exactly.
- Do not invent major visual traits unless needed to make the
  character visually reproducible.
- Preserve clothing, age, species, hairstyle, fur, colors,
  accessories and other identity-defining features.
- The character should be clearly visible.
- Prefer a full-body or near-full-body three-quarter view.
- Use a simple neutral background.
- Use clean studio-like lighting.
- Avoid complicated environments.
- Avoid action poses.
- Avoid other characters.
- Avoid visible text, captions, logos or watermarks.
- Keep the visual style consistent with the global video style.
- Make the character easy to reuse in later scenes.
- The prompt must be provider-neutral.
- Do not include model-specific parameters such as seed,
  sampler, CFG scale or model version.

VISUAL SIGNATURE RULES:

- Keep visual_signature concise.
- Include only identity-defining visual characteristics.
- Do not include scene-specific information.
- Do not include camera instructions.
- Do not include temporary expressions or actions.
- It should remain valid for every scene containing that character.

Return exactly one result for every supplied character.
""".strip()


# ---------------------------------------------------------
# BUILD INPUT CONTEXT
# ---------------------------------------------------------

def build_context(spec: dict, job: dict) -> dict:
    """
    Build only the information needed for character design.
    """

    return {
        "video_format": {
            "aspect_ratio": spec["video"]["aspect_ratio"],
            "resolution": spec["video"]["resolution"],
        },

        "global_visual_spec": spec["visual"],

        "job_style": job.get("style", {}),

        "characters": job.get("characters", []),
    }


# ---------------------------------------------------------
# GENERATION
# ---------------------------------------------------------

def generate_character_reference_prompts(
    client: OpenAI,
    spec: dict,
    job: dict,
    validation_feedback: str | None = None,
) -> CharacterReferenceOutput:

    context = build_context(spec, job)

    user_prompt = (
        "Create canonical character reference prompts for all "
        "characters in the following video job.\n\n"
        "INPUT:\n"
        + json.dumps(
            context,
            indent=2,
            ensure_ascii=False,
        )
    )

    if validation_feedback:

        user_prompt += (
            "\n\nThe previous attempt failed deterministic "
            "validation.\n\n"
            "Fix all of the following problems:\n"
            + validation_feedback
        )

    response = client.responses.parse(
        model=MODEL,

        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],

        text_format=CharacterReferenceOutput,
    )

    result = response.output_parsed

    if result is None:
        raise RuntimeError(
            "AI response did not contain parsed "
            "character reference prompts."
        )

    return result


# ---------------------------------------------------------
# DETERMINISTIC VALIDATION
# ---------------------------------------------------------

def validate_character_references(
    job: dict,
    result: CharacterReferenceOutput,
) -> list[str]:

    errors: list[str] = []

    source_characters = job.get("characters", [])
    generated_characters = result.characters

    # -----------------------------------------------------
    # Expected IDs
    # -----------------------------------------------------

    expected_ids = [
        character["character_id"]
        for character in source_characters
    ]

    actual_ids = [
        character.character_id
        for character in generated_characters
    ]

    # -----------------------------------------------------
    # Character count
    # -----------------------------------------------------

    if len(expected_ids) != len(actual_ids):

        errors.append(
            f"Expected {len(expected_ids)} characters, "
            f"but generated {len(actual_ids)}."
        )

    # -----------------------------------------------------
    # Duplicate IDs
    # -----------------------------------------------------

    if len(actual_ids) != len(set(actual_ids)):

        errors.append(
            "Generated character IDs contain duplicates."
        )

    # -----------------------------------------------------
    # Exact ID match
    # -----------------------------------------------------

    if set(actual_ids) != set(expected_ids):

        errors.append(
            f"Character IDs do not match. "
            f"Expected {expected_ids}, got {actual_ids}."
        )

    # -----------------------------------------------------
    # Individual content
    # -----------------------------------------------------

    for character in generated_characters:

        character_id = character.character_id

        if not character.prompt.strip():

            errors.append(
                f"{character_id}: reference prompt is empty."
            )

        if not character.negative_prompt.strip():

            errors.append(
                f"{character_id}: negative prompt is empty."
            )

        if not character.visual_signature.strip():

            errors.append(
                f"{character_id}: visual signature is empty."
            )

        # Keep visual_signature reasonably compact.
        if len(character.visual_signature) > 500:

            errors.append(
                f"{character_id}: visual_signature is too long "
                f"({len(character.visual_signature)} characters)."
            )

    return errors


# ---------------------------------------------------------
# UPDATE VIDEO JOB
# ---------------------------------------------------------

def apply_character_references(
    job: dict,
    result: CharacterReferenceOutput,
) -> dict:

    updated_job = copy.deepcopy(job)

    result_map = {
        character.character_id: character
        for character in result.characters
    }

    job_id = updated_job["job_id"]

    for character in updated_job.get(
        "characters",
        [],
    ):

        character_id = character["character_id"]

        generated = result_map[character_id]

        image_path = (
            f"output/{job_id}/characters/"
            f"{character_id}/reference.png"
        )

        character["reference"] = {
            "status": "prompt_generated",

            "prompt":
                generated.prompt,

            "negative_prompt":
                generated.negative_prompt,

            "visual_signature":
                generated.visual_signature,

            "image_file": None,

            "planned_image_file":
                image_path,
        }

    updated_job["status"] = (
        "character_reference_prompts_generated"
    )

    return updated_job


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
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - CHARACTER REFERENCE GENERATOR v1")
    print("=" * 60)

    # -----------------------------------------------------
    # CONFIG CHECK
    # -----------------------------------------------------

    if not os.getenv("OPENAI_API_KEY"):

        print(
            "\nERROR: OPENAI_API_KEY environment "
            "variable is not set."
        )

        return 1

    if not MODEL:

        print(
            "\nERROR: OPENAI_MODEL environment "
            "variable is not set."
        )

        return 1

    # -----------------------------------------------------
    # LOAD
    # -----------------------------------------------------

    try:

        spec = load_yaml(SPEC_FILE)
        original_job = load_json(JOB_FILE)

    except Exception as exc:

        print(
            f"\nERROR loading input files:\n{exc}"
        )

        return 1

    characters = original_job.get(
        "characters",
        [],
    )

    if not characters:

        print(
            "\nERROR: video_job.json contains no characters."
        )

        return 1

    print(
        f"\nJob ID:     {original_job.get('job_id')}"
    )

    print(
        f"Model:      {MODEL}"
    )

    print(
        f"Characters: {len(characters)}"
    )

    for character in characters:

        print(
            f"  {character['character_id']} "
            f"- {character.get('name', '<unnamed>')}"
        )

    # -----------------------------------------------------
    # CLIENT
    # -----------------------------------------------------

    client = OpenAI()

    max_attempts = 3
    validation_feedback = None

    result: CharacterReferenceOutput | None = None

    # -----------------------------------------------------
    # GENERATE + VALIDATE
    # -----------------------------------------------------

    for attempt in range(
        1,
        max_attempts + 1,
    ):

        print(
            f"\nGenerating character reference prompts "
            f"(attempt {attempt}/{max_attempts})..."
        )

        try:

            result = generate_character_reference_prompts(
                client=client,
                spec=spec,
                job=original_job,
                validation_feedback=validation_feedback,
            )

        except Exception as exc:

            print(
                "\nERROR during character reference "
                f"generation:\n{exc}"
            )

            return 1

        errors = validate_character_references(
            original_job,
            result,
        )

        if not errors:
            break

        print(
            "\nGenerated character references "
            "failed validation:"
        )

        for error in errors:

            print(
                f"  [ERROR] {error}"
            )

        validation_feedback = "\n".join(
            f"- {error}"
            for error in errors
        )

    else:

        print(
            "\nERROR: character reference generation "
            "failed validation after all attempts."
        )

        return 1

    if result is None:

        print(
            "\nERROR: no generated output."
        )

        return 1

    # -----------------------------------------------------
    # UPDATE JOB
    # -----------------------------------------------------

    candidate_job = apply_character_references(
        original_job,
        result,
    )

    save_job(
        candidate_job
    )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    print(
        "\nCHARACTER REFERENCE PROMPTS "
        "GENERATED SUCCESSFULLY"
    )

    for generated in result.characters:

        source_character = next(
            character
            for character in characters
            if character["character_id"]
            == generated.character_id
        )

        print(
            f"\n{generated.character_id} "
            f"- {source_character.get('name')}"
        )

        print(
            f"  Signature: "
            f"{generated.visual_signature}"
        )

        prompt_preview = generated.prompt

        if len(prompt_preview) > 120:
            prompt_preview = (
                prompt_preview[:117] + "..."
            )

        print(
            f"  Prompt:    {prompt_preview}"
        )

    print(
        "\nvideo_job.json updated."
    )

    print(
        'Status: '
        '"character_reference_prompts_generated"'
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())