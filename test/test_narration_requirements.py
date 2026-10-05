import copy
import io
import json
import os
import unittest
from contextlib import ExitStack, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import narration_requirements as req
import script_generator as generator
import script_timing_rewriter as local
import script_duration_rewriter as global_rewrite
from test_script_duration_rewriter import make_job
import test_script_timing_rewriter as local_tests


BRIEF = 'Nyuszi és farkas. Write English AABB rhyming couplets, 100–120 spoken words; keep pairs inside scenes.'


class NarrationRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.job = make_job()
        self.job.update(seed={'text': BRIEF}, idea={'title': 'A prose blueprint'})
        self.spec = {'video': {'target_duration_sec': 30, 'min_duration_sec': 25, 'max_duration_sec': 35},
                     'content': {}, 'visual': {}, 'audio': {'voiceover': {}}, 'subtitles': {}}

    def test_seed_formats_and_missing_legacy_seed(self):
        for seed in ({'text': BRIEF}, BRIEF):
            self.assertEqual(req.original_user_request({'seed': seed}), BRIEF)
        for seed in (None, {}, {'text': None}, 1):
            client = Mock()
            self.assertEqual(req.review_narration(client, 'model', {'seed': seed}, []), [])
            client.responses.parse.assert_not_called()

    def test_all_three_actual_writer_requests_contain_verbatim_brief(self):
        client = Mock()
        client.responses.parse.return_value.output_parsed = Mock()
        generator.generate_script(client, self.spec, self.job)
        self.assert_request(client)
        scene = local_tests.ScriptTimingRewriterTests().make_scene()
        self.job['script']['scenes'] = [scene]
        text = scene['voiceover']
        budget = local.calculate_rewrite_budget(scene, text)
        local.generate_rewrite(client, self.job, scene, 'voiceover', text, budget)
        self.assert_request(client)
        self.job = make_job()
        self.job['seed'] = {'text': BRIEF}
        plan = global_rewrite.build_rewrite_plan(self.job, self.spec)
        global_rewrite.generate_rewrite(client, self.job, plan)
        self.assert_request(client)

    def assert_request(self, client):
        request = client.responses.parse.call_args.kwargs
        self.assertIn(BRIEF, request['input'][1]['content'])
        self.assertIn('AUTHOR REQUIREMENTS', request['input'][0]['content'])
        self.assertIn('complete rhyme', request['input'][0]['content'])

    def test_review_reports_failures_and_checks_full_script(self):
        client = Mock()
        client.responses.parse.return_value.output_parsed = req.RequirementReview(
            errors=['Scene 1: prose instead of requested AABB couplets.'])
        errors = req.review_narration(client, 'test-model', self.job, self.job['script']['scenes'])
        self.assertIn('prose', errors[0])
        payload = json.loads(client.responses.parse.call_args.kwargs['input'][1]['content'])
        self.assertEqual(payload['original_user_request'], BRIEF)
        self.assertEqual(payload['scope'], 'full_script')
        self.assertEqual(len(payload['scenes']), 5)
        client.responses.parse.return_value.output_parsed = None
        with self.assertRaises(RuntimeError):
            req.review_narration(client, 'test-model', self.job, [])

    def test_local_scope_preserves_other_scenes_and_job(self):
        before = copy.deepcopy(self.job)
        scenes = req.rewritten_scenes(self.job, {2: 'By the pool in light,\nThey played till night.'})
        self.assertEqual(self.job, before)
        self.assertEqual(scenes[0]['voiceover'], before['script']['scenes'][0]['voiceover'])
        client = Mock()
        client.responses.parse.return_value.output_parsed = req.RequirementReview(errors=[])
        self.assertEqual(req.review_narration(client, 'model', self.job, scenes, [2]), [])
        payload = json.loads(client.responses.parse.call_args.kwargs['input'][1]['content'])
        self.assertEqual(payload['changed_scene_ids'], [2])
        self.assertEqual(payload['scope'], 'changed_scenes_only')
        self.assertIn('pool in light', payload['scenes'][1]['voiceover'])

    def test_generator_retries_semantic_failure_before_save(self):
        generated = Mock()
        generated.model_dump.return_value = {'target_duration_sec': 30, 'voiceover': 'verse',
            'scenes': [{'scene_id': 1, 'type': 'hook', 'duration_sec': 30, 'voiceover': 'verse'}]}
        for results, expected in (([['Scene 1: missing rhyme'], []], 0),
                                  ([['missing rhyme']] * 3, 1),
                                  (RuntimeError('review unavailable'), 1)):
            with self.subTest(results=results), ExitStack() as stack:
                stack.enter_context(redirect_stdout(io.StringIO()))
                stack.enter_context(patch.dict(os.environ, {'OPENAI_API_KEY': 'mock'}))
                stack.enter_context(patch.object(generator, 'OpenAI'))
                stack.enter_context(patch.object(generator, 'load_yaml', return_value=self.spec))
                stack.enter_context(patch.object(generator, 'load_json', return_value=self.job))
                gen = stack.enter_context(patch.object(generator, 'generate_script', return_value=generated))
                stack.enter_context(patch.object(generator, 'validate_video_job', side_effect=lambda *a: []))
                stack.enter_context(patch.object(generator, 'review_narration', side_effect=results))
                save = stack.enter_context(patch.object(generator, 'save_job'))
                self.assertEqual(generator.main(), expected)
                self.assertEqual(save.call_count, int(expected == 0))
                if gen.call_count > 1:
                    self.assertIn('rhyme', gen.call_args_list[1].kwargs['validation_feedback'])

    def test_both_rewriters_reject_without_mutation_and_feed_back_errors(self):
        for worker in (local, global_rewrite):
            with self.subTest(worker=worker.__name__), ExitStack() as stack:
                job = copy.deepcopy(self.job)
                if worker is local:
                    scene = local_tests.ScriptTimingRewriterTests().make_scene()
                    job['script']['scenes'] = [scene]
                    output = local.TimingRewriteOutput(scene_id=4, voiceover='Brief prose.')
                    stack.enter_context(patch.object(worker, 'parse_args', return_value=SimpleNamespace(scene=4)))
                else:
                    output = global_rewrite.DurationRewriteOutput(mode='shorten', scenes=[
                        global_rewrite.DurationRewriteScene(scene_id=2, voiceover='Brief prose.')])
                    stack.enter_context(patch.object(worker, 'parse_args'))
                    stack.enter_context(patch.object(worker, 'load_yaml', return_value=self.spec))
                before = copy.deepcopy(job)
                stack.enter_context(redirect_stdout(io.StringIO()))
                stack.enter_context(patch.dict(os.environ, {'OPENAI_API_KEY': 'mock'}))
                stack.enter_context(patch.object(worker, 'OpenAI'))
                stack.enter_context(patch.object(worker, 'load_json', return_value=job))
                generate = stack.enter_context(patch.object(worker, 'generate_rewrite', return_value=output))
                stack.enter_context(patch.object(worker, 'validate_rewrite', side_effect=lambda *a, **kw: []))
                review = stack.enter_context(patch.object(worker, 'review_narration', return_value=['missing rhyme']))
                save = stack.enter_context(patch.object(worker, 'save_job_atomic'))
                apply = stack.enter_context(patch.object(worker, 'apply_rewrite'))
                self.assertEqual(worker.main(), 1)
                self.assertEqual(review.call_count, worker.MAX_ATTEMPTS)
                self.assertEqual(generate.call_args_list[1].kwargs['validation_feedback'], ['missing rhyme'])
                save.assert_not_called()
                apply.assert_not_called()
                self.assertEqual(job, before)
                # An accepted retry may reach application; no rejected candidate may.
                review.side_effect = [['missing rhyme'], []]
                class Accepted(Exception):
                    pass
                apply.side_effect = Accepted
                with self.assertRaises(Accepted):
                    worker.main()
                apply.assert_called_once()
                self.assertEqual(job, before)
                # A failed review is a technical stop, never implicit approval.
                apply.reset_mock()
                review.side_effect = RuntimeError('review unavailable')
                self.assertEqual(worker.main(), 1)
                apply.assert_not_called()
                save.assert_not_called()
