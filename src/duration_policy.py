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


# Supported pipeline bounds; local_ltx retains its existing conservative range.
# still_motion is local FFmpeg rendering and has no fixed provider ceiling.
PROVIDER_SCENE_BOUNDS = {'runway': (2.0, 10.0), 'local_ltx': (2.0, 10.0),
                         'still_motion': (0.0, math.inf)}

def scene_duration_range(spec: dict, provider: str | None = None) -> tuple[float, float]:
    import os
    provider = (provider if provider is not None else os.getenv('VIDEO_PROVIDER', 'local_ltx')).strip().lower()
    if provider not in PROVIDER_SCENE_BOUNDS:
        raise ValueError(f'Unsupported VIDEO_PROVIDER: {provider}')
    scene = spec.get('visual', {}).get('scene', {})
    lower = float(scene.get('min_duration_sec', 2.0))
    upper = float(scene.get('max_duration_sec', 10.0))
    if not all(math.isfinite(v) for v in (lower, upper)) or not 0 < lower <= upper:
        raise ValueError('visual.scene duration must satisfy 0 < min_duration_sec <= max_duration_sec (finite).')
    provider_min, provider_max = PROVIDER_SCENE_BOUNDS[provider]
    minimum, maximum = max(lower, provider_min), min(upper, provider_max)
    if minimum > maximum:
        raise ValueError(f'visual.scene range {lower:g}-{upper:g}s has no overlap with '
                         f'{provider} supported range {provider_min:g}-{provider_max:g}s; fix the YAML or provider.')
    return minimum, maximum

def scene_planning_spec(spec: dict) -> dict:
    """Constrain planning without changing the saved YAML snapshot."""
    from copy import deepcopy
    result = deepcopy(spec)
    minimum, maximum = scene_duration_range(spec)
    result.setdefault('visual', {}).setdefault('scene', {}).update(
        min_duration_sec=minimum, max_duration_sec=maximum)
    return result


def approved_scene_duration_range(job: dict, timing: dict, provider: str) -> tuple[float, float]:
    """Use the job snapshot; legacy jobs retain their recorded timing contract."""
    if isinstance(job.get('spec_snapshot'), dict):
        return scene_duration_range(job['spec_snapshot'], provider)
    return scene_duration_range({'visual': {'scene': {
        'min_duration_sec': timing.get('min_video_duration_sec', 2.0),
        'max_duration_sec': timing.get('max_video_duration_sec', 10.0),
    }}}, provider)
