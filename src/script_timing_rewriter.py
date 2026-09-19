from __future__ import annotations

import argparse
import copy
import json
import math
import os

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from pipeline_status import (
    set_legacy_status_from_stage,
)

from validator import load_json


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

JOB_FILE = (
    PROJECT_ROOT
    / "jobs"
    / "video_job.json"
)


MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
)

VOICE_SAFETY_SEC = float(
    os.getenv(
        "SCRIPT_REWRITE_VOICE_SAFETY_SEC",
        "0.35",
    )
)

MAX_ATTEMPTS = int(
    os.getenv(
        "SCRIPT_REWRITE_MAX_ATTEMPTS",
        "3",
    )
)


REWRITABLE_FIELDS = (
    "voiceover",
    "voiceover_text",
    "narration",
    "spoken_text",
)


SYSTEM_PROMPT = """
You rewrite short-form video voiceover text to satisfy a strict timing budget.

The existing scene concept, joke, plot facts, character identities, visual action,
and continuity are already approved.

Your job is ONLY to shorten the spoken wording.

RULES:

1. Preserve the exact story meaning and essential joke/punchline.
2. Preserve character identities and relationships.
3. Do not introduce new events, objects, actions, locations, or visual requirements.
4. Do not change what the approved scene visually means.
5. Prefer concise natural spoken English.
6. Remove redundancy, filler, setup words, and unnecessary explanation first.
7. The result must sound natural when spoken at normal conversational speed.
8. Never write unnaturally compressed or telegraphic English.
9. Never try to solve timing through fast speech.
10. Respect BOTH the supplied maximum word count and maximum character count.
11. Return only the requested structured output.

The replacement should be as close as possible to the original meaning while
being safely short enough for natural-speed text-to-speech.
""".strip()


class TimingRewriteOutput(BaseModel):

    scene_id: int
    voiceover: str


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Rewrite one scene voiceover to fit "
            "the natural-speed scene timing limit."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        required=True,
        help=(
            "Scene ID requiring timing rewrite."
        ),
    )

    return parser.parse_args()


def save_job_atomic(
    job: dict,
) -> None:

    temporary_file = (
        JOB_FILE.with_name(
            JOB_FILE.name
            + ".tmp"
        )
    )

    temporary_file.write_text(
        json.dumps(
            job,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary_file,
        JOB_FILE,
    )


def find_script_scene(
    job: dict,
    scene_id: int,
) -> dict | None:

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

        if (
            scene.get(
                "scene_id"
            )
            == scene_id
        ):

            return scene

    return None


def find_visual_scene(
    job: dict,
    scene_id: int,
) -> dict | None:

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

        if (
            scene.get(
                "scene_id"
            )
            == scene_id
        ):

            return scene

    return None


def get_rewritable_voice_field(
    scene: dict,
) -> tuple[str, str]:

    for field in REWRITABLE_FIELDS:

        value = scene.get(
            field
        )

        if (
            isinstance(
                value,
                str,
            )
            and value.strip()
        ):

            return (
                field,
                value.strip(),
            )

    if scene.get(
        "dialogue"
    ):

        raise RuntimeError(
            f"Scene {scene.get('scene_id')}: "
            f"timing rewrite for structured dialogue "
            f"is not implemented yet."
        )

    raise RuntimeError(
        f"Scene {scene.get('scene_id')}: "
        f"no rewritable voiceover field found."
    )


def count_words(
    text: str,
) -> int:

    return len(
        text.split()
    )


def calculate_rewrite_budget(
    scene: dict,
    original_text: str,
) -> dict[str, Any]:

    timing = scene.get(
        "timing",
        {},
    )

    if (
        timing.get(
            "status"
        )
        != "failed"
    ):

        raise RuntimeError(
            f"Scene {scene.get('scene_id')}: "
            f"timing status is not failed."
        )

    if not timing.get(
        "script_revision_required"
    ):

        raise RuntimeError(
            f"Scene {scene.get('scene_id')}: "
            f"timing does not require script revision."
        )

    voice_duration = timing.get(
        "voice_duration_sec"
    )

    headroom = timing.get(
        "headroom_sec"
    )

    max_video_duration = timing.get(
        "max_video_duration_sec"
    )

    if voice_duration is None:

        raise RuntimeError(
            "Timing data contains no voice_duration_sec."
        )

    if headroom is None:

        raise RuntimeError(
            "Timing data contains no headroom_sec."
        )

    if max_video_duration is None:

        raise RuntimeError(
            "Timing data contains no max_video_duration_sec."
        )

    voice_duration = float(
        voice_duration
    )

    headroom = float(
        headroom
    )

    max_video_duration = float(
        max_video_duration
    )

    maximum_voice_duration = (
        max_video_duration
        - headroom
    )

    target_voice_duration = (
        maximum_voice_duration
        - VOICE_SAFETY_SEC
    )

    if target_voice_duration <= 0:

        raise RuntimeError(
            "Calculated target voice duration "
            "is not positive."
        )

    if voice_duration <= target_voice_duration:

        raise RuntimeError(
            "Current natural voice already fits "
            "the rewrite target."
        )

    duration_ratio = (
        target_voice_duration
        / voice_duration
    )

    current_words = count_words(
        original_text
    )

    current_chars = len(
        original_text
    )

    # Additional 3% textual safety margin because
    # TTS duration is not perfectly linear with words
    # or characters.

    text_ratio = min(
        0.97,
        duration_ratio
        * 0.97,
    )

    max_words = max(
        4,
        math.floor(
            current_words
            * text_ratio
        ),
    )

    max_chars = max(
        20,
        math.floor(
            current_chars
            * text_ratio
        ),
    )

    return {

        "current_voice_duration_sec":
            round(
                voice_duration,
                3,
            ),

        "maximum_voice_duration_sec":
            round(
                maximum_voice_duration,
                3,
            ),

        "target_voice_duration_sec":
            round(
                target_voice_duration,
                3,
            ),

        "duration_ratio":
            duration_ratio,

        "current_words":
            current_words,

        "current_chars":
            current_chars,

        "max_words":
            max_words,

        "max_chars":
            max_chars,
    }


def build_rewrite_context(
    job: dict,
    scene: dict,
    source_field: str,
    original_text: str,
    budget: dict[str, Any],
) -> dict[str, Any]:

    scenes = (
        job
        .get(
            "script",
            {},
        )
        .get(
            "scenes",
            [],
        )
    )

    scene_id = scene.get(
        "scene_id"
    )

    previous_scene = None
    next_scene = None

    for index, candidate in enumerate(
        scenes
    ):

        if (
            candidate.get(
                "scene_id"
            )
            != scene_id
        ):

            continue

        if index > 0:

            previous_scene = (
                scenes[
                    index - 1
                ]
            )

        if (
            index + 1
            < len(
                scenes
            )
        ):

            next_scene = (
                scenes[
                    index + 1
                ]
            )

        break

    def neighboring_voice(
        candidate: dict | None,
    ) -> str | None:

        if candidate is None:

            return None

        try:

            _, text = (
                get_rewritable_voice_field(
                    candidate
                )
            )

            return text

        except RuntimeError:

            return None

    return {

        "job_id":
            job.get(
                "job_id"
            ),

        "scene_id":
            scene_id,

        "source_field":
            source_field,

        "original_voiceover":
            original_text,

        "current_words":
            budget[
                "current_words"
            ],

        "current_chars":
            budget[
                "current_chars"
            ],

        "measured_natural_voice_duration_sec":
            budget[
                "current_voice_duration_sec"
            ],

        "target_voice_duration_sec":
            budget[
                "target_voice_duration_sec"
            ],

        "maximum_words":
            budget[
                "max_words"
            ],

        "maximum_characters":
            budget[
                "max_chars"
            ],

        "scene":
            {
                key: value
                for key, value
                in scene.items()
                if key not in {
                    "voice",
                    "timing",
                    "timing_revisions",
                }
            },

        "previous_scene_voiceover":
            neighboring_voice(
                previous_scene
            ),

        "next_scene_voiceover":
            neighboring_voice(
                next_scene
            ),
    }


def generate_rewrite(
    client: OpenAI,
    job: dict,
    scene: dict,
    source_field: str,
    original_text: str,
    budget: dict[str, Any],
    validation_feedback: list[str] | None = None,
) -> TimingRewriteOutput:

    context = build_rewrite_context(
        job=job,
        scene=scene,
        source_field=source_field,
        original_text=original_text,
        budget=budget,
    )

    user_message = (
        "Rewrite the scene voiceover so it can be "
        "spoken naturally within the timing budget.\n\n"
        "Hard limits:\n"
        f"- maximum words: {budget['max_words']}\n"
        f"- maximum characters: {budget['max_chars']}\n"
        f"- target natural voice duration: "
        f"{budget['target_voice_duration_sec']:.3f} seconds\n\n"
        "Preserve the same scene meaning, story beat, "
        "characters, visual action, and punchline.\n\n"
        "Context:\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            indent=2,
        )
    )

    if validation_feedback:

        user_message += (
            "\n\nThe previous candidate failed deterministic "
            "validation. Fix all of these issues:\n"
        )

        for error in validation_feedback:

            user_message += (
                f"- {error}\n"
            )

    response = (
        client
        .responses
        .parse(
            model=MODEL,
            input=[
                {
                    "role":
                        "system",

                    "content":
                        SYSTEM_PROMPT,
                },
                {
                    "role":
                        "user",

                    "content":
                        user_message,
                },
            ],
            text_format=
                TimingRewriteOutput,
        )
    )

    parsed = response.output_parsed

    if parsed is None:

        raise RuntimeError(
            "Model returned no parsed rewrite output."
        )

    return parsed


def validate_rewrite(
    scene_id: int,
    original_text: str,
    budget: dict[str, Any],
    output: TimingRewriteOutput,
) -> list[str]:

    errors: list[str] = []

    if (
        output.scene_id
        != scene_id
    ):

        errors.append(
            f"scene_id must be {scene_id}."
        )

    candidate = (
        output.voiceover.strip()
    )

    if not candidate:

        errors.append(
            "voiceover must not be empty."
        )

        return errors

    if candidate == original_text.strip():

        errors.append(
            "voiceover was not shortened."
        )

    word_count = count_words(
        candidate
    )

    char_count = len(
        candidate
    )

    if (
        word_count
        > budget[
            "max_words"
        ]
    ):

        errors.append(
            f"voiceover has {word_count} words; "
            f"maximum is {budget['max_words']}."
        )

    if (
        char_count
        > budget[
            "max_chars"
        ]
    ):

        errors.append(
            f"voiceover has {char_count} characters; "
            f"maximum is {budget['max_chars']}."
        )

    return errors


def apply_rewrite(
    job: dict,
    scene_id: int,
    source_field: str,
    original_text: str,
    output: TimingRewriteOutput,
    budget: dict[str, Any],
) -> None:

    scene = find_script_scene(
        job,
        scene_id,
    )

    if scene is None:

        raise RuntimeError(
            f"Scene {scene_id} disappeared."
        )

    new_text = (
        output.voiceover.strip()
    )

    revisions = scene.setdefault(
        "timing_revisions",
        [],
    )

    revisions.append(
        {

            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "reason":
                "natural_voice_exceeds_scene_limit",

            "source_field":
                source_field,

            "old_text":
                original_text,

            "new_text":
                new_text,

            "old_word_count":
                count_words(
                    original_text
                ),

            "new_word_count":
                count_words(
                    new_text
                ),

            "old_char_count":
                len(
                    original_text
                ),

            "new_char_count":
                len(
                    new_text
                ),

            "measured_voice_duration_sec":
                budget[
                    "current_voice_duration_sec"
                ],

            "target_voice_duration_sec":
                budget[
                    "target_voice_duration_sec"
                ],

            "max_words":
                budget[
                    "max_words"
                ],

            "max_chars":
                budget[
                    "max_chars"
                ],
        }
    )

    scene[
        source_field
    ] = new_text

    # The spoken text changed, therefore the old voice
    # and timing are no longer valid.

    scene.pop(
        "voice",
        None,
    )

    scene.pop(
        "timing",
        None,
    )

    # Future-proofing for later pipeline stages.

    scene.pop(
        "subtitles",
        None,
    )

    # The still image remains valid because the rewriter
    # is explicitly forbidden from changing scene meaning.
    #
    # The video does NOT remain valid because its duration
    # must eventually follow the new natural voice.

    visual_scene = find_visual_scene(
        job,
        scene_id,
    )

    if visual_scene is not None:

        visual_scene.pop(
            "video",
            None,
        )

    # Keep the script-level narration synchronized with
    # the authoritative per-scene voiceovers.

    script = job.setdefault(
        "script",
        {},
    )

    combined_voiceover: list[str] = []

    for script_scene in script.get(
        "scenes",
        [],
    ):

        try:

            _, text = (
                get_rewritable_voice_field(
                    script_scene
                )
            )

        except RuntimeError:

            continue

        combined_voiceover.append(
            text
        )

    script[
        "voiceover"
    ] = " ".join(
        combined_voiceover
    )

    script.pop(
        "duration_normalization",
        None,
    )

    job.pop(
        "timing_summary",
        None,
    )

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


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SCRIPT TIMING REWRITER v2")
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

    except Exception as exc:

        print(
            f"\nERROR loading job:\n"
            f"{exc}"
        )

        return 1

    scene = find_script_scene(
        job,
        args.scene,
    )

    if scene is None:

        print(
            f"\nERROR: scene "
            f"{args.scene} not found."
        )

        return 1

    try:

        (
            source_field,
            original_text,
        ) = get_rewritable_voice_field(
            scene
        )

        budget = calculate_rewrite_budget(
            scene,
            original_text,
        )

    except Exception as exc:

        print(
            f"\nERROR: {exc}"
        )

        return 1

    print(
        f"\nScene: {args.scene}"
    )

    print(
        f"Field: {source_field}"
    )

    print(
        f"Current voice duration: "
        f"{budget['current_voice_duration_sec']:.3f}s"
    )

    print(
        f"Maximum voice duration: "
        f"{budget['maximum_voice_duration_sec']:.3f}s"
    )

    print(
        f"Rewrite target duration: "
        f"{budget['target_voice_duration_sec']:.3f}s"
    )

    print(
        f"Current words: "
        f"{budget['current_words']}"
    )

    print(
        f"Maximum words: "
        f"{budget['max_words']}"
    )

    print(
        f"Current chars: "
        f"{budget['current_chars']}"
    )

    print(
        f"Maximum chars: "
        f"{budget['max_chars']}"
    )

    client = OpenAI()

    feedback: list[str] | None = None
    accepted_output = None

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1,
    ):

        print(
            f"\nRewrite attempt "
            f"{attempt}/{MAX_ATTEMPTS}"
        )

        try:

            output = generate_rewrite(
                client=client,
                job=job,
                scene=scene,
                source_field=source_field,
                original_text=original_text,
                budget=budget,
                validation_feedback=
                    feedback,
            )

        except Exception as exc:

            print(
                f"\nERROR calling rewrite model:\n"
                f"{exc}"
            )

            return 1

        errors = validate_rewrite(
            scene_id=args.scene,
            original_text=
                original_text,
            budget=budget,
            output=output,
        )

        if not errors:

            accepted_output = output
            break

        feedback = errors

        print(
            "  Candidate rejected:"
        )

        for error in errors:

            print(
                f"  - {error}"
            )

    if accepted_output is None:

        print(
            "\nERROR: no valid rewrite "
            "after maximum attempts."
        )

        return 1

    candidate_job = copy.deepcopy(
        job
    )

    apply_rewrite(
        job=candidate_job,
        scene_id=args.scene,
        source_field=source_field,
        original_text=original_text,
        output=accepted_output,
        budget=budget,
    )

    set_legacy_status_from_stage(
        candidate_job,
        "voiceovers",
    )

    save_job_atomic(
        candidate_job
    )

    new_text = (
        accepted_output
        .voiceover
        .strip()
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "SCRIPT TIMING REWRITE COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nOld words: "
        f"{count_words(original_text)}"
    )

    print(
        f"New words: "
        f"{count_words(new_text)}"
    )

    print(
        f"Old chars: "
        f"{len(original_text)}"
    )

    print(
        f"New chars: "
        f"{len(new_text)}"
    )

    print(
        "\nOld voiceover:"
    )

    print(
        original_text
    )

    print(
        "\nNew voiceover:"
    )

    print(
        new_text
    )

    print(
        "\nOld voice invalidated: YES"
    )

    print(
        "Old timing invalidated: YES"
    )

    print(
        "Old video invalidated: YES"
    )

    print(
        "Scene image preserved: YES"
    )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )