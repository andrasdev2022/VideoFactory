from __future__ import annotations

from tts_settings import resolve_tts_settings

from genre_policy import genre_instruction

import argparse
import json
import os

from pathlib import Path
from typing import Any

from openai import OpenAI

from pipeline_status import (
    set_legacy_status_from_stage,
)

from validator import (
    load_json,
)


from genre_policy import runtime_spec as load_yaml

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

SPEC_FILE = (
    PROJECT_ROOT
    / "config"
    / "video_spec_v1.yaml"
)

JOB_FILE = (
    PROJECT_ROOT
    / "jobs"
    / "video_job.json"
)


TTS_FORMAT = os.getenv(
    "OPENAI_TTS_FORMAT",
    "wav",
).lower()

SUPPORTED_FORMATS = {
    "mp3",
    "opus",
    "aac",
    "flac",
    "wav",
    "pcm",
}


MAX_INPUT_CHARS = 4096


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Generate per-scene voiceover audio "
            "with configured speech settings."
        )
    )

    parser.add_argument(
        "--scene",
        type=int,
        default=None,
        help=(
            "Generate voiceover only for one scene. "
            "Example: --scene 2"
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Regenerate voice audio even if "
            "it already exists."
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


def normalize_spoken_value(
    value: Any,
) -> str:

    if value is None:

        return ""

    if isinstance(
        value,
        str,
    ):

        return value.strip()

    if isinstance(
        value,
        dict,
    ):

        for key in (
            "text",
            "line",
            "content",
            "voiceover",
            "narration",
        ):

            candidate = value.get(
                key
            )

            if (
                isinstance(
                    candidate,
                    str,
                )
                and candidate.strip()
            ):

                return candidate.strip()

        return ""

    if isinstance(
        value,
        list,
    ):

        parts: list[str] = []

        for item in value:

            part = normalize_spoken_value(
                item
            )

            if part:

                parts.append(
                    part
                )

        return " ".join(
            parts
        ).strip()

    return ""


def extract_scene_voice_text(
    scene: dict,
) -> tuple[str, str]:

    preferred_fields = (
        "voiceover",
        "voiceover_text",
        "narration",
        "spoken_text",
        "dialogue",
    )

    for field in preferred_fields:

        if field not in scene:
            continue

        text = normalize_spoken_value(
            scene.get(
                field
            )
        )

        if text:

            return (
                text,
                field,
            )

    raise RuntimeError(
        f"Scene {scene.get('scene_id')}: "
        f"no usable voiceover/narration/dialogue "
        f"text was found."
    )


def validate_voice_text(
    scene_id: int,
    text: str,
) -> None:

    if not text.strip():

        raise RuntimeError(
            f"Scene {scene_id}: "
            f"voice text is empty."
        )

    if len(text) > MAX_INPUT_CHARS:

        raise RuntimeError(
            f"Scene {scene_id}: "
            f"voice text is too long "
            f"({len(text)} chars). "
            f"Maximum: {MAX_INPUT_CHARS}."
        )


def get_scene_duration(
    job: dict,
    scene_id: int,
) -> float | None:

    scene = find_script_scene(
        job,
        scene_id,
    )

    if scene is None:

        return None

    duration = scene.get(
        "duration_sec"
    )

    if duration is None:

        return None

    return float(
        duration
    )


def build_voice_instructions(
    spec: dict,
) -> str:

    voice_spec = (
        spec
        .get(
            "audio",
            {},
        )
        .get(
            "voiceover",
            {},
        )
    )

    style = voice_spec.get(
        "style",
        "energetic",
    )

    language = (
        spec
        .get(
            "video",
            {},
        )
        .get(
            "language",
            "en",
        )
    )

    return (
        f"Speak in {language}. "
        f"Use a {style} delivery suitable for "
        f"short-form social media. "
        f"Use a natural conversational speaking pace. "
        f"Do not rush the delivery to fit a time limit. "
        f"Keep pauses natural and expressive. "
        f"Sound clear, engaging, emotionally appropriate, and human. "
        f"Maintain the same narrator identity and vocal "
        f"character across scenes. "
        f"Do not add, remove, paraphrase, or repeat words. "
        f"Read exactly the supplied text."
        + genre_instruction(spec=spec)
        + ("\nAdditional delivery instructions: " + voice_spec["instructions"].strip()
           if voice_spec.get("instructions", "").strip() else "")
    )


def get_voice_output_path(
    job: dict,
    scene_id: int,
    response_format: str | None = None,
) -> Path:

    job_id = job.get(
        "job_id"
    )

    if not job_id:

        raise RuntimeError(
            "job_id is missing."
        )

    output_directory = (
        PROJECT_ROOT
        / "output"
        / str(job_id)
        / "audio"
        / "voice"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return (
        output_directory
        / (
            f"scene_"
            f"{scene_id:03d}."
            f"{response_format or TTS_FORMAT}"
        )
    )


def scene_voice_is_generated(
    scene: dict,
) -> bool:

    voice = scene.get(
        "voice",
        {},
    )

    status = voice.get(
        "status"
    )

    voice_file = voice.get(
        "file"
    )

    if (
        status
        not in {
            "generated",
            "completed",
            "passed",
        }
        or not voice_file
    ):

        return False

    path = (
        PROJECT_ROOT
        / voice_file
    )

    return path.exists()


def effective_voice_instructions(spec):
    settings = resolve_tts_settings(spec)
    if not settings['model'].startswith('gpt-4o-mini-tts'):
        return ''
    instructions = build_voice_instructions(spec)
    if len(instructions) > 4096:
        raise ValueError('Combined TTS instructions exceed 4096 characters.')
    return instructions


def voice_settings_match(spec, scene):
    settings = resolve_tts_settings(spec)
    voice = scene.get('voice', {})
    text, _ = extract_scene_voice_text(scene)
    return (all(voice.get(key) == settings[setting] for key, setting in
                (('model', 'model'), ('voice', 'voice'), ('speed', 'speed'), ('format', 'response_format')))
            and voice.get('input_text') == text
            and voice.get('instructions', '') == effective_voice_instructions(spec))


def generate_scene_voice(
    client: OpenAI,
    spec: dict,
    job: dict,
    scene: dict,
    force: bool,
) -> bool:

    scene_id = scene.get(
        "scene_id"
    )

    if scene_id is None:

        raise RuntimeError(
            "Script scene has no scene_id."
        )

    settings = resolve_tts_settings(spec)
    if scene_voice_is_generated(scene) and not force and voice_settings_match(spec, scene):
        print(f"  SKIP: Scene {scene_id} voice settings and text are unchanged.")
        return False

    (
        voice_text,
        source_field,
    ) = extract_scene_voice_text(
        scene
    )

    validate_voice_text(
        scene_id,
        voice_text,
    )

    output_path = (
        get_voice_output_path(
            job,
            scene_id,
            settings["response_format"],
        )
    )

    temporary_path = (
        output_path.with_name(
            output_path.stem
            + ".tmp"
            + output_path.suffix
        )
    )

    if temporary_path.exists():

        temporary_path.unlink()

    instructions = effective_voice_instructions(spec)

    planned_duration = (
        get_scene_duration(
            job,
            scene_id,
        )
    )

    print(
        f"\nGenerating voice for scene "
        f"{scene_id}"
    )

    print(
        f"  Model:       "
        f"{settings['model']}"
    )

    print(
        f"  Voice:       "
        f"{settings['voice']}"
    )

    print(
        f"  Format:      "
        f"{settings['response_format']}"
    )

    print(
        f"  Speed:       "
        f"{settings['speed']:.2f} (configured speed)"
    )

    print(
        f"  Source:      "
        f"{source_field}"
    )

    print(
        f"  Text chars:  "
        f"{len(voice_text)}"
    )

    if planned_duration is not None:

        print(
            f"  Planned scene length: "
            f"{planned_duration:.2f}s"
        )

    try:

        with (
            client
            .audio
            .speech
            .with_streaming_response
            .create(
                model=settings["model"],
                voice=settings["voice"],
                input=voice_text,
                **({"instructions": instructions} if settings["model"].startswith("gpt-4o-mini-tts") else {}),
                response_format=
                    settings["response_format"],
                speed=settings["speed"],
            )
        ) as response:

            response.stream_to_file(
                temporary_path
            )

        if not temporary_path.exists():

            raise RuntimeError(
                "TTS API produced no output file."
            )

        file_size = (
            temporary_path
            .stat()
            .st_size
        )

        if file_size <= 0:

            raise RuntimeError(
                "TTS API produced an empty file."
            )

        os.replace(
            temporary_path,
            output_path,
        )

    except Exception:

        if temporary_path.exists():

            temporary_path.unlink()

        raise

    relative_file = str(
        output_path.relative_to(
            PROJECT_ROOT
        )
    ).replace(
        "\\",
        "/",
    )

    scene["voice"] = {

        "status":
            "generated",

        "file":
            relative_file,

        "provider":
            "openai",

        "model":
            settings["model"],

        "voice":
            settings["voice"],

        "format":
            settings["response_format"],

        "speed":
            settings["speed"],

        "source_field":
            source_field,

        "input_text":
            voice_text,

        "instructions":
            instructions,

        "planned_scene_duration_sec":
            planned_duration,

        "file_size_bytes":
            output_path
            .stat()
            .st_size,

        "qc": {
            "status":
                "pending",
        },
    }

    # Invalidate derivatives containing old audio or depending on its duration.
    job.pop('timing_summary', None)
    state = job.get('orchestration', {}).get('scenes', {}).get(str(scene_id))
    if state is not None:
        state.update(video_attempts=0, state='in_progress')
    for visual in job.get('visuals', {}).get('scenes', []):
        if visual.get('scene_id') == scene_id:
            for key in ('video', 'motion_strategy', 'semantic_qc_policy'):
                visual.pop(key, None)
    for key in ('generation', 'render'):
        job.get('subtitles', {}).pop(key, None)
    for key in ('plan', 'assets', 'mix'):
        job.get('audio', {}).pop(key, None)
    job.pop('final_qc', None)
    for key in ('video_file', 'mixed_video_file', 'subtitled_video_file', 'subtitle_file'):
        job.get('output', {}).pop(key, None)

    # A new voice invalidates previous timing.
    if "timing" in scene:

        del scene[
            "timing"
        ]

    # Any base assembly containing the old voice
    # is now stale.

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

    print(
        f"  Saved:       "
        f"{relative_file}"
    )

    print(
        f"  Bytes:       "
        f"{output_path.stat().st_size:,}"
    )

    return True


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - VOICE GENERATOR v2")
    print("=" * 60)

    args = parse_args()

    if not os.getenv(
        "OPENAI_API_KEY"
    ):

        print(
            "\nERROR: OPENAI_API_KEY "
            "environment variable is not set."
        )

        return 1

    if (
        TTS_FORMAT
        not in SUPPORTED_FORMATS
    ):

        print(
            f"\nERROR: unsupported "
            f"OPENAI_TTS_FORMAT: "
            f"{TTS_FORMAT}"
        )

        return 1

    try:

        spec = load_yaml(
            SPEC_FILE
        )
        settings = resolve_tts_settings(spec)

        job = load_json(
            JOB_FILE
        )

    except Exception as exc:

        print(
            f"\nERROR loading input files:\n"
            f"{exc}"
        )

        return 1

    script_scenes = (
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

    if not script_scenes:

        print(
            "\nERROR: script contains no scenes."
        )

        return 1

    if args.scene is not None:

        selected_scene = (
            find_script_scene(
                job,
                args.scene,
            )
        )

        if selected_scene is None:

            print(
                f"\nERROR: scene "
                f"{args.scene} not found."
            )

            return 1

        selected_scenes = [
            selected_scene
        ]

    else:

        selected_scenes = (
            script_scenes
        )

    print(
        f"\nJob ID: "
        f"{job.get('job_id')}"
    )

    print(
        f"Model:  "
        f"{settings['model']}"
    )

    print(
        f"Voice:  "
        f"{settings['voice']}"
    )

    print(
        f"Speed:  "
        f"{settings['speed']:.2f} "
        f"(configured)"
    )

    print(
        f"Scenes: "
        f"{len(selected_scenes)}"
    )

    client = OpenAI()

    generated_count = 0
    skipped_count = 0
    failed_count = 0

    for scene in selected_scenes:

        scene_id = scene.get(
            "scene_id"
        )

        try:

            generated = (
                generate_scene_voice(
                    client=client,
                    spec=spec,
                    job=job,
                    scene=scene,
                    force=args.force,
                )
            )

            if generated:

                generated_count += 1

            else:

                skipped_count += 1

        except Exception as exc:

            failed_count += 1

            print(
                f"\nERROR generating voice "
                f"for scene {scene_id}:\n"
                f"{exc}"
            )

            scene["voice"] = {

                "status":
                    "failed",

                "error":
                    str(exc),

                "qc": {
                    "status":
                        "pending",
                },
            }

            if "timing" in scene:

                del scene[
                    "timing"
                ]

            set_legacy_status_from_stage(
                job,
                "voiceovers",
            )

            save_job_atomic(
                job
            )

            return 1

        set_legacy_status_from_stage(
            job,
            "voiceovers",
        )

        save_job_atomic(
            job
        )

    set_legacy_status_from_stage(
        job,
        "voiceovers",
    )

    save_job_atomic(
        job
    )

    stage = (
        job[
            "pipeline_status"
        ][
            "voiceovers"
        ]
    )

    print(
        "\n" + "=" * 60
    )

    print(
        "VOICE GENERATION COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nGenerated this run: "
        f"{generated_count}"
    )

    print(
        f"Skipped: "
        f"{skipped_count}"
    )

    print(
        f"Failed: "
        f"{failed_count}"
    )

    print(
        f"Stage state: "
        f"{stage['state']}"
    )

    print(
        f"Ready: "
        f"{stage['ready']}/"
        f"{stage['total']}"
    )

    print(
        f"Pending: "
        f"{stage['pending']}"
    )

    print(
        f"Job status: "
        f"{job.get('status')}"
    )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )