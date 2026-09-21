from __future__ import annotations

from genre_policy import genre_instruction

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline_status import (
    set_legacy_status_from_stage,
)

from validator import load_json

from video_qc import (
    run_ffprobe,
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


API_BASE_URL = os.getenv(
    "ELEVENLABS_API_BASE_URL",
    "https://api.elevenlabs.io",
).rstrip(
    "/"
)

MUSIC_MODEL = os.getenv(
    "ELEVENLABS_MUSIC_MODEL",
    "music_v2_5",
)

SFX_MODEL = os.getenv(
    "ELEVENLABS_SFX_MODEL",
    "eleven_text_to_sound_v2",
)

MUSIC_OUTPUT_FORMAT = os.getenv(
    "ELEVENLABS_MUSIC_OUTPUT_FORMAT",
    "mp3_48000_192",
)

SFX_OUTPUT_FORMAT = os.getenv(
    "ELEVENLABS_SFX_OUTPUT_FORMAT",
    "mp3_44100_128",
)

HTTP_TIMEOUT_SEC = int(
    os.getenv(
        "ELEVENLABS_HTTP_TIMEOUT_SEC",
        "300",
    )
)

SFX_DEFAULT_DURATION_SEC = float(
    os.getenv(
        "ELEVENLABS_SFX_DEFAULT_DURATION_SEC",
        "1.5",
    )
)

SFX_PROMPT_INFLUENCE = float(
    os.getenv(
        "ELEVENLABS_SFX_PROMPT_INFLUENCE",
        "0.5",
    )
)

# ElevenLabs Sound Effects currently accepts at most 450
# characters. Keep a safety margin for provider-side validation.
SFX_MAX_PROMPT_CHARS = int(
    os.getenv(
        "ELEVENLABS_SFX_MAX_PROMPT_CHARS",
        "430",
    )
)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Generate background music and sound-effect assets "
            "for the current job with ElevenLabs."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
    )

    parser.add_argument(
        "--music-only",
        action="store_true",
    )

    parser.add_argument(
        "--sfx-only",
        action="store_true",
    )

    args = parser.parse_args()

    if (
        args.music_only
        and args.sfx_only
    ):

        parser.error(
            "--music-only and --sfx-only "
            "cannot be used together."
        )

    return args


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


def get_api_key() -> str:

    value = os.getenv(
        "ELEVENLABS_API_KEY",
        "",
    ).strip()

    if not value:

        raise RuntimeError(
            "ELEVENLABS_API_KEY is missing."
        )

    return value


def get_timeline(
    job: dict,
) -> list[dict[str, Any]]:

    assembly = job.get(
        "assembly",
        {},
    )

    if assembly.get(
        "status"
    ) != "passed":

        raise RuntimeError(
            "Base assembly must pass before "
            "audio asset generation."
        )

    timeline = assembly.get(
        "timeline"
    )

    if not isinstance(
        timeline,
        list,
    ) or not timeline:

        raise RuntimeError(
            "Assembly timeline is missing."
        )

    return timeline


def get_total_duration_ms(
    job: dict,
    timeline: list[
        dict[str, Any]
    ],
) -> int:

    duration = (
        job
        .get(
            "assembly",
            {},
        )
        .get(
            "actual",
            {},
        )
        .get(
            "duration_sec"
        )
    )

    if duration is None:

        duration = (
            timeline[
                -1
            ]
            .get(
                "end_sec"
            )
        )

    if duration is None:

        raise RuntimeError(
            "Unable to determine final video duration."
        )

    duration_ms = int(
        round(
            float(
                duration
            )
            * 1000
        )
    )

    return max(
        3000,
        min(
            600000,
            duration_ms,
        ),
    )


def get_scene_ids(
    timeline: list[
        dict[str, Any]
    ],
) -> set[int]:

    result: set[int] = set()

    for item in timeline:

        scene_id = item.get(
            "scene_id"
        )

        if scene_id is None:

            continue

        result.add(
            int(
                scene_id
            )
        )

    return result


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


def build_music_prompt(
    job: dict,
    duration_ms: int,
) -> str:

    idea = job.get(
        "idea",
        {},
    )

    audio = job.get(
        "audio",
        {},
    )

    music = audio.get(
        "background_music",
        {},
    )

    style = (
        music.get(
            "style"
        )
        or "light cinematic underscore"
    )

    genre = (
        idea.get(
            "genre"
        )
        or "short-form story"
    )

    concept = (
        idea.get(
            "concept"
        )
        or idea.get(
            "title"
        )
        or ""
    )

    duration_sec = (
        duration_ms
        / 1000.0
    )

    return (
        f"Create a {duration_sec:.1f}-second instrumental "
        f"background track for a vertical short-form video. "
        f"Style: {style}. Genre/context: {genre}. "
        f"Story context: {concept}. "
        f"{genre_instruction(job)} "
        + ("For this scene, the explicitly authored music style takes precedence over generic genre mood defaults. "
           if job.get("_scene_music_request") else "")
        +
        "Keep the arrangement genre-appropriate, polished, and "
        "supportive of spoken narration. Use restrained dynamics "
        "and avoid large transient hits that could mask dialogue. "
        "No vocals, no speech, no spoken words, no artist imitation, "
        "and no recognizable copyrighted melody. "
        "Maintain a coherent continuous underscore and finish cleanly."
    )


def normalize_prompt_text(
    value: Any,
) -> str:

    return " ".join(
        str(
            value
        )
        .replace(
            "\n",
            " ",
        )
        .split()
    )


def truncate_prompt_text(
    value: str,
    max_chars: int,
) -> str:

    value = normalize_prompt_text(
        value
    )

    if max_chars <= 0:

        return ""

    if len(
        value
    ) <= max_chars:

        return value

    if max_chars <= 3:

        return value[
            :max_chars
        ]

    candidate = value[
        :max_chars - 1
    ].rstrip()

    last_space = candidate.rfind(
        " "
    )

    if (
        last_space
        >= max_chars
        // 2
    ):

        candidate = candidate[
            :last_space
        ].rstrip()

    return (
        candidate
        + "…"
    )


def build_sfx_prompt(
    job: dict,
    effect: dict[str, Any],
    scene_id: int,
) -> str:

    effect_name = normalize_prompt_text(
        effect.get(
            "effect"
        )
        or "short cinematic sound effect"
    )

    script_scene = find_script_scene(
        job,
        scene_id,
    )

    visual_scene = find_visual_scene(
        job,
        scene_id,
    )

    context_parts: list[str] = []

    if script_scene is not None:

        voice_text = (
            script_scene
            .get(
                "voice",
                {},
            )
            .get(
                "input_text"
            )
            or script_scene.get(
                "voiceover"
            )
        )

        if voice_text:

            context_parts.append(
                normalize_prompt_text(
                    voice_text
                )
            )

    if visual_scene is not None:

        motion = visual_scene.get(
            "motion_prompt"
        )

        if motion:

            context_parts.append(
                normalize_prompt_text(
                    motion
                )
            )

    prefix = (
        "Clean isolated sound effect: "
        + truncate_prompt_text(
            effect_name,
            100,
        )
        + ". "
    )

    suffix = (
        " Short, clear, suitable for the scene and its genre. "
        "No speech, no music bed, no narration, no branded "
        "sound, and no copyrighted audio."
    )

    context = normalize_prompt_text(
        " ".join(
            context_parts
        )
    )

    available_context_chars = max(
        0,
        SFX_MAX_PROMPT_CHARS
        - len(
            prefix
        )
        - len(
            suffix
        )
        - len(
            "Scene context: ."
        ),
    )

    context = truncate_prompt_text(
        context,
        available_context_chars,
    )

    if context:

        prompt = (
            prefix
            + "Scene context: "
            + context
            + "."
            + suffix
        )

    else:

        prompt = (
            prefix
            + suffix.lstrip()
        )

    prompt = normalize_prompt_text(
        prompt
    )

    # Final hard guard: never send an over-limit prompt even if
    # future wording/configuration changes above.
    return truncate_prompt_text(
        prompt,
        SFX_MAX_PROMPT_CHARS,
    )


def sanitize_slug(
    value: str,
) -> str:

    value = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        value,
    ).strip(
        "_"
    ).lower()

    return (
        value[
            :48
        ]
        or "effect"
    )


def build_music_request(
    prompt: str,
    duration_ms: int,
) -> tuple[
    str,
    dict[str, Any],
]:

    query = urllib.parse.urlencode(
        {
            "output_format":
                MUSIC_OUTPUT_FORMAT,
        }
    )

    url = (
        f"{API_BASE_URL}"
        f"/v1/music?"
        f"{query}"
    )

    body = {
        "prompt":
            prompt,

        "music_length_ms":
            duration_ms,

        "model_id":
            MUSIC_MODEL,

        "force_instrumental":
            True,
    }

    return (
        url,
        body,
    )


def build_sfx_request(
    prompt: str,
    duration_sec: float,
) -> tuple[
    str,
    dict[str, Any],
]:

    duration_sec = max(
        0.5,
        min(
            30.0,
            float(
                duration_sec
            ),
        ),
    )

    influence = max(
        0.0,
        min(
            1.0,
            SFX_PROMPT_INFLUENCE,
        ),
    )

    query = urllib.parse.urlencode(
        {
            "output_format":
                SFX_OUTPUT_FORMAT,
        }
    )

    url = (
        f"{API_BASE_URL}"
        f"/v1/sound-generation?"
        f"{query}"
    )

    body = {
        "text":
            prompt,

        "loop":
            False,

        "duration_seconds":
            duration_sec,

        "prompt_influence":
            influence,

        "model_id":
            SFX_MODEL,
    }

    return (
        url,
        body,
    )


def http_post_json_for_bytes(
    *,
    url: str,
    body: dict[str, Any],
    api_key: str,
) -> tuple[
    bytes,
    dict[str, str],
]:

    request = urllib.request.Request(
        url=url,
        data=json.dumps(
            body
        ).encode(
            "utf-8"
        ),
        headers={
            "xi-api-key":
                api_key,

            "Content-Type":
                "application/json",

            "Accept":
                "audio/mpeg",
        },
        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=HTTP_TIMEOUT_SEC,
        ) as response:

            payload = response.read()

            headers = {
                key.lower():
                    value
                for key, value
                in response.headers.items()
            }

    except urllib.error.HTTPError as exc:

        try:

            detail = (
                exc.read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )

        except Exception:

            detail = str(
                exc
            )

        raise RuntimeError(
            f"ElevenLabs HTTP {exc.code}: {detail}"
        ) from exc

    except urllib.error.URLError as exc:

        raise RuntimeError(
            f"ElevenLabs request failed: {exc}"
        ) from exc

    if not payload:

        raise RuntimeError(
            "ElevenLabs returned an empty audio response."
        )

    return (
        payload,
        headers,
    )


def write_bytes_atomic(
    path: Path,
    payload: bytes,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        path.with_name(
            path.name
            + ".tmp"
        )
    )

    temporary_file.write_bytes(
        payload
    )

    os.replace(
        temporary_file,
        path,
    )


def analyze_audio(
    path: Path,
) -> dict[str, Any]:

    probe = run_ffprobe(
        path
    )

    streams = probe.get(
        "streams",
        [],
    )

    audio_streams = [
        stream
        for stream in streams
        if stream.get(
            "codec_type"
        )
        == "audio"
    ]

    video_streams = [
        stream
        for stream in streams
        if stream.get(
            "codec_type"
        )
        == "video"
    ]

    audio_stream = (
        audio_streams[0]
        if audio_streams
        else {}
    )

    duration = (
        probe
        .get(
            "format",
            {},
        )
        .get(
            "duration"
        )
    )

    try:

        duration_value = float(
            duration
        )

    except (
        TypeError,
        ValueError,
    ):

        duration_value = None

    sample_rate = audio_stream.get(
        "sample_rate"
    )

    try:

        sample_rate_value = int(
            sample_rate
        )

    except (
        TypeError,
        ValueError,
    ):

        sample_rate_value = None

    return {
        "file_size_bytes":
            path.stat().st_size,

        "audio_stream_count":
            len(
                audio_streams
            ),

        "video_stream_count":
            len(
                video_streams
            ),

        "codec":
            audio_stream.get(
                "codec_name"
            ),

        "sample_rate":
            sample_rate_value,

        "channels":
            audio_stream.get(
                "channels"
            ),

        "duration_sec":
            (
                round(
                    duration_value,
                    3,
                )
                if duration_value
                is not None
                else None
            ),
    }


def validate_audio(
    actual: dict[str, Any],
) -> list[str]:

    errors: list[str] = []

    if actual.get(
        "audio_stream_count"
    ) != 1:

        errors.append(
            "Generated asset must contain exactly one audio stream."
        )

    if actual.get(
        "video_stream_count"
    ) != 0:

        errors.append(
            "Generated audio asset must not contain a video stream."
        )

    if (
        actual.get(
            "duration_sec"
        )
        is None
        or float(
            actual[
                "duration_sec"
            ]
        )
        <= 0.1
    ):

        errors.append(
            "Generated audio duration is invalid."
        )

    if (
        actual.get(
            "file_size_bytes",
            0,
        )
        <= 1000
    ):

        errors.append(
            "Generated audio file is unexpectedly small."
        )

    return errors


def music_signature(
    prompt: str,
    duration_ms: int,
) -> dict[str, Any]:

    return {
        "provider":
            "elevenlabs",

        "model":
            MUSIC_MODEL,

        "output_format":
            MUSIC_OUTPUT_FORMAT,

        "prompt":
            prompt,

        "music_length_ms":
            duration_ms,

        "force_instrumental":
            True,
    }


def sfx_signature(
    *,
    prompt: str,
    scene_id: int,
    effect_name: str,
    duration_sec: float,
) -> dict[str, Any]:

    return {
        "provider":
            "elevenlabs",

        "model":
            SFX_MODEL,

        "output_format":
            SFX_OUTPUT_FORMAT,

        "scene_id":
            scene_id,

        "effect":
            effect_name,

        "prompt":
            prompt,

        "duration_sec":
            round(
                duration_sec,
                3,
            ),

        "prompt_influence":
            round(
                SFX_PROMPT_INFLUENCE,
                3,
            ),
    }


def existing_generation_matches(
    generation: Any,
    signature: dict[str, Any],
    file_path: Path,
) -> bool:

    if not isinstance(
        generation,
        dict,
    ):

        return False

    return (
        generation.get(
            "status"
        )
        == "passed"
        and generation.get(
            "source_signature"
        )
        == signature
        and file_path.exists()
    )


def invalidate_mix(
    job: dict,
) -> None:

    audio = job.get(
        "audio"
    )

    if isinstance(
        audio,
        dict,
    ):

        audio.pop(
            "mix",
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
            "mixed_video_file"
        ] = None

        output[
            "video_file"
        ] = None

    job.pop(
        "final_qc",
        None,
    )


def generate_music(
    *,
    job: dict,
    duration_ms: int,
    force: bool,
    api_key: str,
    output_name: str = "background_music.mp3",
) -> bool:

    audio = job.setdefault(
        "audio",
        {},
    )

    music = audio.setdefault(
        "background_music",
        {},
    )

    if not music.get(
        "required",
        False,
    ):

        return False

    edit = job.get('scene_edit_scope', {})
    existing_file = music.get('audio_file')
    if (output_name == 'background_music.mp3' and edit and not force
            and 'voiceover' not in edit.get('fields', [])
            and music.get('generation', {}).get('status') == 'passed'
            and existing_file and (PROJECT_ROOT / existing_file).is_file()):
        print('Preserving approved background music for this scene edit.')
        return False

    prompt = build_music_prompt(
        job,
        duration_ms,
    )

    signature = music_signature(
        prompt,
        duration_ms,
    )

    output_path = (
        PROJECT_ROOT
        / "output"
        / str(
            job[
                "job_id"
            ]
        )
        / "audio"
        / "generated"
        / "music"
        / output_name
    )

    if (
        not force
        and existing_generation_matches(
            music.get(
                "generation"
            ),
            signature,
            output_path,
        )
    ):

        print(
            "Background music already matches current job."
        )

        return False

    (
        url,
        body,
    ) = build_music_request(
        prompt,
        duration_ms,
    )

    print(
        f"\nGenerating background music "
        f"({duration_ms / 1000.0:.3f}s)..."
    )

    payload, headers = (
        http_post_json_for_bytes(
            url=url,
            body=body,
            api_key=api_key,
        )
    )

    write_bytes_atomic(
        output_path,
        payload,
    )

    actual = analyze_audio(
        output_path
    )

    errors = validate_audio(
        actual
    )

    if errors:

        output_path.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            "Generated background music failed QC: "
            + "; ".join(
                errors
            )
        )

    checked_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    music[
        "provider"
    ] = "elevenlabs"

    music[
        "model"
    ] = MUSIC_MODEL

    music[
        "audio_file"
    ] = relative_path(
        output_path
    )

    music[
        "generation"
    ] = {
        "status":
            "passed",

        "checked_at":
            checked_at,

        "prompt":
            prompt,

        "source_signature":
            signature,

        "response_headers": {
            key:
                headers[
                    key
                ]
            for key in (
                "song-id",
                "content-type",
            )
            if key in headers
        },

        "actual":
            actual,

        "errors":
            [],

        "warnings":
            [],
    }

    print(
        f"  Saved: {relative_path(output_path)}"
    )

    return True


def generate_sfx(
    *,
    job: dict,
    timeline: list[
        dict[str, Any]
    ],
    force: bool,
    api_key: str,
) -> tuple[
    int,
    int,
    list[str],
]:

    audio = job.setdefault(
        "audio",
        {},
    )

    sound_effects = audio.setdefault(
        "sound_effects",
        {},
    )

    if not sound_effects.get(
        "enabled",
        False,
    ):

        return (
            0,
            0,
            [],
        )

    scene_ids = get_scene_ids(
        timeline
    )

    generated = 0
    skipped = 0
    warnings: list[str] = []

    for index, effect in enumerate(
        sound_effects.get(
            "effects",
            [],
        ),
        start=1,
    ):

        scene_id = effect.get(
            "scene_id"
        )

        try:

            scene_id = int(
                scene_id
            )

        except (
            TypeError,
            ValueError,
        ):

            warning = (
                f"SFX #{index} has invalid scene_id; skipped."
            )

            warnings.append(
                warning
            )

            effect[
                "generation"
            ] = {
                "status":
                    "skipped",

                "reason":
                    "invalid_scene_id",
            }

            skipped += 1
            continue

        if scene_id not in scene_ids:

            warning = (
                f"SFX #{index} references scene {scene_id}, "
                f"which is not in the final assembly timeline; skipped."
            )

            warnings.append(
                warning
            )

            effect[
                "generation"
            ] = {
                "status":
                    "skipped",

                "reason":
                    "scene_not_in_final_timeline",
            }

            skipped += 1
            continue

        effect_name = str(
            effect.get(
                "effect"
            )
            or f"scene {scene_id} sound effect"
        )

        duration_sec = float(
            effect.get(
                "duration_sec",
                SFX_DEFAULT_DURATION_SEC,
            )
        )

        duration_sec = max(
            0.5,
            min(
                30.0,
                duration_sec,
            ),
        )

        prompt = build_sfx_prompt(
            job,
            effect,
            scene_id,
        )

        signature = sfx_signature(
            prompt=prompt,
            scene_id=scene_id,
            effect_name=
                effect_name,
            duration_sec=
                duration_sec,
        )

        output_path = (
            PROJECT_ROOT
            / "output"
            / str(
                job[
                    "job_id"
                ]
            )
            / "audio"
            / "generated"
            / "sfx"
            / (
                f"scene_{scene_id:03d}_"
                f"{index:02d}_"
                f"{sanitize_slug(effect_name)}"
                f".mp3"
            )
        )

        if (
            not force
            and existing_generation_matches(
                effect.get(
                    "generation"
                ),
                signature,
                output_path,
            )
        ):

            print(
                (
                    f"SFX scene {scene_id} already "
                    f"matches current request."
                )
            )

            continue

        (
            url,
            body,
        ) = build_sfx_request(
            prompt,
            duration_sec,
        )

        print(
            (
                f"\nGenerating SFX scene {scene_id}: "
                f"{effect_name}"
            )
        )

        payload, headers = (
            http_post_json_for_bytes(
                url=url,
                body=body,
                api_key=api_key,
            )
        )

        write_bytes_atomic(
            output_path,
            payload,
        )

        actual = analyze_audio(
            output_path
        )

        errors = validate_audio(
            actual
        )

        if errors:

            output_path.unlink(
                missing_ok=True
            )

            raise RuntimeError(
                (
                    f"Generated SFX for scene {scene_id} "
                    f"failed QC: "
                )
                + "; ".join(
                    errors
                )
            )

        effect[
            "provider"
        ] = "elevenlabs"

        effect[
            "model"
        ] = SFX_MODEL

        effect[
            "audio_file"
        ] = relative_path(
            output_path
        )

        effect[
            "generation_prompt"
        ] = prompt

        effect[
            "generation"
        ] = {
            "status":
                "passed",

            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "source_signature":
                signature,

            "response_headers": {
                key:
                    headers[
                        key
                    ]
                for key in (
                    "character-cost",
                    "content-type",
                )
                if key in headers
            },

            "actual":
                actual,

            "errors":
                [],

            "warnings":
                [],
        }

        generated += 1

        print(
            f"  Saved: {relative_path(output_path)}"
        )

    return (
        generated,
        skipped,
        warnings,
    )


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - ELEVENLABS AUDIO ASSETS v1")
    print("=" * 60)

    args = parse_args()

    try:

        job = load_json(
            JOB_FILE
        )

        timeline = get_timeline(
            job
        )

        duration_ms = get_total_duration_ms(
            job,
            timeline,
        )

        audio = job.setdefault(
            "audio",
            {},
        )

        music_required = bool(
            audio
            .get(
                "background_music",
                {},
            )
            .get(
                "required",
                False,
            )
        )

        effects_enabled = bool(
            audio
            .get(
                "sound_effects",
                {},
            )
            .get(
                "enabled",
                False,
            )
        )

        need_music = (
            not args.sfx_only
            and (music_required or any(s.get("music_override") for s in job.get("visuals", {}).get("scenes", [])))
        )

        need_sfx = (
            not args.music_only
            and effects_enabled
        )

        if not (
            need_music
            or need_sfx
        ):

            raise RuntimeError(
                "No audio assets are enabled for generation."
            )

        api_key = get_api_key()

        changed = False

        generated_sfx = 0
        skipped_sfx = 0
        warnings: list[str] = []

        if need_music:

            changed = (
                generate_music(
                    job=job,
                    duration_ms=
                        duration_ms,
                    force=args.force,
                    api_key=api_key,
                )
                or changed
            )

        if not args.sfx_only:
            from scene_music import generate_scene_music
            changed = generate_scene_music(job, timeline, force=args.force, api_key=api_key) or changed

        if need_sfx:

            (
                generated_sfx,
                skipped_sfx,
                sfx_warnings,
            ) = generate_sfx(
                job=job,
                timeline=timeline,
                force=args.force,
                api_key=api_key,
            )

            changed = (
                changed
                or generated_sfx
                > 0
            )

            warnings.extend(
                sfx_warnings
            )

        if changed:

            invalidate_mix(
                job
            )

        audio[
            "assets"
        ] = {
            "status":
                "passed",

            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "provider":
                "elevenlabs",

            "music_generated_or_current":
                need_music,

            "sfx_generated_this_run":
                generated_sfx,

            "sfx_skipped":
                skipped_sfx,

            "errors":
                [],

            "warnings":
                warnings,
        }

        set_legacy_status_from_stage(
            job,
            "audio_assets",
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

        audio = job.setdefault(
            "audio",
            {},
        )

        audio[
            "assets"
        ] = {
            "status":
                "failed",

            "checked_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "provider":
                "elevenlabs",

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
            "audio_assets",
        )

        save_job_atomic(
            job
        )

        print(
            f"\nERROR: {exc}"
        )

        return 1

    print(
        "\n" + "=" * 60
    )

    print(
        "AUDIO ASSET GENERATION COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nMusic file: "
        f"{job.get('audio', {}).get('background_music', {}).get('audio_file')}"
    )

    print(
        f"SFX generated this run: "
        f"{generated_sfx}"
    )

    print(
        f"SFX skipped: "
        f"{skipped_sfx}"
    )

    for warning in warnings:

        print(
            f"  [WARNING] {warning}"
        )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
