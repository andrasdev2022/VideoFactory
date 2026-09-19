from __future__ import annotations

import argparse
import subprocess
import sys
import json
import os
import re

from pathlib import Path
from typing import Any
from validator import load_json
from datetime import datetime, timezone

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

SRC_DIR = (
    PROJECT_ROOT
    / "src"
)

JOB_FILE = (
    PROJECT_ROOT
    / "jobs"
    / "video_job.json"
)


GENERATED_STATUSES = {
    "generated",
    "completed",
    "passed",
}


VIDEO_SEMANTIC_QC_POLICY_VERSION = (
    "target_window_v4_static_fallback"
)


ACTION_GENERATE_IMAGE = (
    "generate_image"
)

ACTION_IMAGE_QC = (
    "image_qc"
)

ACTION_IMAGE_SEMANTIC_QC = (
    "image_semantic_qc"
)

ACTION_GENERATE_VIDEO = (
    "generate_video"
)

ACTION_STOP_TIMING = (
    "stop_timing_not_ready"
)

ACTION_VIDEO_QC = (
    "video_qc"
)

ACTION_VIDEO_SEMANTIC_QC = (
    "video_semantic_qc"
)

ACTION_TRIM_VIDEO = (
    "trim_video"
)

ACTION_RETRY_VIDEO_FROM_QC = (
    "retry_video_from_qc"
)

ACTION_SAFE_MOTION_FALLBACK = (
    "safe_motion_fallback"
)

ACTION_UPGRADE_SAFE_MOTION_POLICY = (
    "upgrade_safe_motion_policy"
)

ACTION_LOCAL_VIDEO_FALLBACK = (
    "local_video_fallback"
)

ACTION_UPGRADE_LOCAL_FALLBACK_POLICY = (
    "upgrade_local_fallback_policy"
)

ACTION_COMPLETE = (
    "complete"
)

ACTION_STOP_IMAGE = (
    "stop_image_attempts"
)

ACTION_STOP_VIDEO = (
    "stop_video_attempts"
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Run the Video Factory pipeline "
            "for one scene."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        required=True,
        help=(
            "Scene ID to process. "
            "Example: --scene 2"
        ),
    )

    parser.add_argument(
        "--max-image-attempts",
        type=int,
        default=2,
        help=(
            "Maximum image generations for "
            "the scene. Default: 2"
        ),
    )

    parser.add_argument(
        "--max-video-attempts",
        type=int,
        default=3,
        help=(
            "Maximum video generations for "
            "the scene. Default: 3"
        ),
    )

    parser.add_argument(
        "--reset-attempts",
        action="store_true",
        help=(
            "Reset the persistent image/video attempt "
            "counters for this scene before processing."
        ),
    )

    args = parser.parse_args()

    if args.max_image_attempts < 1:

        parser.error(
            "--max-image-attempts "
            "must be at least 1."
        )

    if args.max_video_attempts < 1:

        parser.error(
            "--max-video-attempts "
            "must be at least 1."
        )

    return args


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
            scene.get("scene_id")
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
            scene.get("scene_id")
            == scene_id
        ):

            return scene

    return None


def inspect_scene_state(
    job: dict,
    scene_id: int,
) -> dict[str, Any]:

    scene = find_visual_scene(
        job,
        scene_id,
    )

    if scene is None:

        raise RuntimeError(
            f"Visual scene {scene_id} "
            f"does not exist."
        )

    script_scene = find_script_scene(
        job,
        scene_id,
    )

    if script_scene is None:

        raise RuntimeError(
            f"Script scene {scene_id} "
            f"does not exist."
        )

    timing = script_scene.get(
        "timing",
        {},
    )

    image = scene.get(
        "image",
        {},
    )

    video = scene.get(
        "video",
        {},
    )

    image_qc = image.get(
        "qc",
        {},
    )

    image_semantic_qc = image.get(
        "semantic_qc",
        {},
    )

    video_qc = video.get(
        "qc",
        {},
    )

    video_semantic_qc = video.get(
        "semantic_qc",
        {},
    )

    trimmed = video.get(
        "trimmed",
        {},
    )

    return {

        "timing_status":
            timing.get(
                "status"
            ),

        "render_duration_sec":
            timing.get(
                "render_duration_sec"
            ),

        "script_revision_required":
            timing.get(
                "script_revision_required",
                False,
            ),

        "image_status":
            image.get(
                "status"
            ),

        "image_file":
            image.get(
                "file"
            ),

        "image_qc":
            image_qc.get(
                "status"
            ),

        "image_semantic_qc":
            image_semantic_qc.get(
                "status"
            ),

        "video_status":
            video.get(
                "status"
            ),

        "video_provider":
            video.get(
                "provider"
            ),

        "video_file":
            video.get(
                "file"
            ),

        "video_qc":
            video_qc.get(
                "status"
            ),

        "video_semantic_qc":
            video_semantic_qc.get(
                "status"
            ),

        "video_semantic_qc_policy_version":
            video_semantic_qc.get(
                "policy_version"
            ),

        "trimmed_status":
            trimmed.get(
                "status"
            ),

        "trimmed_file":
            trimmed.get(
                "file"
            ),

        "motion_strategy":
            scene.get(
                "motion_strategy"
            ),

        "semantic_motion_mode":
            scene
            .get(
                "semantic_qc_policy",
                {},
            )
            .get(
                "motion_mode"
            ),
    }


def infer_allowed_exit_character_ids(
    job: dict,
    scene_id: int,
) -> list[str]:

    script_scene = find_script_scene(
        job,
        scene_id,
    )

    visual_scene = find_visual_scene(
        job,
        scene_id,
    )

    if (
        script_scene is None
        or visual_scene is None
    ):

        return []

    visual = script_scene.get(
        "visual",
        {},
    )

    text_fragments = [
        str(
            value
        )
        for value in (
            visual.get(
                "description",
                ""
            ),
            visual.get(
                "camera",
                ""
            ),
            visual_scene.get(
                "continuity_notes",
                ""
            ),
        )
        if value
    ]

    # Keep inference local to one sentence/clause.
    #
    # The previous implementation searched a large character window
    # across concatenated text. In Scene 5 that allowed the phrase
    # "departing employee" attached to Mike to leak into the nearby
    # Mr. Whiskers context and incorrectly mark both characters as
    # allowed to leave.

    segments: list[str] = []

    for fragment in text_fragments:

        segments.extend(
            segment.strip().lower()
            for segment in re.split(
                r"[.!?;\n]+",
                fragment,
            )
            if segment.strip()
        )

    character_map = {
        character.get(
            "character_id"
        ):
            character.get(
                "name"
            )
        for character in job.get(
            "characters",
            [],
        )
        if character.get(
            "character_id"
        )
    }

    exit_markers = (
        " exits",
        " exit ",
        " leaves",
        " leave ",
        " departs",
        " departing",
        " walks toward",
        " walks to",
        " heads toward",
        " heads to",
        " moves toward the elevator",
        " toward the elevator",
    )

    allowed: list[str] = []

    for character_id in (
        visual_scene.get(
            "characters",
            [],
        )
        or []
    ):

        name = character_map.get(
            character_id
        )

        if not isinstance(
            name,
            str,
        ):

            continue

        lowered_name = name.lower()

        allowed_for_character = any(
            lowered_name in segment
            and any(
                marker in (
                    " "
                    + segment
                    + " "
                )
                for marker in exit_markers
            )
            for segment in segments
        )

        if allowed_for_character:

            allowed.append(
                character_id
            )

    return allowed


def build_safe_motion_prompt(
    job: dict,
    scene_id: int,
) -> str:

    scene = find_visual_scene(
        job,
        scene_id,
    )

    if scene is None:

        raise RuntimeError(
            f"Visual scene {scene_id} "
            f"does not exist."
        )

    allowed_exit_ids = (
        infer_allowed_exit_character_ids(
            job,
            scene_id,
        )
    )

    character_map = {
        character.get(
            "character_id"
        ):
            character.get(
                "name"
            )
        for character in job.get(
            "characters",
            [],
        )
        if character.get(
            "character_id"
        )
    }

    allowed_exit_names = [
        character_map.get(
            character_id,
            character_id,
        )
        for character_id in allowed_exit_ids
    ]

    fixed_names = [
        character_map.get(
            character_id,
            character_id,
        )
        for character_id in (
            scene.get(
                "characters",
                [],
            )
            or []
        )
        if character_id
        not in allowed_exit_ids
    ]

    parts = [
        (
            "Locked-off camera. Preserve the approved "
            "source-image identity, environment, and "
            "overall composition."
        ),
    ]

    if allowed_exit_names:

        parts.append(
            (
                f"{', '.join(allowed_exit_names)} may continue "
                f"the simple departure already implied by the "
                f"approved scene and may leave frame only as a "
                f"natural result of that departure. Do not "
                f"duplicate, teleport, disappear abruptly, or "
                f"reappear."
            )
        )

    if fixed_names:

        parts.append(
            (
                f"{', '.join(fixed_names)} remain clearly visible "
                f"in their source-image positions for the entire "
                f"shot."
            )
        )

    parts.append(
        (
            "No camera movement, scene change, new action, "
            "character duplication, or morphing. Keep all "
            "identity, clothing, anatomy, props, and background "
            "stable. Only subtle breathing, blinking, and tiny "
            "head movement besides the explicitly allowed "
            "departure. One continuous shot."
        )
    )

    return " ".join(
        parts
    )


def apply_safe_motion_fallback(
    job: dict,
    scene_id: int,
) -> str:

    scene = find_visual_scene(
        job,
        scene_id,
    )

    if scene is None:

        raise RuntimeError(
            f"Visual scene {scene_id} "
            f"does not exist."
        )

    old_prompt = (
        scene.get(
            "motion_prompt"
        )
        or ""
    )

    previous_video = (
        scene.get(
            "video",
            {}
        )
    )

    previous_semantic_qc = (
        previous_video
        .get(
            "semantic_qc",
            {}
        )
    )

    allowed_exit_ids = (
        infer_allowed_exit_character_ids(
            job,
            scene_id,
        )
    )

    new_prompt = build_safe_motion_prompt(
        job,
        scene_id,
    )

    history = scene.setdefault(
        "motion_prompt_history",
        [],
    )

    history.append(
        {
            "timestamp":
                utc_now_iso(),

            "reason":
                "semantic_qc_repeated_failure",

            "strategy":
                "safe_fallback_v2",

            "old_motion_prompt":
                old_prompt,

            "new_motion_prompt":
                new_prompt,

            "allowed_exit_character_ids":
                allowed_exit_ids,

            "previous_video_task_id":
                previous_video.get(
                    "task_id"
                ),

            "previous_semantic_qc_errors":
                list(
                    previous_semantic_qc.get(
                        "errors",
                        [],
                    )
                    or []
                ),

            "previous_semantic_qc_notes":
                previous_semantic_qc.get(
                    "overall_notes"
                ),
        }
    )

    scene[
        "motion_prompt"
    ] = new_prompt

    scene[
        "motion_strategy"
    ] = "safe_fallback_v2"

    scene[
        "semantic_qc_policy"
    ] = {
        "version":
            "safe_fallback_v2",

        "allowed_exit_character_ids":
            allowed_exit_ids,
    }

    scene.pop(
        "video",
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

    return new_prompt


def upgrade_safe_motion_policy_for_existing_video(
    job: dict,
    scene_id: int,
) -> str:

    scene = find_visual_scene(
        job,
        scene_id,
    )

    if scene is None:

        raise RuntimeError(
            f"Visual scene {scene_id} "
            f"does not exist."
        )

    video = scene.get(
        "video"
    )

    if not isinstance(
        video,
        dict,
    ):

        raise RuntimeError(
            f"Scene {scene_id}: existing video "
            f"is required for policy-only recovery."
        )

    allowed_exit_ids = (
        infer_allowed_exit_character_ids(
            job,
            scene_id,
        )
    )

    new_prompt = build_safe_motion_prompt(
        job,
        scene_id,
    )

    history = scene.setdefault(
        "motion_prompt_history",
        [],
    )

    history.append(
        {
            "timestamp":
                utc_now_iso(),

            "reason":
                "upgrade_safe_fallback_policy_for_existing_video",

            "strategy":
                "safe_fallback_v2",

            "old_motion_prompt":
                scene.get(
                    "motion_prompt",
                    ""
                ),

            "new_motion_prompt":
                new_prompt,

            "allowed_exit_character_ids":
                allowed_exit_ids,

            "preserved_video_task_id":
                video.get(
                    "task_id"
                ),
        }
    )

    scene[
        "motion_prompt"
    ] = new_prompt

    scene[
        "motion_strategy"
    ] = "safe_fallback_v2"

    scene[
        "semantic_qc_policy"
    ] = {
        "version":
            "safe_fallback_v2",

        "allowed_exit_character_ids":
            allowed_exit_ids,
    }

    video[
        "semantic_qc"
    ] = {
        "status":
            "pending",
    }

    video.pop(
        "trimmed",
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

    return new_prompt


def upgrade_local_fallback_policy_for_existing_video(
    job: dict,
    scene_id: int,
) -> str:

    scene = find_visual_scene(
        job,
        scene_id,
    )

    if scene is None:

        raise RuntimeError(
            f"Visual scene {scene_id} "
            f"does not exist."
        )

    video = scene.get(
        "video"
    )

    if not isinstance(
        video,
        dict,
    ):

        raise RuntimeError(
            f"Scene {scene_id}: existing fallback video "
            f"is required for policy-only recovery."
        )

    if scene.get(
        "motion_strategy"
    ) != "still_image_fallback_v1":

        raise RuntimeError(
            f"Scene {scene_id}: motion strategy is not "
            f"still_image_fallback_v1."
        )

    new_prompt = (
        "Deterministic static hold on the approved source image. "
        "No independent character or object motion is required. "
        "An imperceptible or extremely subtle camera push-in is "
        "acceptable but not required to be visually detectable. "
        "All characters, props, clothing, anatomy, background, "
        "and composition remain stable. No character duplication, "
        "no scene change, and no morphing."
    )

    history = scene.setdefault(
        "motion_prompt_history",
        [],
    )

    history.append(
        {
            "timestamp":
                utc_now_iso(),

            "reason":
                "upgrade_local_fallback_semantic_policy",

            "strategy":
                "still_image_fallback_v1",

            "old_motion_prompt":
                scene.get(
                    "motion_prompt",
                    ""
                ),

            "new_motion_prompt":
                new_prompt,

            "preserved_video_task_id":
                video.get(
                    "task_id"
                ),

            "video_regenerated":
                False,
        }
    )

    scene[
        "motion_prompt"
    ] = new_prompt

    scene[
        "semantic_qc_policy"
    ] = {
        "version":
            "still_image_fallback_v2",

        "motion_mode":
            "static_hold",

        "allowed_exit_character_ids":
            [],
    }

    video[
        "semantic_qc"
    ] = {
        "status":
            "pending",
    }

    video.pop(
        "trimmed",
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

    return new_prompt


def image_is_generated(
    state: dict[str, Any],
) -> bool:

    return (
        state.get("image_status")
        in GENERATED_STATUSES
        and bool(
            state.get(
                "image_file"
            )
        )
    )


def video_is_generated(
    state: dict[str, Any],
) -> bool:

    return (
        state.get("video_status")
        in GENERATED_STATUSES
        and bool(
            state.get(
                "video_file"
            )
        )
    )


def choose_next_action(
    state: dict[str, Any],
    image_attempts: int,
    video_attempts: int,
    max_image_attempts: int,
    max_video_attempts: int,
) -> str:

    # =====================================================
    # TIMING GATE
    # =====================================================

    if (
        state.get(
            "timing_status"
        )
        != "passed"
        or state.get(
            "render_duration_sec"
        )
        is None
    ):

        return ACTION_STOP_TIMING

    # =====================================================
    # IMAGE
    # =====================================================

    if not image_is_generated(
        state
    ):

        if (
            image_attempts
            >= max_image_attempts
        ):

            return ACTION_STOP_IMAGE

        return ACTION_GENERATE_IMAGE

    # -----------------------------------------------------
    # Image technical QC
    # -----------------------------------------------------

    image_qc = state.get(
        "image_qc"
    )

    if image_qc != "passed":

        if image_qc == "failed":

            if (
                image_attempts
                >= max_image_attempts
            ):

                return ACTION_STOP_IMAGE

            return ACTION_GENERATE_IMAGE

        return ACTION_IMAGE_QC

    # -----------------------------------------------------
    # Image semantic QC
    # -----------------------------------------------------

    image_semantic_qc = (
        state.get(
            "image_semantic_qc"
        )
    )

    if (
        image_semantic_qc
        != "passed"
    ):

        if (
            image_semantic_qc
            == "failed"
        ):

            if (
                image_attempts
                >= max_image_attempts
            ):

                return ACTION_STOP_IMAGE

            return ACTION_GENERATE_IMAGE

        return ACTION_IMAGE_SEMANTIC_QC

    # =====================================================
    # VIDEO
    # =====================================================

    if not video_is_generated(
        state
    ):

        # A provider failure during the deterministic safe-motion
        # Runway attempt should not abort the scene. The safe
        # strategy has already been exhausted, so switch directly
        # to the deterministic local still-image fallback instead
        # of spending another provider generation attempt.
        if (
            state.get(
                "video_status"
            )
            == "failed"
            and state.get(
                "motion_strategy"
            )
            == "safe_fallback_v2"
        ):

            return ACTION_LOCAL_VIDEO_FALLBACK

        if (
            video_attempts
            >= max_video_attempts
        ):

            return ACTION_STOP_VIDEO

        return ACTION_GENERATE_VIDEO

    # -----------------------------------------------------
    # Video technical QC
    # -----------------------------------------------------

    video_qc = state.get(
        "video_qc"
    )

    if video_qc != "passed":

        if video_qc == "failed":

            if (
                video_attempts
                >= max_video_attempts
            ):

                return ACTION_STOP_VIDEO

            return ACTION_GENERATE_VIDEO

        return ACTION_VIDEO_QC

    # -----------------------------------------------------
    # Video semantic QC
    # -----------------------------------------------------

    video_semantic_qc = (
        state.get(
            "video_semantic_qc"
        )
    )

    # Repeated Runway recovery is exhausted. If the
    # scene already used safe_fallback_v2, do not spend another
    # vision pass trying to salvage a manually invalid artifact.
    # Switch directly to the deterministic local fallback.

    if (
        video_semantic_qc
        == "failed"
        and state.get(
            "motion_strategy"
        )
        == "safe_fallback_v2"
    ):

        return ACTION_LOCAL_VIDEO_FALLBACK

    if (
        video_semantic_qc
        == "failed"
        and state.get(
            "motion_strategy"
        )
        == "still_image_fallback_v1"
    ):

        if (
            state.get(
                "semantic_motion_mode"
            )
            == "static_hold"
            and state.get(
                "video_semantic_qc_policy_version"
            )
            == VIDEO_SEMANTIC_QC_POLICY_VERSION
        ):

            return ACTION_STOP_VIDEO

        return ACTION_UPGRADE_LOCAL_FALLBACK_POLICY

    # A failed semantic result from an older QC policy must be
    # re-evaluated before spending another provider attempt.

    if (
        video_semantic_qc
        == "failed"
        and state.get(
            "video_semantic_qc_policy_version"
        )
        != VIDEO_SEMANTIC_QC_POLICY_VERSION
    ):

        if state.get(
            "motion_strategy"
        ) in {
            "safe_fallback_v1",
            "safe_fallback_v2",
        }:

            return ACTION_UPGRADE_SAFE_MOTION_POLICY

        return ACTION_VIDEO_SEMANTIC_QC

    if (
        video_semantic_qc
        == "passed"
    ):

        if (
            state.get(
                "trimmed_status"
            )
            != "passed"
            or not state.get(
                "trimmed_file"
            )
        ):

            return ACTION_TRIM_VIDEO

        return ACTION_COMPLETE

    if (
        video_semantic_qc
        == "failed"
    ):

        if (
            state.get(
                "motion_strategy"
            )
            == "safe_fallback_v1"
        ):

            return ACTION_UPGRADE_SAFE_MOTION_POLICY

        if (
            state.get(
                "motion_strategy"
            )
            == "safe_fallback_v2"
        ):

            return ACTION_LOCAL_VIDEO_FALLBACK

        if (
            state.get(
                "motion_strategy"
            )
            == "still_image_fallback_v1"
        ):

            if (
                state.get(
                    "semantic_motion_mode"
                )
                == "static_hold"
                and state.get(
                    "video_semantic_qc_policy_version"
                )
                == VIDEO_SEMANTIC_QC_POLICY_VERSION
            ):

                return ACTION_STOP_VIDEO

            return ACTION_UPGRADE_LOCAL_FALLBACK_POLICY

        if (
            video_attempts
            >= max_video_attempts
        ):

            return ACTION_STOP_VIDEO

        # First generated video failed semantic QC.
        #
        # Retry once using semantic QC feedback.

        if video_attempts <= 1:

            return (
                ACTION_RETRY_VIDEO_FROM_QC
            )

        # A second semantic failure means the motion
        # strategy itself is too fragile. Do not ask
        # another model for another potentially complex
        # motion plan. Switch to a deterministic,
        # locked-camera safe fallback for the final
        # allowed generation attempt.

        return ACTION_SAFE_MOTION_FALLBACK

    return ACTION_VIDEO_SEMANTIC_QC


def infer_initial_attempts(
    state: dict[str, Any],
) -> tuple[int, int]:

    image_attempts = 0
    video_attempts = 0

    if (
        state.get(
            "image_status"
        )
        in GENERATED_STATUSES
        or state.get(
            "image_status"
        )
        == "failed"
        or state.get(
            "image_file"
        )
    ):

        image_attempts = 1

    if (
        state.get(
            "video_status"
        )
        in GENERATED_STATUSES
        or state.get(
            "video_status"
        )
        == "failed"
        or state.get(
            "video_file"
        )
    ):

        video_attempts = 1

    return (
        image_attempts,
        video_attempts,
    )

def utc_now_iso() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

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

def derive_orchestration_state(
    observed_state: dict[str, Any],
) -> str:

    if (
        observed_state.get(
            "video_semantic_qc"
        )
        == "passed"
    ):

        return "completed"

    return "in_progress"

def append_orchestration_history(
    orchestration_scene: dict,
    action: str,
    result: str,
    details: dict[str, Any] | None = None,
) -> None:

    history = (
        orchestration_scene
        .setdefault(
            "history",
            [],
        )
    )

    entry = {
        "timestamp":
            utc_now_iso(),

        "action":
            action,

        "result":
            result,

        "image_attempts":
            orchestration_scene.get(
                "image_attempts",
                0,
            ),

        "video_attempts":
            orchestration_scene.get(
                "video_attempts",
                0,
            ),
    }

    if details:

        entry["details"] = details

    history.append(
        entry
    )

    # Prevent the job file from growing forever.
    if len(history) > 100:

        del history[:-100]

def get_or_create_scene_orchestration(
    job: dict,
    scene_id: int,
    observed_state: dict[str, Any],
) -> dict:

    orchestration = (
        job.setdefault(
            "orchestration",
            {},
        )
    )

    scene_states = (
        orchestration.setdefault(
            "scenes",
            {},
        )
    )

    scene_key = str(
        scene_id
    )

    existing = (
        scene_states.get(
            scene_key
        )
    )

    if existing is not None:

        existing.setdefault(
            "image_attempts",
            0,
        )

        existing.setdefault(
            "video_attempts",
            0,
        )

        existing.setdefault(
            "last_action",
            None,
        )

        existing.setdefault(
            "state",
            derive_orchestration_state(
                observed_state
            ),
        )

        existing.setdefault(
            "history",
            [],
        )

        existing["updated_at"] = (
            utc_now_iso()
        )

        return existing

    (
        inferred_image_attempts,
        inferred_video_attempts,
    ) = infer_initial_attempts(
        observed_state
    )

    created = {
        "image_attempts":
            inferred_image_attempts,

        "video_attempts":
            inferred_video_attempts,

        "last_action":
            None,

        "state":
            derive_orchestration_state(
                observed_state
            ),

        "created_at":
            utc_now_iso(),

        "updated_at":
            utc_now_iso(),

        "history":
            [],
    }

    scene_states[
        scene_key
    ] = created

    append_orchestration_history(
        created,
        action="state_migration",
        result="initialized",
        details={
            "inferred_from_existing_artifacts":
                True,
        },
    )

    return created

def reset_scene_attempts(
    job: dict,
    scene_id: int,
    observed_state: dict[str, Any],
) -> dict:

    orchestration_scene = (
        get_or_create_scene_orchestration(
            job,
            scene_id,
            observed_state,
        )
    )

    orchestration_scene[
        "image_attempts"
    ] = 0

    orchestration_scene[
        "video_attempts"
    ] = 0

    orchestration_scene[
        "last_action"
    ] = "reset_attempts"

    orchestration_scene[
        "state"
    ] = derive_orchestration_state(
        observed_state
    )

    orchestration_scene[
        "updated_at"
    ] = utc_now_iso()

    append_orchestration_history(
        orchestration_scene,
        action="reset_attempts",
        result="completed",
    )

    return orchestration_scene

def start_generation_attempt(
    job: dict,
    scene_id: int,
    observed_state: dict[str, Any],
    counter_name: str,
    action: str,
) -> int:

    if counter_name not in {
        "image_attempts",
        "video_attempts",
    }:

        raise ValueError(
            f"Unsupported attempt counter: "
            f"{counter_name}"
        )

    orchestration_scene = (
        get_or_create_scene_orchestration(
            job,
            scene_id,
            observed_state,
        )
    )

    orchestration_scene[
        counter_name
    ] = (
        orchestration_scene.get(
            counter_name,
            0,
        )
        + 1
    )

    orchestration_scene[
        "last_action"
    ] = action

    orchestration_scene[
        "state"
    ] = "running"

    orchestration_scene[
        "updated_at"
    ] = utc_now_iso()

    append_orchestration_history(
        orchestration_scene,
        action=action,
        result="started",
    )

    return orchestration_scene[
        counter_name
    ]

def record_orchestration_result(
    job: dict,
    scene_id: int,
    observed_state: dict[str, Any],
    action: str,
    result: str,
    orchestration_state: str = "in_progress",
    details: dict[str, Any] | None = None,
) -> dict:

    scene_state = (
        get_or_create_scene_orchestration(
            job,
            scene_id,
            observed_state,
        )
    )

    scene_state[
        "last_action"
    ] = action

    scene_state[
        "state"
    ] = orchestration_state

    scene_state[
        "updated_at"
    ] = utc_now_iso()

    append_orchestration_history(
        scene_state,
        action=action,
        result=result,
        details=details,
    )

    return scene_state

def load_persistent_attempts(
    job: dict,
    scene_id: int,
    observed_state: dict[str, Any],
) -> tuple[int, int]:

    orchestration_scene = (
        get_or_create_scene_orchestration(
            job,
            scene_id,
            observed_state,
        )
    )

    return (
        int(
            orchestration_scene.get(
                "image_attempts",
                0,
            )
        ),
        int(
            orchestration_scene.get(
                "video_attempts",
                0,
            )
        ),
    )

def run_worker(
    script_name: str,
    arguments: list[str],
) -> int:

    script_path = (
        SRC_DIR
        / script_name
    )

    command = [
        sys.executable,
        str(script_path),
        *arguments,
    ]

    print(
        "\n" + "-" * 60
    )

    print(
        "RUN:"
    )

    print(
        " ".join(
            command
        )
    )

    print(
        "-" * 60
    )

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
    )

    return (
        completed.returncode
    )


def print_scene_state(
    state: dict[str, Any],
) -> None:

    print(
        "\nCurrent scene state:"
    )

    print(
        f"  timing:            "
        f"{state.get('timing_status')}"
    )

    print(
        f"  render duration:   "
        f"{state.get('render_duration_sec')}"
    )

    print(
        f"  image:             "
        f"{state.get('image_status')}"
    )

    print(
        f"  image QC:          "
        f"{state.get('image_qc')}"
    )

    print(
        f"  image semantic QC: "
        f"{state.get('image_semantic_qc')}"
    )

    print(
        f"  video:             "
        f"{state.get('video_status')}"
    )

    print(
        f"  video QC:          "
        f"{state.get('video_qc')}"
    )

    print(
        f"  video semantic QC: "
        f"{state.get('video_semantic_qc')}"
    )

    print(
        f"  trimmed video:     "
        f"{state.get('trimmed_status')}"
    )


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - SCENE ORCHESTRATOR v8")
    print("=" * 60)

    args = parse_args()

    # -----------------------------------------------------
    # Initial job load
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

    script_scene = (
        find_script_scene(
            job,
            args.scene,
        )
    )

    if script_scene is None:

        print(
            f"\nERROR: script scene "
            f"{args.scene} does not exist."
        )

        return 1

    visual_scene = (
        find_visual_scene(
            job,
            args.scene,
        )
    )

    if visual_scene is None:

        print(
            f"\nERROR: visual scene "
            f"{args.scene} does not exist."
        )

        print(
            "Generate visual prompts first."
        )

        return 1

    try:

        initial_state = (
            inspect_scene_state(
                job,
                args.scene,
            )
        )

    except Exception as exc:

        print(
            f"\nERROR: {exc}"
        )

        return 1

    # -----------------------------------------------------
    # Persistent orchestrator state
    # -----------------------------------------------------

    if args.reset_attempts:

        orchestration_scene = (
            reset_scene_attempts(
                job,
                args.scene,
                initial_state,
            )
        )

        save_job_atomic(
            job
        )

        print(
            "\nPersistent attempt counters reset."
        )

    else:

        orchestration_scene = (
            get_or_create_scene_orchestration(
                job,
                args.scene,
                initial_state,
            )
        )

        save_job_atomic(
            job
        )

    print(
        f"\nJob ID: "
        f"{job.get('job_id')}"
    )

    print(
        f"Scene: "
        f"{args.scene}"
    )

    print(
        f"Max image attempts: "
        f"{args.max_image_attempts}"
    )

    print(
        f"Max video attempts: "
        f"{args.max_video_attempts}"
    )

    print(
        f"Persistent image attempts: "
        f"{orchestration_scene.get('image_attempts', 0)}"
    )

    print(
        f"Persistent video attempts: "
        f"{orchestration_scene.get('video_attempts', 0)}"
    )

    print_scene_state(
        initial_state
    )

    max_orchestrator_steps = 30

    # =====================================================
    # ORCHESTRATION LOOP
    # =====================================================

    for step in range(
        1,
        max_orchestrator_steps + 1,
    ):

        try:

            job = load_json(
                JOB_FILE
            )

            state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            (
                image_attempts,
                video_attempts,
            ) = load_persistent_attempts(
                job,
                args.scene,
                state,
            )

            save_job_atomic(
                job
            )

        except Exception as exc:

            print(
                f"\nERROR reloading job state:\n"
                f"{exc}"
            )

            return 1

        action = choose_next_action(
            state=state,
            image_attempts=
                image_attempts,
            video_attempts=
                video_attempts,
            max_image_attempts=
                args.max_image_attempts,
            max_video_attempts=
                args.max_video_attempts,
        )

        print(
            f"\n[Step {step}] "
            f"Next action: {action}"
        )

        print(
            f"  image attempts: "
            f"{image_attempts}/"
            f"{args.max_image_attempts}"
        )

        print(
            f"  video attempts: "
            f"{video_attempts}/"
            f"{args.max_video_attempts}"
        )

        # =================================================
        # COMPLETE
        # =================================================

        if action == ACTION_COMPLETE:

            record_orchestration_result(
                job,
                args.scene,
                state,
                action=ACTION_COMPLETE,
                result="passed",
                orchestration_state=
                    "completed",
            )

            save_job_atomic(
                job
            )

            print_scene_state(
                state
            )

            print(
                "\n" + "=" * 60
            )

            print(
                f"SCENE {args.scene} COMPLETE"
            )

            print(
                "=" * 60
            )

            print(
                f"\nPersistent image generations: "
                f"{image_attempts}"
            )

            print(
                f"Persistent video generations: "
                f"{video_attempts}"
            )

            return 0

        # =================================================
        # STOP TIMING
        # =================================================

        if (
            action
            == ACTION_STOP_TIMING
        ):

            record_orchestration_result(
                job,
                args.scene,
                state,
                action=ACTION_STOP_TIMING,
                result="timing_not_ready",
                orchestration_state=
                    "failed",
                details={
                    "timing_status":
                        state.get(
                            "timing_status"
                        ),
                    "render_duration_sec":
                        state.get(
                            "render_duration_sec"
                        ),
                    "script_revision_required":
                        state.get(
                            "script_revision_required",
                            False,
                        ),
                },
            )

            save_job_atomic(
                job
            )

            print_scene_state(
                state
            )

            print(
                f"\nERROR: Scene {args.scene} "
                f"cannot continue to image/video generation "
                f"until natural voice timing has passed."
            )

            if state.get(
                "script_revision_required"
            ):

                print(
                    "Script revision is required first."
                )

            return 1

        # =================================================
        # STOP IMAGE
        # =================================================

        if (
            action
            == ACTION_STOP_IMAGE
        ):

            record_orchestration_result(
                job,
                args.scene,
                state,
                action=ACTION_STOP_IMAGE,
                result="attempt_limit_reached",
                orchestration_state=
                    "failed",
                details={
                    "max_image_attempts":
                        args.max_image_attempts,
                },
            )

            save_job_atomic(
                job
            )

            print_scene_state(
                state
            )

            print(
                f"\nERROR: Scene "
                f"{args.scene} exceeded "
                f"the maximum number of "
                f"image attempts "
                f"({args.max_image_attempts})."
            )

            return 1

        # =================================================
        # STOP VIDEO
        # =================================================

        if (
            action
            == ACTION_STOP_VIDEO
        ):

            record_orchestration_result(
                job,
                args.scene,
                state,
                action=ACTION_STOP_VIDEO,
                result="attempt_limit_reached",
                orchestration_state=
                    "failed",
                details={
                    "max_video_attempts":
                        args.max_video_attempts,
                },
            )

            save_job_atomic(
                job
            )

            print_scene_state(
                state
            )

            print(
                f"\nERROR: Scene "
                f"{args.scene} exceeded "
                f"the maximum number of "
                f"video attempts "
                f"({args.max_video_attempts})."
            )

            return 1

        # =================================================
        # IMAGE GENERATION
        # =================================================

        if (
            action
            == ACTION_GENERATE_IMAGE
        ):

            current_attempt = (
                start_generation_attempt(
                    job,
                    args.scene,
                    state,
                    counter_name=
                        "image_attempts",
                    action=
                        ACTION_GENERATE_IMAGE,
                )
            )

            save_job_atomic(
                job
            )

            print(
                f"\nStarting image attempt "
                f"{current_attempt}/"
                f"{args.max_image_attempts}"
            )

            rc = run_worker(
                "image_generator.py",
                [
                    "--mode",
                    "scene_image",

                    "--scene",
                    str(
                        args.scene
                    ),

                    "--force",
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_GENERATE_IMAGE,
                result=(
                    "completed"
                    if rc == 0
                    else "worker_failed"
                ),
                details={
                    "return_code":
                        rc,
                },
            )

            save_job_atomic(
                job
            )

            if rc != 0:

                print(
                    "\nERROR: image generator "
                    "returned non-zero exit code."
                )

                return 1

            continue

        # =================================================
        # IMAGE QC
        # =================================================

        if (
            action
            == ACTION_IMAGE_QC
        ):

            rc = run_worker(
                "image_qc.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            qc_result = (
                new_state.get(
                    "image_qc"
                )
                or "unknown"
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_IMAGE_QC,
                result=
                    qc_result,
                details={
                    "return_code":
                        rc,
                },
            )

            save_job_atomic(
                job
            )

            continue

        # =================================================
        # IMAGE SEMANTIC QC
        # =================================================

        if (
            action
            == ACTION_IMAGE_SEMANTIC_QC
        ):

            rc = run_worker(
                "image_semantic_qc.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            semantic_result = (
                new_state.get(
                    "image_semantic_qc"
                )
                or "unknown"
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_IMAGE_SEMANTIC_QC,
                result=
                    semantic_result,
                details={
                    "return_code":
                        rc,
                },
            )

            save_job_atomic(
                job
            )

            continue

        # =================================================
        # NORMAL VIDEO GENERATION
        # =================================================

        if (
            action
            == ACTION_GENERATE_VIDEO
        ):

            current_attempt = (
                start_generation_attempt(
                    job,
                    args.scene,
                    state,
                    counter_name=
                        "video_attempts",
                    action=
                        ACTION_GENERATE_VIDEO,
                )
            )

            save_job_atomic(
                job
            )

            print(
                f"\nStarting video attempt "
                f"{current_attempt}/"
                f"{args.max_video_attempts}"
            )

            rc = run_worker(
                "image_to_video_generator.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),

                    "--force",
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_GENERATE_VIDEO,
                result=(
                    "completed"
                    if rc == 0
                    else "worker_failed"
                ),
                details={
                    "return_code":
                        rc,
                    "attempt":
                        current_attempt,
                },
            )

            save_job_atomic(
                job
            )

            if rc != 0:

                print(
                    "\nERROR: video generator "
                    "returned non-zero exit code."
                )

                return 1

            continue

        # =================================================
        # VIDEO QC
        # =================================================

        if (
            action
            == ACTION_VIDEO_QC
        ):

            rc = run_worker(
                "video_qc.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            qc_result = (
                new_state.get(
                    "video_qc"
                )
                or "unknown"
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_VIDEO_QC,
                result=
                    qc_result,
                details={
                    "return_code":
                        rc,
                },
            )

            save_job_atomic(
                job
            )

            continue

        # =================================================
        # VIDEO SEMANTIC QC
        # =================================================

        if (
            action
            == ACTION_VIDEO_SEMANTIC_QC
        ):

            rc = run_worker(
                "video_semantic_qc.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            semantic_result = (
                new_state.get(
                    "video_semantic_qc"
                )
                or "unknown"
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_VIDEO_SEMANTIC_QC,
                result=
                    semantic_result,
                details={
                    "return_code":
                        rc,
                },
            )

            save_job_atomic(
                job
            )

            continue

        # =================================================
        # EXACT VIDEO TRIM
        # =================================================

        if (
            action
            == ACTION_TRIM_VIDEO
        ):

            rc = run_worker(
                "scene_video_trimmer.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            trim_result = (
                new_state.get(
                    "trimmed_status"
                )
                or "unknown"
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_TRIM_VIDEO,
                result=
                    trim_result,
                details={
                    "return_code":
                        rc,
                },
            )

            save_job_atomic(
                job
            )

            if rc != 0:

                print(
                    "\nERROR: exact scene trim failed."
                )

                return 1

            continue

        # =================================================
        # FIRST VIDEO SEMANTIC FAILURE
        # =================================================

        if (
            action
            == ACTION_RETRY_VIDEO_FROM_QC
        ):

            print(
                "\nVideo semantic QC failed."
            )

            print(
                "Strategy: retry video using "
                "semantic QC feedback."
            )

            current_attempt = (
                start_generation_attempt(
                    job,
                    args.scene,
                    state,
                    counter_name=
                        "video_attempts",
                    action=
                        ACTION_RETRY_VIDEO_FROM_QC,
                )
            )

            save_job_atomic(
                job
            )

            print(
                f"Starting video attempt "
                f"{current_attempt}/"
                f"{args.max_video_attempts}"
            )

            rc = run_worker(
                "image_to_video_generator.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),

                    "--retry-from-qc",
                ],
            )

            job = load_json(
                JOB_FILE
            )

            new_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                new_state,
                action=
                    ACTION_RETRY_VIDEO_FROM_QC,
                result=(
                    "completed"
                    if rc == 0
                    else "worker_failed"
                ),
                details={
                    "return_code":
                        rc,
                    "attempt":
                        current_attempt,
                },
            )

            save_job_atomic(
                job
            )

            if rc != 0:

                print(
                    "\nERROR: QC-based video "
                    "retry failed."
                )

                return 1

            continue

        # =================================================
        # UPGRADE LEGACY SAFE FALLBACK POLICY
        # =================================================

        if (
            action
            == ACTION_UPGRADE_SAFE_MOTION_POLICY
        ):

            print(
                "\nUpgrading safe fallback policy "
                "without regenerating the video."
            )

            try:

                upgraded_prompt = (
                    upgrade_safe_motion_policy_for_existing_video(
                        job,
                        args.scene,
                    )
                )

            except Exception as exc:

                record_orchestration_result(
                    job,
                    args.scene,
                    state,
                    action=
                        ACTION_UPGRADE_SAFE_MOTION_POLICY,
                    result=
                        "upgrade_failed",
                    orchestration_state=
                        "failed",
                    details={
                        "error":
                            str(
                                exc
                            ),
                    },
                )

                save_job_atomic(
                    job
                )

                print(
                    f"\nERROR upgrading safe "
                    f"motion policy:\n{exc}"
                )

                return 1

            upgraded_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                upgraded_state,
                action=
                    ACTION_UPGRADE_SAFE_MOTION_POLICY,
                result="applied",
                details={
                    "motion_prompt":
                        upgraded_prompt,

                    "video_regenerated":
                        False,
                },
            )

            save_job_atomic(
                job
            )

            print(
                f"  Updated prompt: "
                f"{upgraded_prompt}"
            )

            print(
                "  Existing Runway video preserved."
            )

            continue

        # =================================================
        # REPEATED VIDEO SEMANTIC FAILURE
        # =================================================

        if (
            action
            == ACTION_SAFE_MOTION_FALLBACK
        ):

            print(
                "\nVideo semantic QC failed again."
            )

            print(
                "Strategy change: deterministic "
                "safe motion fallback."
            )

            try:

                safe_prompt = (
                    apply_safe_motion_fallback(
                        job,
                        args.scene,
                    )
                )

            except Exception as exc:

                record_orchestration_result(
                    job,
                    args.scene,
                    state,
                    action=
                        ACTION_SAFE_MOTION_FALLBACK,
                    result=
                        "fallback_failed",
                    orchestration_state=
                        "failed",
                    details={
                        "error":
                            str(
                                exc
                            ),
                    },
                )

                save_job_atomic(
                    job
                )

                print(
                    f"\nERROR applying safe "
                    f"motion fallback:\n{exc}"
                )

                return 1

            fallback_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                fallback_state,
                action=
                    ACTION_SAFE_MOTION_FALLBACK,
                result="applied",
                details={
                    "motion_prompt":
                        safe_prompt,
                },
            )

            current_attempt = (
                start_generation_attempt(
                    job,
                    args.scene,
                    fallback_state,
                    counter_name=
                        "video_attempts",
                    action=
                        ACTION_SAFE_MOTION_FALLBACK,
                )
            )

            save_job_atomic(
                job
            )

            print(
                f"  Safe prompt: {safe_prompt}"
            )

            print(
                f"\nStarting video attempt "
                f"{current_attempt}/"
                f"{args.max_video_attempts}"
            )

            rc = run_worker(
                "image_to_video_generator.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),

                    "--force",
                ],
            )

            job = load_json(
                JOB_FILE
            )

            final_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                final_state,
                action=
                    ACTION_SAFE_MOTION_FALLBACK,
                result=(
                    "completed"
                    if rc == 0
                    else "worker_failed"
                ),
                details={
                    "return_code":
                        rc,
                    "attempt":
                        current_attempt,
                    "strategy":
                        "safe_fallback_v1",
                },
            )

            save_job_atomic(
                job
            )

            if rc != 0:

                print(
                    "\nWARNING: Runway generation with the "
                    "safe-motion fallback failed."
                )

                print(
                    "Switching to deterministic local "
                    "still-image fallback."
                )

                # Keep the scene orchestrator alive. The failed
                # provider artifact is recorded in job state, and
                # choose_next_action() will route safe_fallback_v2
                # directly to ACTION_LOCAL_VIDEO_FALLBACK.
                continue

            continue

        # =================================================
        # UPGRADE LOCAL FALLBACK SEMANTIC POLICY
        # =================================================

        if (
            action
            == ACTION_UPGRADE_LOCAL_FALLBACK_POLICY
        ):

            print(
                "\nUpgrading deterministic fallback "
                "semantic policy without regenerating video."
            )

            try:

                updated_prompt = (
                    upgrade_local_fallback_policy_for_existing_video(
                        job,
                        args.scene,
                    )
                )

            except Exception as exc:

                record_orchestration_result(
                    job,
                    args.scene,
                    state,
                    action=
                        ACTION_UPGRADE_LOCAL_FALLBACK_POLICY,
                    result=
                        "upgrade_failed",
                    orchestration_state=
                        "failed",
                    details={
                        "error":
                            str(
                                exc
                            ),
                    },
                )

                save_job_atomic(
                    job
                )

                print(
                    f"\nERROR upgrading local "
                    f"fallback policy:\n{exc}"
                )

                return 1

            upgraded_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                upgraded_state,
                action=
                    ACTION_UPGRADE_LOCAL_FALLBACK_POLICY,
                result="applied",
                details={
                    "motion_prompt":
                        updated_prompt,

                    "video_regenerated":
                        False,
                },
            )

            save_job_atomic(
                job
            )

            print(
                f"  Updated prompt: "
                f"{updated_prompt}"
            )

            print(
                "  Existing local fallback video preserved."
            )

            continue

        # =================================================
        # LOCAL DETERMINISTIC VIDEO FALLBACK
        # =================================================

        if (
            action
            == ACTION_LOCAL_VIDEO_FALLBACK
        ):

            print(
                "\nRunway recovery exhausted."
            )

            print(
                "Strategy change: deterministic "
                "local still-image video fallback."
            )

            record_orchestration_result(
                job,
                args.scene,
                state,
                action=
                    ACTION_LOCAL_VIDEO_FALLBACK,
                result="started",
                details={
                    "video_attempts":
                        video_attempts,
                },
            )

            save_job_atomic(
                job
            )

            rc = run_worker(
                "scene_video_fallback.py",
                [
                    "--scene",
                    str(
                        args.scene
                    ),

                    "--force",
                ],
            )

            job = load_json(
                JOB_FILE
            )

            fallback_state = (
                inspect_scene_state(
                    job,
                    args.scene,
                )
            )

            record_orchestration_result(
                job,
                args.scene,
                fallback_state,
                action=
                    ACTION_LOCAL_VIDEO_FALLBACK,
                result=(
                    "completed"
                    if rc == 0
                    else "worker_failed"
                ),
                details={
                    "return_code":
                        rc,

                    "runway_attempts_preserved":
                        video_attempts,
                },
            )

            save_job_atomic(
                job
            )

            if rc != 0:

                print(
                    "\nERROR: local deterministic "
                    "video fallback failed."
                )

                return 1

            continue

        # =================================================
        # UNKNOWN ACTION
        # =================================================

        record_orchestration_result(
            job,
            args.scene,
            state,
            action=str(
                action
            ),
            result="unknown_action",
            orchestration_state=
                "failed",
        )

        save_job_atomic(
            job
        )

        print(
            f"\nERROR: unknown orchestrator "
            f"action: {action}"
        )

        return 1

    # -----------------------------------------------------
    # Internal loop protection
    # -----------------------------------------------------

    job = load_json(
        JOB_FILE
    )

    state = (
        inspect_scene_state(
            job,
            args.scene,
        )
    )

    record_orchestration_result(
        job,
        args.scene,
        state,
        action=
            "orchestrator_step_limit",
        result=
            "step_limit_reached",
        orchestration_state=
            "failed",
    )

    save_job_atomic(
        job
    )

    print(
        "\nERROR: orchestrator exceeded "
        "maximum internal step count."
    )

    return 1

if __name__ == "__main__":

    raise SystemExit(
        main()
    )