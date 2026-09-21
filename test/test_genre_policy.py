import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from genre_policy import prepare_spec, runtime_spec, genre_instruction
from new_job import build_job, generate_bootstrap
import test_new_job
from voice_generator import build_voice_instructions
from audio_asset_generator import build_music_prompt
from script_generator import SYSTEM_PROMPT


class GenrePolicyTests(unittest.TestCase):
    def test_tragedy_replaces_conflicting_defaults_without_mutating_yaml(self):
        spec = {'content': {'genre': 'tragedy', 'style': 'fast_paced', 'structure': {
            'payoff': {'purpose': 'unexpected ending or punchline'}}},
            'visual': {'style': {'style_description': 'colorful surreal comedy, exaggerated expressions'}},
            'audio': {'voiceover': {'style': 'energetic'}}}
        before = copy.deepcopy(spec)
        resolved = prepare_spec(spec)
        self.assertEqual(spec, before)
        self.assertNotIn('punchline', resolved['content']['structure']['payoff']['purpose'])
        self.assertNotIn('comedy', resolved['visual']['style']['style_description'])
        self.assertNotEqual('energetic', resolved['audio']['voiceover']['style'])
        self.assertIn('tragedy', build_voice_instructions(resolved))
        self.assertNotIn('core joke', SYSTEM_PROMPT)

    def test_custom_genre_and_explicit_visual_medium_survive(self):
        spec = {'content': {'genre': 'historical_epic'}, 'visual': {'style': {
            'preset': 'anime', 'style_description': 'cel shaded anime'}}}
        resolved = prepare_spec(spec)
        self.assertEqual(resolved['visual'], spec['visual'])
        self.assertIn('historical_epic', genre_instruction(spec=resolved))
        self.assertIn('Do not default to comedy', genre_instruction(spec=resolved))

    def test_new_job_freezes_spec_and_genre_even_if_model_returns_comedy(self):
        fixture = test_new_job.NewJobTests()
        spec = fixture.make_spec()
        spec['content'] = {'genre': 'tragedy'}
        job = build_job(fixture.make_output(), spec, 'demo')
        spec['content']['genre'] = 'comedy'
        self.assertEqual(job['idea']['genre'], 'tragedy')
        self.assertEqual(job['idea']['core_joke'], '')
        self.assertEqual(job['spec_snapshot']['content']['genre'], 'tragedy')
        self.assertIn('tragedy', build_music_prompt(job, 30000))
        self.assertNotIn('Keep the arrangement light, playful', build_music_prompt(job, 30000))

    def test_runtime_uses_snapshot_after_yaml_changes_and_legacy_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config').mkdir()
            (root / 'jobs').mkdir()
            config = root / 'config' / 'video_spec_v1.yaml'
            config.write_text('content:\n  genre: comedy\n')
            job = root / 'jobs' / 'video_job.json'
            job.write_text(json.dumps({'spec_snapshot': {'content': {'genre': 'tragedy'}}}))
            self.assertEqual(runtime_spec(config)['content']['genre'], 'tragedy')
            job.write_text('{}')
            self.assertEqual(runtime_spec(config)['content']['genre'], 'comedy')

    def test_bootstrap_request_contains_genre_instruction(self):
        client = Mock()
        generate_bootstrap(client, 'A knight remembers his companions.', {'content': {'genre': 'tragedy'}, 'video': {'target_duration_sec': 30, 'aspect_ratio': '9:16'}})
        request = client.responses.parse.call_args.kwargs
        self.assertIn('Genre tragedy', request['input'][0]['content'])
