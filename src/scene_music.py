"""Optional scene-local music replacements on the assembled timeline."""
from copy import deepcopy


def generate_scene_music(job, timeline, *, force, api_key):
    from audio_asset_generator import generate_music
    by_id = {int(item['scene_id']): item for item in timeline}
    changed = False
    for scene in job.get('visuals', {}).get('scenes', []):
        override = scene.get('music_override')
        if not override:
            continue
        item = by_id[int(scene['scene_id'])]
        duration = float(item['end_sec']) - float(item['start_sec'])
        isolated = deepcopy(job)
        isolated['audio']['background_music'] = override
        isolated['_scene_music_request'] = True
        script_scene = next((s for s in job.get('script', {}).get('scenes', []) if s.get('scene_id') == scene['scene_id']), {})
        isolated.setdefault('idea', {})['concept'] = script_scene.get('voiceover') or isolated.get('idea', {}).get('concept', '')
        override['required'] = True
        changed = generate_music(job=isolated, duration_ms=round(duration * 1000),
            force=force, api_key=api_key, output_name=f"scene_{int(scene['scene_id']):03d}.mp3") or changed
    return changed


def mix_scene_music(job, timeline, resolve):
    by_id = {int(item['scene_id']): item for item in timeline}
    tracks = []
    for scene in job.get('visuals', {}).get('scenes', []):
        override = scene.get('music_override')
        if not override:
            continue
        scene_id = int(scene['scene_id'])
        item = by_id[scene_id]
        if override.get('generation', {}).get('status') != 'passed':
            raise RuntimeError(f'Scene {scene_id} music has not been generated successfully.')
        relative, path = resolve(override.get('audio_file'))
        start, end = float(item['start_sec']), float(item['end_sec'])
        tracks.append(dict(index=10000 + scene_id, scene_id=scene_id,
            effect='scene_music', kind='scene_music', file=relative, path=path,
            start_sec=start, duration_sec=end-start, volume=float(override.get('volume', 0.2)),
            timing_source='scene_relative'))
    return tracks
