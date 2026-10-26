"""Exclusive budget consistency and equality with frozen uninstrumented geometry."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_profile as run
from profile_curve import compute_profiled, STAGES


class InstrumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = run.camera_from_candidate(json.loads(run.CAMERA.read_text()))
        cls.prior = np.array(json.loads(run.FLOOR.read_text())['nominal_transform'])[:3, :3].T @ [0., 0., 1.]
        rows = run.read_csv(run.DENSE / 'scene_results_r01/image_diagnostics.csv')
        row = next(r for r in rows if r['session'] == run.SESSION and int(r['frame']) == 302)
        cls.image = cv2.imread(row['source_native_png'])
        cv2.setNumThreads(1)

    def test_stage_names_unique(self):
        self.assertEqual(len(STAGES), 10)
        self.assertEqual(len(set(STAGES)), 10)

    def test_invalid_resolution_rejected(self):
        with self.assertRaises(ValueError):
            compute_profiled(np.zeros((360, 640, 3), np.uint8), self.camera, self.prior)

    def test_invalid_dtype_rejected(self):
        with self.assertRaises(ValueError):
            compute_profiled(self.image.astype(float), self.camera, self.prior)

    def test_blank_image_has_same_rejection(self):
        blank = np.zeros_like(self.image)
        curves, up, stats = compute_profiled(blank, self.camera, self.prior)
        self.assertEqual(run.canonical((curves, up)), run.canonical(run.compute(blank, self.camera, self.prior, True)))
        self.assertEqual(stats['hough_candidates'], 0)
        self.assertEqual(stats['evaluated_planes'], 0)
        self.assertFalse(up['accepted'])

    def test_actual_image_all_fields_and_order_exact(self):
        curves, up, stats = compute_profiled(self.image, self.camera, self.prior)
        self.assertEqual(run.canonical((curves, up)), run.canonical(run.compute(self.image, self.camera, self.prior, True)))
        self.assertEqual(stats['evaluated_planes'], len(curves))
        self.assertEqual(stats['distinct_planes'], sum(r['accepted'] for r in curves))

    def test_no_image_or_calibration_mutation(self):
        before = self.image.copy(); K = self.camera.K.copy(); D = self.camera.D.copy()
        compute_profiled(self.image, self.camera, self.prior)
        np.testing.assert_array_equal(self.image, before)
        np.testing.assert_array_equal(self.camera.K, K)
        np.testing.assert_array_equal(self.camera.D, D)

    def test_exclusive_times_sum_to_wall(self):
        _, _, stats = compute_profiled(self.image, self.camera, self.prior)
        exclusive = [stats[k + '_ns'] for k in STAGES]
        self.assertTrue(all(type(v) is int and v >= 0 for v in exclusive))
        self.assertGreaterEqual(stats['other_and_instrumentation_ns'], 0)
        self.assertEqual(sum(exclusive) + stats['other_and_instrumentation_ns'], stats['wall_ns'])

    def test_no_cross_frame_state(self):
        compute_profiled(self.image, self.camera, self.prior)
        blank = np.zeros_like(self.image)
        curves, up, _ = compute_profiled(blank, self.camera, self.prior)
        self.assertEqual(curves, [])
        self.assertFalse(up['accepted'])

    def test_synthetic_budget_uses_mean_not_sum_of_medians(self):
        rows = []
        for native, wall in ((10, 100), (50, 200)):
            r = dict.fromkeys([s + '_ns' for s in STAGES], 0)
            r.update(native_edges_ns=native, wall_ns=wall, other_and_instrumentation_ns=wall - native)
            rows.append(r)
        data = run.stage_summary(rows, 'synthetic')
        self.assertAlmostEqual(sum(r['mean_ms'] for r in data), .00015)
        self.assertAlmostEqual(sum(r['share_of_mean_wall_percent'] for r in data), 100.)
        self.assertAlmostEqual(next(r for r in data if r['stage'] == 'native_edges')['share_of_mean_wall_percent'], 20.)


class SavedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads((HERE / 'results_r01/summary.json').read_text())
        cls.rows = run.read_csv(HERE / 'results_r01/all_image_profile.csv')
        cls.pairs = run.read_csv(HERE / 'results_r01/paired_measurements.csv')
        cls.detailed = run.read_csv(HERE / 'results_r01/paired_stage_measurements.csv')

    def test_all_978_and_nine_sessions_retained(self):
        self.assertEqual(len(self.rows), 978)
        self.assertEqual(len({r['session'] for r in self.rows}), 9)

    def test_all_saved_candidate_hash_checks_passed(self):
        self.assertEqual(self.summary['result_mismatches'], 0)
        self.assertTrue(all(r['all_candidate_and_up_fields_exact'] == 'True' for r in self.rows))
        self.assertTrue(all(r['all_candidate_and_up_fields_exact'] == 'True' for r in self.pairs))

    def test_all_source_hashes_unchanged(self):
        run.check_hashes(self.summary['source_sha256'])

    def test_all_output_hashes_match(self):
        for name, h in self.summary['output_sha256'].items():
            self.assertEqual(run.sha256(HERE / 'results_r01' / name), h)

    def test_native_image_dimensions_and_not_edited(self):
        self.assertFalse(self.summary['source_images_edited'])
        self.assertTrue(all(r['image_decode_in_timing'] == 'False' for r in self.rows))

    def test_paired_order_balanced(self):
        self.assertEqual(len(self.pairs), 156)
        self.assertEqual(Counter(r['first'] for r in self.pairs), {'plain': 78, 'profiled': 78})
        self.assertEqual(len(self.detailed), 156)
        self.assertEqual(set(Counter(r['frame'] for r in self.detailed).values()), {3})

    def test_outer_timer_contains_internal_wall(self):
        self.assertTrue(all(int(r['outer_call_wall_ns']) >= int(r['wall_ns']) > 0 for r in self.detailed))

    def test_every_row_has_nonoverlapping_budget(self):
        for r in self.rows + self.detailed:
            values = [int(r[k + '_ns']) for k in STAGES]
            self.assertTrue(all(v >= 0 for v in values))
            residual = int(r['other_and_instrumentation_ns'])
            self.assertGreaterEqual(residual, 0)
            self.assertEqual(sum(values) + residual, int(r['wall_ns']))

    def test_counter_bounds(self):
        for r in self.rows:
            self.assertTrue(int(r['valid_ray_pixels']) <= int(r['roi_edge_pixels']) <= int(r['raw_edge_pixels']))
            self.assertTrue(0 <= int(r['hough_candidates']) <= 200)
            self.assertLessEqual(int(r['bin_winners']), 121 * int(r['hough_candidates']))
            n = int(r['distinct_planes'])
            self.assertEqual(int(r['potential_up_pairs']), n * (n - 1) // 2)

    def test_aggregate_shares_sum_to_one_hundred(self):
        groups = defaultdict(list)
        for r in run.read_csv(HERE / 'results_r01/stage_summary.csv'):
            groups[r['population']].append(r)
        self.assertEqual(len(groups), 11)
        for rows in groups.values():
            self.assertEqual(len(rows), 11)
            self.assertAlmostEqual(sum(float(r['share_of_mean_wall_percent']) for r in rows), 100.)
            self.assertAlmostEqual(sum(float(r['mean_ms']) for r in rows), float(rows[0]['total_wall_mean_ms']))

    def test_no_physical_or_optimization_claim(self):
        self.assertFalse(self.summary['optimization_implemented'])
        self.assertFalse(self.summary['end_to_end_latency_measured'])
        self.assertFalse(self.summary['production_changed'])
        self.assertTrue(all(r['usable_for_ffb'] == 'False' for r in self.rows))


if __name__ == '__main__':
    unittest.main()
