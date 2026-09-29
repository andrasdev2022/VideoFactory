"""Shared SFX policy: the current YAML can veto SFX even on resumed jobs."""
from pathlib import Path
from validator import load_yaml

SPEC_FILE = Path(__file__).resolve().parent.parent / 'config/video_spec_v1.yaml'


def sound_effects_enabled(job, *, spec=None):
    current = load_yaml(SPEC_FILE) if spec is None else spec
    flags = [current.get('audio', {}).get('sound_effects', {}).get('enabled', True),
             job.get('spec_snapshot', {}).get('audio', {}).get('sound_effects', {}).get('enabled', True),
             job.get('audio', {}).get('sound_effects', {}).get('enabled', True)]
    if any(type(flag) is not bool for flag in flags):
        raise ValueError('audio.sound_effects.enabled must be a boolean (true or false).')
    return all(flags)


def synchronize_sfx_policy(job):
    """Invalidate only audio caches on an effective policy change; retain assets."""
    enabled = sound_effects_enabled(job)
    audio = job.setdefault('audio', {})
    previous = audio.get('sfx_policy_enabled', True)
    audio['sfx_policy_enabled'] = enabled
    if previous == enabled:
        return False
    for key in ('assets', 'mix'):
        audio.pop(key, None)
    job.pop('final_qc', None)
    output = job.get('output', {})
    for key in ('video_file', 'mixed_video_file'):
        output[key] = None
    from pipeline_status import refresh_pipeline_status
    refresh_pipeline_status(job)
    return True
