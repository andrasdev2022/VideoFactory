"""Local portrait cover from an approved scene image and the job's headline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOB_FILE = PROJECT_ROOT / 'jobs' / 'video_job.json'
SIZE = (1080, 1920)


def valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def thumbnail_ready(job: dict, root: Path) -> bool:
    thumbnail = job.get('metadata', {}).get('thumbnail', {})
    filename = thumbnail.get('image_file')
    return bool(filename and valid_image(root / filename)) or not thumbnail.get('required', False)


def thumbnail_signature(job: dict, root: Path) -> dict:
    metadata = dict(job.get('metadata', {}).get('thumbnail', {}))
    filename = metadata.get('image_file')
    path = root / filename if filename else None
    metadata['file_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None
    return metadata


def font(size: int):
    configured = os.getenv('THUMBNAIL_FONT')
    candidates = [configured] if configured else [
        str(Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts' / 'arialbd.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        'DejaVuSans-Bold.ttf',
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    raise ValueError('No usable font found. Set THUMBNAIL_FONT to a bold TrueType font file.')


def fit_text(text: str):
    text = ' '.join(text.split())
    if not text:
        raise ValueError('Thumbnail text is empty.')
    draw = ImageDraw.Draw(Image.new('RGB', SIZE))
    for size in range(100, 27, -2):
        face = font(size)
        lines = []
        for word in text.split():
            if draw.textlength(word, font=face) > 920:
                break
            if lines and draw.textlength(lines[-1] + ' ' + word, font=face) <= 920:
                lines[-1] += ' ' + word
            else:
                lines.append(word)
        else:
            joined = '\n'.join(lines)
            box = draw.multiline_textbbox((0, 0), joined, font=face, spacing=14, stroke_width=2)
            if len(lines) <= 4 and box[3] - box[1] <= 410:
                return joined, face, box
    raise ValueError('Thumbnail text is too long; use a short headline.')


def generate(job: dict, root: Path, scene_id: int | None = None, force: bool = False) -> bool:
    thumbnail = job.setdefault('metadata', {}).setdefault('thumbnail', {})
    if not thumbnail.get('required', False) and scene_id is None and not force:
        print('Thumbnail is optional; skipping.')
        return False
    previous = thumbnail.get('image_file')
    if previous and not thumbnail.get('generator') and not force and scene_id is None:
        if valid_image(root / previous):
            print('Existing custom thumbnail preserved.')
            return False
    selected_id = scene_id if scene_id is not None else thumbnail.get('scene_id')
    scenes = job.get('visuals', {}).get('scenes', [])
    approved = [s for s in scenes if s.get('image', {}).get('qc', {}).get('status') == 'passed'
                and s.get('image', {}).get('semantic_qc', {}).get('status') == 'passed'
                and s.get('image', {}).get('file')]
    selected = next((s for s in approved if selected_id is None or s.get('scene_id') == selected_id), None)
    if selected is None:
        raise ValueError('No approved source image available for the requested thumbnail scene.')
    source = root / selected['image']['file']
    text = thumbnail.get('text') or job.get('metadata', {}).get('title', '')
    lines, face, box = fit_text(text)
    signature = hashlib.sha256(source.read_bytes() + json.dumps(
        {'text': text, 'size': SIZE, 'version': 1, 'font': hashlib.sha256(Path(face.path).read_bytes()).hexdigest()},
        sort_keys=True).encode()).hexdigest()
    destination = root / 'output' / str(job['job_id']) / 'thumbnails' / 'thumbnail.jpg'
    if (not force and thumbnail.get('source_signature') == signature
            and previous == destination.relative_to(root).as_posix() and valid_image(destination)):
        print('Thumbnail already current.')
        return False
    # Fit, never crop: preserve faces and props; use a separate headline panel.
    canvas = Image.new('RGB', SIZE, '#101927')
    with Image.open(source) as original:
        picture = ImageOps.contain(ImageOps.exif_transpose(original).convert('RGB'), (1080, 1380), Image.Resampling.LANCZOS)
        canvas.paste(picture, ((1080 - picture.width) // 2, (1380 - picture.height) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((80, 1410, 1000, 1417), fill='#ffd65a')
    draw.multiline_text((540, 1470 - box[1]), lines, font=face, fill='#ffffff',
                        anchor='ma', align='center', spacing=14, stroke_width=2, stroke_fill='#101927')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp.jpg')
    try:
        canvas.save(temporary, 'JPEG', quality=94, optimize=True)
        if not valid_image(temporary):
            raise ValueError('Generated thumbnail failed image validation.')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    thumbnail.update(image_file=destination.relative_to(root).as_posix(), scene_id=selected['scene_id'],
                     generator='local_scene_cover_v1', source_signature=signature, width=1080, height=1920)
    job['final_qc'] = {'status': 'pending', 'publish_ready': False}
    print(f"Thumbnail generated: {thumbnail['image_file']} (scene {selected['scene_id']})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=int, help='Use this approved scene; default: first approved scene.')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        job = json.loads(JOB_FILE.read_text(encoding='utf-8'))
        if generate(job, PROJECT_ROOT, args.scene, args.force):
            from pipeline_status import refresh_pipeline_status
            refresh_pipeline_status(job)
            temporary = JOB_FILE.with_suffix('.tmp.json')
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            os.replace(temporary, JOB_FILE)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'THUMBNAIL FAILED: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
