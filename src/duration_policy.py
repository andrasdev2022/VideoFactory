"""Shared inclusive duration acceptance range for planning and export."""
import math


def duration_range(spec: dict) -> tuple[float, float]:
    video = spec.get('video', {})
    lower = float(video.get('min_duration_sec', 25))
    upper = float(video.get('max_duration_sec', 35))
    target = float(video.get('target_duration_sec', 30))
    if not all(math.isfinite(x) for x in (lower, upper, target)) or not 0 < lower <= target <= upper:
        raise ValueError('Video duration must satisfy 0 < min_duration_sec <= target_duration_sec <= max_duration_sec.')
    return lower, upper


def correction_target(total: float, spec: dict) -> float:
    lower, upper = duration_range(spec)
    return min(upper, max(lower, total))
