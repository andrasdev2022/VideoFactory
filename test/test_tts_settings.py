import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import tts_settings as settings
import voice_generator as gen
import voice_orchestrator as orchestration
import pipeline_orchestrator as master


class TtsSettingsTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)

    def spec(self, **overrides):
        return {'video': {'language': 'en'}, 'audio': {'voiceover': {
            'model': 'gpt-4o-mini-tts', 'voice': 'cedar', 'speed': .9,
            'style': 'gentle', 'instructions': 'Warm and restrained.', **overrides}}}

    def test_defaults_legacy_natural_and_overrides(self):
        self.assertEqual(settings.resolve_tts_settings({})['speed'], 1)
        self.assertEqual(settings.resolve_tts_settings(self.spec(speed='natural'))['speed'], 1)
        with patch.dict(os.environ, {'OPENAI_TTS_VOICE': 'marin', 'OPENAI_TTS_MODEL': 'gpt-4o-mini-tts-2025-12-15'}):
            config = settings.resolve_tts_settings(self.spec())
            self.assertEqual(config['voice'], 'marin')
            self.assertEqual(config['model'], 'gpt-4o-mini-tts-2025-12-15')

    def test_invalid_values_rejected(self):
        for value in [0, 4.1, True, 'fast', 'nan', float('inf')]:
            with self.assertRaises(ValueError): settings.resolve_tts_settings(self.spec(speed=value))
        for patch_value in [{'voice': 'unknown'}, {'model': 'unknown'}, {'response_format': 'pcm'},
                            {'instructions': []}, {'model': 'tts-1', 'voice': 'onyx'},
                            {'model': 'tts-1', 'voice': 'marin', 'instructions': ''}]:
            with self.assertRaises(ValueError): settings.resolve_tts_settings(self.spec(**patch_value))

    def generate(self, spec):
        root = Path(self.tmp.name)
        scene = {'scene_id': 1, 'voiceover': 'Hello.', 'timing': {'status': 'passed'}}
        job = {'job_id': 'test', 'script': {'scenes': [scene]},
               'visuals': {'scenes': [{'scene_id': 1, 'image': {'file': 'image.png'}, 'video': {'file': 'old.mp4'}}]},
               'audio': {'mix': {'status': 'passed'}}, 'final_qc': {'status': 'passed'}}
        client = Mock()
        # Mock context manager object explicitly.
        from unittest.mock import MagicMock
        context = MagicMock()
        context.__enter__.return_value.stream_to_file.side_effect = lambda path: path.write_bytes(b'fake audio')
        client.audio.speech.with_streaming_response.create.return_value = context
        with patch.object(gen, 'PROJECT_ROOT', root):
            self.assertTrue(gen.generate_scene_voice(client, spec, job, scene, False))
        return client, job, scene

    def test_request_cache_and_downstream_invalidation(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        spec = self.spec()
        client, job, scene = self.generate(spec)
        request = client.audio.speech.with_streaming_response.create.call_args.kwargs
        self.assertEqual(request['speed'], .9); self.assertEqual(request['voice'], 'cedar')
        self.assertIn('Warm and restrained.', request['instructions'])
        self.assertNotIn('timing', scene); self.assertNotIn('mix', job['audio'])
        self.assertNotIn('video', job['visuals']['scenes'][0]); self.assertIn('image', job['visuals']['scenes'][0])
        self.assertTrue(gen.voice_settings_match(spec, scene))
        with patch.object(gen, 'PROJECT_ROOT', Path(self.tmp.name)):
            self.assertFalse(gen.generate_scene_voice(client, spec, job, scene, False))
        self.assertEqual(client.audio.speech.with_streaming_response.create.call_count, 1)
        for updates in [{'voice':'marin'}, {'speed':1.1}, {'instructions':'Whisper.'}, {'style':'bright'}, {'response_format':'mp3'}]:
            self.assertFalse(gen.voice_settings_match(self.spec(**updates), scene))
        scene['voiceover'] = 'Different words.'
        self.assertFalse(gen.voice_settings_match(spec, scene))

    def test_legacy_model_omits_instructions(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        client, _, _ = self.generate(self.spec(model='tts-1', voice='onyx', instructions=''))
        self.assertNotIn('instructions', client.audio.speech.with_streaming_response.create.call_args.kwargs)

    def test_orchestrator_accepts_configured_speed_and_rejects_stale_settings(self):
        state = {'voice_status': 'generated', 'voice_file':'voice.wav', 'voice_speed':.9,
                 'expected_voice_speed':.9, 'voice_settings_current': True, 'voice_qc_status':None}
        self.assertEqual(orchestration.choose_next_action(state, 1, 3), orchestration.ACTION_QC)
        state['voice_settings_current'] = False
        self.assertEqual(orchestration.choose_next_action(state, 1, 3), orchestration.ACTION_GENERATE)
        self.assertEqual(orchestration.choose_next_action(state, 3, 3), orchestration.ACTION_STOP)

    def test_master_does_not_skip_stale_voice(self):
        with patch.object(master,'load_job',return_value={'script':{'scenes':[{'scene_id':1}]}}), \
             patch.object(master,'narration_is_current',return_value=False):
            self.assertFalse(master.all_voice_timing_completed())

    def test_long_combined_instructions_rejected(self):
        with self.assertRaisesRegex(ValueError, '4096'):
            gen.effective_voice_instructions(self.spec(instructions='a'*4096))
