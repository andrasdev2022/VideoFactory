from __future__ import annotations

from genre_policy import genre_instruction

import argparse
import json
import os
import sys

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from validator import load_json


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"

MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
)


class SoundEffectPlan(BaseModel):
    scene_id: int
    effect: str
    offset_sec: float
    duration_sec: float
    volume: float


class AudioPlanOutput(BaseModel):
    background_music_style: str
    effects: list[SoundEffectPlan]


SYSTEM_PROMPT = """
You are the AUDIO PLANNER worker inside an automated short-form
video production system.

Given the final timed script, design a restrained audio plan.

Rules:
- Keep narration clearly dominant.
- Return one concise background music style.
- Use 0-4 sound effects total.
- Add only sound effects that materially improve a scene.
- Use only supplied scene IDs.
- offset_sec is relative to the beginning of that scene.
- Keep offset_sec inside the scene render duration.
- duration_sec must be between 0.5 and 3.0 seconds.
- volume must be between 0.10 and 1.00.
- Effects must contain no dialogue, music, brands, or copyrighted audio.
- Prefer simple isolated effects that a text-to-SFX model can generate.
- The supplied final-video state is authoritative over script intentions.
- If a scene has sfx_allowed=false or motion_mode=static_hold, do not
  create an action sound effect for that scene; the final video does
  not visibly perform the scripted action.
- Do not add an effect merely because a scene exists.
""".strip()


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Create a scene-aligned background music and SFX plan."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate the audio plan.",
    )

    return parser.parse_args()


def save_job_atomic(
    job: dict,
) -> None:

    temporary = JOB_FILE.with_name(
        JOB_FILE.name + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            job,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        JOB_FILE,
    )


def find_visual_scene(
    job: dict,
    scene_id: int,
) -> dict[str, Any] | None:

    for scene in (
        job
        .get(
            "visuals",
            {},
        )
        .get(
            "scenes",
            [],
        )
    ):

        if scene.get(
            "scene_id"
        ) == scene_id:

            return scene

    return None


def is_static_hold_scene(
    job: dict,
    scene_id: int,
) -> bool:

    scene = find_visual_scene(
        job,
        scene_id,
    )

    if scene is None:

        return False

    motion_mode = (
        scene
        .get(
            "semantic_qc_policy",
            {},
        )
        .get(
            "motion_mode"
        )
    )

    if motion_mode == "static_hold":

        return True

    return (
        scene.get(
            "motion_strategy"
        )
        == "still_image_fallback_v1"
    )


def filter_effects_for_final_video(
    job: dict,
    effects: list[SoundEffectPlan],
) -> tuple[
    list[SoundEffectPlan],
    list[dict[str, Any]],
]:

    kept: list[SoundEffectPlan] = []
    skipped: list[dict[str, Any]] = []

    for effect in effects:

        if is_static_hold_scene(
            job,
            effect.scene_id,
        ):

            skipped.append(
                {
                    "scene_id":
                        effect.scene_id,

                    "effect":
                        effect.effect,

                    "reason":
                        "final_video_static_hold",
                }
            )

            continue

        kept.append(
            effect
        )

    return (
        kept,
        skipped,
    )


def build_context(
    job: dict,
) -> dict[str, Any]:

    scenes = []

    for scene in (
        job
        .get(
            "script",
            {},
        )
        .get(
            "scenes",
            [],
        )
    ):

        timing = scene.get(
            "timing",
            {},
        )

        scene_id = scene.get(
            "scene_id"
        )

        visual_scene = (
            find_visual_scene(
                job,
                int(
                    scene_id
                ),
            )
            if scene_id
            is not None
            else None
        )

        final_video = (
            visual_scene.get(
                "video",
                {},
            )
            if visual_scene
            is not None
            else {}
        )

        semantic_qc = final_video.get(
            "semantic_qc",
            {},
        )

        semantic_policy = (
            visual_scene.get(
                "semantic_qc_policy",
                {},
            )
            if visual_scene
            is not None
            else {}
        )

        scenes.append(
            {
                "scene_id":
                    scene_id,

                "type":
                    scene.get(
                        "type"
                    ),

                "voiceover":
                    (
                        scene
                        .get(
                            "voice",
                            {},
                        )
                        .get(
                            "input_text"
                        )
                        or scene.get(
                            "voiceover",
                            "",
                        )
                    ),

                "render_duration_sec":
                    timing.get(
                        "render_duration_sec"
                    ),

                "visual":
                    scene.get(
                        "visual",
                        {},
                    ),

                "final_motion_prompt":
                    (
                        visual_scene.get(
                            "motion_prompt"
                        )
                        if visual_scene
                        is not None
                        else None
                    ),

                "motion_strategy":
                    (
                        visual_scene.get(
                            "motion_strategy"
                        )
                        if visual_scene
                        is not None
                        else None
                    ),

                "motion_mode":
                    semantic_policy.get(
                        "motion_mode"
                    ),

                "sfx_allowed":
                    (
                        not is_static_hold_scene(
                            job,
                            int(
                                scene_id
                            ),
                        )
                        if scene_id
                        is not None
                        else True
                    ),

                "final_video_provider":
                    final_video.get(
                        "provider"
                    ),

                "final_video_semantic_notes":
                    semantic_qc.get(
                        "overall_notes"
                    ),
            }
        )

    return {
        "idea":
            job.get(
                "idea",
                {},
            ),

        "existing_music_style":
            (
                job
                .get(
                    "audio",
                    {},
                )
                .get(
                    "background_music",
                    {},
                )
                .get(
                    "style"
                )
            ),

        "scenes":
            scenes,
    }


def validate_audio_plan(
    job: dict,
    output: AudioPlanOutput,
) -> list[str]:

    errors: list[str] = []

    if not output.background_music_style.strip():
        errors.append(
            "Background music style is empty."
        )

    if len(
        output.effects
    ) > 4:
        errors.append(
            "Audio plan contains more than 4 SFX."
        )

    scene_durations: dict[int, float] = {}

    for scene in (
        job
        .get(
            "script",
            {},
        )
        .get(
            "scenes",
            [],
        )
    ):

        scene_id = scene.get(
            "scene_id"
        )

        duration = (
            scene
            .get(
                "timing",
                {},
            )
            .get(
                "render_duration_sec"
            )
        )

        if (
            scene_id is not None
            and duration is not None
        ):
            scene_durations[
                int(
                    scene_id
                )
            ] = float(
                duration
            )

    for index, effect in enumerate(
        output.effects,
        start=1,
    ):

        if effect.scene_id not in scene_durations:
            errors.append(
                (
                    f"SFX {index}: invalid scene_id "
                    f"{effect.scene_id}."
                )
            )
            continue

        if not effect.effect.strip():
            errors.append(
                f"SFX {index}: empty effect."
            )

        if not (
            0.5
            <= effect.duration_sec
            <= 3.0
        ):
            errors.append(
                (
                    f"SFX {index}: duration "
                    f"{effect.duration_sec} is outside 0.5-3.0."
                )
            )

        if not (
            0.10
            <= effect.volume
            <= 1.00
        ):
            errors.append(
                (
                    f"SFX {index}: volume "
                    f"{effect.volume} is outside 0.10-1.00."
                )
            )

        scene_duration = scene_durations[
            effect.scene_id
        ]

        if not (
            0.0
            <= effect.offset_sec
            < scene_duration
        ):
            errors.append(
                (
                    f"SFX {index}: offset "
                    f"{effect.offset_sec} is outside scene "
                    f"{effect.scene_id} duration "
                    f"{scene_duration:.3f}s."
                )
            )

    return errors


def apply_audio_plan(
    job: dict,
    output: AudioPlanOutput,
    skipped_effects: list[
        dict[str, Any]
    ] | None = None,
) -> None:

    audio = job.setdefault(
        "audio",
        {},
    )

    background = audio.setdefault(
        "background_music",
        {},
    )

    background[
        "style"
    ] = (
        output
        .background_music_style
        .strip()
    )

    sound_effects = audio.setdefault(
        "sound_effects",
        {},
    )

    sound_effects[
        "enabled"
    ] = True

    sound_effects[
        "effects"
    ] = [
        {
            "scene_id":
                effect.scene_id,

            "effect":
                effect.effect.strip(),

            "offset_sec":
                round(
                    effect.offset_sec,
                    3,
                ),

            "duration_sec":
                round(
                    effect.duration_sec,
                    3,
                ),

            "volume":
                round(
                    effect.volume,
                    3,
                ),
        }
        for effect
        in output.effects
    ]

    skipped_effects = (
        skipped_effects
        or []
    )

    audio[
        "plan"
    ] = {
        "status":
            "passed",

        "checked_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "model":
            MODEL,

        "effect_count":
            len(
                output.effects
            ),

        "skipped_effect_count":
            len(
                skipped_effects
            ),

        "skipped_effects":
            skipped_effects,
    }

    audio.pop(
        "assets",
        None,
    )

    audio.pop(
        "mix",
        None,
    )

    background[
        "audio_file"
    ] = None

    for effect in sound_effects[
        "effects"
    ]:
        effect[
            "audio_file"
        ] = None

    output_section = job.get(
        "output"
    )

    if isinstance(
        output_section,
        dict,
    ):
        output_section[
            "mixed_video_file"
        ] = None

        output_section[
            "video_file"
        ] = None

    job.pop(
        "final_qc",
        None,
    )


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - AUDIO PLAN GENERATOR v1")
    print("=" * 60)

    args = parse_args()

    if not os.getenv(
        "OPENAI_API_KEY"
    ):
        print(
            "\nERROR: OPENAI_API_KEY is not set."
        )
        return 1

    try:
        job = load_json(
            JOB_FILE
        )

        existing_plan = (
            job
            .get(
                "audio",
                {},
            )
            .get(
                "plan",
                {},
            )
        )

        if (
            existing_plan.get(
                "status"
            )
            == "passed"
            and not args.force
        ):
            print(
                "\nAudio plan already passed. Use --force to regenerate."
            )
            return 0

        context = build_context(
            job
        )

        if not context[
            "scenes"
        ]:
            raise RuntimeError(
                "Script contains no scenes."
            )

        for scene in context[
            "scenes"
        ]:
            if scene.get(
                "render_duration_sec"
            ) is None:
                raise RuntimeError(
                    (
                        f"Scene {scene.get('scene_id')} has no "
                        "passed render timing."
                    )
                )

        client = OpenAI()

        response = client.responses.parse(
            model=MODEL,

            input=[
                {
                    "role":
                        "system",

                    "content":
                        SYSTEM_PROMPT + genre_instruction(job),
                },
                {
                    "role":
                        "user",

                    "content":
                        (
                            "Create the audio plan for this final "
                            "timed short:\n\n"
                            + json.dumps(
                                context,
                                ensure_ascii=False,
                                indent=2,
                            )
                        ),
                },
            ],

            text_format=AudioPlanOutput,
        )

        result = response.output_parsed

        if result is None:
            raise RuntimeError(
                "Audio planner returned no parsed output."
            )

        (
            filtered_effects,
            skipped_effects,
        ) = filter_effects_for_final_video(
            job,
            result.effects,
        )

        result = AudioPlanOutput(
            background_music_style=
                result.background_music_style,

            effects=
                filtered_effects,
        )

        errors = validate_audio_plan(
            job,
            result,
        )

        if errors:
            raise RuntimeError(
                "; ".join(
                    errors
                )
            )

        apply_audio_plan(
            job,
            result,
            skipped_effects=
                skipped_effects,
        )

        save_job_atomic(
            job
        )

    except Exception as exc:
        print(
            f"\nERROR: {exc}"
        )
        return 1

    print(
        "\nAUDIO PLAN GENERATED"
    )

    print(
        (
            "Music: "
            + job[
                "audio"
            ][
                "background_music"
            ][
                "style"
            ]
        )
    )

    effects = (
        job[
            "audio"
        ][
            "sound_effects"
        ][
            "effects"
        ]
    )

    print(
        f"SFX count: {len(effects)}"
    )

    for effect in effects:
        print(
            (
                f"  scene {effect['scene_id']} "
                f"+{effect['offset_sec']:.3f}s: "
                f"{effect['effect']}"
            )
        )

    skipped_effects = (
        job[
            "audio"
        ][
            "plan"
        ].get(
            "skipped_effects",
            [],
        )
    )

    for effect in skipped_effects:

        print(
            (
                "  [WARNING] Skipped SFX for "
                f"scene {effect['scene_id']}: "
                f"{effect['effect']} "
                f"({effect['reason']})"
            )
        )

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
