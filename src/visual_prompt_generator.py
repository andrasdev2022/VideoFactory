from __future__ import annotations

from pathlib import Path
import copy
import json
import os
import sys
import argparse

from openai import OpenAI
from pydantic import BaseModel
from validator import load_json, load_yaml
from pipeline_status import set_legacy_status_from_stage

MAX_MOTION_PROMPT_CHARS = 400

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

class VisualScenePrompt(BaseModel):
    scene_id: int

    image_prompt: str

    motion_prompt: str

    negative_prompt: str

    characters: list[str]

    continuity_notes: str


class VisualPromptOutput(BaseModel):
    scenes: list[VisualScenePrompt]

class MotionPromptScene(BaseModel):
    scene_id: int
    motion_prompt: str


class MotionPromptOutput(BaseModel):
    scenes: list[MotionPromptScene]

# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

SYSTEM_PROMPT = """
You are the VISUAL PROMPT GENERATOR worker inside an
automated short-form video production system.

Your task is to convert storyboard scenes into high-quality
provider-neutral prompts for future AI image/video generation.

For every supplied scene, generate:

1. image_prompt
   - Describes the visual appearance of the scene.
   - Must describe subject, environment, lighting, composition,
     expression and relevant visual details.
   - Must preserve character appearance and global style.

2. motion_prompt
   - Describe ONLY the motion that should happen after the
     supplied scene image becomes the opening frame.
   - Do not redescribe the scene, environment, clothing or
     character appearance unless needed for motion continuity.
   - Prefer subtle, controlled motion over complex action.
   - Keep the number of independently moving subjects low.
   - Prefer one primary subject motion plus one simple camera motion.
   - Characters that do not need to move should remain stable
     and continuously visible.
   - Do not move important characters out of frame unless the
     storyboard explicitly requires it.
   - Avoid multi-step actions such as:
     walk in -> turn -> sit -> react -> leave.
   - Avoid teleporting, disappearing, reappearing or rapid
     position changes.
   - Prefer motions such as:
     subtle head movement,
     blinking,
     small hand or paw movement,
     slight body movement,
     slow camera push-in,
     slow pan,
     subtle background movement.
   - Use one continuous shot.
   - Keep motion_prompt concise, preferably below 350 characters.

3. negative_prompt
   - Describes undesirable artifacts or inconsistencies.

4. characters
   - Must contain only character IDs supplied in the input scene.

5. continuity_notes
   - Short notes describing what must remain visually consistent
     with previous and future scenes.

Important rules:

- Produce exactly one output scene for every input scene.
- Preserve scene IDs exactly.
- Do not add or remove scenes.
- Do not invent new main characters.
- Use only supplied character IDs.
- Preserve character clothing and appearance.
- Preserve the global visual style.
- The final video is vertical 9:16.
- Avoid unnecessary complexity in a single shot.
- Do not generate visible subtitles, captions, logos or UI text
  inside image_prompt unless the scene absolutely requires it.
- Text overlays are added later by the video assembler.
- Avoid copyrighted characters, brands or logos unless explicitly
  supplied in the source material.
- Keep prompts provider-neutral.
- Do not include technical provider parameters such as seed,
  CFG scale, model version or sampler.
- Avoid conflicting camera instructions.
- Make the first visual frame immediately readable on a phone screen.
- Focus on one clear visual idea per scene.

CAMERA / CHARACTER VISIBILITY RULES:

- If an important character must remain visible throughout the shot,
  do not use camera motion that can crop that character out.
- Prefer a locked camera when multiple important characters must
  remain visible.
- Use push-in or zoom only when the shot's important subjects will
  remain inside the frame for the entire motion.
- Character visibility requirements take priority over cinematic
  camera movement.
- When uncertain, prefer a stable composition with subtle natural
  character motion.

IMAGE-TO-VIDEO PHILOSOPHY:

The image already defines:
- composition
- environment
- character appearance
- clothing
- lighting
- pose
- general scene meaning

Therefore the motion prompt should NOT recreate the scene.

The video generator should mainly animate the approved still image.

Prefer:
stable image + subtle animation

over:
complex cinematic action

A simple successful motion is better than an ambitious unstable one.
""".strip()

MOTION_ONLY_SYSTEM_PROMPT = """
You generate ONLY motion prompts for image-to-video generation.

The approved still image already defines:
- composition
- environment
- character identity
- clothing
- lighting
- pose
- visual style
- scene meaning

DO NOT redesign or reinterpret the image.

Your task is only to describe stable motion that begins from the
approved still image.

MOTION RULES:

1. Prefer exactly ONE primary motion.

2. Prefer one of:
   - one simple character movement, OR
   - one simple camera movement.

3. Other characters should remain stable with only natural
   micro-movements such as blinking, breathing, or tiny head movement.

4. Do not require secondary gestures unless they are essential
   to understanding the story.

5. If multiple important characters must remain visible, prefer
   a locked-off camera.

6. Never use camera movement that is likely to crop an important
   character out of frame.

7. Avoid:
   - teleporting
   - disappearing
   - reappearing
   - entering and exiting repeatedly
   - complex multi-step actions
   - rapid position changes
   - multiple sequential actions

8. Use one continuous shot.

9. If the still image already communicates the story clearly,
   prefer minimal subject movement.

10. Keep the motion prompt concise and below 400 characters.

If previous semantic QC feedback is supplied, use it to avoid
repeating the same failure.

Return only the requested structured output.
"""

# ---------------------------------------------------------
# BUILD INPUT CONTEXT
# ---------------------------------------------------------

def build_context(
    spec: dict,
    job: dict,
    scenes: list[dict],
) -> dict:
    """
    Build the minimal context needed by the visual prompt generator.
    """

    return {
        "video": {
            "aspect_ratio": spec["video"]["aspect_ratio"],
            "resolution": spec["video"]["resolution"],
            "fps": spec["video"]["fps"],
        },

        "global_visual_spec": spec["visual"],

        "job_style": job.get("style", {}),

        "characters": job.get("characters", []),

        "global_prompt": job.get(
            "visuals",
            {}
        ).get(
            "global_prompt",
            ""
        ),

        "global_negative_prompt": job.get(
            "visuals",
            {}
        ).get(
            "negative_prompt",
            ""
        ),

        "scenes": scenes,
    }


# ---------------------------------------------------------
# GENERATION
# ---------------------------------------------------------

def generate_visual_prompts(
    client: OpenAI,
    spec: dict,
    job: dict,
    scenes: list[dict],
    validation_feedback: str | None = None,
) -> VisualPromptOutput:

    context = build_context(
        spec,
        job,
        scenes,
        )

    user_prompt = (
        "Generate visual prompts for all scenes in the following "
        "video job.\n\nINPUT:\n"
        + json.dumps(
            context,
            indent=2,
            ensure_ascii=False,
        )
    )

    if validation_feedback:

        user_prompt += (
            "\n\nThe previous attempt failed deterministic "
            "validation.\n\nFix these problems:\n"
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
        text_format=VisualPromptOutput,
    )

    result = response.output_parsed

    if result is None:
        raise RuntimeError(
            "AI response did not contain parsed visual prompts."
        )

    return result


# ---------------------------------------------------------
# DETERMINISTIC VALIDATION
# ---------------------------------------------------------

def validate_visual_prompts(
    job: dict,
    source_scenes: list[dict],
    output: VisualPromptOutput,
) -> list[str]:

    errors: list[str] = []

    script_scenes = source_scenes
    generated_scenes = output.scenes

    # -----------------------------------------------------
    # Scene count
    # -----------------------------------------------------

    if len(script_scenes) != len(generated_scenes):

        errors.append(
            f"Expected {len(script_scenes)} visual scenes, "
            f"but generated {len(generated_scenes)}."
        )

    # -----------------------------------------------------
    # Expected scene IDs
    # -----------------------------------------------------

    expected_ids = [
        scene["scene_id"]
        for scene in script_scenes
    ]

    actual_ids = [
        scene.scene_id
        for scene in generated_scenes
    ]

    if actual_ids != expected_ids:

        errors.append(
            f"Scene IDs do not match. "
            f"Expected {expected_ids}, got {actual_ids}."
        )

    # -----------------------------------------------------
    # Validate individual scenes
    # -----------------------------------------------------

    script_scene_map = {
        scene["scene_id"]: scene
        for scene in script_scenes
    }

    known_character_ids = {
        character["character_id"]
        for character in job.get("characters", [])
    }

    for generated_scene in generated_scenes:

        scene_id = generated_scene.scene_id

        # -------------------------------------------------
        # Prompt must not be empty
        # -------------------------------------------------

        if not generated_scene.image_prompt.strip():

            errors.append(
                f"Scene {scene_id}: image_prompt is empty."
            )

        if not generated_scene.motion_prompt.strip():

            errors.append(
                f"Scene {scene_id}: motion_prompt is empty."
            )

        if len(generated_scene.motion_prompt) > MAX_MOTION_PROMPT_CHARS:

            errors.append(
                f"Scene {scene_id}: motion_prompt is too long "
                f"({len(generated_scene.motion_prompt)} chars). "
                f"Maximum: {MAX_MOTION_PROMPT_CHARS}."
            )

        motion_lower = generated_scene.motion_prompt.lower()

        complexity_markers = [
            " then ",
            " after that ",
            " followed by ",
            " next ",
            " walks across ",
            " leaves the frame ",
            " exits the frame ",
        ]

        marker_count = sum(
            1
            for marker in complexity_markers
            if marker in motion_lower
        )

        if marker_count >= 2:

            errors.append(
                f"Scene {scene_id}: motion_prompt appears too complex "
                f"for stable image-to-video generation."
            )

        # -------------------------------------------------
        # Character IDs must exist
        # -------------------------------------------------

        for character_id in generated_scene.characters:

            if character_id not in known_character_ids:

                errors.append(
                    f"Scene {scene_id}: unknown character "
                    f"ID '{character_id}'."
                )

        # -------------------------------------------------
        # Characters must match storyboard
        # -------------------------------------------------

        source_scene = script_scene_map.get(scene_id)

        if source_scene is None:
            continue

        expected_characters = set(
            source_scene.get(
                "visual",
                {}
            ).get(
                "characters",
                []
            )
        )

        actual_characters = set(
            generated_scene.characters
        )

        if actual_characters != expected_characters:

            errors.append(
                f"Scene {scene_id}: character mismatch. "
                f"Expected {sorted(expected_characters)}, "
                f"got {sorted(actual_characters)}."
            )

    return errors


# ---------------------------------------------------------
# SAVE VIDEO JOB
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

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Video Factory visual prompt generator"
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Generate visual prompts only for one scene. "
            "Example: --scene 2"
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Regenerate prompts even if they "
            "already exist."
        ),
    )

    parser.add_argument(
        "--motion-only",
        action="store_true",
        help=(
            "Regenerate only the motion_prompt for one "
            "existing visual scene. Requires --scene."
        ),
    )

    args = parser.parse_args()

    if (
        args.motion_only
        and args.scene is None
    ):

        parser.error(
            "--motion-only requires --scene."
        )

    return args

def find_script_scene(
    job: dict,
    scene_id: int,
) -> dict | None:

    for scene in job.get(
        "script",
        {},
    ).get(
        "scenes",
        [],
    ):

        if scene.get("scene_id") == scene_id:
            return scene

    return None

def merge_visual_scenes(
    job: dict,
    generated: VisualPromptOutput,
) -> None:

    visuals = job.setdefault(
        "visuals",
        {},
    )

    existing_scenes = visuals.setdefault(
        "scenes",
        [],
    )

    existing_map = {
        scene["scene_id"]: scene
        for scene in existing_scenes
    }

    for generated_scene in generated.scenes:

        scene_id = generated_scene.scene_id

        new_data = generated_scene.model_dump()

        # Preserve downstream data such as generated
        # image/video/QC if this scene already exists.
        if scene_id in existing_map:

            existing = existing_map[
                scene_id
            ]

            preserved_keys = [
                "image",
                "video",
            ]

            for key in preserved_keys:

                if key in existing:

                    new_data[key] = existing[key]

            existing.clear()
            existing.update(
                new_data
            )

        else:

            existing_scenes.append(
                new_data
            )

    existing_scenes.sort(
        key=lambda scene:
            scene["scene_id"]
    )

def build_motion_only_context(
    spec: dict,
    job: dict,
    script_scene: dict,
    visual_scene: dict,
) -> dict:

    # Reuse the normal visual generator context so
    # character/style/spec information remains consistent.

    context = build_context(
        spec,
        job,
        [
            script_scene
        ],
    )

    context[
        "approved_existing_visual"
    ] = {

        "scene_id":
            visual_scene.get(
                "scene_id"
            ),

        "image_prompt":
            visual_scene.get(
                "image_prompt"
            ),

        "continuity_notes":
            visual_scene.get(
                "continuity_notes"
            ),

        "characters":
            visual_scene.get(
                "characters",
                [],
            ),
    }

    previous_semantic_qc = (
        visual_scene
        .get(
            "video",
            {},
        )
        .get(
            "semantic_qc"
        )
    )

    if previous_semantic_qc:

        context[
            "previous_video_semantic_qc"
        ] = previous_semantic_qc

    return context

def generate_motion_prompt(
    client: OpenAI,
    spec: dict,
    job: dict,
    script_scene: dict,
    visual_scene: dict,
    validation_feedback: str | None = None,
) -> MotionPromptOutput:

    context = build_motion_only_context(
        spec=spec,
        job=job,
        script_scene=script_scene,
        visual_scene=visual_scene,
    )

    user_content = (
        "Generate a replacement motion_prompt for "
        "the selected scene.\n\n"
        "IMPORTANT:\n"
        "- Do not change the image composition.\n"
        "- Do not generate a new image_prompt.\n"
        "- Preserve approved character identities.\n"
        "- Prefer stable, simple motion.\n\n"
        "INPUT CONTEXT:\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            indent=2,
        )
    )

    if validation_feedback:

        user_content += (
            "\n\n"
            "THE PREVIOUS GENERATED MOTION PROMPT "
            "FAILED DETERMINISTIC VALIDATION.\n"
            "Correct these problems:\n"
            f"{validation_feedback}"
        )

    response = client.responses.parse(
        model=MODEL,

        input=[
            {
                "role": "system",
                "content":
                    MOTION_ONLY_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content":
                    user_content,
            },
        ],

        text_format=MotionPromptOutput,
    )

    result = response.output_parsed

    if result is None:

        raise RuntimeError(
            "OpenAI returned no parsed "
            "motion prompt output."
        )

    return result

def validate_motion_only_output(
    script_scene: dict,
    output: MotionPromptOutput,
) -> list[str]:

    errors: list[str] = []

    expected_scene_id = (
        script_scene.get(
            "scene_id"
        )
    )

    if len(output.scenes) != 1:

        errors.append(
            "Motion-only generation must return "
            "exactly one scene."
        )

        return errors

    generated_scene = (
        output.scenes[0]
    )

    scene_id = (
        generated_scene.scene_id
    )

    if scene_id != expected_scene_id:

        errors.append(
            f"Expected scene "
            f"{expected_scene_id}, "
            f"but generated scene "
            f"{scene_id}."
        )

    motion_prompt = (
        generated_scene
        .motion_prompt
        .strip()
    )

    if not motion_prompt:

        errors.append(
            f"Scene {scene_id}: "
            f"motion_prompt is empty."
        )

        return errors

    if (
        len(motion_prompt)
        > MAX_MOTION_PROMPT_CHARS
    ):

        errors.append(
            f"Scene {scene_id}: "
            f"motion_prompt is too long "
            f"({len(motion_prompt)} chars). "
            f"Maximum: "
            f"{MAX_MOTION_PROMPT_CHARS}."
        )

    motion_lower = (
        motion_prompt.lower()
    )

    complexity_markers = [
        " then ",
        " after that ",
        " followed by ",
        " next ",
        " walks across ",
        " leaves the frame ",
        " exits the frame ",
    ]

    marker_count = sum(
        1
        for marker in complexity_markers
        if marker in motion_lower
    )

    if marker_count >= 2:

        errors.append(
            f"Scene {scene_id}: "
            f"motion_prompt appears too complex "
            f"for stable image-to-video generation."
        )

    return errors

def apply_motion_only_output(
    job: dict,
    output: MotionPromptOutput,
) -> list[int]:

    invalidated_video_scene_ids: list[int] = []

    visual_scenes = (
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

    visual_map = {
        scene.get("scene_id"): scene
        for scene in visual_scenes
    }

    for generated_scene in output.scenes:

        scene_id = (
            generated_scene.scene_id
        )

        visual_scene = (
            visual_map.get(
                scene_id
            )
        )

        if visual_scene is None:

            raise RuntimeError(
                f"Scene {scene_id}: "
                f"existing visual scene "
                f"not found."
            )

        old_motion_prompt = (
            visual_scene.get(
                "motion_prompt"
            )
        )

        new_motion_prompt = (
            generated_scene
            .motion_prompt
            .strip()
        )

        changed = (
            old_motion_prompt
            != new_motion_prompt
        )

        visual_scene[
            "motion_prompt"
        ] = new_motion_prompt

        # ---------------------------------------------
        # Motion changes invalidate VIDEO only.
        #
        # Image and image QC remain valid because
        # image_prompt has not changed.
        # ---------------------------------------------

        if changed:

            if "video" in visual_scene:

                del visual_scene[
                    "video"
                ]

            invalidated_video_scene_ids.append(
                scene_id
            )

    return invalidated_video_scene_ids


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - VISUAL PROMPT GENERATOR v1")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # API CONFIG
    # -----------------------------------------------------

    if not os.getenv(
        "OPENAI_API_KEY"
    ):

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
    # LOAD FILES
    # -----------------------------------------------------

    try:

        spec = load_yaml(
            SPEC_FILE
        )

        original_job = load_json(
            JOB_FILE
        )

    except Exception as exc:

        print(
            f"\nERROR loading input files:\n"
            f"{exc}"
        )

        return 1

    # -----------------------------------------------------
    # SCRIPT SCENES
    # -----------------------------------------------------

    all_script_scenes = (
        original_job
        .get(
            "script",
            {},
        )
        .get(
            "scenes",
            [],
        )
    )

    if not all_script_scenes:

        print(
            "\nERROR: script contains no scenes."
        )

        return 1

    # -----------------------------------------------------
    # EXISTING VISUAL SCENES
    # -----------------------------------------------------

    existing_visual_scenes = {
        scene["scene_id"]: scene
        for scene in (
            original_job
            .get(
                "visuals",
                {},
            )
            .get(
                "scenes",
                [],
            )
        )
        if "scene_id" in scene
    }

    # =====================================================
    # MOTION-ONLY MODE
    # =====================================================

    if args.motion_only:

        selected_script_scene = (
            find_script_scene(
                original_job,
                args.scene,
            )
        )

        if selected_script_scene is None:

            print(
                f"\nERROR: script scene "
                f"{args.scene} not found."
            )

            return 1

        selected_visual_scene = (
            existing_visual_scenes.get(
                args.scene
            )
        )

        if selected_visual_scene is None:

            print(
                f"\nERROR: visual scene "
                f"{args.scene} does not exist."
            )

            print(
                "Generate normal visual prompts first."
            )

            return 1

        existing_image_prompt = (
            selected_visual_scene.get(
                "image_prompt"
            )
        )

        if not existing_image_prompt:

            print(
                f"\nERROR: scene {args.scene} "
                f"has no existing image_prompt."
            )

            return 1

        existing_motion_prompt = (
            selected_visual_scene.get(
                "motion_prompt"
            )
        )

        if (
            existing_motion_prompt
            and not args.force
        ):

            print(
                f"\nScene {args.scene} already has "
                f"a motion_prompt."
            )

            print(
                "Use --force to regenerate it."
            )

            return 0

        print(
            f"\nJob ID: "
            f"{original_job.get('job_id')}"
        )

        print(
            f"Model:  {MODEL}"
        )

        print(
            f"Mode:   motion-only"
        )

        print(
            f"Scene:  {args.scene}"
        )

        if args.force:

            print(
                "Force regeneration: YES"
            )

        client = OpenAI()

        max_attempts = 3
        validation_feedback = None

        result: MotionPromptOutput | None = None

        for attempt in range(
            1,
            max_attempts + 1,
        ):

            print(
                f"\nGenerating motion prompt "
                f"(attempt {attempt}/"
                f"{max_attempts})..."
            )

            try:

                result = (
                    generate_motion_prompt(
                        client=client,
                        spec=spec,
                        job=original_job,
                        script_scene=
                            selected_script_scene,
                        visual_scene=
                            selected_visual_scene,
                        validation_feedback=
                            validation_feedback,
                    )
                )

            except Exception as exc:

                print(
                    f"\nERROR during motion prompt "
                    f"generation:\n{exc}"
                )

                return 1

            errors = (
                validate_motion_only_output(
                    selected_script_scene,
                    result,
                )
            )

            if not errors:
                break

            print(
                "\nGenerated motion prompt "
                "failed validation:"
            )

            for error in errors:

                print(
                    f"  [ERROR] {error}"
                )

            validation_feedback = (
                "\n".join(
                    f"- {error}"
                    for error in errors
                )
            )

        else:

            print(
                "\nERROR: motion prompt generation "
                "failed validation after all attempts."
            )

            return 1

        if result is None:

            print(
                "\nERROR: no generated "
                "motion prompt output."
            )

            return 1

        candidate_job = copy.deepcopy(
            original_job
        )

        invalidated_scene_ids = (
            apply_motion_only_output(
                candidate_job,
                result,
            )
        )

        set_legacy_status_from_stage(
            candidate_job,
            "visual_prompts",
        )

        save_job(
            candidate_job
        )

        generated_scene = (
            result.scenes[0]
        )

        print(
            "\nMOTION PROMPT GENERATED SUCCESSFULLY"
        )

        print(
            f"\nScene "
            f"{generated_scene.scene_id}"
        )

        print(
            f"  Motion: "
            f"{generated_scene.motion_prompt}"
        )

        print(
            f"  Motion chars: "
            f"{len(generated_scene.motion_prompt)}"
        )

        print(
            "  Image prompt preserved: YES"
        )

        if invalidated_scene_ids:

            print(
                "  Previous video invalidated: YES"
            )

        else:

            print(
                "  Previous video invalidated: NO "
                "(motion prompt unchanged)"
            )

        print(
            "\nvideo_job.json updated."
        )

        print(
            f"Job status: "
            f"{candidate_job.get('status')}"
        )

        return 0

    # =====================================================
    # NORMAL VISUAL PROMPT MODE
    # =====================================================

    if args.scene is not None:

        selected_scene = (
            find_script_scene(
                original_job,
                args.scene,
            )
        )

        if selected_scene is None:

            print(
                f"\nERROR: script scene "
                f"{args.scene} not found."
            )

            return 1

        if (
            args.scene
            in existing_visual_scenes
            and not args.force
        ):

            print(
                f"\nScene {args.scene} already "
                f"has visual prompts."
            )

            print(
                "Use --force to regenerate it."
            )

            return 0

        scenes_to_generate = [
            selected_scene
        ]

    else:

        if args.force:

            scenes_to_generate = (
                all_script_scenes
            )

        else:

            scenes_to_generate = [
                scene
                for scene in all_script_scenes
                if scene.get("scene_id")
                not in existing_visual_scenes
            ]

    if not scenes_to_generate:

        print(
            "\nNo visual prompts need generation."
        )

        return 0

    print(
        f"\nJob ID: "
        f"{original_job.get('job_id')}"
    )

    print(
        f"Model:  {MODEL}"
    )

    print(
        f"Scenes to generate: "
        f"{len(scenes_to_generate)}"
    )

    print(
        "Scene IDs: "
        + ", ".join(
            str(
                scene.get(
                    "scene_id"
                )
            )
            for scene
            in scenes_to_generate
        )
    )

    if args.force:

        print(
            "Force regeneration: YES"
        )

    client = OpenAI()

    max_attempts = 3
    validation_feedback = None

    result: VisualPromptOutput | None = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):

        print(
            f"\nGenerating visual prompts "
            f"(attempt {attempt}/"
            f"{max_attempts})..."
        )

        try:

            result = (
                generate_visual_prompts(
                    client=client,
                    spec=spec,
                    job=original_job,
                    scenes=
                        scenes_to_generate,
                    validation_feedback=
                        validation_feedback,
                )
            )

        except Exception as exc:

            print(
                f"\nERROR during visual prompt "
                f"generation:\n{exc}"
            )

            return 1

        errors = (
            validate_visual_prompts(
                original_job,
                scenes_to_generate,
                result,
            )
        )

        if not errors:
            break

        print(
            "\nGenerated visual prompts "
            "failed validation:"
        )

        for error in errors:

            print(
                f"  [ERROR] {error}"
            )

        validation_feedback = (
            "\n".join(
                f"- {error}"
                for error in errors
            )
        )

    else:

        print(
            "\nERROR: visual prompt generation "
            "failed validation after all attempts."
        )

        return 1

    if result is None:

        print(
            "\nERROR: no generated visual "
            "prompt output."
        )

        return 1

    candidate_job = copy.deepcopy(
        original_job
    )

    merge_visual_scenes(
        candidate_job,
        result,
    )

    set_legacy_status_from_stage(
        candidate_job,
        "visual_prompts",
    )

    save_job(
        candidate_job
    )

    print(
        "\nVISUAL PROMPTS GENERATED SUCCESSFULLY"
    )

    print(
        f"\nGenerated scenes: "
        f"{len(result.scenes)}"
    )

    for generated_scene in result.scenes:

        scene_id = (
            generated_scene.scene_id
        )

        print(
            f"\nScene {scene_id}"
        )

        image_preview = (
            generated_scene.image_prompt
        )

        if len(image_preview) > 100:

            image_preview = (
                image_preview[:97]
                + "..."
            )

        motion_preview = (
            generated_scene.motion_prompt
        )

        if len(motion_preview) > 160:

            motion_preview = (
                motion_preview[:157]
                + "..."
            )

        print(
            f"  Image:  "
            f"{image_preview}"
        )

        print(
            f"  Motion: "
            f"{motion_preview}"
        )

        print(
            f"  Motion chars: "
            f"{len(generated_scene.motion_prompt)}"
        )

    print(
        "\nvideo_job.json updated."
    )

    print(
        f"Job status: "
        f"{candidate_job.get('status')}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())