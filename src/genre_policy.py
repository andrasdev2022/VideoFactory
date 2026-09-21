"""Persisted creative direction shared by all production stages."""
from copy import deepcopy
import json
from pathlib import Path

PROFILES = {
    'tragedy': 'Serious tragic storytelling, irreversible loss and emotional consequences. No comic relief, gags, punchlines or cheerful resolution. Somber restrained narration and mournful dramatic music.',
    'melancholic_drama': 'Reflective, bittersweet drama about loss and memory. Restrained sincere narration and sparse melancholic music. No forced comedy or slapstick.',
    'drama': 'Emotionally grounded serious conflict and consequences. Sincere expressive narration and dramatic music. No forced jokes.',
    'romance': 'Sincere emotional connection and intimacy. Warm restrained narration and tender music. No forced jokes or absurd escalation.',
    'romantic_comedy': 'Romantic connection with light character-driven humor, warm narration and playful romantic music.',
    'absurd_comedy': 'Absurd escalation, clear comic payoff, expressive narration and playful music.',
    'comedy': 'Character-driven humor with a clear comic payoff and playful narration and music.',
    'horror': 'Dread and suspense, unsettling atmosphere and restrained ominous music. No forced comic relief.',
    'thriller': 'Mounting tension and suspense, focused narration and tense music. No forced comic relief.',
    'dark_fantasy': 'Somber fantastical storytelling, ominous atmosphere and dark dramatic music. No forced comic relief.',
}


def genre_name(spec=None, job=None):
    if job is not None:
        return str(job.get('creative_direction', {}).get('genre') or
                   job.get('idea', {}).get('genre') or 'absurd_comedy').strip()
    return str((spec or {}).get('content', {}).get('genre') or 'absurd_comedy').strip()


def genre_instruction(job=None, *, spec=None):
    if job is not None:
        saved = job.get('spec_snapshot', {}).get('content', {}).get('genre_instruction')
        if isinstance(saved, str) and saved.strip():
            return saved
    name = genre_name(spec, job)
    direction = PROFILES.get(name.lower(),
        'Interpret this genre consistently across story, emotional arc, pacing, narration, imagery, music and sound effects. Do not default to comedy unless the genre calls for it.')
    return ('\nCREATIVE DIRECTION: Genre ' + name + '. ' + direction +
            ' This direction takes precedence over conflicting generic mood defaults. '
            'Visual medium (anime, realism, etc.) is independent of genre. '
            'Preserve the genre during timing rewrites; never introduce jokes merely to create a payoff.\n')


def prepare_spec(spec):
    result = deepcopy(spec)
    name = genre_name(result)
    content = result.setdefault('content', {})
    content['genre'] = name
    content['genre_instruction'] = genre_instruction(spec=result)
    if 'comedy' not in name.lower():
        if content.get('style') == 'fast_paced':
            content['style'] = 'pacing appropriate to the genre and emotional arc'
        for beat in content.get('structure', {}).values():
            if isinstance(beat, dict):
                purpose = beat.get('purpose', '')
                if purpose in ('increase absurdity/conflict', 'unexpected ending or punchline'):
                    beat['purpose'] = 'develop and resolve the emotional conflict in the selected genre'
        visual = result.setdefault('visual', {}).setdefault('style', {})
        if 'colorful surreal comedy' in visual.get('style_description', ''):
            visual['style_description'] = 'cinematic lighting, clear subjects, expressions and atmosphere appropriate to ' + name
        voice = result.setdefault('audio', {}).setdefault('voiceover', {})
        if voice.get('style') in (None, 'energetic', 'energetic storyteller'):
            voice['style'] = 'expressive, natural, emotionally appropriate to ' + name
    return result


def runtime_spec(path):
    """New jobs freeze the spec; legacy jobs keep their existing YAML behavior."""
    from validator import load_yaml
    path = Path(path)
    job_path = path.parent.parent / 'jobs' / 'video_job.json'
    if job_path.exists():
        job = json.loads(job_path.read_text(encoding='utf-8-sig'))
        if isinstance(job.get('spec_snapshot'), dict):
            return deepcopy(job['spec_snapshot'])
    return load_yaml(path)
