from __future__ import annotations

from pathlib import Path
from typing import Literal
import copy
import json
import os
import sys

from openai import OpenAI
from pydantic import BaseModel

from validator import load_json, load_yaml, validate_video_job


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SPEC_FILE = PROJECT_ROOT / "config" / "video_spec_v1.yaml"
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")


# ---------------------------------------------------------
# STRUCTURED OUTPUT MODELS
# ---------------------------------------------------------

class SceneVisual(BaseModel):
    description: str
    characters: list[str]
    camera: str
    emotion: str


class Scene(BaseModel):
    scene_id: int

    type: Literal[
        "hook",
        "setup",
        "escalation",
        "payoff",
        "ending",
        "cta",
    ]

    duration_sec: int
    voiceover: str
    visual: SceneVisual
    text_overlay: str | None


class ScriptOutput(BaseModel):
    target_duration_sec: int
    voiceover: str
    scenes: list[Scene]


# ---------------------------------------------------------
# PROMPT
# ---------------------------------------------------------

SYSTEM_PROMPT = """
You are the SCRIPT GENERATOR worker inside an automated
short-form video production system.

Your job is to convert a supplied video idea into a complete
short-video script.

Important rules:

1. Follow the supplied VIDEO_SPEC.
2. Preserve the original concept and core joke.
3. Do not invent new main characters unless necessary.
4. Use only supplied character IDs in scene.visual.characters.
5. Scene IDs must start at 1 and be sequential.
6. The sum of all scene durations MUST exactly equal
   target_duration_sec.
7. The opening scene must function as a strong hook.
8. Keep pacing fast and appropriate for short-form video.
9. Avoid unnecessary exposition.
10. The ending must contain a clear payoff or punchline.
11. Write natural spoken English for voiceover.
12. Visual descriptions must be concrete enough for a future
    AI image/video generator.
13. Do not place important visual text inside the generated
    scene image. Use text_overlay for text intended to appear
    on screen.

Return the result using the required structured output schema.
""".strip()


# ---------------------------------------------------------
# BUILD GENERATION CONTEXT
# ---------------------------------------------------------

def build_context(spec: dict, job: dict) -> dict:
    """
    Build only the context needed by the script generator.
    """

    return {
        "video_spec": {
            "video": spec["video"],
            "content": spec["content"],
            "visual": spec["visual"],
            "audio": {
                "voiceover": spec["audio"]["voiceover"]
            },
            "subtitles": spec["subtitles"],
        },

        "idea": job["idea"],

        "characters": job.get("characters", []),

        "style": job.get("style", {}),

        "requested_target_duration_sec":
            spec["video"]["target_duration_sec"],
    }


# ---------------------------------------------------------
# CALL LLM
# ---------------------------------------------------------

def generate_script(
    client: OpenAI,
    spec: dict,
    job: dict,
    validation_feedback: str | None = None,
) -> ScriptOutput:

    context = build_context(spec, job)

    user_prompt = """
Generate the complete video script from the following input.

INPUT:
""" + json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )

    if validation_feedback:
        user_prompt += """

The previous attempt failed deterministic validation.

Fix all of these problems:

""" + validation_feedback

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

        text_format=ScriptOutput,
    )

    script = response.output_parsed

    if script is None:
        raise RuntimeError(
            "The AI response did not contain a parsed script."
        )

    return script


# ---------------------------------------------------------
# SAVE JOB ATOMICALLY
# ---------------------------------------------------------

def save_job(job: dict) -> None:
    """
    Save JSON using a temporary file first.
    This prevents a partially written VideoJob if writing fails.
    """

    temp_file = JOB_FILE.with_name(
        JOB_FILE.name + ".tmp"
    )

    with temp_file.open(
        "w",
        encoding="utf-8"
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
    print("VIDEO FACTORY - SCRIPT GENERATOR v1")
    print("=" * 60)

    # -----------------------------------------------------
    # API KEY CHECK
    # -----------------------------------------------------

    if not os.getenv("OPENAI_API_KEY"):

        print(
            "\nERROR: OPENAI_API_KEY environment "
            "variable is not set."
        )

        print(
            '\nPowerShell example:\n'
            '$env:OPENAI_API_KEY="your-key-here"'
        )

        return 1

    # -----------------------------------------------------
    # LOAD FILES
    # -----------------------------------------------------

    try:
        spec = load_yaml(SPEC_FILE)
        original_job = load_json(JOB_FILE)

    except Exception as exc:
        print(f"\nERROR loading files: {exc}")
        return 1

    print(f"\nJob ID: {original_job.get('job_id')}")
    print(f"Model:  {MODEL}")

    idea = original_job.get("idea", {})

    print(
        f"Idea:   "
        f"{idea.get('title', '<missing title>')}"
    )

    # -----------------------------------------------------
    # OPENAI CLIENT
    # -----------------------------------------------------

    client = OpenAI()

    # We don't mutate the original object until generation
    # has passed deterministic validation.
    candidate_job = copy.deepcopy(original_job)

    # -----------------------------------------------------
    # GENERATE + VALIDATE
    # -----------------------------------------------------

    max_attempts = 3
    validation_feedback = None

    for attempt in range(1, max_attempts + 1):

        print(
            f"\nGenerating script "
            f"(attempt {attempt}/{max_attempts})..."
        )

        try:
            generated_script = generate_script(
                client=client,
                spec=spec,
                job=original_job,
                validation_feedback=validation_feedback,
            )

        except Exception as exc:

            print(
                f"\nERROR during AI generation:\n{exc}"
            )

            return 1

        candidate_job = copy.deepcopy(original_job)

        candidate_job["script"] = (
            generated_script.model_dump()
        )

        candidate_job["status"] = "scripted"

        # -------------------------------------------------
        # EXISTING VALIDATOR
        # -------------------------------------------------

        errors = validate_video_job(
            spec,
            candidate_job,
        )

        if not errors:
            break

        print("\nGenerated script failed validation:")

        for error in errors:
            print(f"  [ERROR] {error}")

        validation_feedback = "\n".join(
            f"- {error}"
            for error in errors
        )

    else:

        print(
            "\nERROR: Script generation failed "
            "validation after all attempts."
        )

        return 1

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    save_job(candidate_job)

    script = candidate_job["script"]

    total_duration = sum(
        scene["duration_sec"]
        for scene in script["scenes"]
    )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    print("\nSCRIPT GENERATED SUCCESSFULLY")

    print(
        f"\nTarget duration: "
        f"{script['target_duration_sec']}s"
    )

    print(
        f"Actual duration: "
        f"{total_duration}s"
    )

    print(
        f"Scenes: "
        f"{len(script['scenes'])}"
    )

    print("\nScenes:")

    for scene in script["scenes"]:

        print(
            f"  {scene['scene_id']}. "
            f"{scene['type']:10} "
            f"{scene['duration_sec']}s"
        )

    print(
        "\nvideo_job.json updated."
    )

    print(
        'Status: "scripted"'
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())