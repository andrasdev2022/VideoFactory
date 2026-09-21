import copy
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import visual_styles as styles
import new_job
import pipeline_orchestrator as master
import visual_prompt_generator as prompts
import character_reference_generator as references
import test_new_job
import image_generator


class VisualStylesTests(unittest.TestCase):
    def test_presets_persist_and_replace_conflicting_defaults(self):
        fixture = test_new_job.NewJobTests()
        spec = fixture.make_spec()
        spec['visual'] = {'style': {'realistic': False, 'style_description': 'surreal cartoon'}}
        original = copy.deepcopy(spec)
        for name, (realistic, description) in styles.PRESETS.items():
            selected = styles.select_style(spec, name)
            job = new_job.build_job(fixture.make_output(), selected, 'test')
            job = json.loads(json.dumps(job))  # Saved-job resume round trip.
            self.assertEqual(job['style']['preset'], name)
            self.assertEqual(job['style']['realistic'], realistic)
            self.assertEqual(job['style']['visual'], description)
            effective = styles.effective_visual_spec(spec, job)
            self.assertEqual(effective['style']['style_description'], description)
            self.assertEqual(effective['style']['realistic'], realistic)
        self.assertEqual(spec, original)

    def test_default_keeps_legacy_behavior(self):
        fixture = test_new_job.NewJobTests()
        spec = fixture.make_spec()
        for choice in (None, 'default'):
            selected = styles.select_style(spec, choice)
            self.assertEqual(selected, spec)
            job = new_job.build_job(fixture.make_output(), selected, 'test')
            self.assertNotIn('preset', job['style'])
            self.assertEqual(job['style']['visual'], fixture.make_output().style.visual)
            self.assertNotIn('VISUAL STYLE OVERRIDE', styles.style_instruction(job))
            self.assertIn('CREATIVE DIRECTION', styles.style_instruction(job))

    def test_both_prompt_contexts_use_saved_style(self):
        spec = {'video': {'aspect_ratio': '9:16', 'resolution': '1080x1920', 'fps': 30},
                'visual': {'style': {'realistic': False, 'style_description': 'cartoon'}}}
        job = {'style': styles.persist_style({}, styles.select_style(spec, 'cinematic_realism'))}
        for context in (prompts.build_context(spec, job, []), references.build_context(spec, job)):
            self.assertTrue(context['global_visual_spec']['style']['realistic'])
            self.assertIn('authoritative', context['visual_style_instruction'])

    def test_cli_rejects_resume_style_change_and_unknown_preset(self):
        for args in [['--visual-style', 'anime'], ['--idea', 'test', '--visual-style', 'unknown']]:
            with patch('sys.argv', ['pipeline_orchestrator.py', *args]), self.assertRaises(SystemExit) as error:
                master.parse_args()
            self.assertEqual(error.exception.code, 2)
        with patch('sys.argv', ['pipeline_orchestrator.py', '--idea', 'test', '--visual-style', 'anime']):
            self.assertEqual(master.parse_args().visual_style, 'anime')

    def test_master_passes_preset_to_bootstrap(self):
        args = SimpleNamespace(idea='A romance', job_id=None, visual_style='cinematic_realism')
        with patch.object(master, 'run_worker', side_effect=RuntimeError('stop after bootstrap')) as worker:
            with self.assertRaisesRegex(RuntimeError, 'stop after bootstrap'):
                master.run_pipeline(args)
        self.assertEqual(worker.call_args.args, ('new_job', 'new_job.py',
            ['--idea', 'A romance', '--visual-style', 'cinematic_realism']))

    def test_image_requests_include_authoritative_style(self):
        job = {'style': styles.persist_style({}, styles.select_style({}, 'photorealistic'))}
        scene_prompt = image_generator.build_scene_prompt(job, {'scene_id': 1, 'image_prompt': 'A couple in a cafe'}, [])
        reference_prompt = image_generator.build_character_prompt(
            {'character_id': 'char-001', 'reference': {'prompt': 'Adult person'}}, job)
        for prompt in (scene_prompt, reference_prompt):
            self.assertIn('VISUAL STYLE OVERRIDE', prompt)
            self.assertIn('Photorealistic photography', prompt)
