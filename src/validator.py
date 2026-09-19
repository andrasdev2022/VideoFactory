from pathlib import Path
import json
import sys

import yaml


# A projekt gyökérkönyvtára:
# video_factory/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SPEC_FILE = PROJECT_ROOT / "config" / "video_spec_v1.yaml"
JOB_FILE = PROJECT_ROOT / "jobs" / "video_job.json"


def load_yaml(path: Path) -> dict:
    """Load a YAML file and return its contents as a dictionary."""
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def load_json(path: Path) -> dict:
    """Load a JSON file and return its contents as a dictionary."""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def validate_video_job(spec: dict, job: dict) -> list[str]:
    """
    Validate a video job against VIDEO_SPEC.

    Returns a list of validation errors.
    An empty list means that validation passed.
    """
    errors = []

    # ---------------------------------------------------------
    # 1. SPEC VERSION
    # ---------------------------------------------------------

    expected_version = str(spec.get("version"))
    actual_version = str(job.get("spec_version"))

    if actual_version != expected_version:
        errors.append(
            f"Spec version mismatch: "
            f"job={actual_version}, expected={expected_version}"
        )

    # ---------------------------------------------------------
    # 2. REQUIRED TOP-LEVEL FIELDS
    # ---------------------------------------------------------

    required_fields = [
        "job_id",
        "spec_version",
        "status",
        "idea",
        "script",
        "visuals",
        "audio",
        "subtitles",
        "metadata",
        "output",
    ]

    for field in required_fields:
        if field not in job:
            errors.append(f"Missing required field: {field}")

    # If important sections are missing, further checks could fail.
    if errors:
        return errors

    # ---------------------------------------------------------
    # 3. VIDEO DURATION
    # ---------------------------------------------------------

    target_duration = job["script"].get("target_duration_sec")

    min_duration = spec["video"]["min_duration_sec"]
    max_duration = spec["video"]["max_duration_sec"]

    if target_duration is None:
        errors.append("script.target_duration_sec is missing")

    elif not min_duration <= target_duration <= max_duration:
        errors.append(
            f"Invalid target duration: {target_duration}s. "
            f"Allowed range: {min_duration}-{max_duration}s"
        )

    # ---------------------------------------------------------
    # 4. SCENES
    # ---------------------------------------------------------

    scenes = job["script"].get("scenes", [])

    min_scenes = spec["content"]["structure"].get(
        "scene_count",
        spec["content"].get("scene_count", {})
    ).get("min", 1)

    max_scenes = spec["content"]["structure"].get(
        "scene_count",
        spec["content"].get("scene_count", {})
    ).get("max", 999)

    scene_count = len(scenes)

    if not min_scenes <= scene_count <= max_scenes:
        errors.append(
            f"Invalid scene count: {scene_count}. "
            f"Allowed range: {min_scenes}-{max_scenes}"
        )

    # ---------------------------------------------------------
    # 5. INDIVIDUAL SCENE DURATIONS
    # ---------------------------------------------------------

    min_scene_duration = spec["visual"]["scene"]["min_duration_sec"]
    max_scene_duration = spec["visual"]["scene"]["max_duration_sec"]

    for scene in scenes:
        scene_id = scene.get("scene_id", "?")
        duration = scene.get("duration_sec")

        if duration is None:
            errors.append(
                f"Scene {scene_id}: duration_sec is missing"
            )
            continue

        if not min_scene_duration <= duration <= max_scene_duration:
            errors.append(
                f"Scene {scene_id}: invalid duration {duration}s. "
                f"Allowed range: "
                f"{min_scene_duration}-{max_scene_duration}s"
            )

    # ---------------------------------------------------------
    # 6. TOTAL SCENE DURATION
    # ---------------------------------------------------------

    durations = [
        scene.get("duration_sec")
        for scene in scenes
        if isinstance(scene.get("duration_sec"), (int, float))
    ]

    total_scene_duration = sum(durations)

    if (
        target_duration is not None
        and total_scene_duration != target_duration
    ):
        errors.append(
            f"Scene durations total {total_scene_duration}s, "
            f"but target duration is {target_duration}s"
        )

    # ---------------------------------------------------------
    # 7. OUTPUT RESOLUTION
    # ---------------------------------------------------------

    expected_resolution = spec["video"]["resolution"]
    actual_resolution = job["output"].get("resolution")

    if actual_resolution != expected_resolution:
        errors.append(
            f"Invalid resolution: {actual_resolution}. "
            f"Expected: {expected_resolution}"
        )

    # ---------------------------------------------------------
    # 8. FPS
    # ---------------------------------------------------------

    expected_fps = spec["video"]["fps"]
    actual_fps = job["output"].get("fps")

    if actual_fps != expected_fps:
        errors.append(
            f"Invalid FPS: {actual_fps}. "
            f"Expected: {expected_fps}"
        )

    # ---------------------------------------------------------
    # 9. SUBTITLES
    # ---------------------------------------------------------

    if spec["subtitles"]["enabled"]:
        if not job["subtitles"].get("enabled"):
            errors.append(
                "Subtitles are required by VIDEO_SPEC"
            )

    # ---------------------------------------------------------
    # 10. VOICEOVER
    # ---------------------------------------------------------

    if spec["audio"]["voiceover"]["required"]:
        voiceover = job["script"].get("voiceover")

        if not voiceover:
            errors.append(
                "Voiceover is required but script.voiceover is empty"
            )

    # ---------------------------------------------------------
    # 11. HOOK
    # ---------------------------------------------------------

    if spec["quality"]["content"]["hook_required"]:
        hook = job["idea"].get("hook")

        if not hook:
            errors.append(
                "Hook is required but idea.hook is empty"
            )

    return errors


def main() -> int:

    print("=" * 60)
    print("VIDEO FACTORY - VALIDATOR v1")
    print("=" * 60)

    try:
        spec = load_yaml(SPEC_FILE)
        job = load_json(JOB_FILE)

    except FileNotFoundError as exc:
        print(f"\nERROR: File not found: {exc.filename}")
        return 1

    except json.JSONDecodeError as exc:
        print(f"\nERROR: Invalid JSON: {exc}")
        return 1

    except yaml.YAMLError as exc:
        print(f"\nERROR: Invalid YAML: {exc}")
        return 1

    errors = validate_video_job(spec, job)

    print(f"\nJob ID:       {job.get('job_id')}")
    print(f"Spec version: {job.get('spec_version')}")
    print(f"Status:       {job.get('status')}")

    scenes = job.get("script", {}).get("scenes", [])

    total_duration = sum(
        scene.get("duration_sec", 0)
        for scene in scenes
    )

    print(f"Scenes:       {len(scenes)}")
    print(f"Duration:     {total_duration}s")

    if errors:

        print("\nVALIDATION FAILED\n")

        for error in errors:
            print(f"  [ERROR] {error}")

        print(f"\n{len(errors)} error(s) found.")

        return 1

    print("\nVALIDATION PASSED")
    print("\nVideoJob conforms to VIDEO_SPEC v1.")

    return 0


if __name__ == "__main__":
    sys.exit(main())