"""Local LTX motion planning; no model imports or generation calls."""

POLICY_VERSION = "local_ltx_motion_v1"

GENERATION_RULES = """
LOCAL LTX OVERRIDE (takes precedence over general motion advice):
- Use a locked-off camera, with no pan, push-in, zoom, or orbit.
- Request exactly one small, visible action by one subject already in frame.
  Prefer a small head tilt or a small paw movement; do not chain actions.
- Keep other subjects and props in their source-image positions.
- Keep the story's gag readable in the image. Do not depend on prop reveals,
  object transfers, walking, full-body turns, or coordinated character actions.
- Keep faces unobscured. Do not animate steam, smoke, fog, mist, or particles.
  For new image prompts, avoid foreground haze covering the characters.
- Use positive, concrete language and at most 45 words for motion_prompt.
- Keep continuity_notes brief and about identity, clothing, and composition,
  not additional actions. Never request a scene transition.
"""


def system_prompt(base: str, provider: str) -> str:
    return base + "\n" + GENERATION_RULES if provider == "local_ltx" else base


def previous_seed(scene: dict) -> int | None:
    video = scene.get("video", {})
    if video.get("provider") == "local_ltx" and video.get("seed") is not None:
        return int(video["seed"])
    value = scene.get("local_ltx_last_seed")
    return int(value) if value is not None else None


def preserve_seed(scene: dict) -> None:
    seed = previous_seed(scene)
    if seed is not None:
        scene["local_ltx_last_seed"] = seed


def continuity_failure(qc: dict) -> bool:
    if qc.get("morphing_or_shape_drift") or qc.get("unexpected_scene_cut"):
        return True
    if any(qc.get(key) is False for key in (
        "source_frame_continuity_ok", "anatomy_ok", "temporal_progression_coherent",
    )):
        return True
    return any(
        character.get(key) is False
        for character in qc.get("characters", [])
        for key in ("present_throughout", "identity_stable", "appearance_stable", "clothing_stable")
    )


def build_motion_plan(job: dict, scene: dict, retry: bool = False) -> dict:
    """Simplify failed motion rather than append demands to a failed plan.

    Keep authored motion on the initial attempt. Existing jobs remain usable;
    new and --motion-only prompts use GENERATION_RULES at planning time.
    """
    qc = scene.get("video", {}).get("semantic_qc", {})
    safe = scene.get("motion_strategy") == "safe_fallback_v2"
    stage = "authored"
    motion = scene.get("motion_prompt", "").strip()
    if safe or (retry and qc.get("status") == "failed"):
        names = {c.get("character_id"): c.get("name") for c in job.get("characters", [])}
        subject = next((names[c] for c in scene.get("characters", []) if names.get(c)), None)
        # No character-specific anatomy for a scene with no known character.
        if subject:
            if safe or continuity_failure(qc):
                motion = f"{subject} breathes gently in place with a small visible chest movement."
                stage = "identity_recovery" if not safe else "minimal_motion"
            else:
                motion = f"{subject} makes one small, slow head tilt while staying in place."
                stage = "single_motion"
        else:
            motion = "The main subject makes one small, slow movement in place."
            stage = "minimal_motion" if safe else "single_motion"
        motion = (
            "Locked-off camera. " + motion
            + " All subjects stay clearly visible in their original positions. "
            "Faces, bodies, clothing, props and background remain stable. "
            "Clear view throughout. One continuous shot."
        )

    continuity = scene.get("continuity_notes", "").strip()
    # Retry plans already contain continuity constraints. Do not reintroduce
    # old action/steam/reveal requirements through verbose continuity notes.
    prompt = motion
    if stage == "authored" and continuity:
        prompt += " Continuity: " + continuity
    if stage == "authored":
        prompt += " Preserve identity and composition. One continuous shot."
    return {"version": POLICY_VERSION, "stage": stage, "motion_prompt": motion, "prompt": prompt}


def qc_motion_prompt(scene: dict) -> str | None:
    video = scene.get("video", {})
    if video.get("provider") == "local_ltx" and video.get("effective_motion_prompt"):
        return video["effective_motion_prompt"]
    return scene.get("motion_prompt")
