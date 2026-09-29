import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import visual_supervisor as vs
import image_generator as images
import image_semantic_qc as image_qc
import video_semantic_qc as video_qc
import pipeline_orchestrator as pipeline


def fixture():
    return {'job_id': 'test', 'spec_snapshot': {'video': {'aspect_ratio': '9:16'}},
            'idea': {'title': 'Hands in sand'}, 'style': {},
            'characters': [{'character_id': 'c1', 'name': 'Kael', 'description': 'scar above eyebrow',
                            'reference': {'prompt': 'An armored man', 'visual_signature': 'black armor'}}],
            'script': {'voiceover': 'Only burning sand.', 'scenes': [
                {'scene_id': 1, 'voiceover': 'Only burning sand.', 'visual': {'description': 'Hands in sand'}}]},
            'visuals': {'scenes': [{'scene_id': 1, 'image_prompt': 'Extreme close-up of hands; eyebrow scar visible',
                                   'motion_prompt': 'Push in', 'characters': ['c1']}]}}


def plan():
    return vs.Plan(scenes=[vs.SceneContract(
        scene_id=1, image_prompt='Close-up of hands in smoking sand, black armor at wrists. No face.',
        motion_prompt='Slow centered camera push-in only.', negative_prompt='No text or faces',
        continuity_notes='Only visible armor and hands must match.', must_show=['hands', 'smoking sand'],
        optional=['distant oasis'], must_not_show=['face'],
        characters=[vs.Visibility(character_id='c1', visible_traits=['black armor at wrists'],
                                  not_required=['face', 'eyebrow scar'])],
        story_preservation='Burning sand replaces water.', resolutions=['Remove scar visibility from hand close-up.'])],
        references=[vs.ReferenceContract(character_id='c1', prompt='Canonical armored man on neutral background',
                                         must_show=['black armor', 'eyebrow scar'], must_not_show=['other characters'])],
        unresolved_conflicts=[])


def review():
    return vs.Review(approved=True, story_preserved=True, conflicts=[])


def approve(job):
    with patch.object(vs, 'ask', side_effect=[plan(), review()]):
        assert vs.supervise(job, Mock(), lambda j: None)
    return job


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'VIDEO_PROVIDER': 'still_motion'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_no_approval_blocks_all_image_entry_points_even_force(self):
        job = fixture(); client = Mock(); scene = job['visuals']['scenes'][0]
        calls = [lambda: images.generate_character_reference(client, job, job['characters'][0], True),
                 lambda: images.generate_scene_image(client, job, scene, True),
                 lambda: images.generate_image(client, 'x', Path('/tmp/not-written.png'), '1024x1024', job=job),
                 lambda: images.generate_scene_image_with_references(client, 'x', [], Path('/tmp/not-written.png'), job=job)]
        for call in calls:
            with self.assertRaisesRegex(RuntimeError, 'supervisor BLOCK'):
                call()
        client.images.generate.assert_not_called()
        client.images.edit.assert_not_called()

    def test_manual_cli_blocks_before_constructing_client(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test'}), \
             patch.object(images, 'load_json', return_value=fixture()), \
             patch.object(images, 'parse_args', return_value=SimpleNamespace(mode='scene_image', scene=1, force=True)), \
             patch.object(images, 'OpenAI') as client:
            self.assertEqual(images.main(), 1)
            client.assert_not_called()

    def test_refusal_or_empty_structured_response_fails_closed(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        job = fixture()
        with self.assertRaisesRegex(RuntimeError, 'no structured result'):
            vs.supervise(job, client, lambda j: None)
        self.assertEqual(job['visual_supervisor']['status'], 'blocked')
        client.images.generate.assert_not_called()

    def test_changed_policy_expires_approval(self):
        job = approve(fixture())
        with patch.object(vs, 'QC_RULES', vs.QC_RULES + ' Additional policy'):
            with self.assertRaisesRegex(RuntimeError, 'stale'):
                vs.require_approval(job)

    def test_complete_plan_and_independent_review_required(self):
        job = approve(fixture())
        self.assertEqual(vs.require_approval(job), plan())
        self.assertEqual(job['script']['voiceover'], 'Only burning sand.')
        self.assertIn('eyebrow scar visible', job['visual_supervisor']['original_inputs']['scenes'][0]['image_prompt'])
        self.assertNotIn('eyebrow scar', job['visuals']['scenes'][0]['image_prompt'])

    def test_missing_scene_or_reference_cannot_be_approved(self):
        for field in ('scenes', 'references'):
            candidate = plan(); setattr(candidate, field, [])
            with patch.object(vs, 'ask', return_value=candidate) as ask:
                job = fixture()
                self.assertFalse(vs.supervise(job, Mock(), lambda j: None, 2))
                self.assertEqual(ask.call_count, 2)
                self.assertEqual(job['visual_supervisor']['status'], 'blocked')

    def test_reviewer_conflicts_are_fed_back_and_repaired(self):
        rejected = vs.Review(approved=False, story_preserved=True, conflicts=['Wrong framing'])
        with patch.object(vs, 'ask', side_effect=[plan(), rejected, plan(), review()]) as ask:
            job = fixture()
            self.assertTrue(vs.supervise(job, Mock(), lambda j: None))
            self.assertEqual(ask.call_args_list[2].args[3]['feedback'], ['Wrong framing'])
            self.assertEqual(len(job['visual_supervisor']['rounds']), 2)

    def test_repeated_conflict_is_bounded_and_blocked(self):
        bad = vs.Review(approved=True, story_preserved=False, conflicts=[])
        with patch.object(vs, 'ask', side_effect=[plan(), bad] * 3) as ask:
            job = fixture()
            self.assertFalse(vs.supervise(job, Mock(), lambda j: None))
            self.assertEqual(ask.call_count, 6)
            with self.assertRaises(RuntimeError): vs.require_approval(job)

    def test_api_error_revokes_old_approval_and_persists_failure(self):
        job = approve(fixture()); job['style']['lighting'] = 'new'
        saved = []
        with patch.object(vs, 'ask', side_effect=RuntimeError('network failure')):
            with self.assertRaisesRegex(RuntimeError, 'network failure'):
                vs.supervise(job, Mock(), lambda j: saved.append(deepcopy(j)))
        self.assertEqual(saved[0]['visual_supervisor']['status'], 'blocked')
        self.assertIn('network failure', saved[-1]['visual_supervisor']['rounds'][0]['error'])
        self.assertEqual(len(job['visual_supervisor_history']), 1)

    def test_mutations_expire_approval(self):
        original = approve(fixture())
        mutations = [lambda j: j['script']['scenes'][0].update(voiceover='changed story'),
                     lambda j: j['characters'][0].update(description='different character'),
                     lambda j: j['characters'][0]['reference'].update(prompt='changed reference'),
                     lambda j: j['visuals']['scenes'][0].update(image_prompt='wide shot'),
                     lambda j: j['visuals']['scenes'][0].update(motion_prompt='run'),
                     lambda j: j['style'].update(medium='anime'),
                     lambda j: j['spec_snapshot'].update(visual={'new': True}),
                     lambda j: j['visual_supervisor']['plan']['scenes'][0]['must_show'].append('new demand')]
        for mutate in mutations:
            job = deepcopy(original); mutate(job)
            with self.assertRaisesRegex(RuntimeError, 'BLOCK'): vs.require_approval(job)
        with patch.dict('os.environ', {'VIDEO_PROVIDER': 'runway'}):
            with self.assertRaises(RuntimeError): vs.require_approval(original)
        with patch.dict('os.environ', {'STILL_MOTION_MAX_ZOOM': '1.08'}):
            with self.assertRaises(RuntimeError): vs.require_approval(original)

    def test_media_and_qc_do_not_expire_approval_or_spend_more_calls(self):
        job = approve(fixture())
        job['characters'][0]['reference'].update(status='generated', image_file='reference.png')
        job['visuals']['scenes'][0]['image'] = {'status': 'generated', 'semantic_qc': {'status': 'failed'}}
        job['orchestration']['scenes']['1']['image_attempts'] = 2
        with patch.object(vs, 'ask') as ask:
            self.assertTrue(vs.supervise(job, Mock(), lambda j: None))
            ask.assert_not_called()

    def test_legacy_artifacts_and_attempts_invalidated_without_changing_voice(self):
        job = fixture()
        job['visuals']['scenes'][0].update(image={'status': 'generated'}, video={'status': 'generated'})
        job['script']['scenes'][0]['voice'] = {'file': 'voice.wav'}
        job['characters'][0]['reference']['image_file'] = 'old.png'
        job['orchestration'] = {'scenes': {'1': {'image_attempts': 2}}}
        job['final_qc'] = {'publish_ready': True}
        job['output'] = {'directory': 'output/test', 'fps': 30, 'video_file': 'old.mp4'}
        approve(job)
        self.assertNotIn('image', job['visuals']['scenes'][0])
        self.assertNotIn('image_file', job['characters'][0]['reference'])
        self.assertEqual(job['orchestration']['scenes']['1']['image_attempts'], 0)
        self.assertEqual(job['script']['scenes'][0]['voice']['file'], 'voice.wav')
        self.assertNotIn('final_qc', job)
        self.assertEqual(job['output']['fps'], 30)
        self.assertEqual(job['output']['directory'], 'output/test')
        self.assertIsNone(job['output']['video_file'])

    def test_generator_and_both_qc_receive_same_contract(self):
        job = approve(fixture()); scene = job['visuals']['scenes'][0]
        contract = vs.contract_text(job, scene)
        self.assertIn(contract, images.build_scene_prompt(job, scene, []))
        self.assertEqual(json.loads(image_qc.build_text_context(job, scene))['approved_visual_contract'], contract)
        self.assertEqual(json.loads(video_qc.build_context(job, scene, []))['approved_visual_contract'], contract)
        self.assertIn('visible traits only', image_qc.SYSTEM_PROMPT)
        self.assertIn('visible traits only', video_qc.SYSTEM_PROMPT)

    def test_image_retry_preserves_contract_and_includes_feedback(self):
        job = approve(fixture()); scene = job['visuals']['scenes'][0]
        scene['image'] = {'semantic_qc': {'status': 'failed', 'overall_notes': 'Face dominates frame'}}
        prompt = images.build_scene_prompt(job, scene, [])
        self.assertIn('Face dominates frame', prompt)
        self.assertIn(vs.contract_text(job, scene), prompt)
        vs.require_approval(job)

    def test_approved_low_level_generate_and_edit_work(self):
        job = approve(fixture()); client = Mock()
        response = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b'fake-image').decode())])
        client.images.generate.return_value = response
        client.images.edit.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'out.png'
            images.generate_image(client, 'approved test', out, '1024x1024', job=job)
            self.assertEqual(out.read_bytes(), b'fake-image')
            ref = Path(directory) / 'ref.png'; ref.write_bytes(b'reference')
            images.generate_scene_image_with_references(client, 'approved test', [ref], out, job=job)
            client.images.edit.assert_called_once()

    def test_master_gate_runs_before_reference_images_even_on_resume(self):
        args = SimpleNamespace(idea=None, stop_after=pipeline.STAGE_SUPERVISOR,
                               max_local_rewrites=3, max_global_iterations=3)
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory)/'job.json'; active.write_text('{}')
            with patch.object(pipeline, 'JOB_FILE', active), patch.object(pipeline, 'load_job', return_value=fixture()), \
                 patch.object(pipeline, 'run_standard_stage', side_effect=lambda *a: calls.append(a)), \
                 patch.object(pipeline, 'run_voice_timing'), patch('genre_policy.runtime_spec', return_value={}), \
                 patch.object(pipeline, 'run_worker', side_effect=lambda *a: calls.append(a)):
                pipeline.run_pipeline(args)
        self.assertEqual(calls[-1][:2], (pipeline.STAGE_SUPERVISOR, 'visual_supervisor.py'))
        self.assertNotIn(pipeline.STAGE_CHARACTER_IMAGES, [c[0] for c in calls])

    def test_master_supervisor_failure_prevents_image_stage(self):
        args = SimpleNamespace(idea=None, stop_after=None, max_local_rewrites=3, max_global_iterations=3)
        stages = []
        def worker(stage, *args):
            if stage == pipeline.STAGE_SUPERVISOR:
                raise pipeline.PipelineError('blocked')
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory)/'job.json'; active.write_text('{}')
            with patch.object(pipeline, 'JOB_FILE', active), patch.object(pipeline, 'load_job', return_value=fixture()), \
                 patch.object(pipeline, 'run_standard_stage', side_effect=lambda *a: stages.append(a[0])), \
                 patch.object(pipeline, 'run_voice_timing'), patch('genre_policy.runtime_spec', return_value={}), \
                 patch.object(pipeline, 'run_worker', side_effect=worker):
                with self.assertRaisesRegex(pipeline.PipelineError, 'blocked'):
                    pipeline.run_pipeline(args)
        self.assertNotIn(pipeline.STAGE_CHARACTER_IMAGES, stages)


if __name__ == '__main__':
    unittest.main()
