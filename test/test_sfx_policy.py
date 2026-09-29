from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import sfx_policy as policy
import audio_asset_generator as assets
import audio_plan_generator as planner
import final_audio_mix as mixer
import final_qc_export as export
import pipeline_orchestrator as pipeline
from service_budget_preflight import estimate_elevenlabs_audio_credits
from new_job import build_job
import test_new_job


class SfxPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'spec.yaml'
        self.config.write_text('audio:\n  sound_effects:\n    enabled: false\n')
        self.patch = patch.object(policy, 'SPEC_FILE', self.config)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def job(self):
        return {'spec_snapshot': {'audio': {'sound_effects': {'enabled': True}}},
                'audio': {'sound_effects': {'enabled': True, 'effects': [
                    {'scene_id': 1, 'audio_file': 'missing-sfx.mp3', 'duration_sec': 2}]},
                    'mix': {'status': 'passed', 'file': 'old.mp4'}, 'assets': {'status': 'passed'}},
                'output': {'video_file': 'old.mp4'}, 'final_qc': {'status': 'passed'}}

    def test_bootstrap_uses_yaml_false(self):
        fixture = test_new_job.NewJobTests()
        spec = fixture.make_spec()
        spec.setdefault('audio', {})['sound_effects'] = {'enabled': False}
        job = build_job(fixture.make_output(), spec, 'test')
        self.assertFalse(job['audio']['sound_effects']['enabled'])
        self.assertFalse(job['spec_snapshot']['audio']['sound_effects']['enabled'])

    def test_current_yaml_vetoes_snapshot_and_manual_job_true(self):
        self.assertFalse(policy.sound_effects_enabled(self.job()))
        self.config.write_text('audio:\n  sound_effects:\n    enabled: true\n')
        self.assertTrue(policy.sound_effects_enabled(self.job()))
        job = self.job(); job['audio']['sound_effects']['enabled'] = False
        self.assertFalse(policy.sound_effects_enabled(job))
        job = self.job(); job['spec_snapshot']['audio']['sound_effects']['enabled'] = False
        self.assertFalse(policy.sound_effects_enabled(job))

    def test_quoted_false_rejected(self):
        self.config.write_text('audio:\n  sound_effects:\n    enabled: "false"\n')
        with self.assertRaisesRegex(ValueError, 'boolean'):
            policy.sound_effects_enabled(self.job())

    def test_planner_cannot_reenable_or_apply_returned_effects(self):
        job = self.job()
        result = planner.AudioPlanOutput(background_music_style='Piano', effects=[
            planner.SoundEffectPlan(scene_id=1, effect='Thunder', offset_sec=0, duration_sec=1, volume=.5)])
        planner.apply_audio_plan(job, result)
        self.assertFalse(job['audio']['sound_effects']['enabled'])
        self.assertEqual(job['audio']['sound_effects']['effects'], [])
        self.assertEqual(job['audio']['background_music']['style'], 'Piano')

    def test_force_sfx_generation_still_skipped(self):
        # No timeline or valid source files: disabled policy must return before processing.
        self.assertEqual(assets.generate_sfx(job=self.job(), timeline=[], force=True, api_key='unused'), (0, 0, []))

    def test_sfx_only_cli_does_not_require_credentials(self):
        job = self.job()
        with patch.object(assets, 'load_json', return_value=job), \
             patch.object(assets, 'parse_args', return_value=SimpleNamespace(sfx_only=True, music_only=False, force=True)), \
             patch.object(assets, 'get_timeline', return_value=[]), \
             patch.object(assets, 'get_total_duration_ms', return_value=1000), \
             patch.object(assets, 'save_job_atomic'), patch.object(assets, 'get_api_key') as key:
            self.assertEqual(assets.main(), 0)
            key.assert_not_called()

    def test_existing_effects_omitted_but_music_kept_and_cache_differs(self):
        job = self.job(); (self.root/'music.mp3').write_bytes(b'music')
        (self.root/'missing-sfx.mp3').write_bytes(b'sfx')
        (self.root/'source.mp4').write_bytes(b'video')
        job['audio']['background_music'] = {'required': True, 'audio_file': 'music.mp3'}
        timeline = [{'scene_id': 1, 'start_sec': 0, 'end_sec': 3}]
        with patch.object(mixer, 'PROJECT_ROOT', self.root):
            music, effects, _ = mixer.collect_mix_inputs(job, timeline)
            self.assertIsNotNone(music); self.assertEqual(effects, [])
            disabled = mixer.build_source_signature(self.root/'source.mp4', 'base', music, effects, 3)
            self.config.write_text('audio:\n  sound_effects:\n    enabled: true\n')
            music, effects, _ = mixer.collect_mix_inputs(job, timeline)
            self.assertEqual(len(effects), 1)
            enabled = mixer.build_source_signature(self.root/'source.mp4', 'base', music, effects, 3)
            self.assertNotEqual(disabled, enabled)

    def test_budget_excludes_disabled_sfx(self):
        self.assertEqual(estimate_elevenlabs_audio_credits(self.job())['estimated_sfx_credits'], 0)

    def test_resume_invalidates_only_audio_and_export_once(self):
        job = self.job(); job['visuals'] = {'scenes': [{'scene_id': 1, 'image': {'file': 'image.png'}}]}
        before = deepcopy(job['visuals'])
        with patch.object(pipeline, 'load_json', return_value=job), patch.object(pipeline, 'save_job_atomic') as save:
            pipeline.load_job(); save.assert_called_once()
        self.assertNotIn('mix', job['audio']); self.assertNotIn('assets', job['audio'])
        self.assertNotIn('final_qc', job)
        self.assertEqual(job['visuals'], before)
        self.assertEqual(len(job['audio']['sound_effects']['effects']), 1)
        self.assertFalse(policy.synchronize_sfx_policy(job))
        self.config.write_text('audio:\n  sound_effects:\n    enabled: true\n')
        self.assertTrue(policy.synchronize_sfx_policy(job))

    def test_direct_export_rejects_stale_sfx_mix_without_mutation(self):
        job = self.job(); before = deepcopy(job)
        with self.assertRaisesRegex(RuntimeError, 'final_audio_mix.py'):
            export.run_final_qc_export(job, {}, True)
        self.assertEqual(job, before)
