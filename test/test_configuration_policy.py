"""Configuration conflicts must fail before work or runtime-state changes."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from duration_policy import scene_duration_range, scene_planning_spec, approved_scene_duration_range
import scene_timing
import pipeline_orchestrator as master
from tts_settings import validate_idea_tts_environment


class ConfigurationPolicyTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.spec = {'visual': {'scene': {'min_duration_sec': 1, 'max_duration_sec': 24}},
                     'audio': {'voiceover': {'voice': 'nova', 'model': 'gpt-4o-mini-tts',
                                            'response_format': 'wav'}}}

    def test_scene_intersection_and_planning_do_not_mutate_snapshot(self):
        original = copy.deepcopy(self.spec)
        self.assertEqual(scene_duration_range(self.spec, 'still_motion'), (1, 24))
        for provider in ('runway', 'local_ltx'):
            self.assertEqual(scene_duration_range(self.spec, provider), (2, 10))
        with patch.dict(os.environ, {'VIDEO_PROVIDER': 'runway'}):
            self.assertEqual(scene_planning_spec(self.spec)['visual']['scene'],
                             {'min_duration_sec': 2, 'max_duration_sec': 10})
        self.assertEqual(original, self.spec)

    def test_invalid_or_disjoint_ranges_fail(self):
        for lower, upper in [(11, 24), (0, 10), (8, 3), (float('nan'), 10), (2, float('inf'))]:
            self.spec['visual']['scene'].update(min_duration_sec=lower, max_duration_sec=upper)
            with self.assertRaises(ValueError):
                scene_duration_range(self.spec, 'runway')

    def test_timing_ignores_removed_env_and_uses_yaml_minimum_and_maximum(self):
        self.spec['visual']['scene']['min_duration_sec'] = 3
        with patch.dict(os.environ, {'VIDEO_PROVIDER': 'still_motion',
                                    'SCENE_TIMING_MIN_VIDEO_SEC': 'bad',
                                    'SCENE_TIMING_MAX_VIDEO_SEC': '10'}):
            short = scene_timing.calculate_scene_timing(1, 4, self.spec)
            long = scene_timing.calculate_scene_timing(12, 12, self.spec)
            excessive = scene_timing.calculate_scene_timing(25, 24, self.spec)
        self.assertEqual(short['render_duration_sec'], 3)
        self.assertEqual(long['status'], 'passed')
        self.assertEqual(long['max_video_duration_sec'], 24)
        self.assertTrue(excessive['script_revision_required'])
        self.assertIsNone(excessive['render_duration_sec'])

    def test_saved_snapshot_and_legacy_approved_bounds(self):
        timing = {'min_video_duration_sec': 2, 'max_video_duration_sec': 20}
        self.assertEqual(approved_scene_duration_range({'spec_snapshot': self.spec}, timing, 'still_motion'), (1, 24))
        self.assertEqual(approved_scene_duration_range({}, timing, 'still_motion'), (2, 20))
        self.assertEqual(approved_scene_duration_range({}, timing, 'runway'), (2, 10))

    def test_missing_or_matching_tts_environment_passes(self):
        validate_idea_tts_environment(self.spec)
        with patch.dict(os.environ, {'OPENAI_TTS_VOICE': 'nova', 'OPENAI_TTS_MODEL': 'gpt-4o-mini-tts',
                                    'OPENAI_TTS_FORMAT': 'wav'}):
            validate_idea_tts_environment(self.spec)

    def test_all_conflicts_reported_with_fix(self):
        with patch.dict(os.environ, {'OPENAI_TTS_VOICE': 'marin', 'OPENAI_TTS_MODEL': 'tts-1',
                                    'OPENAI_TTS_FORMAT': 'mp3'}):
            with self.assertRaises(ValueError) as ctx:
                validate_idea_tts_environment(self.spec)
        for value in ('nova', 'marin', 'gpt-4o-mini-tts', 'tts-1', 'wav', 'mp3',
                      'audio.voiceover.response_format', 'OPENAI_TTS_FORMAT', 'Fix', '--idea'):
            self.assertIn(value, str(ctx.exception))
        with patch.dict(os.environ, {'OPENAI_TTS_VOICE': ''}):
            with self.assertRaises(ValueError):
                validate_idea_tts_environment(self.spec)

    def test_new_idea_checks_current_yaml_before_preflight_and_preserves_old_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config').mkdir()
            (root / 'config' / 'video_spec_v1.yaml').write_text(json.dumps(self.spec), encoding='utf-8')
            old_job = root / 'video_job.json'
            old_job.write_text('{"spec_snapshot":{"audio":{"voiceover":{"voice":"marin"}}}}', encoding='utf-8')
            before = old_job.read_bytes()
            with patch.object(master, 'PROJECT_ROOT', root), patch.object(master, 'JOB_FILE', old_job), \
                 patch('sys.argv', ['pipeline_orchestrator.py', '--idea', 'New beach video']), \
                 patch.dict(os.environ, {'OPENAI_TTS_VOICE': 'marin'}), \
                 patch.object(master, 'preflight') as preflight, \
                 patch.object(master, 'run_pipeline') as pipeline, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(master.main(), 1)
            preflight.assert_not_called()
            pipeline.assert_not_called()
            self.assertEqual(before, old_job.read_bytes())
            self.assertIn("voice='nova'", output.getvalue())

    def test_new_idea_rejects_disjoint_scene_range_before_preflight(self):
        self.spec['visual']['scene']['min_duration_sec'] = 11
        with patch('sys.argv', ['pipeline_orchestrator.py', '--idea', 'New video']), \
             patch('validator.load_yaml', return_value=self.spec), \
             patch.dict(os.environ, {'VIDEO_PROVIDER': 'runway'}), \
             patch.object(master, 'save_job_atomic') as save, \
             patch.object(master, 'preflight') as preflight, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(master.main(), 1)
        preflight.assert_not_called()
        save.assert_not_called()
        self.assertIn('no overlap', output.getvalue())

    def test_video_generation_uses_snapshot_bounds(self):
        import image_to_video_generator as generator
        scene = {'scene_id': 1, 'motion_prompt': 'Hold', 'image': {
            'file': 'image.png', 'qc': {'status': 'passed'}, 'semantic_qc': {'status': 'passed'}}}
        timing = {'status': 'passed', 'render_duration_sec': 12,
                  'min_video_duration_sec': 2, 'max_video_duration_sec': 10}
        job = {'spec_snapshot': self.spec, 'script': {'scenes': [{'scene_id': 1, 'timing': timing}]}}
        with patch.object(generator, 'VIDEO_PROVIDER', 'still_motion'):
            self.assertEqual(generator.validate_scene_preconditions(job, scene), [])
            timing['render_duration_sec'] = 25
            self.assertTrue(generator.validate_scene_preconditions(job, scene))
        timing['render_duration_sec'] = 12
        with patch.object(generator, 'VIDEO_PROVIDER', 'runway'):
            self.assertTrue(generator.validate_scene_preconditions(job, scene))

    def test_valid_new_idea_reaches_preflight_but_resume_skips_config_guard(self):
        for idea in (None, 'New beach video'):
            with self.subTest(idea=idea), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'config').mkdir()
                (root / 'config' / 'video_spec_v1.yaml').write_text(json.dumps(self.spec), encoding='utf-8')
                argv = ['pipeline_orchestrator.py'] + (['--idea', idea] if idea else [])
                with patch.object(master, 'PROJECT_ROOT', root), patch.object(master, 'JOB_FILE', root/'missing.json'), \
                     patch('sys.argv', argv), \
                     patch('tts_settings.validate_idea_tts_environment', wraps=validate_idea_tts_environment) as guard, \
                     patch.object(master, 'preflight', side_effect=RuntimeError('test stop')) as preflight, \
                     patch.object(master, 'run_pipeline') as pipeline, redirect_stdout(io.StringIO()):
                    self.assertEqual(master.main(), 1)
                preflight.assert_called_once()
                pipeline.assert_not_called()
                self.assertEqual(guard.call_count, int(idea is not None))
