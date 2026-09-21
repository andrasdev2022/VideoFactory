import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import final_audio_mix as mix


class MixVolumeTests(unittest.TestCase):
    def test_voice_gain_is_after_duck_split_and_in_cache_signature(self):
        with patch.dict(os.environ, {'FINAL_MIX_VOICE_VOLUME': '0.85'}):
            graph, _ = mix.build_filter_complex(total_duration=3,
                music={'volume': 0.35}, effects=[])
            self.assertIn('[voice_level]volume=0.850000[voice]', graph)
            self.assertIn('[voice_raw]asplit=2[voice_level][duck_main]', graph)
            self.assertIn('[music_preduck][duck_main]', graph)
            with tempfile.TemporaryDirectory() as tmp, patch.object(mix, "PROJECT_ROOT", Path(tmp)):
                video = Path(tmp) / 'source.mp4'
                video.write_bytes(b'video')
                signature = mix.build_source_signature(source_video=video,
                    source_kind='base', total_duration=3, music=None, effects=[])
                self.assertEqual(signature['mix_config']['voice_volume'], 0.85)

    def test_music_override_uses_existing_audio_and_overrides_saved_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'music.mp3').write_bytes(b'music')
            job = {'audio': {'background_music': {'audio_file': 'music.mp3', 'volume': 0.2}}}
            with patch.object(mix, 'PROJECT_ROOT', root), patch.dict(os.environ, {'FINAL_MIX_MUSIC_VOLUME': '0.35'}):
                music, _, _ = mix.collect_mix_inputs(job, [])
                self.assertEqual(music['volume'], 0.35)
                self.assertEqual(job['audio']['background_music']['volume'], 0.2)

    def test_voice_only_and_invalid_values(self):
        with patch.dict(os.environ, {'FINAL_MIX_VOICE_VOLUME': '0.85'}):
            graph, _ = mix.build_filter_complex(total_duration=3, music=None, effects=[])
            self.assertIn('[voice_level]volume=0.850000[voice]', graph)
        for invalid in ('-0.1', '1.1', 'nan', 'inf', 'invalid'):
            with patch.dict(os.environ, {'FINAL_MIX_VOICE_VOLUME': invalid}):
                with self.assertRaises(ValueError):
                    mix.volume_setting('FINAL_MIX_VOICE_VOLUME', 1.0)
