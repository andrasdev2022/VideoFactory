from __future__ import annotations

from genre_policy import prepare_spec, genre_instruction, genre_name
from visual_styles import CHOICES, select_style, persist_style

from copy import deepcopy
import argparse
import json
import os
import shutil
import sys

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from validator import load_json, load_yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"
SPEC_FILE = PROJECT_ROOT / "config" / "video_spec_v1.yaml"
HISTORY_DIR = PROJECT_ROOT / "jobs" / "history"

MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
)


class IdeaBlueprint(BaseModel):
    title: str
    concept: str
    genre: str
    target_audience: str
    hook: str
    core_joke: str = ""  # Legacy field; empty for non-comedy genres.
    ending: str


class CharacterBlueprint(BaseModel):
    name: str
    role: str
    description: str
    personality: str


class StyleBlueprint(BaseModel):
    visual: str
    cinematic: bool
    realistic: bool
    lighting: str
    camera: str
    color_palette: str


class MetadataBlueprint(BaseModel):
    title: str
    description: str
    hashtags: list[str]
    thumbnail_text: str


class BootstrapOutput(BaseModel):
    idea: IdeaBlueprint
    characters: list[CharacterBlueprint]
    style: StyleBlueprint
    metadata: MetadataBlueprint
    background_music_style: str


SYSTEM_PROMPT = """
You are the NEW JOB bootstrap worker inside an automated
short-form AI video factory.

Convert the user's rough seed into a production-ready story blueprint.

Rules:
- Preserve the user's core idea.
- Follow the supplied genre across the story, metadata and music. For non-comedy genres, core_joke must be empty; use an emotional conflict instead.
- If visual_spec.style.preset is present, it overrides conflicting visual-medium or realism wording in the seed. Use it consistently for style and character appearance.
- Write the production content in English.
- Make it suitable for a roughly 30-second vertical short.
- Keep the story simple enough for reliable image-to-video generation.
- Prefer 1-3 recurring main characters.
- Make every character visually distinctive and reproducible.
- Do not use copyrighted fictional characters, brands, celebrities,
  logos, or recognizable protected franchises.
- The hook must be immediate.
- The ending must contain a payoff, joke, surprise, or emotional beat.
- Metadata must accurately describe the resulting story.
- Hashtags: 3-8 items, each starting with #.
- Thumbnail text should be short and punchy.
- Background music style should support narration and not overpower it.
- Do not write scene-level script here. A later worker does that.
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a fresh Video Factory job from one rough idea."
        )
    )

    parser.add_argument(
        "--idea",
        required=True,
        help="Rough story seed for the new video.",
    )

    parser.add_argument(
        "--job-id",
        default=None,
        help="Optional explicit job ID.",
    )

    parser.add_argument("--visual-style", choices=CHOICES, default=None, help="Visual preset for this new job.")
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def make_job_id() -> str:
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%d-%H%M%S"
    )


def sanitize_hashtags(
    values: list[str],
) -> list[str]:

    result: list[str] = []

    for value in values:
        value = " ".join(
            str(value).split()
        ).strip()

        if not value:
            continue

        if not value.startswith("#"):
            value = "#" + value

        value = value.replace(
            " ",
            "",
        )

        if value not in result:
            result.append(
                value
            )

    defaults = [
        "#shorts",
        "#ai",
        "#story",
    ]

    for value in defaults:
        if len(result) >= 3:
            break

        if value not in result:
            result.append(
                value
            )

    return result[:8]


def archive_current_job() -> Path | None:

    if not JOB_FILE.exists():
        return None

    try:
        job = load_json(
            JOB_FILE
        )

        job_id = str(
            job.get(
                "job_id"
            )
            or "unknown"
        )

    except Exception:
        job_id = "unreadable"

    HISTORY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        HISTORY_DIR
        / f"{job_id}.json"
    )

    if destination.exists():
        stamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d-%H%M%S"
        )

        destination = (
            HISTORY_DIR
            / f"{job_id}-{stamp}.json"
        )

    shutil.copy2(
        JOB_FILE,
        destination,
    )

    return destination


def save_job_atomic(
    job: dict,
) -> None:

    JOB_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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


def build_generation_context(
    seed: str,
    spec: dict,
) -> dict[str, Any]:

    return {
        "user_seed":
            seed,

        "video": {
            "target_duration_sec":
                spec[
                    "video"
                ][
                    "target_duration_sec"
                ],

            "language":
                spec[
                    "video"
                ].get(
                    "language",
                    "en",
                ),

            "aspect_ratio":
                spec[
                    "video"
                ][
                    "aspect_ratio"
                ],
        },

        "content_spec":
            spec.get(
                "content",
                {},
            ),

        "visual_spec":
            spec.get(
                "visual",
                {},
            ),
    }


def generate_bootstrap(
    client: OpenAI,
    seed: str,
    spec: dict,
) -> BootstrapOutput:

    spec = prepare_spec(spec)
    context = build_generation_context(
        seed,
        spec,
    )

    response = client.responses.parse(
        model=MODEL,

        input=[
            {
                "role":
                    "system",

                "content":
                    SYSTEM_PROMPT + genre_instruction(spec=spec),
            },
            {
                "role":
                    "user",

                "content":
                    (
                        "Create the new video-job blueprint "
                        "from this input:\n\n"
                        + json.dumps(
                            context,
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
            },
        ],

        text_format=BootstrapOutput,
    )

    output = response.output_parsed

    if output is None:
        raise RuntimeError(
            "Bootstrap model returned no parsed output."
        )

    return output


def validate_bootstrap(
    output: BootstrapOutput,
) -> list[str]:

    errors: list[str] = []

    if not (
        1
        <= len(
            output.characters
        )
        <= 3
    ):
        errors.append(
            "Bootstrap must contain 1-3 characters."
        )

    if not output.idea.title.strip():
        errors.append(
            "Idea title is empty."
        )

    if not output.idea.hook.strip():
        errors.append(
            "Idea hook is empty."
        )

    if not output.idea.ending.strip():
        errors.append(
            "Idea ending is empty."
        )

    if not output.metadata.title.strip():
        errors.append(
            "Metadata title is empty."
        )

    if len(
        output.metadata.title
    ) > 100:
        errors.append(
            "Metadata title exceeds 100 characters."
        )

    hashtags = sanitize_hashtags(
        output.metadata.hashtags
    )

    if not (
        3
        <= len(
            hashtags
        )
        <= 8
    ):
        errors.append(
            "Metadata must contain 3-8 hashtags."
        )

    return errors


def build_job(
    output: BootstrapOutput,
    spec: dict,
    job_id: str,
) -> dict:

    idea = output.idea.model_dump()

    idea.update(
        {
            "idea_id":
                f"idea-{job_id}",

            "originality": {
                "is_original":
                    True,

                "source_material":
                    None,
            },
        }
    )

    characters = []

    for index, character in enumerate(
        output.characters,
        start=1,
    ):
        item = character.model_dump()

        item[
            "character_id"
        ] = f"char-{index:03d}"

        item[
            "visual_consistency_key"
        ] = (
            f"character_{index:03d}_v1"
        )

        characters.append(
            item
        )

    metadata = output.metadata.model_dump()

    metadata[
        "hashtags"
    ] = sanitize_hashtags(
        metadata[
            "hashtags"
        ]
    )

    thumbnail_text = metadata.pop(
        "thumbnail_text"
    )

    metadata[
        "thumbnail"
    ] = {
        "required":
            True,

        "text":
            thumbnail_text,

        "image_file":
            None,
    }

    video_spec = spec[
        "video"
    ]

    output_spec = spec.get(
        "output",
        {},
    )

    platforms = spec.get(
        "platforms",
        {},
    )

    publishing = {
        platform: {
            "enabled":
                bool(
                    config.get(
                        "enabled",
                        False,
                    )
                ),

            "status":
                "pending",

            "platform_id":
                None,
        }
        for platform, config
        in platforms.items()
    }

    spec = prepare_spec(spec)
    idea["genre"] = genre_name(spec)
    if "comedy" not in genre_name(spec).lower():
        idea["core_joke"] = ""
    style = persist_style(output.style.model_dump(), spec)

    style[
        "consistency_required"
    ] = True

    return {
        "spec_snapshot": deepcopy(spec),
        "creative_direction": {"genre": genre_name(spec)},
        "job_id":
            job_id,

        "spec_version":
            str(
                spec.get(
                    "version"
                )
            ),

        "created_at":
            utc_now_iso(),

        "status":
            "created",

        "seed":
            {
                "text":
                    None,
            },

        "idea":
            idea,

        "characters":
            characters,

        "style":
            style,

        "script":
            {},

        "visuals": {
            "global_prompt":
                "",

            "scenes":
                [],
        },

        "audio": {
            "voiceover": {
                "required":
                    True,

                "provider":
                    "openai",

                "language":
                    video_spec.get(
                        "language",
                        "en",
                    ),

                "style":
                    spec.get("audio", {}).get("voiceover", {}).get("style", "natural storyteller"),

                "speed":
                    1.0,

                "audio_file":
                    None,
            },

            "background_music": {
                "required":
                    True,

                "provider":
                    "elevenlabs",

                "style":
                    output.background_music_style,

                "volume":
                    0.20,

                "audio_file":
                    None,
            },

            "sound_effects": {
                "enabled":
                    True,

                "effects":
                    [],
            },
        },

        "subtitles": {
            "enabled":
                True,

            "language":
                video_spec.get(
                    "language",
                    "en",
                ),

            "burned_in":
                True,

            "max_lines":
                int(
                    spec[
                        "subtitles"
                    ].get(
                        "max_lines",
                        2,
                    )
                ),

            "max_chars_per_line":
                int(
                    spec[
                        "subtitles"
                    ].get(
                        "max_chars_per_line",
                        32,
                    )
                ),

            "style": {
                "font":
                    "Arial Bold",

                "position":
                    "lower_center",

                "animation":
                    "word_highlight",
            },

            "subtitle_file":
                None,
        },

        "metadata":
            metadata,

        "output": {
            "directory":
                f"output/{job_id}/",

            "video_file":
                None,

            "video_format":
                output_spec.get(
                    "video_format",
                    "mp4",
                ),

            "video_codec":
                output_spec.get(
                    "video_codec",
                    "h264",
                ),

            "audio_codec":
                output_spec.get(
                    "audio_codec",
                    "aac",
                ),

            "resolution":
                video_spec[
                    "resolution"
                ],

            "fps":
                video_spec[
                    "fps"
                ],
        },

        "publishing":
            publishing,

        "analytics": {
            "status":
                "not_published",

            "views":
                None,

            "likes":
                None,

            "comments":
                None,

            "shares":
                None,

            "average_watch_time_sec":
                None,

            "completion_rate":
                None,

            "engagement_rate":
                None,
        },

        "errors":
            [],
    }


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - NEW JOB v1")
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
        spec = load_yaml(
            SPEC_FILE
        )

        spec = prepare_spec(select_style(spec, args.visual_style))
        print(f"Visual style: {args.visual_style or 'default'}")

        client = OpenAI()

        print(
            f"\nModel: {MODEL}"
        )

        print(
            f"Seed:  {args.idea}"
        )

        result = generate_bootstrap(
            client,
            args.idea,
            spec,
        )

        errors = validate_bootstrap(
            result
        )

        if errors:
            raise RuntimeError(
                "; ".join(
                    errors
                )
            )

        job_id = (
            args.job_id
            or make_job_id()
        )

        archived = archive_current_job()

        job = build_job(
            result,
            spec,
            job_id,
        )

        job[
            "seed"
        ][
            "text"
        ] = args.idea

        save_job_atomic(
            job
        )

    except Exception as exc:
        print(
            f"\nERROR: {exc}"
        )
        return 1

    print(
        "\nNEW JOB CREATED"
    )

    print(
        f"Job ID:     {job_id}"
    )

    print(
        f"Title:      {job['idea']['title']}"
    )

    print(
        f"Characters: {len(job['characters'])}"
    )

    for character in job[
        "characters"
    ]:
        print(
            (
                f"  {character['character_id']} - "
                f"{character['name']}: "
                f"{character['description']}"
            )
        )

    if archived is not None:
        print(
            (
                "Previous active job archived: "
                + str(
                    archived.relative_to(
                        PROJECT_ROOT
                    )
                )
            )
        )

    print(
        "\nActive job: jobs/video_job.json"
    )

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
