"""Durable, single-result QC decisions. No provider calls or global QC bypass."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

PHASES = {
    'image_qc': ('image', 'qc'),
    'image_semantic_qc': ('image', 'semantic_qc'),
    'video_qc': ('video', 'qc'),
    'video_semantic_qc': ('video', 'semantic_qc'),
}
MAX_REPAIRS = 3


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scene_for(job, sid):
    return next(s for s in job['visuals']['scenes'] if s['scene_id'] == sid)


def state_for(job, sid):
    return job.setdefault('orchestration', {}).setdefault('scenes', {}).setdefault(str(sid), {})


def failed_phase(scene):
    for phase, (media, key) in PHASES.items():
        if scene.get(media, {}).get(key, {}).get('status') == 'failed':
            return phase
    return None


def fingerprint(root, name):
    if not name:
        raise ValueError('QC artifact filename is missing.')
    path = root / name
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    if path.stat().st_size == 0:
        raise ValueError(f'QC artifact is empty: {name}')
    return {'file': name, 'sha256': h.hexdigest(), 'size': path.stat().st_size}


def inputs_signature(job, sid, root):
    # Authored requirements, effective config, supervisor contract and QC code.
    from visual_supervisor import source
    authored = source(job)
    scene = scene_for(job, sid)
    files = {}
    for name in ('image_qc.py', 'video_qc.py', 'qc_continuation.py'):
        path = root / 'src' / name
        if path.exists():
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    refs = [c.get('reference', {}) for c in job.get('characters', [])
            if c.get('character_id') in scene.get('characters', [])]
    return digest({'inputs': authored, 'supervisor': job.get('visual_supervisor'),
                   'policies': files, 'references': refs,
                   'semantic_policy': scene.get('semantic_qc_policy'),
                   'runtime': {k: v for k, v in os.environ.items()
                               if k.startswith(('VIDEO_QC_', 'IMAGE_QC_', 'STILL_MOTION_', 'LOCAL_LTX_'))
                               and not k.startswith('LOCAL_LTX_SERVER_')
                               and not any(secret in k for secret in ('KEY', 'TOKEN', 'SECRET'))}})


def checkpoint(job, sid, phase, root, reason):
    if job.get('qc_continuation'):
        raise ValueError('An unresolved QC continuation already exists.')
    media, key = PHASES[phase]
    scene = scene_for(job, sid)
    artifact = scene[media]
    attempts = state_for(job, sid).get(f'{media}_attempts', 0)
    point = {
        'version': 1, 'id': uuid.uuid4().hex, 'created_at': now(),
        'job_id': job['job_id'], 'scene_id': sid, 'phase': phase,
        'artifact': deepcopy(artifact), 'qc_result': deepcopy(artifact[key]),
        'requirements_sha256': inputs_signature(job, sid, root),
        'attempts': attempts, 'repairs': max(0, attempts - 1), 'reason': reason,
    }
    try:
        point['fingerprint'] = fingerprint(root, artifact.get('file'))
    except (OSError, ValueError) as exc:
        point['technical_error'] = str(exc)
    if media == 'video' and scene.get('image', {}).get('file'):
        try:
            point['source_fingerprint'] = fingerprint(root, scene['image']['file'])
        except (OSError, ValueError) as exc:
            point['technical_error'] = str(exc)
    job['qc_continuation'] = point
    return point


def describe(point):
    return (f"QC megállás: job={point['job_id']}, scene={point['scene_id']}, "
            f"fázis={point['phase']}; {point['attempts']} generálás, "
            f"{point['repairs']} javítás. Ok: {point['reason']}\n"
            f"QC: {json.dumps(point['qc_result'], ensure_ascii=False)}\n"
            'Folytatás kézi elfogadással: python src/pipeline_orchestrator.py -OverruleQC\n'
            'Új javítási ciklus: python src/pipeline_orchestrator.py -RetryQC')


def validate_point(job, root):
    p = job.get('qc_continuation')
    if not p:
        raise ValueError('Nincs mentett QC-folytatási pont.')
    if p.get('version') != 1 or p.get('job_id') != job.get('job_id') or p.get('phase') not in PHASES:
        raise ValueError('Elavult vagy másik jobhoz tartozó QC-pont.')
    scene = scene_for(job, p['scene_id'])
    media, _ = PHASES[p['phase']]
    if scene.get(media) != p['artifact'] or inputs_signature(job, p['scene_id'], root) != p['requirements_sha256']:
        raise ValueError('Elavult QC-pont: a média metaadata vagy követelménye megváltozott.')
    return p, scene


def assert_readable(root, artifact, media):
    path = root / artifact['file']
    if media == 'image':
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
    else:
        # Decode the complete stream: an old technical PASS cannot bless corrupt bytes.
        result = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path),
                                 '-map', '0:v:0', '-f', 'null', '-'],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise ValueError('Videó nem dekódolható: ' + result.stderr[-1000:])


def archive(job, sid, root):
    """Preserve current media before any targeted regeneration can overwrite it."""
    scene = scene_for(job, sid)
    folder = root / 'output' / str(job['job_id']) / 'history' / ('qc-' + uuid.uuid4().hex)
    saved = []
    for media in ('image', 'video'):
        artifact = scene.get(media, {})
        for record in (artifact, artifact.get('trimmed', {})):
            name = record.get('file')
            if name and (root / name).is_file():
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f'{media}-{len(saved)}-{Path(name).name}'
                shutil.copy2(root / name, target)
                saved.append(str(target.relative_to(root)))
    return saved


def invalidate_dependents(job, sid, media):
    scene = scene_for(job, sid)
    if media == 'image':
        scene.pop('video', None)
    else:
        scene.get('video', {}).pop('trimmed', None)
    job.pop('assembly', None)
    job.pop('final_qc', None)
    job.setdefault('subtitles', {}).pop('render', None)
    job.setdefault('audio', {}).pop('mix', None)
    for key in ('video_file', 'base_video_file', 'subtitled_video_file', 'mixed_video_file'):
        job.setdefault('output', {})[key] = None
    thumbnail = job.get('metadata', {}).get('thumbnail', {})
    thumbnail.pop('source_signature', None)


def prepare_still_repair(job, sid, root):
    scene = scene_for(job, sid)
    feedback = deepcopy(scene['video']['semantic_qc'])
    source = deepcopy(scene['image'])
    try:
        assert_readable(root, source, 'image')
    except (OSError, ValueError, KeyError):
        # An unavailable source can be regenerated, never used as an edit target.
        source['qc'] = {'status': 'failed'}
    source['semantic_qc'] = feedback
    source['semantic_qc']['overall_notes'] = (
        'Video QC feedback: repair the source image composition to keep required subjects '
        'and props visible throughout the configured camera crop. Preserve the approved '
        'supervisor contract. ' + str(feedback.get('overall_notes', '')) + ' Errors: ' +
        json.dumps(feedback.get('errors', []), ensure_ascii=False))
    scene['image_repair_source'] = source
    scene.pop('image', None)
    invalidate_dependents(job, sid, 'image')
    # Image corrections within this video repair cycle have their own bounded budget.
    state_for(job, sid)['image_attempts'] = 0


def resolve(job_path, root, decision=None):
    job = json.loads(job_path.read_text(encoding='utf-8-sig'))
    if not job.get('qc_continuation'):
        if decision:
            raise ValueError('Nincs mentett QC-folytatási pont.')
        return
    if decision is None:
        raise ValueError(describe(job['qc_continuation']))
    p, scene = validate_point(job, root)
    media, key = PHASES[p['phase']]
    artifact = scene[media]
    if p.get('fingerprint') and (root / p['fingerprint']['file']).exists():
        if fingerprint(root, p['fingerprint']['file']) != p['fingerprint']:
            raise ValueError('A média megváltozott; a QC-pont elavult.')
    if p.get('source_fingerprint') and (root / p['source_fingerprint']['file']).exists():
        if fingerprint(root, p['source_fingerprint']['file']) != p['source_fingerprint']:
            raise ValueError('A forráskép megváltozott; a QC-pont elavult.')
    if decision == 'overrule':
        if key != 'semantic_qc' or p.get('technical_error') or artifact.get('qc', {}).get('status') != 'passed':
            raise ValueError('Technikai QC-hiba nem bírálható felül.')
        if fingerprint(root, artifact.get('file')) != p.get('fingerprint'):
            raise ValueError('A média megváltozott; a QC-pont elavult.')
        if p.get('source_fingerprint') and fingerprint(root, p['source_fingerprint']['file']) != p['source_fingerprint']:
            raise ValueError('A forráskép megváltozott; a QC-pont elavult.')
        assert_readable(root, artifact, media)
    elif decision != 'retry':
        raise ValueError('Unknown QC decision.')
    # A retry may repair missing/corrupt media; it never accepts those bytes.
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = job_path.parent / 'history' / f'before-qc-{stamp}.json'
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(job_path, backup)
    event = {'point': deepcopy(p), 'decision': decision, 'at': now(), 'backup': str(backup)}
    if decision == 'overrule':
        artifact[key]['status'] = 'passed'
        artifact[key]['manual_override'] = {'at': event['at'], 'point_id': p['id']}
    else:
        event['media_backups'] = archive(job, p['scene_id'], root)
        state = state_for(job, p['scene_id'])
        state[f'{media}_attempts'] = 0
        state['state'] = 'in_progress'
        # Keep failed QC as repair feedback. A new cycle starts with a fresh generation.
        invalidate_dependents(job, p['scene_id'], media)
    job.setdefault('qc_continuation_history', []).append(event)
    job.pop('qc_continuation')
    temporary = job_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(job_path)


def route_failure(job, sid, root, max_image, max_video):
    """Return a scoped action before legacy fallback routing, or None."""
    scene = scene_for(job, sid)
    phase = failed_phase(scene)
    state = state_for(job, sid)
    if not phase:
        return None
    media, key = PHASES[phase]
    attempts = state.get(f'{media}_attempts', 0)
    limit = min(1 + MAX_REPAIRS, max_image if media == 'image' else max_video)
    if attempts >= limit:
        checkpoint(job, sid, phase, root, 'Javítási keret kimerült; a QC továbbra is hibát jelez.')
        return 'qc_blocked'
    backups = archive(job, sid, root)
    job.setdefault('qc_repair_history', []).append({
        'scene_id': sid, 'phase': phase, 'at': now(), 'attempts_before': attempts,
        'artifact': deepcopy(scene[media]), 'media_backups': backups})
    if media == 'image':
        invalidate_dependents(job, sid, 'image')
        return 'generate_image'
    if key == 'semantic_qc' and scene['video'].get('provider') in ('still_motion', 'local_ffmpeg'):
        prepare_still_repair(job, sid, root)
        return 'generate_image'
    invalidate_dependents(job, sid, 'video')
    return 'retry_video_from_qc' if key == 'semantic_qc' else 'generate_video'
