"""Offline regression tests: real files, mocked generation and no paid APIs."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import qc_continuation as qc
import scene_orchestrator as scene_runner
import pipeline_orchestrator as master


class QCFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'jobs').mkdir()
        self.path = self.root / 'jobs/video_job.json'
        Image.new('RGB', (20, 20), 'red').save(self.root / 'image.png')
        (self.root / 'video.mp4').write_bytes(b'video placeholder')
        self.job = {
            'job_id': 'test', 'spec_snapshot': {'version': 1},
            'script': {'scenes': [{'scene_id': 1, 'timing': {'status': 'passed', 'render_duration_sec': 3}},
                                  {'scene_id': 2, 'timing': {'status': 'passed', 'render_duration_sec': 3}}]},
            'visuals': {'scenes': [self.scene(1), self.scene(2)]},
            'orchestration': {'scenes': {'1': {'image_attempts': 4, 'video_attempts': 4}}},
            'assembly': {'status': 'passed'}, 'final_qc': {'status': 'passed'},
            'audio': {'assets': {'music': 'keep'}, 'mix': {'status': 'passed'}},
            'output': {'video_file': 'final.mp4'},
        }

    def scene(self, sid):
        return {'scene_id': sid, 'image_prompt': 'approved',
                'image': {'status': 'generated', 'file': 'image.png', 'qc': {'status': 'passed'},
                          'semantic_qc': {'status': 'passed'}},
                'video': {'status': 'generated', 'file': 'video.mp4', 'provider': 'still_motion',
                          'qc': {'status': 'passed'}, 'semantic_qc': {'status': 'failed',
                          'policy_version': scene_runner.VIDEO_SEMANTIC_QC_POLICY_VERSION,
                          'errors': ['egg cropped'], 'overall_notes': 'Egg outside frame'}}}

    def save(self):
        self.path.write_text(json.dumps(self.job), encoding='utf-8')

    def load(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def point(self, phase='video_semantic_qc'):
        qc.checkpoint(self.job, 1, phase, self.root, 'exhausted')
        self.save()


class ContinuationTests(QCFixture):
    def test_plain_resume_does_not_mutate_or_spend(self):
        self.point()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '-OverruleQC'):
            qc.resolve(self.path, self.root)
        self.assertEqual(before, self.path.read_bytes())

    def test_override_is_once_scoped_and_preserves_original_result(self):
        self.point()
        original = deepcopy(self.job)
        with patch.object(qc, 'assert_readable'):
            qc.resolve(self.path, self.root, 'overrule')
        result = self.load()
        self.assertNotIn('qc_continuation', result)
        self.assertEqual(result['visuals']['scenes'][1], original['visuals']['scenes'][1])
        accepted = result['visuals']['scenes'][0]['video']['semantic_qc']
        self.assertEqual(accepted['status'], 'passed')
        self.assertEqual(accepted['errors'], ['egg cropped'])
        event = result['qc_continuation_history'][0]
        self.assertEqual(event['point']['qc_result']['status'], 'failed')
        self.assertEqual(json.loads(Path(event['backup']).read_text()), original)
        self.assertEqual((self.root / 'video.mp4').read_bytes(), b'video placeholder')
        with self.assertRaisesRegex(ValueError, 'Nincs'):
            qc.resolve(self.path, self.root, 'overrule')
        qc.state_for(result, 2)['video_attempts'] = 4
        self.assertEqual(qc.route_failure(result, 2, self.root, 4, 4), 'qc_blocked')
        self.assertEqual(result['qc_continuation']['scene_id'], 2)

    def test_override_image_keeps_video_qc_failed(self):
        s = self.job['visuals']['scenes'][0]
        s['image']['semantic_qc']['status'] = 'failed'
        self.point('image_semantic_qc')
        qc.resolve(self.path, self.root, 'overrule')
        result = self.load()['visuals']['scenes'][0]
        self.assertEqual(result['image']['semantic_qc']['status'], 'passed')
        self.assertEqual(result['video']['semantic_qc']['status'], 'failed')

    def test_stale_job_requirements_and_metadata_rejected(self):
        for change in ('job', 'prompt', 'qc', 'config'):
            with self.subTest(change=change):
                job = deepcopy(self.job)
                self.point()
                if change == 'job': self.job['job_id'] = 'different'
                if change == 'prompt': self.job['visuals']['scenes'][0]['image_prompt'] = 'new'
                if change == 'qc': self.job['visuals']['scenes'][0]['video']['semantic_qc']['errors'] = []
                if change == 'config': self.job['spec_snapshot']['version'] = 2
                self.save()
                with self.assertRaises(ValueError): qc.resolve(self.path, self.root, 'overrule')
                self.job = job

    def test_changed_media_rejected_for_both_decisions(self):
        self.point()
        (self.root / 'video.mp4').write_bytes(b'changed')
        for decision in ('retry', 'overrule'):
            with self.assertRaisesRegex(ValueError, 'megváltozott'):
                qc.resolve(self.path, self.root, decision)

    def test_changed_source_rejected(self):
        self.point()
        Image.new('RGB', (20, 20), 'blue').save(self.root / 'image.png')
        with self.assertRaisesRegex(ValueError, 'forráskép'):
            qc.resolve(self.path, self.root, 'overrule')

    def test_missing_and_unreadable_media_cannot_be_overruled(self):
        self.point()
        with self.assertRaises((ValueError, OSError)):
            qc.resolve(self.path, self.root, 'overrule')  # ffmpeg rejects fake video
        (self.root / 'video.mp4').unlink()
        with self.assertRaises(OSError): qc.resolve(self.path, self.root, 'overrule')

    def test_technical_qc_cannot_be_overruled(self):
        self.job['visuals']['scenes'][0]['video']['qc']['status'] = 'failed'
        self.point('video_qc')
        with self.assertRaisesRegex(ValueError, 'Technikai'):
            qc.resolve(self.path, self.root, 'overrule')

    def test_retry_scopes_invalidation_and_retains_feedback_history(self):
        self.point()
        other = deepcopy(self.job['visuals']['scenes'][1])
        qc.resolve(self.path, self.root, 'retry')
        result = self.load()
        self.assertEqual(result['visuals']['scenes'][1], other)
        self.assertEqual(qc.state_for(result, 1)['video_attempts'], 0)
        self.assertEqual(qc.state_for(result, 1)['image_attempts'], 4)
        self.assertEqual(result['audio']['assets'], {'music': 'keep'})
        self.assertNotIn('mix', result['audio'])
        self.assertNotIn('assembly', result)
        self.assertNotIn('final_qc', result)
        self.assertEqual(result['visuals']['scenes'][0]['video']['semantic_qc']['errors'], ['egg cropped'])
        self.assertTrue(result['qc_continuation_history'][0]['media_backups'])

    def test_initial_generation_plus_three_repairs_and_persistence(self):
        s = self.job['visuals']['scenes'][0]
        s['image']['semantic_qc']['status'] = 'failed'
        s.pop('video')
        state = qc.state_for(self.job, 1)
        for attempts in (1, 2, 3):
            state['image_attempts'] = attempts
            self.assertEqual(qc.route_failure(self.job, 1, self.root, 4, 4), 'generate_image')
            self.save()
            self.job = self.load()
            state = qc.state_for(self.job, 1)
        state['image_attempts'] = 4
        self.assertEqual(qc.route_failure(self.job, 1, self.root, 4, 4), 'qc_blocked')
        self.assertEqual(self.job['qc_continuation']['repairs'], 3)
        self.assertEqual(len(self.job['qc_repair_history']), 3)

    def test_still_motion_repairs_source_with_feedback(self):
        qc.state_for(self.job, 1)['video_attempts'] = 1
        other = deepcopy(self.job['visuals']['scenes'][1])
        self.assertEqual(qc.route_failure(self.job, 1, self.root, 4, 4), 'generate_image')
        s = self.job['visuals']['scenes'][0]
        self.assertNotIn('video', s)
        self.assertNotIn('image', s)
        self.assertIn('egg cropped', s['image_repair_source']['semantic_qc']['overall_notes'])
        self.assertEqual(qc.state_for(self.job, 1)['video_attempts'], 1)
        self.assertEqual(self.job['visuals']['scenes'][1], other)
        self.assertEqual(s['image_prompt'], 'approved')

    def test_provider_repair_uses_qc_feedback(self):
        self.job['visuals']['scenes'][0]['video']['provider'] = 'local_ltx'
        qc.state_for(self.job, 1)['video_attempts'] = 2
        self.assertEqual(qc.route_failure(self.job, 1, self.root, 4, 4), 'retry_video_from_qc')

    def test_missing_point_and_conflicting_flags(self):
        self.save()
        with self.assertRaises(ValueError): qc.resolve(self.path, self.root, 'retry')
        for argv in (['-OverruleQC', '-RetryQC'], ['-RetryQC', '--idea', 'new'],
                     ['-OverRuleQC'], ['--max-image-attempts', '5']):
            with patch('sys.argv', ['pipeline_orchestrator.py'] + argv):
                with self.assertRaises(SystemExit): master.parse_args()

    def test_defaults_are_four_total_generations(self):
        with patch('sys.argv', ['pipeline_orchestrator.py']):
            args = master.parse_args()
            self.assertEqual((args.max_image_attempts, args.max_video_attempts), (4, 4))
        with patch('sys.argv', ['scene_orchestrator.py', '--scene', '1']):
            args = scene_runner.parse_args()
            self.assertEqual((args.max_image_attempts, args.max_video_attempts), (4, 4))

    def test_supervisor_still_blocks_image_generation(self):
        from image_generator import generate_scene_image
        with self.assertRaises(RuntimeError):
            generate_scene_image(None, self.job, self.job['visuals']['scenes'][0], True)

class PipelineIntegrationTests(QCFixture):
    def run_scene(self, worker):
        from argparse import Namespace
        args = Namespace(scene=1, max_image_attempts=4, max_video_attempts=4, reset_attempts=False)
        with patch.object(scene_runner, 'JOB_FILE', self.path), \
             patch.object(scene_runner, 'PROJECT_ROOT', self.root), \
             patch.object(scene_runner, 'parse_args', return_value=args), \
             patch.object(scene_runner, 'run_worker', side_effect=worker):
            return scene_runner.main()

    def test_real_scene_loop_stops_after_three_repairs_without_touching_other_scene(self):
        self.job['visuals']['scenes'][0].pop('video')
        self.job['orchestration']['scenes']['1']['video_attempts'] = 0
        self.save()
        other = deepcopy(self.job['visuals']['scenes'][1])
        calls = []
        def worker(name, args):
            calls.append(name)
            job = self.load()
            scene = job['visuals']['scenes'][0]
            if name == 'image_to_video_generator.py':
                scene['video'] = self.scene(1)['video']
                scene['video']['qc'] = {'status': 'pending'}
                scene['video']['semantic_qc'] = {'status': 'pending'}
            elif name == 'image_generator.py':
                scene['image'] = self.scene(1)['image']
                scene.pop('image_repair_source', None)
            elif name == 'video_qc.py':
                scene['video']['qc'] = {'status': 'passed'}
            elif name == 'video_semantic_qc.py':
                scene['video']['semantic_qc'] = self.scene(1)['video']['semantic_qc']
            else:
                self.fail('Unexpected worker: ' + name)
            self.job = job
            self.save()
            return 0
        self.assertEqual(self.run_scene(worker), 1)
        result = self.load()
        self.assertEqual(calls.count('image_to_video_generator.py'), 4)
        self.assertEqual(calls.count('image_generator.py'), 3)
        self.assertEqual(result['qc_continuation']['repairs'], 3)
        self.assertEqual(result['visuals']['scenes'][1], other)
        before = len(calls)
        self.assertEqual(self.run_scene(worker), 1)
        self.assertEqual(len(calls), before)

    def test_master_pending_decision_blocks_before_preflight(self):
        from argparse import Namespace
        self.point()
        args = Namespace(idea=None, OverruleQC=False, RetryQC=False)
        with patch.object(master, 'JOB_FILE', self.path), \
             patch.object(master, 'PROJECT_ROOT', self.root), \
             patch.object(master, 'parse_args', return_value=args), \
             patch.object(master, 'preflight') as preflight, \
             patch.object(master, 'run_pipeline') as pipeline:
            self.assertEqual(master.main(), 1)
            preflight.assert_not_called()
            pipeline.assert_not_called()

    def test_master_flag_does_not_accept_second_failure(self):
        from argparse import Namespace
        self.point()
        args = Namespace(idea=None, OverruleQC=True, RetryQC=False)
        def next_failure(args):
            job = self.load()
            self.assertEqual(job['visuals']['scenes'][0]['video']['semantic_qc']['status'], 'passed')
            qc.state_for(job, 2)['video_attempts'] = 4
            qc.checkpoint(job, 2, 'video_semantic_qc', self.root, 'second failure')
            self.job = job
            self.save()
            raise master.PipelineError('second failure')
        with patch.object(master, 'JOB_FILE', self.path), \
             patch.object(master, 'PROJECT_ROOT', self.root), \
             patch.object(master, 'parse_args', return_value=args), \
             patch.object(master, 'preflight'), \
             patch.object(qc, 'assert_readable'), \
             patch.object(master, 'run_pipeline', side_effect=next_failure):
            self.assertEqual(master.main(), 1)
        result = self.load()
        self.assertEqual(result['qc_continuation']['scene_id'], 2)
        self.assertEqual(result['visuals']['scenes'][1]['video']['semantic_qc']['status'], 'failed')
        self.assertEqual(len(result['qc_continuation_history']), 1)

    def test_worker_technical_failure_does_not_spin_or_create_override(self):
        self.job['visuals']['scenes'][0]['video']['semantic_qc'] = {'status': 'pending'}
        self.save()
        calls = []
        def worker(name, args):
            calls.append(name)
            return 7
        self.assertEqual(self.run_scene(worker), 1)
        self.assertEqual(calls, ['video_semantic_qc.py'])
        self.assertNotIn('qc_continuation', self.load())


if __name__ == '__main__':
    unittest.main()
