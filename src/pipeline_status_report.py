from pathlib import Path

from validator import load_json
from pipeline_status import (
    refresh_pipeline_status,
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


def main() -> int:

    job = load_json(
        JOB_FILE
    )

    status = (
        refresh_pipeline_status(
            job
        )
    )

    print("=" * 72)
    print("VIDEO FACTORY - PIPELINE STATUS")
    print("=" * 72)

    print(
        f"\nJob ID: "
        f"{job.get('job_id')}"
    )

    print(
        f"Legacy status: "
        f"{job.get('status')}"
    )

    print()

    print(
        f"{'STAGE':32}"
        f"{'STATE':12}"
        f"{'READY':10}"
        f"{'FAILED':10}"
        f"{'PENDING':10}"
    )

    print(
        "-" * 72
    )

    for stage, summary in status.items():

        ready = (
            f"{summary['ready']}/"
            f"{summary['total']}"
        )

        print(
            f"{stage:32}"
            f"{summary['state']:12}"
            f"{ready:10}"
            f"{summary['failed']:<10}"
            f"{summary['pending']:<10}"
        )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )