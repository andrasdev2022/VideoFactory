"""Apply an explicit scene patch and invalidate only its dependent artifacts."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

from local_ltx_motion_policy import preserve_seed
from pipeline_status import refresh_pipeline_status

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {'voiceover', 'image_prompt', 'motion_prompt', 'music_prompt', 'still_motion'}


def apply_patch(job: dict, scene_id: int, patch: dict) -> tuple[dict, list[str]]:
    if not isinstance(patch, dict) or not patch or set(patch) - FIELDS:
        raise ValueError('Patch must contain only: ' + ', '.join(sorted(FIELDS)))
    for key, value in patch.items():
        if key == 'still_motion':
            from still_motion_provider import load_config
            if not isinstance(value, dict) or not value or set(value) - {'mode', 'max_zoom'}:
                raise ValueError('still_motion accepts mode and max_zoom only.')
            load_config(value)
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{key} must be a non-empty string.')
    result = deepcopy(job)
    script = result.get('script', {})
    scene = next((s for s in script.get('scenes', []) if s.get('scene_id') == scene_id), None)
    visual = next((s for s in result.get('visuals', {}).get('scenes', []) if s.get('scene_id') == scene_id), None)
    if scene is None or visual is None:
        raise ValueError(f'Scene {scene_id} needs an existing script and visual prompts.')
    changed = []
    for key, value in patch.items():
        value = value.strip() if isinstance(value, str) else value
        target = scene if key == 'voiceover' else visual
        if key == 'music_prompt':
            previous = visual.get('music_override', {}).get('style')
            if previous != value:
                visual['music_override'] = {'style': value, 'required': True, 'volume': 0.2}
                changed.append(key)
        elif target.get(key) != value:
            target[key] = value
            changed.append(key)
    if not changed:
        return result, []

    audio = result.setdefault('audio', {})
    video_changed = any(key in changed for key in ('voiceover', 'image_prompt', 'motion_prompt', 'still_motion'))
    assembly_changed = video_changed
    if video_changed:
        preserve_seed(visual)
        for key in ('video', 'motion_strategy', 'semantic_qc_policy'):
            visual.pop(key, None)
        state = result.setdefault('orchestration', {}).setdefault('scenes', {}).setdefault(str(scene_id), {})
        state.update(video_attempts=0, state='in_progress')
    if 'image_prompt' in changed:
        visual.pop('image', None)
        state['image_attempts'] = 0
    if 'voiceover' in changed:
        for key in ('voice', 'timing', 'subtitles', 'timing_revisions'):
            scene.pop(key, None)
        result.setdefault('orchestration', {}).setdefault('voice_scenes', {}).pop(str(scene_id), None)
        script.pop('duration_normalization', None)
        result.pop('timing_summary', None)
        script['voiceover'] = ' '.join(s.get('voiceover', '') for s in script['scenes'])
        # Timeline durations may change: recheck signatures for music and SFX.
        audio.pop('assets', None)
    if assembly_changed:
        result.pop('assembly', None)
        for key in ('generation', 'render'):
            result.setdefault('subtitles', {}).pop(key, None)
        output = result.setdefault('output', {})
        for key in ('base_video_file', 'subtitled_video_file', 'subtitle_file'):
            output[key] = None
    if 'music_prompt' in changed:
        audio.pop('assets', None)
    # Image or motion edits can make old planned effects inappropriate.
    if any(key in changed for key in ('image_prompt', 'motion_prompt')):
        audio.pop('plan', None)
        audio.pop('assets', None)
    audio.pop('mix', None)
    result.pop('final_qc', None)
    for key in ('video_file', 'mixed_video_file'):
        result.setdefault('output', {})[key] = None
    result['scene_edit_scope'] = {'scene_id': scene_id, 'fields': changed}
    result['status'] = 'scene_edit_pending'
    result.setdefault('scene_edits', []).append({
        'scene_id': scene_id, 'fields': changed,
        'at': datetime.now(timezone.utc).isoformat(), 'patch': patch})
    refresh_pipeline_status(result)
    return result, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=int, required=True)
    parser.add_argument('--patch', type=Path, required=True, help='UTF-8 JSON with explicit replacement text.')
    parser.add_argument('--dry-run', action='store_true', help='Validate and report without changing the job.')
    parser.add_argument('--regenerate', action='store_true', help='Resume the pipeline after saving; may call paid APIs.')
    args = parser.parse_args()
    path = ROOT / 'jobs' / 'video_job.json'
    try:
        job = json.loads(path.read_text(encoding='utf-8-sig'))
        patch = json.loads(args.patch.read_text(encoding='utf-8-sig'))
        result, changed = apply_patch(job, args.scene, patch)
        print(f"Scene {args.scene}: changed fields: {', '.join(changed) or 'none'}")
        if args.dry_run:
            return 0
        if not changed:
            if args.regenerate:
                return subprocess.call([sys.executable, str(ROOT / 'src' / 'pipeline_orchestrator.py')], cwd=ROOT)
            return 0
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        backup = path.parent / 'history' / f"{job['job_id']}-before-scene-{args.scene}-{stamp}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
        print(f'Job backup: {backup}')
        if args.regenerate:
            return subprocess.call([sys.executable, str(ROOT / 'src' / 'pipeline_orchestrator.py')], cwd=ROOT)
        print('Saved. Resume with: python src/pipeline_orchestrator.py')
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
