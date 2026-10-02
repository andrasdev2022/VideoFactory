"""Resolve and validate narration settings before paid speech requests."""
import math
import os

VOICES = {'alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'nova', 'onyx',
          'sage', 'shimmer', 'verse', 'marin', 'cedar'}
LEGACY_VOICES = VOICES - {'ballad', 'verse', 'marin', 'cedar'}
MODELS = {'gpt-4o-mini-tts', 'gpt-4o-mini-tts-2025-12-15', 'tts-1', 'tts-1-hd'}
FORMATS = {'wav', 'mp3', 'opus', 'aac', 'flac'}

def resolve_tts_settings(spec):
    voice = spec.get('audio', {}).get('voiceover', {})
    def value(key, env, default):
        return os.getenv(env) or voice.get(key, default)
    model = value('model', 'OPENAI_TTS_MODEL', 'gpt-4o-mini-tts')
    name = value('voice', 'OPENAI_TTS_VOICE', 'marin')
    fmt = value('response_format', 'OPENAI_TTS_FORMAT', 'wav')
    speed = voice.get('speed', 1.0)
    if speed == 'natural':
        speed = 1.0
    if isinstance(speed, bool):
        raise ValueError('Narration speed must be a number from 0.25 to 4.0.')
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        raise ValueError('Narration speed must be a number from 0.25 to 4.0, or natural.') from None
    if not math.isfinite(speed) or not 0.25 <= speed <= 4.0:
        raise ValueError('Narration speed must be between 0.25 and 4.0.')
    if model not in MODELS:
        raise ValueError(f'Unsupported TTS model: {model}')
    if name not in (LEGACY_VOICES if model in {'tts-1', 'tts-1-hd'} else VOICES):
        raise ValueError(f'Voice {name} is not supported for {model}.')
    if fmt not in FORMATS:
        raise ValueError(f'Unsupported TTS response_format: {fmt}')
    instructions = voice.get('instructions', '')
    if not isinstance(instructions, str):
        raise ValueError('Narration instructions must be text.')
    if model in {'tts-1', 'tts-1-hd'} and instructions.strip():
        raise ValueError('tts-1 and tts-1-hd do not support instructions; use gpt-4o-mini-tts.')
    return {'model': model, 'voice': name, 'speed': speed, 'response_format': fmt}


def validate_idea_tts_environment(spec: dict) -> None:
    """Reject explicit environment conflicts before a new job can replace the old one."""
    voice = spec.get('audio', {}).get('voiceover', {})
    conflicts = []
    for key, env, default in (
        ('voice', 'OPENAI_TTS_VOICE', 'marin'),
        ('model', 'OPENAI_TTS_MODEL', 'gpt-4o-mini-tts'),
        ('response_format', 'OPENAI_TTS_FORMAT', 'wav'),
    ):
        expected = voice.get(key, default)
        actual = os.getenv(env)
        if actual is not None and actual != expected:
            conflicts.append(f'  audio.voiceover.{key}={expected!r}; {env}={actual!r}')
    if conflicts:
        raise ValueError('TTS YAML/environment mismatch:\n' + '\n'.join(conflicts)
                         + '\nFix config/video_spec_v1.yaml or the environment (including enter-dev.ps1), '
                         'or remove the conflicting environment variable, then rerun with --idea. '
                         'No new job was started.')
    resolve_tts_settings(spec)
