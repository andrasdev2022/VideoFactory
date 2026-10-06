import copy
import io
import json
import shutil
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack, redirect_stdout

from PIL import Image
import character_library as lib
import new_job
import image_generator as images
import character_reference_generator as references
import pipeline_orchestrator as pipeline
import visual_supervisor as vs
import test_new_job as new_tests
from test_visual_supervisor import fixture, plan, review


class CharacterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        for source in Path(vs.__file__).parent.glob("*.py"):
            shutil.copy2(source, self.root / "src" / source.name)
        self.old = fixture()
        c = self.old['characters'][0]
        c.update(personality='Kind', role='hero')
        path = self.root / 'output/old/characters/c1/reference.png'
        path.parent.mkdir(parents=True)
        Image.new('RGB', (20, 30), 'blue').save(path)
        c['reference'].update(image_file=path.relative_to(self.root).as_posix(), status='generated')
        lib.write(self.root / 'jobs/video_job.json', self.old)

    def selected(self):
        lib.import_jobs(self.root)
        item = lib.entries(self.root)[0]
        return lib.select(item['asset_id'], self.root)

    def test_import_repeat_archive_dedup_and_independent_snapshot(self):
        before = (self.root / 'jobs/video_job.json').read_bytes()
        lib.write(self.root / 'jobs/history/old.json', self.old)
        self.assertEqual(lib.import_jobs(self.root)[:2], (1, 1))
        self.assertEqual(lib.import_jobs(self.root)[:2], (0, 2))
        selected = self.selected()
        job = copy.deepcopy(self.old); job['job_id'] = 'new'
        job['characters'][0]['role'] = 'new story role'
        lib.attach(job, selected, self.root)
        self.assertEqual(job['characters'][0]['role'], 'new story role')
        original_image = lib.local_path(self.root, self.old['characters'][0]['reference']['image_file'])
        original_image.unlink()
        self.assertTrue(lib.verify_locked(job['characters'][0], self.root))
        self.assertEqual(before, (self.root / 'jobs/video_job.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            lib.attach(job, selected, self.root)

    def test_bad_selection_missing_corrupt_and_escaping_assets(self):
        selected = self.selected(); asset_id = selected[0]['asset_id']
        for value in ('', 'unknown', f'{asset_id},{asset_id}', ','.join(['a','b','c','d'])):
            with self.assertRaises(ValueError):
                lib.select(value, self.root)
        with self.assertRaises(ValueError):
            lib.local_path(self.root, '../outside.png')
        (self.root / f'character_library/{asset_id}/reference.png').write_bytes(b'broken')
        with self.assertRaises(Exception):
            lib.select(asset_id, self.root)

    def test_catalog_escapes_content_and_contains_preview_and_selector(self):
        self.old['characters'][0]['name'] = '<script>bad()</script>'
        lib.write(self.root / 'jobs/video_job.json', self.old)
        self.selected()
        with redirect_stdout(io.StringIO()):
            path = lib.catalog(self.root)
        page = path.read_text()
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>bad()', page)
        self.assertIn('data:image/png;base64,', page)
        self.assertIn('--characters', page)

    def test_actual_bootstrap_request_includes_selected_identity(self):
        client = Mock(); client.responses.parse.return_value.output_parsed = Mock()
        selected = self.selected()
        spec = new_tests.NewJobTests().make_spec(); spec['video'].update(target_duration_sec=30, aspect_ratio='9:16')
        new_job.generate_bootstrap(client, 'new adventure', spec, selected)
        payload = client.responses.parse.call_args.kwargs['input']
        self.assertIn('SELECTED CAST', payload[0]['content'])
        self.assertEqual(json.loads(payload[1]['content'].split('\n\n', 1)[1])['selected_characters'],
                         [lib.selected_identity(s) for s in selected])

    def test_historical_style_and_cast_do_not_enter_review_or_new_character(self):
        selected = self.selected()
        selected[0]['source_style'] = {'visual': 'No photorealism. Pip and Grandpa Gus appear.'}
        selected[0]['sources'] = [{'title': 'Miso and Grandma'}]
        client = Mock()
        client.responses.parse.side_effect = lambda **kw: SimpleNamespace(
            output_parsed=kw['text_format'](errors=[]))
        lib.review_selection(client, 'mock', 'Kael in a garden', {'visual': {'realistic': True}}, selected)
        payload = client.responses.parse.call_args.kwargs['input']
        self.assertNotIn('Grandpa Gus', payload[1]['content'])
        self.assertNotIn('No photorealism', payload[1]['content'])
        self.assertIn('may coexist with stylized characters', payload[0]['content'])
        job = copy.deepcopy(self.old); job['job_id'] = 'new'
        lib.attach(job, selected, self.root)
        self.assertNotIn('source_style', job['characters'][0]['library_asset'])
        self.assertEqual(job['character_library_provenance']['c1']['sources'], selected[0]['sources'])
        # Older imported jobs also cannot expose historical style/cast to supervisor.
        job['characters'][0]['library_asset'].update(source_style=selected[0]['source_style'],
                                                    sources=selected[0]['sources'])
        self.assertNotIn('Grandpa Gus', json.dumps(vs.source(job)))
        self.assertNotIn('Miso and Grandma', json.dumps(vs.source(job)))

    def test_compatibility_review_fails_closed(self):
        client = Mock()
        def answer(**kwargs):
            return SimpleNamespace(output_parsed=kwargs['text_format'](errors=['rabbit requested; wolf selected']))
        client.responses.parse.side_effect = answer
        with self.assertRaisesRegex(ValueError, 'wolf selected'):
            lib.review_selection(client, 'mock', 'rabbit', {}, self.selected())
        client.responses.parse.side_effect = None
        client.responses.parse.return_value.output_parsed = None
        with self.assertRaises(RuntimeError):
            lib.review_selection(client, 'mock', '', {}, [])

    def test_new_job_conflict_preserves_active_job_and_skips_bootstrap(self):
        selected = self.selected()
        before = (self.root / 'jobs/video_job.json').read_bytes()
        args = SimpleNamespace(idea='an elephant', visual_style=None, job_id=None,
                               characters=selected[0]['asset_id'])
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(patch.dict('os.environ', {'OPENAI_API_KEY': 'mock'}))
            stack.enter_context(patch.object(new_job, 'parse_args', return_value=args))
            stack.enter_context(patch.object(new_job, 'PROJECT_ROOT', self.root))
            stack.enter_context(patch.object(new_job, 'load_yaml', return_value=new_tests.NewJobTests().make_spec()))
            stack.enter_context(patch.object(new_job, 'OpenAI'))
            check = stack.enter_context(patch.object(lib, 'review_selection', side_effect=ValueError('cast conflict')))
            archive = stack.enter_context(patch.object(new_job, 'archive_current_job'))
            bootstrap = stack.enter_context(patch.object(new_job, 'generate_bootstrap'))
            self.assertEqual(new_job.main(), 1)
            check.assert_called_once()
            archive.assert_not_called(); bootstrap.assert_not_called()
        self.assertEqual(before, (self.root / 'jobs/video_job.json').read_bytes())

    def test_new_job_success_snapshots_cast_and_archives_old_job(self):
        selected = self.selected()
        before = (self.root / 'jobs/video_job.json').read_bytes()
        output = new_tests.NewJobTests().make_output()
        source_character = selected[0]['character']
        output.characters = [new_job.CharacterBlueprint(**{k: source_character[k] for k in
                             (*lib.IDENTITY_KEYS, 'role')})]
        output.characters[0].role = 'explorer'
        args = SimpleNamespace(idea='new adventure', visual_style=None, job_id='new',
                               characters=selected[0]['asset_id'])
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(patch.dict('os.environ', {'OPENAI_API_KEY': 'mock'}))
            for key, value in [('PROJECT_ROOT', self.root), ('JOB_FILE', self.root / 'jobs/video_job.json'),
                               ('HISTORY_DIR', self.root / 'jobs/history')]:
                stack.enter_context(patch.object(new_job, key, value))
            stack.enter_context(patch.object(new_job, 'parse_args', return_value=args))
            stack.enter_context(patch.object(new_job, 'load_yaml', return_value=new_tests.NewJobTests().make_spec()))
            stack.enter_context(patch.object(new_job, 'OpenAI'))
            check = stack.enter_context(patch.object(lib, 'review_selection'))
            stack.enter_context(patch.object(new_job, 'generate_bootstrap', return_value=output))
            self.assertEqual(new_job.main(), 0)
            self.assertEqual(check.call_count, 2)
        saved = lib.read(self.root / 'jobs/video_job.json')
        self.assertEqual(saved['seed']['text'], args.idea)
        c = saved['characters'][0]
        self.assertEqual(c['character_id'], 'char-001')
        self.assertEqual(c['description'], source_character['description'])
        self.assertEqual(c['role'], 'explorer')
        self.assertTrue(lib.verify_locked(c, self.root))
        self.assertEqual((self.root / 'jobs/history/test.json').read_bytes(), before)
        # A later catalog import recognizes the reused identity/image as the same asset.
        self.assertEqual(lib.import_jobs(self.root)[:2], (0, 2))
        self.assertEqual(len(lib.entries(self.root)), 1)

    def test_supervisor_and_generator_preserve_reference_and_enforce_integrity(self):
        job = copy.deepcopy(self.old); job['job_id'] = 'new'
        lib.attach(job, self.selected(), self.root)
        c = job['characters'][0]; original = copy.deepcopy(c['reference'])
        with patch.object(vs, 'ROOT', self.root), patch.object(images, 'PROJECT_ROOT', self.root), \
             patch.dict('os.environ', {'VIDEO_PROVIDER': 'still_motion'}), \
             patch.object(vs, 'ask', side_effect=[plan(), review()]):
            self.assertTrue(vs.supervise(job, Mock(), lambda j: None))
            self.assertEqual(c['reference']['image_file'], original['image_file'])
            client = Mock()
            self.assertFalse(images.generate_character_reference(client, job, c, False))
            client.images.generate.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'force-regenerate'):
                images.generate_character_reference(client, job, c, True)
            self.assertEqual(images.get_scene_character_references(job, job['visuals']['scenes'][0])[0][0], c)
            lib.local_path(self.root, c['reference']['image_file']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'missing or changed'):
                images.get_scene_character_references(job, job['visuals']['scenes'][0])

    def test_master_new_job_failure_does_not_mark_previous_job_failed(self):
        path = self.root / 'jobs/video_job.json'
        before = path.read_bytes()
        args = SimpleNamespace(idea='new story', characters=None, OverruleQC=False, RetryQC=False)
        captured = io.StringIO()
        with patch.object(pipeline, 'JOB_FILE', path), \
             patch.object(pipeline, 'parse_args', return_value=args), \
             patch('tts_settings.validate_idea_tts_environment'), \
             patch('duration_policy.scene_duration_range'), \
             patch.object(pipeline, 'preflight'), \
             patch.object(pipeline, 'run_pipeline', side_effect=RuntimeError('cast conflict')), \
             redirect_stdout(captured):
            self.assertEqual(pipeline.main(), 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn('repeat the original --idea command', captured.getvalue())

    def test_resume_rejects_selection_argument(self):
        with patch('sys.argv', ['pipeline_orchestrator.py', '--characters', 'pip']), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                pipeline.parse_args()

    def test_reference_prompt_worker_preserves_locked_cast(self):
        job = copy.deepcopy(self.old); job['job_id'] = 'new'
        lib.attach(job, self.selected(), self.root)
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'mock'}), \
             patch.object(references, 'MODEL', 'mock'), patch.object(references, 'PROJECT_ROOT', self.root), \
             patch.object(references, 'load_yaml', return_value={}), \
             patch.object(references, 'load_json', return_value=job), \
             patch.object(references, 'OpenAI') as client, redirect_stdout(io.StringIO()):
            self.assertEqual(references.main(), 0)
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
