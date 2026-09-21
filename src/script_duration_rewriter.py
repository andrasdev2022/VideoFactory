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

from validator import (
    load_json,
    load_yaml,
)


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

SPEC_FILE = (
    PROJECT_ROOT
    / "config"
    / "video_spec_v1.yaml"
)


MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
)

MAX_ATTEMPTS = int(
    os.getenv(
        "SCRIPT_DURATION_REWRITE_MAX_ATTEMPTS",
        "3",
    )
)

PROTECT_HOOK_MAX_SEC = float(
    os.getenv(
        "SCRIPT_DURATION_PROTECT_HOOK_MAX_SEC",
        "3.5",
    )
)

SHORTEN_TEXT_SAFETY = float(
    os.getenv(
        "SCRIPT_DURATION_SHORTEN_TEXT_SAFETY",
        "0.97",
    )
)

MIN_TARGET_VOICE_SEC = 0.50


REWRITABLE_FIELDS = (
    "voiceover",
    "voiceover_text",
    "narration",
    "spoken_text",
)


SYSTEM_PROMPT = """
You normalize the total spoken duration of a short-form video script.

The visual scenes, character identities, plot, joke structure, scene count,
and scene order are already approved.

You may ONLY rewrite the spoken wording of the supplied scenes.

RULES:

1. Preserve every scene's existing story beat and essential joke.
2. Preserve character identities, relationships, and chronology.
3. Do not add new events, objects, actions, locations, or visual requirements.
4. Do not move information from one scene to another.
5. Keep the hook punchy and preserve the ending/punchline.
6. Use natural conversational spoken English.
7. Never solve timing by implying faster or slower speech.
8. For shortening, remove redundancy, filler, and unnecessary explanation.
9. For expansion, elaborate only on facts/reactions already represented by the
   approved scene; do not invent new visual beats.
10. Respect every scene's deterministic word and character budget.
11. Return only the requested structured output.
""".strip()


class DurationRewriteScene(BaseModel):

    scene_id: int
    voiceover: str


class DurationRewriteOutput(BaseModel):

    mode: str
    scenes: list[DurationRewriteScene]


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Rewrite multiple scene voiceovers so the "
            "total natural-speed video duration moves "
            "toward the global target."
        )
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

        if scene.get(
            "scene_id"
        ) == scene_id:

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

        if scene.get(
            "scene_id"
        ) == scene_id:

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
            f"structured dialogue is not supported "
            f"by the global duration rewriter yet."
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


def collect_scene_metrics(
    job: dict,
) -> list[dict[str, Any]]:

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

    if not scenes:

        raise RuntimeError(
            "Script contains no scenes."
        )

    metrics: list[dict[str, Any]] = []

    for scene in scenes:

        scene_id = scene.get(
            "scene_id"
        )

        timing = scene.get(
            "timing",
            {},
        )

        if timing.get(
            "status"
        ) != "passed":

            raise RuntimeError(
                f"Scene {scene_id}: scene timing "
                f"must pass before global normalization."
            )

        render_duration = timing.get(
            "render_duration_sec"
        )

        voice_duration = timing.get(
            "voice_duration_sec"
        )

        headroom = timing.get(
            "headroom_sec"
        )

        min_render = timing.get(
            "min_video_duration_sec"
        )

        max_render = timing.get(
            "max_video_duration_sec"
        )

        if any(
            value is None
            for value in (
                render_duration,
                voice_duration,
                headroom,
                min_render,
                max_render,
            )
        ):

            raise RuntimeError(
                f"Scene {scene_id}: incomplete timing metadata."
            )

        (
            source_field,
            voice_text,
        ) = get_rewritable_voice_field(
            scene
        )

        protected = (
            scene.get(
                "type"
            )
            == "hook"
            and float(
                render_duration
            )
            <= PROTECT_HOOK_MAX_SEC
        )

        metrics.append(
            {
                "scene_id":
                    scene_id,

                "source_field":
                    source_field,

                "text":
                    voice_text,

                "current_words":
                    count_words(
                        voice_text
                    ),

                "current_chars":
                    len(
                        voice_text
                    ),

                "current_voice_duration_sec":
                    float(
                        voice_duration
                    ),

                "current_render_duration_sec":
                    float(
                        render_duration
                    ),

                "headroom_sec":
                    float(
                        headroom
                    ),

                "min_render_duration_sec":
                    float(
                        min_render
                    ),

                "max_render_duration_sec":
                    float(
                        max_render
                    ),

                "protected":
                    protected,
            }
        )

    return metrics


def allocate_render_targets(
    metrics: list[dict[str, Any]],
    target_total_duration_sec: float,
) -> dict[int, float]:

    targets: dict[int, float] = {}

    protected = [
        metric
        for metric in metrics
        if metric[
            "protected"
        ]
    ]

    active = [
        metric
        for metric in metrics
        if not metric[
            "protected"
        ]
    ]

    fixed_total = sum(
        metric[
            "current_render_duration_sec"
        ]
        for metric in protected
    )

    for metric in protected:

        targets[
            metric[
                "scene_id"
            ]
        ] = metric[
            "current_render_duration_sec"
        ]

    remaining = (
        float(
            target_total_duration_sec
        )
        - fixed_total
    )

    minimum_possible = sum(
        metric[
            "min_render_duration_sec"
        ]
        for metric in active
    )

    maximum_possible = sum(
        metric[
            "max_render_duration_sec"
        ]
        for metric in active
    )

    if (
        remaining
        < minimum_possible
        - 1e-6
    ):

        raise RuntimeError(
            "Global target is below the minimum "
            "render duration achievable with the "
            "current scene count."
        )

    if (
        remaining
        > maximum_possible
        + 1e-6
    ):

        raise RuntimeError(
            "Global target is above the maximum "
            "render duration achievable with the "
            "current scene count."
        )

    active = list(
        active
    )

    while active:

        weight_total = sum(
            metric[
                "current_render_duration_sec"
            ]
            for metric in active
        )

        if weight_total <= 0:

            share = (
                remaining
                / len(
                    active
                )
            )

            provisional = {
                metric[
                    "scene_id"
                ]:
                    share
                for metric in active
            }

        else:

            provisional = {
                metric[
                    "scene_id"
                ]:
                    (
                        remaining
                        * metric[
                            "current_render_duration_sec"
                        ]
                        / weight_total
                    )
                for metric in active
            }

        clamped_any = False
        next_active: list[
            dict[str, Any]
        ] = []

        for metric in active:

            scene_id = metric[
                "scene_id"
            ]

            value = provisional[
                scene_id
            ]

            minimum = metric[
                "min_render_duration_sec"
            ]

            maximum = metric[
                "max_render_duration_sec"
            ]

            if value < minimum:

                targets[
                    scene_id
                ] = minimum

                remaining -= minimum
                clamped_any = True

            elif value > maximum:

                targets[
                    scene_id
                ] = maximum

                remaining -= maximum
                clamped_any = True

            else:

                next_active.append(
                    metric
                )

        if not clamped_any:

            for metric in active:

                targets[
                    metric[
                        "scene_id"
                    ]
                ] = provisional[
                    metric[
                        "scene_id"
                    ]
                ]

            break

        active = next_active

    difference = (
        target_total_duration_sec
        - sum(
            targets.values()
        )
    )

    if abs(
        difference
    ) > 1e-6:

        adjustable = [
            metric
            for metric in metrics
            if not metric[
                "protected"
            ]
        ]

        for metric in reversed(
            adjustable
        ):

            scene_id = metric[
                "scene_id"
            ]

            candidate = (
                targets[
                    scene_id
                ]
                + difference
            )

            if (
                metric[
                    "min_render_duration_sec"
                ]
                <= candidate
                <= metric[
                    "max_render_duration_sec"
                ]
            ):

                targets[
                    scene_id
                ] = candidate
                difference = 0.0
                break

    if abs(
        difference
    ) > 1e-5:

        raise RuntimeError(
            "Unable to allocate the exact global "
            "duration target within scene bounds."
        )

    rounded_targets = {
        scene_id:
            round(
                duration,
                3,
            )
        for scene_id, duration
        in targets.items()
    }

    rounding_difference = round(
        float(
            target_total_duration_sec
        )
        - sum(
            rounded_targets.values()
        ),
        3,
    )

    if abs(
        rounding_difference
    ) >= 0.001:

        adjustable = [
            metric
            for metric in metrics
            if not metric[
                "protected"
            ]
        ]

        for metric in reversed(
            adjustable
        ):

            scene_id = metric[
                "scene_id"
            ]

            candidate = round(
                rounded_targets[
                    scene_id
                ]
                + rounding_difference,
                3,
            )

            if (
                metric[
                    "min_render_duration_sec"
                ]
                <= candidate
                <= metric[
                    "max_render_duration_sec"
                ]
            ):

                rounded_targets[
                    scene_id
                ] = candidate

                rounding_difference = round(
                    float(
                        target_total_duration_sec
                    )
                    - sum(
                        rounded_targets.values()
                    ),
                    3,
                )

                if abs(
                    rounding_difference
                ) < 0.001:

                    break

    if abs(
        rounding_difference
    ) >= 0.001:

        raise RuntimeError(
            "Unable to preserve the exact global target "
            "after millisecond rounding."
        )

    return rounded_targets


def build_rewrite_plan(
    job: dict,
    spec: dict,
) -> dict[str, Any]:

    summary = job.get(
        "timing_summary",
        {},
    )

    if summary.get(
        "status"
    ) != "complete":

        raise RuntimeError(
            "Global timing summary must be complete "
            "before script duration normalization."
        )

    if not summary.get(
        "script_revision_recommended"
    ):

        raise RuntimeError(
            "Global timing is already within "
            "the accepted target range."
        )

    current_total = summary.get(
        "total_render_duration_sec"
    )

    if current_total is None:

        raise RuntimeError(
            "Global timing summary contains no "
            "total render duration."
        )

    from duration_policy import correction_target
    current_total = float(current_total)
    target_total = correction_target(current_total, spec)
    if abs(current_total - target_total) < 1e-6:
        raise RuntimeError("Global timing is already within the accepted duration range.")

    mode = (
        "shorten"
        if current_total
        > target_total
        else "expand"
    )

    metrics = collect_scene_metrics(
        job
    )

    targets = allocate_render_targets(
        metrics,
        target_total,
    )

    budgets: list[dict[str, Any]] = []

    for metric in metrics:

        scene_id = metric[
            "scene_id"
        ]

        target_render = targets[
            scene_id
        ]

        current_voice = metric[
            "current_voice_duration_sec"
        ]

        target_voice = max(
            MIN_TARGET_VOICE_SEC,
            target_render
            - metric[
                "headroom_sec"
            ],
        )

        ratio = (
            target_voice
            / current_voice
        )

        current_words = metric[
            "current_words"
        ]

        current_chars = metric[
            "current_chars"
        ]

        protected = metric[
            "protected"
        ]

        budget: dict[str, Any] = {
            **metric,

            "target_render_duration_sec":
                target_render,

            "target_voice_duration_sec":
                round(
                    target_voice,
                    3,
                ),

            "duration_ratio":
                ratio,

            "rewrite_required":
                not protected,
        }

        if protected:

            budget[
                "min_words"
            ] = current_words

            budget[
                "max_words"
            ] = current_words

            budget[
                "max_chars"
            ] = current_chars

        elif mode == "shorten":

            text_ratio = min(
                0.98,
                ratio
                * SHORTEN_TEXT_SAFETY,
            )

            max_words = max(
                4,
                math.floor(
                    current_words
                    * text_ratio
                ),
            )

            if current_words > 4:

                max_words = min(
                    max_words,
                    current_words - 1,
                )

            max_chars = max(
                20,
                math.floor(
                    current_chars
                    * text_ratio
                ),
            )

            budget[
                "min_words"
            ] = 1

            budget[
                "max_words"
            ] = max_words

            budget[
                "max_chars"
            ] = max_chars

        else:

            min_words = max(
                current_words + 1,
                math.ceil(
                    current_words
                    * ratio
                    * 0.93
                ),
            )

            max_words = max(
                min_words,
                math.ceil(
                    current_words
                    * ratio
                    * 1.08
                ),
            )

            max_chars = max(
                current_chars + 10,
                math.ceil(
                    current_chars
                    * ratio
                    * 1.12
                ),
            )

            budget[
                "min_words"
            ] = min_words

            budget[
                "max_words"
            ] = max_words

            budget[
                "max_chars"
            ] = max_chars

        budgets.append(
            budget
        )

    rewrite_scene_ids = [
        budget[
            "scene_id"
        ]
        for budget in budgets
        if budget[
            "rewrite_required"
        ]
    ]

    if not rewrite_scene_ids:

        raise RuntimeError(
            "No scenes are available for "
            "global duration rewriting."
        )

    return {
        "mode":
            mode,

        "current_total_duration_sec":
            round(
                current_total,
                3,
            ),

        "target_total_duration_sec":
            round(
                target_total,
                3,
            ),

        "rewrite_scene_ids":
            rewrite_scene_ids,

        "budgets":
            budgets,
    }


def build_rewrite_context(
    job: dict,
    plan: dict[str, Any],
) -> dict[str, Any]:

    budget_map = {
        budget[
            "scene_id"
        ]:
            budget
        for budget in plan[
            "budgets"
        ]
    }

    scenes_context = []

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

        budget = budget_map[
            scene_id
        ]

        scenes_context.append(
            {
                "scene_id":
                    scene_id,

                "scene_type":
                    scene.get(
                        "type"
                    ),

                "original_voiceover":
                    budget[
                        "text"
                    ],

                "protected":
                    budget[
                        "protected"
                    ],

                "current_voice_duration_sec":
                    budget[
                        "current_voice_duration_sec"
                    ],

                "current_render_duration_sec":
                    budget[
                        "current_render_duration_sec"
                    ],

                "target_voice_duration_sec":
                    budget[
                        "target_voice_duration_sec"
                    ],

                "target_render_duration_sec":
                    budget[
                        "target_render_duration_sec"
                    ],

                "min_words":
                    budget[
                        "min_words"
                    ],

                "max_words":
                    budget[
                        "max_words"
                    ],

                "max_characters":
                    budget[
                        "max_chars"
                    ],

                "visual":
                    scene.get(
                        "visual"
                    ),

                "text_overlay":
                    scene.get(
                        "text_overlay"
                    ),
            }
        )

    return {
        "idea":
            job.get(
                "idea"
            ),

        "mode":
            plan[
                "mode"
            ],

        "current_total_duration_sec":
            plan[
                "current_total_duration_sec"
            ],

        "target_total_duration_sec":
            plan[
                "target_total_duration_sec"
            ],

        "rewrite_scene_ids":
            plan[
                "rewrite_scene_ids"
            ],

        "scenes":
            scenes_context,
    }


def generate_rewrite(
    client: OpenAI,
    job: dict,
    plan: dict[str, Any],
    validation_feedback: list[str] | None = None,
) -> DurationRewriteOutput:

    context = build_rewrite_context(
        job,
        plan,
    )

    mode_instruction = (
        "Shorten the requested scene voiceovers."
        if plan[
            "mode"
        ]
        == "shorten"
        else (
            "Expand the requested scene voiceovers "
            "without adding new visual events."
        )
    )

    user_message = (
        f"{mode_instruction}\n\n"
        f"Current total render duration: "
        f"{plan['current_total_duration_sec']:.3f}s\n"
        f"Target total render duration: "
        f"{plan['target_total_duration_sec']:.3f}s\n\n"
        "Return exactly one rewritten voiceover for every "
        "scene_id listed in rewrite_scene_ids, and no others.\n\n"
        "Context and hard budgets:\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            indent=2,
        )
    )

    if validation_feedback:

        user_message += (
            "\n\nThe previous candidate failed "
            "deterministic validation. Fix every issue:\n"
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
                DurationRewriteOutput,
        )
    )

    parsed = response.output_parsed

    if parsed is None:

        raise RuntimeError(
            "Model returned no parsed rewrite output."
        )

    return parsed


def validate_rewrite(
    plan: dict[str, Any],
    output: DurationRewriteOutput,
) -> list[str]:

    errors: list[str] = []

    if (
        output.mode
        != plan[
            "mode"
        ]
    ):

        errors.append(
            f"mode must be '{plan['mode']}'."
        )

    expected_ids = set(
        plan[
            "rewrite_scene_ids"
        ]
    )

    actual_ids = [
        scene.scene_id
        for scene in output.scenes
    ]

    if len(
        actual_ids
    ) != len(
        set(
            actual_ids
        )
    ):

        errors.append(
            "scene_id values must be unique."
        )

    if set(
        actual_ids
    ) != expected_ids:

        errors.append(
            "Output scene IDs must exactly match "
            f"{sorted(expected_ids)}."
        )

    budget_map = {
        budget[
            "scene_id"
        ]:
            budget
        for budget in plan[
            "budgets"
        ]
    }

    for rewritten in output.scenes:

        budget = budget_map.get(
            rewritten.scene_id
        )

        if budget is None:

            continue

        candidate = (
            rewritten
            .voiceover
            .strip()
        )

        if not candidate:

            errors.append(
                f"Scene {rewritten.scene_id}: "
                f"voiceover must not be empty."
            )

            continue

        original = budget[
            "text"
        ]

        if candidate == original:

            errors.append(
                f"Scene {rewritten.scene_id}: "
                f"voiceover was not changed."
            )

        words = count_words(
            candidate
        )

        chars = len(
            candidate
        )

        if (
            words
            < budget[
                "min_words"
            ]
        ):

            errors.append(
                f"Scene {rewritten.scene_id}: "
                f"{words} words is below minimum "
                f"{budget['min_words']}."
            )

        if (
            words
            > budget[
                "max_words"
            ]
        ):

            errors.append(
                f"Scene {rewritten.scene_id}: "
                f"{words} words exceeds maximum "
                f"{budget['max_words']}."
            )

        if (
            chars
            > budget[
                "max_chars"
            ]
        ):

            errors.append(
                f"Scene {rewritten.scene_id}: "
                f"{chars} characters exceeds maximum "
                f"{budget['max_chars']}."
            )

        if (
            plan[
                "mode"
            ]
            == "shorten"
            and words
            >= budget[
                "current_words"
            ]
        ):

            errors.append(
                f"Scene {rewritten.scene_id}: "
                f"shortening must reduce word count."
            )

        if (
            plan[
                "mode"
            ]
            == "expand"
            and words
            <= budget[
                "current_words"
            ]
        ):

            errors.append(
                f"Scene {rewritten.scene_id}: "
                f"expansion must increase word count."
            )

    return errors


def rebuild_script_voiceover(
    job: dict,
) -> str:

    parts: list[str] = []

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

        try:

            _, text = (
                get_rewritable_voice_field(
                    scene
                )
            )

        except RuntimeError:

            continue

        parts.append(
            text
        )

    combined = " ".join(
        parts
    )

    job.setdefault(
        "script",
        {},
    )[
        "voiceover"
    ] = combined

    return combined


def apply_rewrite(
    job: dict,
    plan: dict[str, Any],
    output: DurationRewriteOutput,
) -> list[int]:

    rewrite_map = {
        scene.scene_id:
            scene.voiceover.strip()
        for scene in output.scenes
    }

    budget_map = {
        budget[
            "scene_id"
        ]:
            budget
        for budget in plan[
            "budgets"
        ]
    }

    changed_scene_ids: list[int] = []
    changes: list[dict[str, Any]] = []

    for scene_id in plan[
        "rewrite_scene_ids"
    ]:

        scene = find_script_scene(
            job,
            scene_id,
        )

        if scene is None:

            raise RuntimeError(
                f"Scene {scene_id} disappeared."
            )

        budget = budget_map[
            scene_id
        ]

        source_field = budget[
            "source_field"
        ]

        old_text = budget[
            "text"
        ]

        new_text = rewrite_map[
            scene_id
        ]

        scene[
            source_field
        ] = new_text

        scene.pop(
            "voice",
            None,
        )

        scene.pop(
            "timing",
            None,
        )

        scene.pop(
            "subtitles",
            None,
        )

        visual_scene = find_visual_scene(
            job,
            scene_id,
        )

        if visual_scene is not None:

            visual_scene.pop(
                "video",
                None,
            )

        changed_scene_ids.append(
            scene_id
        )

        changes.append(
            {
                "scene_id":
                    scene_id,

                "source_field":
                    source_field,

                "old_text":
                    old_text,

                "new_text":
                    new_text,

                "old_word_count":
                    count_words(
                        old_text
                    ),

                "new_word_count":
                    count_words(
                        new_text
                    ),

                "old_char_count":
                    len(
                        old_text
                    ),

                "new_char_count":
                    len(
                        new_text
                    ),

                "old_voice_duration_sec":
                    budget[
                        "current_voice_duration_sec"
                    ],

                "old_render_duration_sec":
                    budget[
                        "current_render_duration_sec"
                    ],

                "target_voice_duration_sec":
                    budget[
                        "target_voice_duration_sec"
                    ],

                "target_render_duration_sec":
                    budget[
                        "target_render_duration_sec"
                    ],
            }
        )

    script = job.setdefault(
        "script",
        {},
    )

    history = script.setdefault(
        "duration_revisions",
        [],
    )

    revision = {
        "timestamp":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "reason":
            "global_natural_voice_duration_normalization",

        "mode":
            plan[
                "mode"
            ],

        "old_total_render_duration_sec":
            plan[
                "current_total_duration_sec"
            ],

        "target_total_render_duration_sec":
            plan[
                "target_total_duration_sec"
            ],

        "changed_scene_ids":
            changed_scene_ids,

        "changes":
            changes,
    }

    history.append(
        revision
    )

    script[
        "duration_normalization"
    ] = {
        "status":
            "pending_remeasure",

        "mode":
            plan[
                "mode"
            ],

        "changed_scene_ids":
            changed_scene_ids,

        "target_total_render_duration_sec":
            plan[
                "target_total_duration_sec"
            ],

        "revision_index":
            len(
                history
            )
            - 1,
    }

    rebuild_script_voiceover(
        job
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

    return changed_scene_ids


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SCRIPT DURATION REWRITER v1")
    print("=" * 60)

    parse_args()

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

        spec = load_yaml(
            SPEC_FILE
        )

        plan = build_rewrite_plan(
            job,
            spec,
        )

    except Exception as exc:

        print(
            f"\nERROR: {exc}"
        )

        return 1

    print(
        f"\nMode:           "
        f"{plan['mode']}"
    )

    print(
        f"Current total:  "
        f"{plan['current_total_duration_sec']:.3f}s"
    )

    print(
        f"Target total:   "
        f"{plan['target_total_duration_sec']:.3f}s"
    )

    print(
        f"Rewrite scenes: "
        f"{plan['rewrite_scene_ids']}"
    )

    for budget in plan[
        "budgets"
    ]:

        print(
            f"\nScene {budget['scene_id']}:"
        )

        print(
            f"  protected:     "
            f"{budget['protected']}"
        )

        print(
            f"  render:        "
            f"{budget['current_render_duration_sec']:.3f}s"
            f" -> "
            f"{budget['target_render_duration_sec']:.3f}s"
        )

        print(
            f"  voice target:  "
            f"{budget['target_voice_duration_sec']:.3f}s"
        )

        print(
            f"  words:         "
            f"{budget['current_words']} "
            f"-> "
            f"{budget['min_words']}-"
            f"{budget['max_words']}"
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
                plan=plan,
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
            plan,
            output,
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
            "\nERROR: no valid global rewrite "
            "after maximum attempts."
        )

        return 1

    candidate_job = copy.deepcopy(
        job
    )

    changed_scene_ids = apply_rewrite(
        candidate_job,
        plan,
        accepted_output,
    )

    set_legacy_status_from_stage(
        candidate_job,
        "voiceovers",
    )

    save_job_atomic(
        candidate_job
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "SCRIPT DURATION REWRITE COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nChanged scenes: "
        f"{changed_scene_ids}"
    )

    for scene_id in changed_scene_ids:

        before = next(
            budget
            for budget in plan[
                "budgets"
            ]
            if budget[
                "scene_id"
            ]
            == scene_id
        )

        after = find_script_scene(
            candidate_job,
            scene_id,
        )

        (
            _,
            new_text,
        ) = get_rewritable_voice_field(
            after
        )

        print(
            f"\nScene {scene_id}:"
        )

        print(
            f"  Old words: "
            f"{before['current_words']}"
        )

        print(
            f"  New words: "
            f"{count_words(new_text)}"
        )

        print(
            f"  Old: {before['text']}"
        )

        print(
            f"  New: {new_text}"
        )

    print(
        "\nVoice/timing/video metadata for changed "
        "scenes has been invalidated."
    )

    print(
        "Natural-speed TTS must now be regenerated "
        "and remeasured."
    )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
