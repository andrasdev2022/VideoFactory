from __future__ import annotations

from typing import Any


PIPELINE_STAGES = (
    "script",
    "visual_prompts",
    "character_reference_prompts",
    "character_references",
    "scene_images",
    "image_qc",
    "image_semantic_qc",
    "scene_videos",
    "video_qc",
    "video_semantic_qc",
    "scene_trimmed",
    "voiceovers",
    "voice_qc",
    "scene_timing",
    "global_timing",
)

def _make_summary(
    total: int,
    ready: int,
    failed: int = 0,
) -> dict[str, Any]:

    total = max(0, total)
    ready = max(0, ready)
    failed = max(0, failed)

    pending = max(
        total - ready - failed,
        0,
    )

    if total == 0:
        state = "pending"

    elif failed > 0:
        state = "failed"

    elif ready == total:
        state = "completed"

    elif ready > 0:
        state = "partial"

    else:
        state = "pending"

    return {
        "state": state,
        "total": total,
        "ready": ready,
        "failed": failed,
        "pending": pending,
    }


def _get_script_scenes(
    job: dict,
) -> list[dict]:

    return (
        job
        .get("script", {})
        .get("scenes", [])
    )


def _get_visual_scenes(
    job: dict,
) -> list[dict]:

    return (
        job
        .get("visuals", {})
        .get("scenes", [])
    )


def _get_characters(
    job: dict,
) -> list[dict]:

    return job.get(
        "characters",
        [],
    )


def _get_expected_scene_ids(
    job: dict,
) -> list[int]:

    result = []

    for scene in _get_script_scenes(job):

        scene_id = scene.get(
            "scene_id"
        )

        if scene_id is not None:
            result.append(scene_id)

    return result


def _get_visual_scene_map(
    job: dict,
) -> dict[int, dict]:

    result = {}

    for scene in _get_visual_scenes(job):

        scene_id = scene.get(
            "scene_id"
        )

        if scene_id is not None:
            result[scene_id] = scene

    return result


def _status_counts_for_scene_field(
    job: dict,
    path: tuple[str, ...],
) -> tuple[int, int, int]:

    expected_ids = (
        _get_expected_scene_ids(job)
    )

    visual_map = (
        _get_visual_scene_map(job)
    )

    ready = 0
    failed = 0

    for scene_id in expected_ids:

        scene = visual_map.get(
            scene_id,
            {},
        )

        value: Any = scene

        for key in path:

            if not isinstance(
                value,
                dict,
            ):
                value = None
                break

            value = value.get(key)

        if value == "passed":
            ready += 1

        elif value == "failed":
            failed += 1

    return (
        len(expected_ids),
        ready,
        failed,
    )


def _compute_script_status(
    job: dict,
) -> dict[str, Any]:

    scenes = _get_script_scenes(
        job
    )

    if not scenes:

        return _make_summary(
            total=1,
            ready=0,
        )

    return _make_summary(
        total=len(scenes),
        ready=len(scenes),
    )


def _compute_visual_prompts_status(
    job: dict,
) -> dict[str, Any]:

    expected_ids = (
        _get_expected_scene_ids(job)
    )

    visual_map = (
        _get_visual_scene_map(job)
    )

    ready = 0

    for scene_id in expected_ids:

        scene = visual_map.get(
            scene_id,
            {},
        )

        image_prompt = (
            scene.get(
                "image_prompt"
            )
        )

        motion_prompt = (
            scene.get(
                "motion_prompt"
            )
        )

        if (
            isinstance(
                image_prompt,
                str,
            )
            and image_prompt.strip()
            and isinstance(
                motion_prompt,
                str,
            )
            and motion_prompt.strip()
        ):

            ready += 1

    return _make_summary(
        total=len(expected_ids),
        ready=ready,
    )


def _compute_character_reference_prompts_status(
    job: dict,
) -> dict[str, Any]:

    characters = (
        _get_characters(job)
    )

    ready = 0
    failed = 0

    for character in characters:

        reference = (
            character.get(
                "reference",
                {},
            )
        )

        status = reference.get(
            "status"
        )

        if status == "failed":

            failed += 1
            continue

        prompt = reference.get(
            "prompt"
        )

        signature = reference.get(
            "visual_signature"
        )

        if (
            isinstance(
                prompt,
                str,
            )
            and prompt.strip()
            and isinstance(
                signature,
                str,
            )
            and signature.strip()
        ):

            ready += 1

    return _make_summary(
        total=len(characters),
        ready=ready,
        failed=failed,
    )


def _compute_character_references_status(
    job: dict,
) -> dict[str, Any]:

    characters = (
        _get_characters(job)
    )

    ready = 0
    failed = 0

    for character in characters:

        reference = (
            character.get(
                "reference",
                {},
            )
        )

        status = reference.get(
            "status"
        )

        if status == "failed":

            failed += 1
            continue

        image_file = reference.get(
            "image_file"
        )

        if (
            status
            in {
                "generated",
                "completed",
                "passed",
            }
            and image_file
        ):

            ready += 1

    return _make_summary(
        total=len(characters),
        ready=ready,
        failed=failed,
    )


def _compute_scene_images_status(
    job: dict,
) -> dict[str, Any]:

    expected_ids = (
        _get_expected_scene_ids(job)
    )

    visual_map = (
        _get_visual_scene_map(job)
    )

    ready = 0
    failed = 0

    for scene_id in expected_ids:

        scene = visual_map.get(
            scene_id,
            {},
        )

        image = scene.get(
            "image",
            {},
        )

        status = image.get(
            "status"
        )

        if status == "failed":

            failed += 1
            continue

        image_file = image.get(
            "file"
        )

        if (
            status
            in {
                "generated",
                "completed",
                "passed",
            }
            and image_file
        ):

            ready += 1

    return _make_summary(
        total=len(expected_ids),
        ready=ready,
        failed=failed,
    )


def _compute_image_qc_status(
    job: dict,
) -> dict[str, Any]:

    total, ready, failed = (
        _status_counts_for_scene_field(
            job,
            (
                "image",
                "qc",
                "status",
            ),
        )
    )

    return _make_summary(
        total=total,
        ready=ready,
        failed=failed,
    )


def _compute_image_semantic_qc_status(
    job: dict,
) -> dict[str, Any]:

    total, ready, failed = (
        _status_counts_for_scene_field(
            job,
            (
                "image",
                "semantic_qc",
                "status",
            ),
        )
    )

    return _make_summary(
        total=total,
        ready=ready,
        failed=failed,
    )


def _compute_scene_videos_status(
    job: dict,
) -> dict[str, Any]:

    expected_ids = (
        _get_expected_scene_ids(job)
    )

    visual_map = (
        _get_visual_scene_map(job)
    )

    ready = 0
    failed = 0

    for scene_id in expected_ids:

        scene = visual_map.get(
            scene_id,
            {},
        )

        video = scene.get(
            "video",
            {},
        )

        status = video.get(
            "status"
        )

        if status == "failed":

            failed += 1
            continue

        video_file = video.get(
            "file"
        )

        if (
            status
            in {
                "generated",
                "completed",
                "passed",
            }
            and video_file
        ):

            ready += 1

    return _make_summary(
        total=len(expected_ids),
        ready=ready,
        failed=failed,
    )


def _compute_video_qc_status(
    job: dict,
) -> dict[str, Any]:

    total, ready, failed = (
        _status_counts_for_scene_field(
            job,
            (
                "video",
                "qc",
                "status",
            ),
        )
    )

    return _make_summary(
        total=total,
        ready=ready,
        failed=failed,
    )


def _compute_video_semantic_qc_status(
    job: dict,
) -> dict[str, Any]:

    total, ready, failed = (
        _status_counts_for_scene_field(
            job,
            (
                "video",
                "semantic_qc",
                "status",
            ),
        )
    )

    return _make_summary(
        total=total,
        ready=ready,
        failed=failed,
    )


def _compute_scene_trimmed_status(
    job: dict,
) -> dict[str, Any]:

    total, ready, failed = (
        _status_counts_for_scene_field(
            job,
            (
                "video",
                "trimmed",
                "status",
            ),
        )
    )

    return _make_summary(
        total=total,
        ready=ready,
        failed=failed,
    )


def refresh_pipeline_status(
    job: dict,
) -> dict[str, Any]:

    pipeline_status = {

        "script":
            _compute_script_status(
                job
            ),

        "visual_prompts":
            _compute_visual_prompts_status(
                job
            ),

        "character_reference_prompts":
            _compute_character_reference_prompts_status(
                job
            ),

        "character_references":
            _compute_character_references_status(
                job
            ),

        "scene_images":
            _compute_scene_images_status(
                job
            ),

        "image_qc":
            _compute_image_qc_status(
                job
            ),

        "image_semantic_qc":
            _compute_image_semantic_qc_status(
                job
            ),

        "scene_videos":
            _compute_scene_videos_status(
                job
            ),

        "video_qc":
            _compute_video_qc_status(
                job
            ),

        "video_semantic_qc":
            _compute_video_semantic_qc_status(
                job
            ),

        "scene_trimmed":
            _compute_scene_trimmed_status(
                job
            ),

        "voiceovers":
            _compute_voiceovers_status(
                job
            ),

        "voice_qc":
            _compute_voice_qc_status(
                job
            ),

        "scene_timing":
            _compute_scene_timing_status(
                job
            ),

        "global_timing":
            _compute_global_timing_status(
                job
            ),
    }

    job["pipeline_status"] = (
        pipeline_status
    )

    return pipeline_status


def set_legacy_status_from_stage(
    job: dict,
    stage: str,
) -> str:

    pipeline_status = (
        refresh_pipeline_status(
            job
        )
    )

    if stage not in pipeline_status:

        raise ValueError(
            f"Unknown pipeline stage: "
            f"{stage}"
        )

    state = (
        pipeline_status[
            stage
        ]["state"]
    )

    mappings = {

        "visual_prompts": {
            "pending":
                "visual_prompts_pending",
            "partial":
                "visual_prompts_partial",
            "completed":
                "visual_prompts_generated",
            "failed":
                "visual_prompts_failed",
        },

        "scene_images": {
            "pending":
                "scene_images_pending",
            "partial":
                "scene_images_partial",
            "completed":
                "scene_images_generated",
            "failed":
                "scene_images_failed",
        },

        "image_qc": {
            "pending":
                "scene_images_qc_pending",
            "partial":
                "scene_images_qc_partial",
            "completed":
                "scene_images_qc_passed",
            "failed":
                "scene_images_qc_failed",
        },

        "image_semantic_qc": {
            "pending":
                "scene_images_semantic_qc_pending",
            "partial":
                "scene_images_semantic_qc_partial",
            "completed":
                "scene_images_semantic_qc_passed",
            "failed":
                "scene_images_semantic_qc_failed",
        },

        "scene_videos": {
            "pending":
                "scene_videos_pending",
            "partial":
                "scene_videos_partial",
            "completed":
                "scene_videos_generated",
            "failed":
                "scene_videos_failed",
        },

        "video_qc": {
            "pending":
                "scene_videos_qc_pending",
            "partial":
                "scene_videos_qc_partial",
            "completed":
                "scene_videos_qc_passed",
            "failed":
                "scene_videos_qc_failed",
        },

        "video_semantic_qc": {
            "pending":
                "scene_videos_semantic_qc_pending",
            "partial":
                "scene_videos_semantic_qc_partial",
            "completed":
                "scene_videos_semantic_qc_passed",
            "failed":
                "scene_videos_semantic_qc_failed",
        },

        "scene_trimmed": {
            "pending":
                "scene_trimmed_pending",
            "partial":
                "scene_trimmed_partial",
            "completed":
                "scene_trimmed_passed",
            "failed":
                "scene_trimmed_failed",
        },

        "voiceovers": {
            "pending":
                "voiceovers_pending",
            "partial":
                "voiceovers_partial",
            "completed":
                "voiceovers_generated",
            "failed":
                "voiceovers_failed",
        },

        "voice_qc": {
            "pending":
                "voice_qc_pending",
            "partial":
                "voice_qc_partial",
            "completed":
                "voice_qc_passed",
            "failed":
                "voice_qc_failed",
        },
        
        "scene_timing": {
            "pending":
                "scene_timing_pending",
            "partial":
                "scene_timing_partial",
            "completed":
                "scene_timing_passed",
            "failed":
                "scene_timing_failed",
        },

        "global_timing": {
            "pending":
                "global_timing_pending",
            "partial":
                "global_timing_partial",
            "completed":
                "global_timing_passed",
            "failed":
                "global_timing_failed",
        },
    }

    stage_mapping = mappings.get(
        stage
    )

    if stage_mapping is None:

        legacy_status = (
            f"{stage}_{state}"
        )

    else:

        legacy_status = (
            stage_mapping[
                state
            ]
        )

    job["status"] = (
        legacy_status
    )

    return legacy_status


def print_stage_status(
    job: dict,
    stage: str,
) -> None:

    pipeline_status = (
        refresh_pipeline_status(
            job
        )
    )

    if stage not in pipeline_status:

        raise ValueError(
            f"Unknown pipeline stage: "
            f"{stage}"
        )

    summary = (
        pipeline_status[
            stage
        ]
    )

    print(
        f"Stage:   {stage}"
    )

    print(
        f"State:   "
        f"{summary['state']}"
    )

    print(
        f"Ready:   "
        f"{summary['ready']}/"
        f"{summary['total']}"
    )

    print(
        f"Failed:  "
        f"{summary['failed']}"
    )

    print(
        f"Pending: "
        f"{summary['pending']}"
    )

def _status_counts_for_script_scene_field(
    job: dict,
    path: tuple[str, ...],
) -> tuple[int, int, int]:

    script_scenes = (
        _get_script_scenes(
            job
        )
    )

    ready = 0
    failed = 0

    for scene in script_scenes:

        value: Any = scene

        for key in path:

            if not isinstance(
                value,
                dict,
            ):

                value = None
                break

            value = value.get(
                key
            )

        if value == "passed":

            ready += 1

        elif value == "failed":

            failed += 1

    return (
        len(script_scenes),
        ready,
        failed,
    )

def _compute_voiceovers_status(
    job: dict,
) -> dict[str, Any]:

    scenes = (
        _get_script_scenes(
            job
        )
    )

    ready = 0
    failed = 0

    for scene in scenes:

        voice = scene.get(
            "voice",
            {},
        )

        status = voice.get(
            "status"
        )

        if status == "failed":

            failed += 1
            continue

        voice_file = voice.get(
            "file"
        )

        if (
            status
            in {
                "generated",
                "completed",
                "passed",
            }
            and voice_file
        ):

            ready += 1

    return _make_summary(
        total=len(scenes),
        ready=ready,
        failed=failed,
    )

def _compute_voice_qc_status(
    job: dict,
) -> dict[str, Any]:

    total, ready, failed = (
        _status_counts_for_script_scene_field(
            job,
            (
                "voice",
                "qc",
                "status",
            ),
        )
    )

    return _make_summary(
        total=total,
        ready=ready,
        failed=failed,
    )

def _compute_scene_timing_status(
    job: dict,
) -> dict[str, Any]:

    scenes = (
        _get_script_scenes(
            job
        )
    )

    ready = 0
    failed = 0

    for scene in scenes:

        status = (
            scene
            .get(
                "timing",
                {},
            )
            .get(
                "status"
            )
        )

        if status == "passed":

            ready += 1

        elif status == "failed":

            failed += 1

    return _make_summary(
        total=len(scenes),
        ready=ready,
        failed=failed,
    )

def _compute_global_timing_status(
    job: dict,
) -> dict[str, Any]:

    scenes = (
        _get_script_scenes(
            job
        )
    )

    if not scenes:

        return _make_summary(
            total=1,
            ready=0,
        )

    timing_statuses = [
        scene
        .get(
            "timing",
            {},
        )
        .get(
            "status"
        )
        for scene in scenes
    ]

    if any(
        status == "failed"
        for status in timing_statuses
    ):

        return _make_summary(
            total=1,
            ready=0,
            failed=1,
        )

    if any(
        status != "passed"
        for status in timing_statuses
    ):

        return _make_summary(
            total=1,
            ready=0,
        )

    summary = job.get(
        "timing_summary",
        {},
    )

    if summary.get(
        "status"
    ) != "complete":

        return _make_summary(
            total=1,
            ready=0,
        )

    if summary.get(
        "script_revision_recommended"
    ):

        return _make_summary(
            total=1,
            ready=0,
            failed=1,
        )

    return _make_summary(
        total=1,
        ready=1,
    )
