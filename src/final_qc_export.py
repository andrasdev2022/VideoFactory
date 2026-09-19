from __future__ import annotations

import argparse
import json
import os
import shutil

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from base_video_assembler import (
    analyze_assembled_media,
    parse_resolution,
)

from pipeline_status import (
    refresh_pipeline_status,
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


FPS_TOLERANCE = float(
    os.getenv(
        "FINAL_QC_FPS_TOLERANCE",
        "0.05",
    )
)

TARGET_DURATION_TOLERANCE_SEC = float(
    os.getenv(
        "FINAL_QC_TARGET_DURATION_TOLERANCE_SEC",
        "4.0",
    )
)

AUDIO_SAMPLE_RATE = int(
    os.getenv(
        "FINAL_QC_AUDIO_SAMPLE_RATE",
        "48000",
    )
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Run final artifact QC and export the publish-ready "
            "video package without re-encoding the approved mix."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rebuild final export files even when the stored "
            "source signature still matches."
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


def relative_path(
    path: Path,
) -> str:

    return str(
        path.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )


def get_source_video(
    job: dict,
) -> Path:

    mix = (
        job
        .get(
            "audio",
            {},
        )
        .get(
            "mix",
            {},
        )
    )

    if mix.get(
        "status"
    ) != "passed":

        raise RuntimeError(
            "Final audio mix has not passed."
        )

    file_value = mix.get(
        "file"
    )

    if not file_value:

        raise RuntimeError(
            "Final audio mix file metadata is missing."
        )

    path = (
        PROJECT_ROOT
        / file_value
    )

    if not path.exists():

        raise RuntimeError(
            f"Final audio mix file does not exist: "
            f"{file_value}"
        )

    return path


def get_export_paths(
    job: dict,
) -> dict[str, Path]:

    root = (
        PROJECT_ROOT
        / "output"
        / str(
            job[
                "job_id"
            ]
        )
        / "final"
    )

    return {
        "video":
            root
            / "video.mp4",

        "subtitles":
            root
            / "subtitles.srt",

        "metadata":
            root
            / "metadata.json",

        "script":
            root
            / "script.json",
    }


def validate_metadata(
    job: dict,
    spec: dict,
) -> tuple[
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    metadata = job.get(
        "metadata",
        {},
    )

    title = metadata.get(
        "title"
    )

    if not isinstance(
        title,
        str,
    ) or not title.strip():

        errors.append(
            "Metadata title is missing."
        )

    else:

        max_length = int(
            spec
            .get(
                "metadata",
                {},
            )
            .get(
                "title",
                {},
            )
            .get(
                "max_length",
                100,
            )
        )

        if len(
            title
        ) > max_length:

            errors.append(
                (
                    f"Metadata title has {len(title)} "
                    f"characters; maximum is {max_length}."
                )
            )

    description = metadata.get(
        "description"
    )

    if not isinstance(
        description,
        str,
    ) or not description.strip():

        errors.append(
            "Metadata description is missing."
        )

    hashtags = metadata.get(
        "hashtags"
    )

    if not isinstance(
        hashtags,
        list,
    ):

        errors.append(
            "Metadata hashtags are missing."
        )

    else:

        hashtag_spec = (
            spec
            .get(
                "metadata",
                {},
            )
            .get(
                "hashtags",
                {},
            )
        )

        minimum = int(
            hashtag_spec.get(
                "min",
                0,
            )
        )

        maximum = int(
            hashtag_spec.get(
                "max",
                999,
            )
        )

        if not (
            minimum
            <= len(
                hashtags
            )
            <= maximum
        ):

            errors.append(
                (
                    f"Metadata has {len(hashtags)} hashtags; "
                    f"expected {minimum}-{maximum}."
                )
            )

        invalid = [
            value
            for value in hashtags
            if (
                not isinstance(
                    value,
                    str,
                )
                or not value.startswith(
                    "#"
                )
            )
        ]

        if invalid:

            warnings.append(
                "One or more hashtag entries do not begin with '#'."
            )

    return (
        errors,
        warnings,
    )


def evaluate_technical_media(
    actual: dict[str, Any],
    spec: dict,
) -> tuple[
    bool,
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    video_spec = spec.get(
        "video",
        {},
    )

    technical_spec = (
        spec
        .get(
            "quality",
            {},
        )
        .get(
            "technical",
            {},
        )
    )

    output_spec = spec.get(
        "output",
        {},
    )

    resolution = (
        technical_spec.get(
            "resolution_required"
        )
        or video_spec.get(
            "resolution",
            "1080x1920",
        )
    )

    width, height = parse_resolution(
        resolution
    )

    if actual.get(
        "width"
    ) != width:

        errors.append(
            (
                f"Final video width is {actual.get('width')}; "
                f"expected {width}."
            )
        )

    if actual.get(
        "height"
    ) != height:

        errors.append(
            (
                f"Final video height is {actual.get('height')}; "
                f"expected {height}."
            )
        )

    expected_fps = float(
        video_spec.get(
            "fps",
            30,
        )
    )

    actual_fps = actual.get(
        "fps"
    )

    if actual_fps is None:

        errors.append(
            "Final video FPS could not be determined."
        )

    elif abs(
        float(
            actual_fps
        )
        - expected_fps
    ) > FPS_TOLERANCE:

        errors.append(
            (
                f"Final video FPS is {actual_fps}; "
                f"expected {expected_fps}."
            )
        )

    expected_video_codec = (
        output_spec.get(
            "video_codec",
            "h264",
        )
    )

    if actual.get(
        "video_codec"
    ) != expected_video_codec:

        errors.append(
            (
                f"Final video codec is "
                f"{actual.get('video_codec')}; "
                f"expected {expected_video_codec}."
            )
        )

    expected_audio_codec = (
        output_spec.get(
            "audio_codec",
            "aac",
        )
    )

    if actual.get(
        "audio_codec"
    ) != expected_audio_codec:

        errors.append(
            (
                f"Final audio codec is "
                f"{actual.get('audio_codec')}; "
                f"expected {expected_audio_codec}."
            )
        )

    if actual.get(
        "video_stream_count"
    ) != 1:

        errors.append(
            "Final file must contain exactly one video stream."
        )

    if (
        technical_spec.get(
            "audio_required",
            True,
        )
        and actual.get(
            "audio_stream_count"
        )
        != 1
    ):

        errors.append(
            "Final file must contain exactly one audio stream."
        )

    if (
        actual.get(
            "audio_sample_rate"
        )
        != AUDIO_SAMPLE_RATE
    ):

        errors.append(
            (
                f"Final audio sample rate is "
                f"{actual.get('audio_sample_rate')}; "
                f"expected {AUDIO_SAMPLE_RATE}."
            )
        )

    duration = actual.get(
        "duration_sec"
    )

    minimum = float(
        video_spec.get(
            "min_duration_sec",
            0,
        )
    )

    maximum = float(
        video_spec.get(
            "max_duration_sec",
            999999,
        )
    )

    target = float(
        video_spec.get(
            "target_duration_sec",
            0,
        )
    )

    if duration is None:

        errors.append(
            "Final duration could not be determined."
        )

    else:

        duration = float(
            duration
        )

        if not (
            minimum
            <= duration
            <= maximum
        ):

            errors.append(
                (
                    f"Final duration is {duration:.3f}s; "
                    f"required range is {minimum:.3f}-"
                    f"{maximum:.3f}s."
                )
            )

        if (
            target > 0
            and abs(
                duration
                - target
            )
            > TARGET_DURATION_TOLERANCE_SEC
        ):

            warnings.append(
                (
                    f"Final duration differs from target "
                    f"{target:.3f}s by "
                    f"{duration - target:+.3f}s."
                )
            )

    max_file_size_mb = float(
        technical_spec.get(
            "max_file_size_mb",
            100,
        )
    )

    file_size = actual.get(
        "file_size_bytes"
    )

    if file_size is None:

        errors.append(
            "Final file size could not be determined."
        )

    elif float(
        file_size
    ) > (
        max_file_size_mb
        * 1024
        * 1024
    ):

        errors.append(
            (
                f"Final file is "
                f"{float(file_size) / 1024 / 1024:.2f} MB; "
                f"maximum is {max_file_size_mb:.2f} MB."
            )
        )

    return (
        not errors,
        errors,
        warnings,
    )


def validate_pipeline_integrity(
    job: dict,
) -> tuple[
    list[str],
    list[str],
]:

    errors: list[str] = []
    warnings: list[str] = []

    statuses = refresh_pipeline_status(
        job
    )

    required_stages = (
        "script",
        "visual_prompts",
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
        "base_assembly",
        "subtitles",
        "audio_assets",
        "audio_mix",
    )

    for stage in required_stages:

        state = (
            statuses
            .get(
                stage,
                {},
            )
            .get(
                "state"
            )
        )

        if state != "completed":

            errors.append(
                (
                    f"Pipeline stage '{stage}' is "
                    f"{state or 'missing'}, not completed."
                )
            )

    subtitles = job.get(
        "subtitles",
        {},
    )

    if subtitles.get(
        "enabled",
        True,
    ):

        subtitle_file = subtitles.get(
            "subtitle_file"
        )

        if not subtitle_file:

            errors.append(
                "Subtitle file metadata is missing."
            )

        elif not (
            PROJECT_ROOT
            / subtitle_file
        ).exists():

            errors.append(
                (
                    "Subtitle file does not exist: "
                    f"{subtitle_file}"
                )
            )

    music = (
        job
        .get(
            "audio",
            {},
        )
        .get(
            "background_music",
            {},
        )
    )

    if music.get(
        "required",
        False,
    ):

        music_file = music.get(
            "audio_file"
        )

        if not music_file:

            errors.append(
                "Required background music file is missing."
            )

        elif not (
            PROJECT_ROOT
            / music_file
        ).exists():

            errors.append(
                (
                    "Required background music file does not exist: "
                    f"{music_file}"
                )
            )

    thumbnail = (
        job
        .get(
            "metadata",
            {},
        )
        .get(
            "thumbnail",
            {},
        )
    )

    if (
        thumbnail.get(
            "required",
            False,
        )
        and not thumbnail.get(
            "image_file"
        )
    ):

        warnings.append(
            (
                "Thumbnail is required by job metadata but has "
                "not been generated yet. Video export can pass, "
                "but the publishing package is not complete."
            )
        )

    return (
        errors,
        warnings,
    )


def build_source_signature(
    job: dict,
    source_video: Path,
) -> dict[str, Any]:

    stat = source_video.stat()

    subtitles = job.get(
        "subtitles",
        {},
    )

    metadata = job.get(
        "metadata",
        {},
    )

    return {
        "source_video":
            relative_path(
                source_video
            ),

        "source_size_bytes":
            stat.st_size,

        "source_mtime_ns":
            stat.st_mtime_ns,

        "subtitle_file":
            subtitles.get(
                "subtitle_file"
            ),

        "metadata": {
            "title":
                metadata.get(
                    "title"
                ),

            "description":
                metadata.get(
                    "description"
                ),

            "hashtags":
                metadata.get(
                    "hashtags"
                ),
        },

        "script_voiceover":
            job
            .get(
                "script",
                {},
            )
            .get(
                "voiceover"
            ),
    }


def export_matches_current_request(
    job: dict,
    source_signature: dict[str, Any],
    paths: dict[str, Path],
) -> bool:

    final_qc = job.get(
        "final_qc",
        {},
    )

    if final_qc.get(
        "status"
    ) != "passed":

        return False

    if final_qc.get(
        "source_signature"
    ) != source_signature:

        return False

    export = final_qc.get(
        "export",
        {},
    )

    expected = {
        "video_file":
            relative_path(
                paths[
                    "video"
                ]
            ),

        "metadata_file":
            relative_path(
                paths[
                    "metadata"
                ]
            ),

        "script_file":
            relative_path(
                paths[
                    "script"
                ]
            ),
    }

    for key, value in expected.items():

        if export.get(
            key
        ) != value:

            return False

    return all(
        paths[
            key
        ].exists()
        for key in (
            "video",
            "metadata",
            "script",
        )
    )


def copy_atomic(
    source: Path,
    destination: Path,
) -> None:

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        destination
        .with_name(
            destination.name
            + ".tmp"
        )
    )

    shutil.copy2(
        source,
        temporary_file,
    )

    os.replace(
        temporary_file,
        destination,
    )


def write_json_atomic(
    path: Path,
    value: Any,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        path
        .with_name(
            path.name
            + ".tmp"
        )
    )

    temporary_file.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary_file,
        path,
    )


def build_export_metadata(
    job: dict,
    actual: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:

    metadata = job.get(
        "metadata",
        {},
    )

    platforms = job.get(
        "publishing",
        {},
    )

    enabled_platforms = [
        name
        for name, config
        in platforms.items()
        if (
            isinstance(
                config,
                dict,
            )
            and config.get(
                "enabled",
                False,
            )
        )
    ]

    return {
        "job_id":
            job.get(
                "job_id"
            ),

        "title":
            metadata.get(
                "title"
            ),

        "description":
            metadata.get(
                "description"
            ),

        "hashtags":
            metadata.get(
                "hashtags",
                [],
            ),

        "technical":
            actual,

        "enabled_platforms":
            enabled_platforms,

        "warnings":
            warnings,

        "exported_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }


def export_final_package(
    job: dict,
    source_video: Path,
    actual: dict[str, Any],
    warnings: list[str],
    paths: dict[str, Path],
) -> dict[str, Any]:

    copy_atomic(
        source_video,
        paths[
            "video"
        ],
    )

    subtitles = job.get(
        "subtitles",
        {},
    )

    subtitle_source = subtitles.get(
        "subtitle_file"
    )

    subtitle_export = None

    if subtitle_source:

        subtitle_source_path = (
            PROJECT_ROOT
            / subtitle_source
        )

        if subtitle_source_path.exists():

            copy_atomic(
                subtitle_source_path,
                paths[
                    "subtitles"
                ],
            )

            subtitle_export = relative_path(
                paths[
                    "subtitles"
                ]
            )

    export_metadata = build_export_metadata(
        job,
        actual,
        warnings,
    )

    write_json_atomic(
        paths[
            "metadata"
        ],
        export_metadata,
    )

    write_json_atomic(
        paths[
            "script"
        ],
        job.get(
            "script",
            {},
        ),
    )

    return {
        "video_file":
            relative_path(
                paths[
                    "video"
                ]
            ),

        "subtitle_file":
            subtitle_export,

        "metadata_file":
            relative_path(
                paths[
                    "metadata"
                ]
            ),

        "script_file":
            relative_path(
                paths[
                    "script"
                ]
            ),
    }


def run_final_qc_export(
    job: dict,
    spec: dict,
    force: bool,
) -> bool:

    source_video = get_source_video(
        job
    )

    actual = analyze_assembled_media(
        source_video
    )

    (
        technical_passed,
        technical_errors,
        technical_warnings,
    ) = evaluate_technical_media(
        actual,
        spec,
    )

    (
        integrity_errors,
        integrity_warnings,
    ) = validate_pipeline_integrity(
        job
    )

    (
        metadata_errors,
        metadata_warnings,
    ) = validate_metadata(
        job,
        spec,
    )

    errors = (
        technical_errors
        + integrity_errors
        + metadata_errors
    )

    warnings = (
        technical_warnings
        + integrity_warnings
        + metadata_warnings
    )

    source_signature = (
        build_source_signature(
            job,
            source_video,
        )
    )

    paths = get_export_paths(
        job
    )

    checked_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    if errors:

        job[
            "final_qc"
        ] = {
            "status":
                "failed",

            "checked_at":
                checked_at,

            "source_file":
                relative_path(
                    source_video
                ),

            "source_signature":
                source_signature,

            "technical":
                actual,

            "errors":
                errors,

            "warnings":
                warnings,
        }

        return False

    if (
        not force
        and export_matches_current_request(
            job,
            source_signature,
            paths,
        )
    ):

        print(
            "Final export already matches the current "
            "approved mix and metadata."
        )

        return False

    export = export_final_package(
        job=job,
        source_video=source_video,
        actual=actual,
        warnings=warnings,
        paths=paths,
    )

    thumbnail_ready = bool(
        job
        .get(
            "metadata",
            {},
        )
        .get(
            "thumbnail",
            {},
        )
        .get(
            "image_file"
        )
    )

    job[
        "final_qc"
    ] = {
        "status":
            "passed",

        "checked_at":
            checked_at,

        "source_file":
            relative_path(
                source_video
            ),

        "source_signature":
            source_signature,

        "technical":
            actual,

        "technical_passed":
            technical_passed,

        "publish_ready":
            thumbnail_ready,

        "export":
            export,

        "errors":
            [],

        "warnings":
            warnings,
    }

    output = job.setdefault(
        "output",
        {},
    )

    output[
        "video_file"
    ] = export[
        "video_file"
    ]

    output[
        "subtitle_file"
    ] = export[
        "subtitle_file"
    ]

    print(
        f"\nFinal video: "
        f"{export['video_file']}"
    )

    print(
        f"Metadata:    "
        f"{export['metadata_file']}"
    )

    print(
        f"Script:      "
        f"{export['script_file']}"
    )

    if export[
        "subtitle_file"
    ]:

        print(
            f"Subtitles:   "
            f"{export['subtitle_file']}"
        )

    if warnings:

        for warning in warnings:

            print(
                f"  [WARNING] {warning}"
            )

    print(
        "PASS"
    )

    return True


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - FINAL QC + EXPORT v1")
    print("=" * 60)

    args = parse_args()

    try:

        job = load_json(
            JOB_FILE
        )

        spec = load_yaml(
            SPEC_FILE
        )

        run_final_qc_export(
            job=job,
            spec=spec,
            force=args.force,
        )

        set_legacy_status_from_stage(
            job,
            "final_qc",
        )

        save_job_atomic(
            job
        )

    except Exception as exc:

        try:

            job

        except NameError:

            print(
                f"\nERROR: {exc}"
            )

            return 1

        job[
            "final_qc"
        ] = {
            "status":
                "failed",

            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "errors": [
                str(
                    exc
                )
            ],

            "warnings":
                [],
        }

        set_legacy_status_from_stage(
            job,
            "final_qc",
        )

        save_job_atomic(
            job
        )

        print(
            f"\nERROR: {exc}"
        )

        return 1

    final_qc = job.get(
        "final_qc",
        {},
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "FINAL QC + EXPORT COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nStatus: "
        f"{final_qc.get('status')}"
    )

    print(
        f"Publish ready: "
        f"{final_qc.get('publish_ready')}"
    )

    return (
        0
        if final_qc.get(
            "status"
        )
        == "passed"
        else 1
    )


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
