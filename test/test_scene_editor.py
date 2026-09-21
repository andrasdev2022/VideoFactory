from copy import deepcopy
import unittest
from scene_editor import apply_patch


def ready_job():
    return {'job_id': 'demo', 'script': {'voiceover': 'One. Two.', 'scenes': [
        {'scene_id': i, 'voiceover': text, 'voice': {'status': 'generated', 'audio_file': f'{i}.wav'},
         'timing': {'status': 'passed', 'render_duration_sec': 5}} for i, text in [(1, 'One.'), (2, 'Two.')]]},
        'visuals': {'scenes': [{'scene_id': i, 'image_prompt': 'Original image',
            'motion_prompt': 'Original motion', 'image': {'status': 'generated', 'file': f'{i}.png'},
            'video': {'status': 'generated', 'file': f'{i}.mp4', 'trimmed': {'status': 'passed'}}}
            for i in (1, 2)]},
        'audio': {'plan': {'status': 'passed'}, 'assets': {'status': 'passed'},
                  'mix': {'status': 'passed'}, 'background_music': {'audio_file': 'base.mp3'}},
        'assembly': {'status': 'passed', 'file': 'base.mp4'},
        'subtitles': {'generation': {'status': 'passed'}, 'render': {'status': 'passed'}},
        'final_qc': {'publish_ready': True}, 'output': {'video_file': 'final.mp4'},
        'orchestration': {'scenes': {'1': {'image_attempts': 2, 'video_attempts': 4}},
                          'voice_scenes': {'1': {'attempts': 3}}}}


class SceneEditorTests(unittest.TestCase):
    def test_motion_edit_preserves_images_narration_other_scenes(self):
        job = ready_job()
        original = deepcopy(job)
        edited, changed = apply_patch(job, 1, {'motion_prompt': 'Slow camera push in.'})
        self.assertEqual(job, original)
        self.assertEqual(changed, ['motion_prompt'])
        self.assertEqual(edited['script'], job['script'])
        self.assertEqual(edited['visuals']['scenes'][1], job['visuals']['scenes'][1])
        self.assertEqual(edited['visuals']['scenes'][0]['image'], job['visuals']['scenes'][0]['image'])
        self.assertNotIn('video', edited['visuals']['scenes'][0])
        self.assertNotIn('assembly', edited)
        self.assertNotIn('final_qc', edited)
        self.assertEqual(edited['orchestration']['scenes']['1']['video_attempts'], 0)
        self.assertEqual(edited['orchestration']['scenes']['1']['image_attempts'], 2)

    def test_image_edit_resets_image_and_video_but_not_voice(self):
        job = ready_job()
        edited, _ = apply_patch(job, 1, {'image_prompt': 'A rainy castle.'})
        self.assertNotIn('image', edited['visuals']['scenes'][0])
        self.assertNotIn('video', edited['visuals']['scenes'][0])
        self.assertEqual(edited['script'], job['script'])
        self.assertEqual(edited['orchestration']['scenes']['1']['image_attempts'], 0)

    def test_voice_edit_rebuilds_timing_subtitles_and_mix(self):
        job = ready_job()
        edited, _ = apply_patch(job, 1, {'voiceover': 'New words.'})
        self.assertNotIn('voice', edited['script']['scenes'][0])
        self.assertNotIn('timing', edited['script']['scenes'][0])
        self.assertEqual(edited['script']['scenes'][1], job['script']['scenes'][1])
        self.assertEqual(edited['script']['voiceover'], 'New words. Two.')
        self.assertNotIn('generation', edited['subtitles'])
        self.assertNotIn('assets', edited['audio'])
        self.assertNotIn('1', edited['orchestration']['voice_scenes'])

    def test_music_edit_preserves_video_and_subtitles(self):
        job = ready_job()
        edited, _ = apply_patch(job, 2, {'music_prompt': 'Sparse mournful cello.'})
        self.assertEqual(edited['assembly'], job['assembly'])
        self.assertEqual(edited['script'], job['script'])
        self.assertEqual(edited['subtitles'], job['subtitles'])
        self.assertEqual(edited['visuals']['scenes'][1]['video'], job['visuals']['scenes'][1]['video'])
        self.assertEqual(edited['audio']['background_music'], job['audio']['background_music'])
        self.assertNotIn('mix', edited['audio'])
        self.assertNotIn('assets', edited['audio'])
        self.assertEqual(edited['visuals']['scenes'][1]['music_override']['style'], 'Sparse mournful cello.')

    def test_same_patch_is_noop_and_bad_patch_is_atomic(self):
        job = ready_job()
        edited, changed = apply_patch(job, 1, {'voiceover': 'One.'})
        self.assertEqual(edited, job)
        self.assertEqual(changed, [])
        for patch in ({}, {'genre': 'tragedy'}, {'motion_prompt': ''}, {'voiceover': 12}):
            with self.assertRaises(ValueError):
                apply_patch(job, 1, patch)
        with self.assertRaises(ValueError):
            apply_patch(job, 99, {'voiceover': 'New'})

    def test_still_motion_override_only_invalidates_selected_video(self):
        job = ready_job()
        edited, _ = apply_patch(job, 1, {'still_motion': {'mode': 'hold', 'max_zoom': 1.0}})
        self.assertEqual(edited['visuals']['scenes'][0]['still_motion']['mode'], 'hold')
        self.assertNotIn('video', edited['visuals']['scenes'][0])
        self.assertEqual(edited['visuals']['scenes'][1], job['visuals']['scenes'][1])
        for value in ({'mode': 'pan'}, {'max_zoom': 2}, {'max_zoom': float('nan')}, {'width': 4}):
            with self.assertRaises(ValueError):
                apply_patch(job, 1, {'still_motion': value})

    def test_out_of_range_edit_stops_before_global_rewrites(self):
        from pipeline_orchestrator import validate_scene_edit_timing, PipelineError
        job = ready_job()
        job['scene_edit_scope'] = {'scene_id': 1}
        spec = {'video': {'target_duration_sec': 30, 'min_duration_sec': 25, 'max_duration_sec': 35}}
        with self.assertRaises(PipelineError):
            validate_scene_edit_timing(job, spec)
        for scene in job['script']['scenes']:
            scene['timing']['render_duration_sec'] = 15
        validate_scene_edit_timing(job, spec)

    def test_cli_dry_run_preserves_job_and_save_makes_backup(self):
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        import scene_editor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'jobs').mkdir()
            job_path = root / 'jobs' / 'video_job.json'
            original = json.dumps(ready_job())
            job_path.write_text(original, encoding='utf-8')
            patch_path = root / 'patch.json'
            patch_path.write_text(json.dumps({'motion_prompt': 'Tiny camera push.'}), encoding='utf-8-sig')
            argv = ['scene_editor.py', '--scene', '1', '--patch', str(patch_path)]
            with patch.object(scene_editor, 'ROOT', root), patch('sys.argv', argv + ['--dry-run']):
                self.assertEqual(scene_editor.main(), 0)
            self.assertEqual(job_path.read_text(), original)
            self.assertFalse((root / 'jobs' / 'history').exists())
            with patch.object(scene_editor, 'ROOT', root), patch('sys.argv', argv):
                self.assertEqual(scene_editor.main(), 0)
            backups = list((root / 'jobs' / 'history').glob('*.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)
            self.assertNotEqual(job_path.read_text(), original)
