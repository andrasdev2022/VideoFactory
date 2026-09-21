import copy
import os
import json
import tempfile
from pathlib import Path
import script_duration_orchestrator as orchestrator
import unittest
from unittest.mock import patch

from still_motion_timing import extend_visual_holds
from script_duration_orchestrator import choose_next_action, inspect_global_state, ACTION_COMPLETE


class VisualHoldTimingTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'VIDEO_PROVIDER': 'still_motion'})
        env.start()
        self.addCleanup(env.stop)
        self.spec = {'video': {'target_duration_sec': 30, 'min_duration_sec': 25, 'max_duration_sec': 35}}
        self.job = {'script': {'duration_normalization': {'status': 'remeasured', 'changed_scene_ids': [1, 2, 3, 4, 5, 6]}, 'scenes': []}}
        for i, duration in enumerate([4, 3.85, 3.8, 2.45, 2, 3.2], 1):
            self.job['script']['scenes'].append({'scene_id': i, 'voiceover': 'Existing narration.',
                'voice': {'file': f'audio/{i}.wav', 'qc': {'status': 'passed', 'actual': {'duration_sec': duration - .3}}},
                'timing': {'status': 'passed', 'render_duration_sec': duration, 'voice_duration_sec': duration - .3,
                           'headroom_sec': .3, 'max_video_duration_sec': 10}})

    def test_romance_recovery_preserves_voice_and_finishes_with_exhausted_budget(self):
        voices = [copy.deepcopy(s['voice']) for s in self.job['script']['scenes']]
        self.assertTrue(extend_visual_holds(self.job, self.spec))
        self.assertAlmostEqual(sum(s['timing']['render_duration_sec'] for s in self.job['script']['scenes']), 25)
        self.assertEqual(voices, [s['voice'] for s in self.job['script']['scenes']])
        self.assertTrue(all(s['voiceover'] == 'Existing narration.' for s in self.job['script']['scenes']))
        self.assertEqual(choose_next_action(inspect_global_state(self.job), 3, 3), ACTION_COMPLETE)
        before = copy.deepcopy(self.job)
        self.assertFalse(extend_visual_holds(self.job, self.spec))
        self.assertEqual(before, self.job)

    def test_other_providers_unchanged(self):
        for provider in ['runway', 'local_ltx']:
            with patch.dict(os.environ, {'VIDEO_PROVIDER': provider}):
                before = copy.deepcopy(self.job)
                self.assertFalse(extend_visual_holds(self.job, self.spec))
                self.assertEqual(before, self.job)

    def test_limits_redistribute_hold(self):
        self.job['script']['scenes'][0]['timing']['max_video_duration_sec'] = 4.1
        self.assertTrue(extend_visual_holds(self.job, self.spec))
        self.assertEqual(self.job['script']['scenes'][0]['timing']['render_duration_sec'], 4.1)
        self.assertAlmostEqual(self.job['timing_summary']['total_render_duration_sec'], 25)

    def test_unsafe_or_unnecessary_changes_rejected_atomically(self):
        for case in ['pending', 'failed', 'stale', 'long', 'capacity', 'video']:
            with self.subTest(case=case):
                job = copy.deepcopy(self.job)
                if case == 'pending': job['script']['duration_normalization']['status'] = 'pending_remeasure'
                if case == 'failed': job['script']['scenes'][0]['voice']['qc']['status'] = 'failed'
                if case == 'stale': job['script']['scenes'][0]['voice']['qc']['actual']['duration_sec'] = 1
                if case in ['long', 'capacity']:
                    for s in job['script']['scenes']:
                        if case == 'long':
                            s['timing']['render_duration_sec'] = 6
                        else:
                            s['timing']['max_video_duration_sec'] = s['timing']['render_duration_sec']
                if case == 'video': job['visuals'] = {'scenes': [{'video': {'file': 'existing.mp4'}}]}
                before = copy.deepcopy(job)
                self.assertFalse(extend_visual_holds(job, self.spec))
                self.assertEqual(before, job)

    def test_real_orchestrator_resumes_exhausted_job_without_workers(self):
        for scene, duration in zip(self.job['script']['scenes'], [5, 4.85, 4.8, 3.45, 2.95, 4.2]):
            scene['timing'].update(render_duration_sec=duration, voice_duration_sec=duration-.3)
            scene['voice']['qc']['actual']['duration_sec'] = duration-.3
        self.job['timing_summary'] = {'status': 'complete', 'script_revision_recommended': True}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config' / 'video_spec_v1.yaml').write_text(json.dumps(self.spec))
            job_file = root / 'video_job.json'
            self.job['orchestration'] = {'script_duration': {'iterations': 3, 'state': 'failed'}}
            job_file.write_text(json.dumps(self.job))
            with patch.object(orchestrator, 'PROJECT_ROOT', root), patch.object(orchestrator, 'JOB_FILE', job_file), \
                 patch('sys.argv', ['script_duration_orchestrator.py']), patch.object(orchestrator, 'run_worker') as worker:
                self.assertEqual(orchestrator.main(), 0)
                worker.assert_not_called()
            result = json.loads(job_file.read_text())
            self.assertEqual(result['orchestration']['script_duration']['iterations'], 3)
            self.assertEqual(result['orchestration']['script_duration']['state'], 'completed')
            self.assertAlmostEqual(result['timing_summary']['total_render_duration_sec'], 25.25)
