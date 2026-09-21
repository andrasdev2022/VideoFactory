from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import final_audio_mix
from scene_music import generate_scene_music, mix_scene_music
from service_budget_preflight import estimate_elevenlabs_audio_credits


class SceneMusicTests(unittest.TestCase):
    def test_generation_targets_only_override_and_unique_file(self):
        job = {'job_id': 'demo', 'audio': {'background_music': {'style': 'base'}},
               'visuals': {'scenes': [{'scene_id': 2, 'music_override': {'style': 'cello'}}]}}
        timeline = [{'scene_id': 2, 'start_sec': 4, 'end_sec': 10}]
        with patch('audio_asset_generator.generate_music', return_value=True) as generate:
            self.assertTrue(generate_scene_music(job, timeline, force=False, api_key='test'))
            args = generate.call_args.kwargs
            self.assertEqual(args['duration_ms'], 6000)
            self.assertEqual(args['output_name'], 'scene_002.mp3')
            self.assertEqual(args['job']['audio']['background_music']['style'], 'cello')
        self.assertEqual(job['audio']['background_music'], {'style': 'base'})

    def test_scene_music_is_in_credit_estimate(self):
        job = {'script': {'scenes': [{'scene_id': 2, 'timing': {'render_duration_sec': 6}}]},
               'visuals': {'scenes': [{'scene_id': 2, 'music_override': {'style': 'cello'}}]}}
        with patch.dict('os.environ', {'ELEVENLABS_MUSIC_CREDITS_PER_MINUTE': '900'}):
            estimate = estimate_elevenlabs_audio_credits(job)
        self.assertEqual(estimate['estimated_music_credits'], 90)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_real_filter_graph_mixes_replacement_with_and_without_base_music(self):
        # Real FFmpeg verifies asplit/ducking labels, time gating, trim and padding.
        track = dict(index=10002, scene_id=2, kind='scene_music', effect='scene_music',
                     start_sec=0.5, duration_sec=0.5, volume=0.2)
        for base in (None, {'volume': 0.2, 'mute_intervals': [(0.5, 1.0)]}):
            graph, label = final_audio_mix.build_filter_complex(total_duration=1.5, music=base, effects=[track])
            command = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=200:duration=1.5']
            if base:
                command += ['-f', 'lavfi', '-i', 'sine=frequency=400:duration=1.5']
            command += ['-f', 'lavfi', '-i', 'sine=frequency=800:duration=0.2',
                        '-filter_complex', graph, '-map', label, '-f', 'null', '-']
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_collect_requires_generated_override_and_mutes_only_its_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'base.mp3').write_bytes(b'base')
            (root / 'scene.mp3').write_bytes(b'scene')
            job = {'audio': {'background_music': {'required': True, 'audio_file': 'base.mp3'}},
                   'visuals': {'scenes': [{'scene_id': 2, 'music_override': {
                       'style': 'cello', 'audio_file': 'scene.mp3', 'generation': {'status': 'passed'}}}]}}
            with patch.object(final_audio_mix, 'PROJECT_ROOT', root):
                base, effects, _ = final_audio_mix.collect_mix_inputs(job, [{'scene_id': 2, 'start_sec': 3, 'end_sec': 8}])
                self.assertEqual(base['mute_intervals'], [(3, 8)])
                self.assertEqual(effects[0]['duration_sec'], 5)
                job['visuals']['scenes'][0]['music_override'].pop('generation')
                with self.assertRaises(RuntimeError):
                    final_audio_mix.collect_mix_inputs(job, [{'scene_id': 2, 'start_sec': 3, 'end_sec': 8}])

    def test_music_only_edit_keeps_approved_base_without_api_call(self):
        import audio_asset_generator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'base.mp3').write_bytes(b'existing')
            job = {'scene_edit_scope': {'scene_id': 2, 'fields': ['music_prompt']},
                   'audio': {'background_music': {'required': True, 'audio_file': 'base.mp3',
                             'generation': {'status': 'passed'}}}}
            with patch.object(audio_asset_generator, 'PROJECT_ROOT', root), patch.object(
                    audio_asset_generator, 'http_post_json_for_bytes') as api:
                self.assertFalse(audio_asset_generator.generate_music(job=job, duration_ms=30000,
                    force=False, api_key='test'))
                api.assert_not_called()
