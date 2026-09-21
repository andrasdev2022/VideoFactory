"""Deterministic, CPU-only video from one approved image."""
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    mode: str = "zoom"
    max_zoom: float = 1.05
    width: int = 720
    height: int = 1280
    fps: int = 24


def load_config(overrides=None):
    overrides = overrides or {}
    config = Config(
        mode=str(overrides.get("mode", os.getenv("STILL_MOTION_MODE", "zoom"))).strip().lower(),
        max_zoom=float(overrides.get("max_zoom", os.getenv("STILL_MOTION_MAX_ZOOM", "1.05"))),
    )
    if config.mode not in {"zoom", "hold"}:
        raise ValueError("STILL_MOTION_MODE must be zoom or hold (pan is not enabled).")
    if not math.isfinite(config.max_zoom) or not 1.0 <= config.max_zoom <= 1.08:
        raise ValueError("STILL_MOTION_MAX_ZOOM must be between 1.0 and 1.08.")
    return config


def frame_count(duration, config):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Still-motion duration must be positive and finite.")
    return max(1, math.ceil(duration * config.fps - 1e-9))


def motion_prompt(config):
    if config.mode == "hold" or config.max_zoom == 1:
        return "Static hold of the approved image. No character, object or camera motion."
    return (f"One continuous, slow centered camera push-in from 1.0x to {config.max_zoom:g}x. "
            "Only the image framing changes. Characters, faces, clothing and props remain "
            "unchanged with no independent movement. Keep all main faces visible.")


def build_command(image, output, duration, config):
    count = frame_count(duration, config)
    zoom = (f"1+{config.max_zoom - 1:.8f}*on/{max(1, count - 1)}"
            if config.mode == "zoom" else "1")
    vf = (
        f"scale={config.width * 2}:{config.height * 2}:force_original_aspect_ratio=increase,"
        f"crop={config.width * 2}:{config.height * 2},setsar=1,"
        f"zoompan=z='{zoom}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
        f"d={count}:s={config.width}x{config.height}:fps={config.fps},format=yuv420p"
    )
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(image),
            "-vf", vf, "-frames:v", str(count), "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-movflags", "+faststart", str(output)]


def generate(*, input_image, output_file, duration_sec, config):
    output_file = Path(output_file)
    if not Path(input_image).is_file():
        raise ValueError(f"Source image missing: {input_image}")
    count = frame_count(duration_sec, config)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_file.with_name(output_file.stem + ".still.tmp.mp4")
    log = output_file.with_suffix(".still-motion.log")
    command = build_command(input_image, temporary, duration_sec, config)
    try:
        with log.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({"config": asdict(config), "command": command}) + "\n")
            stream.flush()
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
            stream.write(f"\nExit code: {result.returncode}\n")
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"Still-motion render failed; see {log}")
        temporary.replace(output_file)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "provider": "still_motion", "model": "ffmpeg_still_motion_v1",
        "ratio": f"{config.width}:{config.height}", "width": config.width,
        "height": config.height, "fps": config.fps, "num_frames": count,
        "still_motion_config": asdict(config),
        "effective_motion_prompt": motion_prompt(config),
        "task_id": f"still-motion-{output_file.stem}",
    }
