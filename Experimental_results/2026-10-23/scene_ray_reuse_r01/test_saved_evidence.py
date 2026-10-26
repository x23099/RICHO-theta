"""Saved result invariants; run only after comparison and replay finish."""
from collections import Counter
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_comparison as study
from cone_dataset import read_csv, sha256


class SavedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proof = json.loads((HERE / 'results_r01/summary.json').read_text())
        cls.replay = json.loads((HERE / 'replay_r01/summary.json').read_text())
        cls.rows = read_csv(HERE / 'replay_r01/frame_metrics.csv')

    def test_all_492_not_only_successful_frames_exact(self):
        rows = read_csv(HERE / 'results_r01/equivalence.csv')
        self.assertEqual(len(rows), 492)
        self.assertEqual(len({r['session'] for r in rows}), 9)
        self.assertEqual(sum(r['up_accepted'] == 'True' for r in rows), 27)
        self.assertTrue(all(r['all_curve_fields_exact'] == 'True' and r['up_fields_exact'] == 'True' for r in rows))
        self.assertEqual(self.proof['all_curve_and_up_mismatches'], 0)

    def test_native_images_and_frozen_sources_unchanged(self):
        for p, h in self.proof['source_sha256'].items():
            self.assertEqual(sha256(Path(p)), h, p)

    def test_frozen_replay_sources_unchanged(self):
        for p, h in self.replay['source_sha256'].items():
            self.assertEqual(sha256(Path(p)), h, p)

    def test_all_comparison_outputs_hashed(self):
        for name, h in self.proof['output_sha256'].items():
            self.assertEqual(sha256(HERE / 'results_r01' / name), h)

    def test_all_replay_outputs_hashed(self):
        for name, h in self.replay['output_sha256'].items():
            self.assertEqual(sha256(HERE / 'replay_r01' / name), h)

    def test_paired_runs_balanced_and_three_per_image(self):
        rows = read_csv(HERE / 'results_r01/scene_stage_measurements.csv')
        self.assertEqual(len(rows), 312)
        groups = Counter((r['variant'], int(r['frame'])) for r in rows)
        self.assertEqual(len(groups), 104)
        self.assertEqual(set(groups.values()), {3})
        positions = Counter((r['variant'], r['position_in_pair']) for r in rows)
        self.assertEqual(set(positions.values()), {78})
        self.assertTrue(all(float(r['scene_service_ms']) > 0 for r in rows))
        self.assertTrue(all(r['image_read_in_timing'] == 'False' for r in rows))

    def test_no_zero_cost_or_end_to_end_claim(self):
        self.assertFalse(self.proof['end_to_end_latency_measured'])
        self.assertFalse(self.replay['cone_compute_cost_included'])
        self.assertFalse(self.replay['original_capture_delivery_latency_reproduced'])

    def test_zero_cost_matches_frozen_reference(self):
        rows = [r for r in self.rows if r['variant'] == 'zero_service_reference']
        self.assertEqual(len(rows), 1547)
        self.assertEqual(sum(r['diagnostic_available'] == 'True' for r in rows), 377)
        self.assertEqual(self.replay['zero_service_mismatches'], 0)

    def test_each_query_present_for_each_variant(self):
        for variant in ('zero_service_reference', 'baseline', 'same_frame_reuse'):
            frames = [int(r['frame']) for r in self.rows if r['variant'] == variant]
            self.assertEqual(frames, list(range(1, 1548)))

    def test_pending_hold_never_outputs(self):
        self.assertTrue(all(r['diagnostic_available'] == 'False'
                            for r in self.rows if r['newer_scene_input_pending'] == 'True'))

    def test_withheld_distance_is_blank(self):
        self.assertTrue(all(r['diagnostic_z_m'] == '' for r in self.rows if r['diagnostic_available'] == 'False'))

    def test_one_second_source_age_unchanged(self):
        for r in self.rows:
            if r['diagnostic_available'] == 'True':
                self.assertLessEqual(float(r['source_age_sec']), 1.)
                self.assertGreaterEqual(float(r['source_age_sec']), 0.)
                self.assertLessEqual(int(r['latest_completed_scene_frame']), int(r['frame']))

    def test_unfinished_future_rejection_is_not_emitted(self):
        self.assertFalse(any(r['diagnostic_available'] == 'True' and
                             r['newer_unfinished_rejection_posthoc'] == 'True' for r in self.rows))

    def test_no_physical_or_production_promotion(self):
        self.assertFalse(self.proof['production_changed'])
        self.assertFalse(self.replay['production_changed'])
        self.assertFalse(self.proof['physical_metric_verified'])
        self.assertTrue(all(r['usable_for_ffb'] == 'False' for r in self.rows))
        self.assertTrue(all(r['physical_metric_verified'] == 'False' for r in self.rows))


if __name__ == '__main__':
    unittest.main()
