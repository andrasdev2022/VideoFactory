import copy
import unittest
from unittest.mock import patch

from duration_policy import duration_range, correction_target
from scene_timing import calculate_job_timing_summary
from still_motion_timing import extend_visual_holds
from final_qc_export import evaluate_technical_media
import test_final_qc_export


class DurationRangeTests(unittest.TestCase):
    spec = {'video': {'target_duration_sec': 30, 'min_duration_sec': 25, 'max_duration_sec': 35}}

    def test_inclusive_boundaries_and_outside(self):
        for total, accepted in [(24.999, False), (25, True), (25.25, True), (30, True), (35, True), (35.001, False), (37.2, False)]:
            job = {'script': {'scenes': [{'timing': {'status': 'passed', 'render_duration_sec': total}}]}}
            summary = calculate_job_timing_summary(job, self.spec)
            self.assertEqual(not summary['script_revision_recommended'], accepted)

    def test_corrections_use_nearest_bound(self):
        self.assertEqual(correction_target(37.2, self.spec), 35)
        self.assertEqual(correction_target(20, self.spec), 25)
        self.assertEqual(correction_target(25.25, self.spec), 25.25)

    def test_short_romance_no_longer_padded(self):
        job = {'script': {'scenes': []}}
        for duration in [5, 4.85, 4.8, 3.45, 2.95, 4.2]:
            job['script']['scenes'].append({'voice': {'qc': {'status': 'passed', 'actual': {'duration_sec': duration-.3}}},
                'timing': {'status': 'passed', 'render_duration_sec': duration, 'voice_duration_sec': duration-.3, 'headroom_sec': .3}})
        before = copy.deepcopy(job)
        with patch.dict('os.environ', {'VIDEO_PROVIDER': 'still_motion'}):
            self.assertFalse(extend_visual_holds(job, self.spec))
        self.assertEqual(job, before)

    def test_final_qc_matches_range(self):
        spec = test_final_qc_export.FinalQCExportTests().make_spec()
        spec['video'].update(self.spec['video'])
        actual = {'video_stream_count':1, 'audio_stream_count':1, 'video_codec': 'h264', 'audio_codec': 'aac', 'width':1080, 'height':1920,
                  'fps':30, 'audio_sample_rate':48000, 'file_size_bytes':1000000}
        for total, accepted in [(25, True), (35, True), (35.033, True), (24.9, False), (35.1, False)]:
            actual['duration_sec'] = total
            passed, errors, warnings = evaluate_technical_media(actual, spec)
            self.assertEqual(passed, accepted, errors)
            self.assertFalse(any('differs from target' in w for w in warnings))

    def test_invalid_config(self):
        for lower, upper in [(36,35), (0,35), (25,float('nan')), (31,35)]:
            with self.assertRaises(ValueError):
                duration_range({'video': {'target_duration_sec':30, 'min_duration_sec':lower, 'max_duration_sec':upper}})
