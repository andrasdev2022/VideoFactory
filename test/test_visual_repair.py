import base64
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_visual_supervisor import fixture, plan, review
import visual_supervisor as vs
import image_generator as images


class RepairTests(unittest.TestCase):
    def approved(self):
        job = fixture()
        job['script']['scenes'].append(dict(job['script']['scenes'][0], scene_id=2))
        job['visuals']['scenes'].append(dict(job['visuals']['scenes'][0], scene_id=2))
        p = plan()
        p.scenes.append(p.scenes[0].model_copy(update={'scene_id': 2}, deep=True))
        with patch.object(vs, 'ask', side_effect=[p, review()]):
            self.assertTrue(vs.supervise(job, Mock(), lambda j: None))
        h = job['visual_supervisor']['plan_hash']
        job['characters'][0]['reference'].update(image_file='ref.png', supervisor_hash=h)
        for s in job['visuals']['scenes']:
            s['image'] = {'file': f"{s['scene_id']}.png", 'supervisor_hash': h,
                          'qc': {'status': 'passed'}, 'semantic_qc': {'status': 'passed'}}
            s['video'] = {'file': f"{s['scene_id']}.mp4"}
            job['orchestration']['scenes'][str(s['scene_id'])]['image_attempts'] = 1
        return job

    def reapprove(self, job, revisions):
        job['visual_supervisor']['source_hash'] = 'stale'
        with patch.object(vs, 'ask', side_effect=[revisions, review()]):
            self.assertTrue(vs.supervise(job, Mock(), lambda j: None))

    def test_partial_revision_preserves_other_scene(self):
        job = self.approved()
        changed = vs.SceneContract.model_validate(job['visual_supervisor']['plan']['scenes'][1])
        changed.must_show.append('silver ring')
        self.reapprove(job, vs.Plan(scenes=[changed], references=[], unresolved_conflicts=[]))
        self.assertEqual(job['visual_supervisor']['invalidation']['scenes'], [2])
        self.assertEqual(job['visuals']['scenes'][0]['video']['file'], '1.mp4')
        self.assertEqual(job['orchestration']['scenes']['1']['image_attempts'], 1)
        self.assertNotIn('image', job['visuals']['scenes'][1])
        self.assertEqual(job['characters'][0]['reference']['image_file'], 'ref.png')
        vs.require_approval(job)

    def test_reapproval_without_revisions_preserves_everything(self):
        job = self.approved()
        self.reapprove(job, vs.Plan(scenes=[], references=[], unresolved_conflicts=[]))
        self.assertEqual(job['visual_supervisor']['invalidation'],
                         {'references': [], 'scenes': [], 'videos_only': []})

    def test_old_schedule_notes_are_removed_without_discarding_media(self):
        job = self.approved()
        record = job['visual_supervisor']
        for scene in record['plan']['scenes']:
            scene['continuity_notes'] += ' Allocate 0:44-0:56 to the payoff.'
        record['plan_hash'] = vs.digest(record['plan'])
        record.pop('approved_inputs')  # v1 record
        for scene in job['visuals']['scenes']:
            scene['image']['supervisor_hash'] = record['plan_hash']
        job['characters'][0]['reference']['supervisor_hash'] = record['plan_hash']
        self.reapprove(job, vs.Plan(scenes=[], references=[], unresolved_conflicts=[]))
        self.assertEqual(job['visual_supervisor']['invalidation']['scenes'], [])
        self.assertNotIn('0:44', job['visuals']['scenes'][0]['continuity_notes'])

    def test_reference_change_invalidates_dependent_scenes(self):
        job = self.approved()
        reference = plan().references[0]
        reference.must_show.append('silver gauntlets')
        self.reapprove(job, vs.Plan(scenes=[], references=[reference], unresolved_conflicts=[]))
        self.assertEqual(job['visual_supervisor']['invalidation']['references'], ['c1'])
        self.assertEqual(job['visual_supervisor']['invalidation']['scenes'], [1, 2])

    def test_schedule_rejected_but_aspect_ratio_allowed(self):
        p = plan(); p.scenes[0].image_prompt += ' Vertical 9:16.'
        vs.validate_plan(fixture(), p)
        p.scenes[0].continuity_notes = 'Allocate 0:44-0:56 and add subtitles later.'
        with self.assertRaisesRegex(ValueError, 'scheduling'):
            vs.validate_plan(fixture(), p)

    def test_timing_change_invalidates_video_only(self):
        job = self.approved()
        job['script']['scenes'][0]['timing'] = {'render_duration_sec': 12}
        self.reapprove(job, vs.Plan(scenes=[], references=[], unresolved_conflicts=[]))
        self.assertEqual(job['visual_supervisor']['invalidation']['videos_only'], [1])
        self.assertIn('image', job['visuals']['scenes'][0])
        self.assertNotIn('video', job['visuals']['scenes'][0])

    def test_failed_image_survives_contract_invalidation_as_edit_source(self):
        job = self.approved()
        job['visuals']['scenes'][1]['image']['semantic_qc']['status'] = 'failed'
        p = plan(); p.scenes[0].scene_id = 2; p.scenes[0].must_show.append('ring')
        p.references = []
        self.reapprove(job, p)
        self.assertEqual(job['visuals']['scenes'][1]['image_repair_source']['file'], '2.png')

    def test_edit_uses_failed_pixels_first_and_preserves_backup_on_error(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(images, 'require_approval'):
            root = Path(folder); target = root / 'scene.png'; ref = root / 'ref.png'
            target.write_bytes(b'failed image'); ref.write_bytes(b'character')
            scene = {'image': {'file': 'scene.png', 'qc': {'status': 'passed'},
                              'semantic_qc': {'status': 'failed', 'reason': 'reflection'}}}
            with patch.object(images, 'PROJECT_ROOT', root):
                backup, audit = images.archive_repair_source(scene, target, 'repair reflection')
            client = Mock()
            def edit(**kwargs):
                self.assertEqual([f.read() for f in kwargs['image']], [b'failed image', b'character'])
                raise RuntimeError('API unavailable')
            client.images.edit.side_effect = edit
            with self.assertRaisesRegex(RuntimeError, 'API unavailable'):
                images.generate_scene_image_with_references(client, 'repair', [ref], target,
                                                           job={}, repair_source=backup)
            self.assertEqual(target.read_bytes(), b'failed image')
            self.assertEqual(backup.read_bytes(), b'failed image')
            self.assertEqual(audit['mode'], 'targeted_edit')
            client.images.generate.assert_not_called()
            client.images.edit.side_effect = None
            client.images.edit.return_value = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b'fixed').decode())])
            images.generate_scene_image_with_references(client, 'repair', [ref], target,
                                                       job={}, repair_source=backup)
            self.assertEqual(target.read_bytes(), b'fixed')
            self.assertEqual(backup.read_bytes(), b'failed image')

    def test_missing_failed_image_stops_instead_of_regenerating(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(images, 'PROJECT_ROOT', Path(folder)):
            with self.assertRaisesRegex(RuntimeError, 'edit source missing'):
                images.archive_repair_source({'image': {'file': 'missing.png', 'qc': {'status': 'passed'},
                    'semantic_qc': {'status': 'failed'}}}, Path(folder) / 'scene.png', 'repair')
