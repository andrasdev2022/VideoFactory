"""Extend short still-motion jobs using visual holds, preserving approved speech."""
import math
import os


def extend_visual_holds(job: dict, spec: dict) -> bool:
    if os.getenv('VIDEO_PROVIDER', 'runway').strip().lower() != 'still_motion':
        return False
    scenes = job.get('script', {}).get('scenes', [])
    if not scenes or job.get('script', {}).get('duration_normalization', {}).get('status') == 'pending_remeasure':
        return False
    durations = []
    limits = []
    for scene in scenes:
        timing = scene.get('timing', {})
        qc = scene.get('voice', {}).get('qc', {})
        if timing.get('status') != 'passed' or qc.get('status') != 'passed':
            return False
        duration = float(timing.get('render_duration_sec') or 0)
        voice = float(qc.get('actual', {}).get('duration_sec') or 0)
        headroom = float(timing.get('headroom_sec', 0.3))
        limit = float(timing.get('max_video_duration_sec', 10))
        if not all(math.isfinite(v) for v in (duration, voice, headroom, limit)):
            return False
        if voice <= 0 or headroom < 0 or duration + 0.001 < voice + headroom or duration > limit:
            return False
        if abs(float(timing.get('voice_duration_sec', -1)) - voice) > 0.001:
            return False
        durations.append(duration)
        limits.append(limit)
    video = spec.get('video', {})
    target = float(video.get('target_duration_sec', 30))
    if not math.isfinite(target) or not float(video.get('min_duration_sec', 20)) <= target <= float(video.get('max_duration_sec', 45)):
        return False
    remaining = round(target - sum(durations), 3)
    if remaining <= 0.001 or sum(limits) + 0.001 < target:
        return False
    # Do not silently alter timings underneath already generated visual assets.
    if any(s.get('video', {}).get('file') for s in job.get('visuals', {}).get('scenes', [])):
        return False
    additions = [0.0] * len(scenes)
    while remaining > 0.0005:
        active = [i for i in range(len(scenes)) if limits[i] - durations[i] - additions[i] > 0.0005]
        if not active:
            return False
        share = max(0.001, round(remaining / len(active), 3))
        for i in active:
            extra = round(min(share, remaining, limits[i] - durations[i] - additions[i]), 3)
            additions[i] = round(additions[i] + extra, 3)
            remaining = round(remaining - extra, 3)
            if remaining <= 0.0005:
                break
    for scene, duration, extra in zip(scenes, durations, additions):
        timing = scene['timing']
        timing['render_duration_sec'] = round(duration + extra, 3)
        timing['visual_hold_sec'] = round(timing.get('visual_hold_sec', 0) + extra, 3)
        timing['timing_policy'] = 'still_motion_visual_hold_v1'
    from scene_timing import calculate_job_timing_summary
    job['timing_summary'] = calculate_job_timing_summary(job, spec)
    normalization = job['script'].setdefault('duration_normalization', {})
    normalization.update(status='completed', changed_scene_ids=[], method='still_motion_visual_hold_v1')
    print(f'Still-motion visual holds: {sum(durations):.3f}s -> {target:.3f}s; narration preserved.')
    return True
