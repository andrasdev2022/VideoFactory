from __future__ import annotations

import json
import os

from pathlib import Path
from typing import Any


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

JOBS_ROOT = (
    PROJECT_ROOT
    / "jobs"
)

RUNS_ROOT = (
    JOBS_ROOT
    / "runs"
)

ACTIVE_JOB_POINTER = (
    JOBS_ROOT
    / "active_job.txt"
)

LEGACY_JOB_FILE = (
    JOBS_ROOT
    / "video_job.json"
)


def resolve_project_path(
    value: str | Path,
) -> Path:

    path = Path(
        value
    )

    if not path.is_absolute():

        path = (
            PROJECT_ROOT
            / path
        )

    return path.resolve()


def get_job_file() -> Path:

    override = os.getenv(
        "VIDEO_JOB_FILE",
        "",
    ).strip()

    if override:

        return resolve_project_path(
            override
        )

    if ACTIVE_JOB_POINTER.exists():

        value = (
            ACTIVE_JOB_POINTER
            .read_text(
                encoding="utf-8"
            )
            .strip()
        )

        if value:

            return resolve_project_path(
                value
            )

    return LEGACY_JOB_FILE


def job_file_for_id(
    job_id: str,
) -> Path:

    return (
        RUNS_ROOT
        / job_id
        / "video_job.json"
    )


def set_active_job_file(
    job_file: Path,
) -> None:

    job_file = job_file.resolve()

    try:

        relative = job_file.relative_to(
            PROJECT_ROOT
        )

        value = str(
            relative
        ).replace(
            "\\",
            "/",
        )

    except ValueError:

        value = str(
            job_file
        )

    ACTIVE_JOB_POINTER.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        ACTIVE_JOB_POINTER
        .with_name(
            ACTIVE_JOB_POINTER.name
            + ".tmp"
        )
    )

    temporary.write_text(
        value
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        ACTIVE_JOB_POINTER,
    )


def load_active_job() -> dict[str, Any]:

    path = get_job_file()

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


def save_job_atomic(
    job: dict[str, Any],
    path: Path | None = None,
) -> None:

    path = (
        path
        if path is not None
        else get_job_file()
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        path.name
        + ".tmp"
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
        path,
    )


def current_job_id() -> str | None:

    try:

        return str(
            load_active_job()
            .get(
                "job_id"
            )
            or ""
        ) or None

    except Exception:

        return None
