import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import thumbnail_generator as cover
import final_qc_export as export


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        Image.new('RGB', (720, 1280), 'orange').save(self.root / 'scene.png')
        self.job = {'job_id': 'demo', 'metadata': {'title': 'Spa', 'thumbnail':
                    {'required': True, 'text': 'PAWS & RELAX — ÁLOM SPA'}},
                    'visuals': {'scenes': [{'scene_id': 2, 'image': {'file': 'scene.png',
                    'qc': {'status': 'passed'}, 'semantic_qc': {'status': 'passed'}}}]},
                    'final_qc': {'status': 'passed'}}

    def test_render_resume_change_and_missing_file(self):
        self.assertTrue(cover.generate(self.job, self.root))
        path = self.root / self.job['metadata']['thumbnail']['image_file']
        with Image.open(path) as image:
            self.assertEqual(image.size, (1080, 1920))
            self.assertEqual(image.format, 'JPEG')
        self.assertEqual(self.job['final_qc']['status'], 'pending')
        self.assertTrue(cover.thumbnail_ready(self.job, self.root))
        self.assertFalse(cover.generate(self.job, self.root))
        self.job['metadata']['thumbnail']['text'] = 'NEW HEADLINE'
        self.assertTrue(cover.generate(self.job, self.root))
        path.unlink()
        self.assertFalse(cover.thumbnail_ready(self.job, self.root))
        self.assertTrue(cover.generate(self.job, self.root))

    def test_unapproved_or_unknown_scene_is_rejected(self):
        with self.assertRaises(ValueError):
            cover.generate(self.job, self.root, scene_id=99)
        self.job['visuals']['scenes'][0]['image']['semantic_qc']['status'] = 'failed'
        with self.assertRaises(ValueError):
            cover.generate(self.job, self.root)

    def test_failed_render_preserves_previous_thumbnail_and_job(self):
        cover.generate(self.job, self.root)
        path = self.root / self.job['metadata']['thumbnail']['image_file']
        original = path.read_bytes()
        before = copy.deepcopy(self.job)
        with patch.object(cover.os, 'replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                cover.generate(self.job, self.root, force=True)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.job, before)

    def test_optional_and_custom_thumbnail(self):
        self.job['metadata']['thumbnail'] = {'required': False}
        self.assertFalse(cover.generate(self.job, self.root))
        self.assertTrue(cover.thumbnail_ready(self.job, self.root))
        self.job['metadata']['thumbnail'] = {'required': True, 'image_file': 'scene.png'}
        self.assertFalse(cover.generate(self.job, self.root))
        (self.root / 'scene.png').write_bytes(b'broken')
        self.assertFalse(cover.thumbnail_ready(self.job, self.root))

    def test_headline_fits_and_long_word_rejected(self):
        text, face, box = cover.fit_text('A LITTLE PUPPY RUNS A VERY LUXURIOUS SPA')
        self.assertLessEqual(box[2] - box[0], 924)
        self.assertLessEqual(box[3] - box[1], 410)
        with self.assertRaises(ValueError):
            cover.fit_text('W' * 400)

    def test_export_copies_thumbnail_and_cache_detects_removal(self):
        cover.generate(self.job, self.root)
        source = self.root / 'mix.mp4'
        source.write_bytes(b'test-video')
        paths = {key: self.root / 'final' / name for key, name in
                 [('video', 'video.mp4'), ('metadata', 'metadata.json'),
                  ('script', 'script.json'), ('subtitles', 'subtitles.srt')]}
        with patch.object(export, 'PROJECT_ROOT', self.root):
            result = export.export_final_package(self.job, source, {}, [], paths)
            self.assertTrue(cover.valid_image(self.root / result['thumbnail_file']))
            metadata = json.loads(paths['metadata'].read_text())
            self.assertEqual(metadata['thumbnail_file'], result['thumbnail_file'])
            signature = export.build_source_signature(self.job, source)
            self.job['final_qc'] = {'status': 'passed', 'source_signature': signature, 'export': result}
            self.assertTrue(export.export_matches_current_request(self.job, signature, paths))
            (self.root / result['thumbnail_file']).unlink()
            self.assertFalse(export.export_matches_current_request(self.job, signature, paths))
