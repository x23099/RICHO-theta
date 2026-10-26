"""Exact per-bin first-min tie behavior and immutable full-result evidence."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_fast as run
from guarded_curve_geometry import bin_winners


def legacy(ids, bins, distance):
    chosen = []
    for b in np.unique(bins):
        options = ids[bins == b]
        chosen.append(options[np.argmin(distance[options])])
    return np.asarray(chosen, dtype=np.intp)


class BinSelectionTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(bin_winners(np.array([], int), np.array([], int), np.array([])).tolist(), [])

    def test_one_element(self):
        np.testing.assert_array_equal(bin_winners([3], [4], [9., 8., 7., 6.]), [3])

    def test_first_of_equal_minima(self):
        np.testing.assert_array_equal(bin_winners([0, 1, 2, 3, 4], [1, 1, 1, 3, 3], [2., 1., 1., 0., 0.]), [1, 3])

    def test_signed_zero_keeps_first_index(self):
        np.testing.assert_array_equal(bin_winners([0, 1, 2, 3], [1, 1, 2, 2], [0., -0., -0., 0.]), [0, 2])

    def test_sparse_indices_and_bin_gaps(self):
        ids = np.array([2, 5, 8, 12, 13]); bins = np.array([30, 30, 32, 99, 99])
        values = np.arange(20., dtype=float)[::-1]
        np.testing.assert_array_equal(bin_winners(ids, bins, values), legacy(ids, bins, values))

    def test_all_one_bin(self):
        ids = np.arange(100); bins = np.ones(100, int); values = np.ones(100)
        np.testing.assert_array_equal(bin_winners(ids, bins, values), [0])

    def test_each_element_own_bin(self):
        ids = np.arange(50); bins = ids * 3; values = np.ones(50)
        np.testing.assert_array_equal(bin_winners(ids, bins, values), ids)

    def test_seeded_random_and_ties_against_legacy(self):
        rng = np.random.default_rng(20261023)
        for _ in range(500):
            n = int(rng.integers(1, 1000))
            ids = np.sort(rng.choice(2000, n, replace=False))
            bins = np.sort(rng.integers(0, 121, n))
            distance = rng.integers(0, 20, 2000).astype(float)
            np.testing.assert_array_equal(bin_winners(ids, bins, distance), legacy(ids, bins, distance))

    def test_extreme_finite_distances(self):
        values = np.array([1e300, -1e300, -1e300, np.nextafter(0., 1.), 0.])
        np.testing.assert_array_equal(bin_winners(np.arange(5), [1, 1, 1, 2, 2], values), [1, 4])

    def test_wrong_shape_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([[0, 1]], [1, 1], [0., 1.])

    def test_float_ids_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0., 1.], [1, 1], [0., 1.])

    def test_boolean_ids_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([False, True], [1, 1], [0., 1.])

    def test_float_bins_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 1], [1., 1.], [0., 1.])

    def test_mismatched_lengths_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 1], [1], [0., 1.])

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 0], [1, 1], [0., 1.])

    def test_unsorted_ids_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([1, 0], [1, 1], [0., 1.])

    def test_unsorted_bins_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 1], [2, 1], [0., 1.])

    def test_negative_ids_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([-1, 1], [1, 1], [0., 1.])

    def test_out_of_range_ids_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 2], [1, 1], [0., 1.])

    def test_nonfinite_selected_distance_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 1], [1, 1], [0., np.nan])

    def test_unused_nan_not_selected(self):
        np.testing.assert_array_equal(bin_winners([0, 2], [1, 1], [1., np.nan, 0.]), [2])

    def test_inputs_not_mutated(self):
        ids = np.arange(10); bins = ids // 3; distance = np.arange(10., 0., -1.)
        original = [x.copy() for x in (ids, bins, distance)]
        bin_winners(ids, bins, distance)
        for now, before in zip((ids, bins, distance), original):
            np.testing.assert_array_equal(now, before)

    def test_unsigned_reverse_ids_rejected_without_overflow(self):
        with self.assertRaises(ValueError):
            bin_winners(np.array([1, 0], np.uint64), [1, 1], [0., 1.])

    def test_unsigned_reverse_bins_rejected_without_overflow(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 1], np.array([2, 1], np.uint64), [0., 1.])

    def test_extreme_signed_bins_do_not_overflow_order_check(self):
        np.testing.assert_array_equal(bin_winners([0, 1], [np.iinfo(np.int64).min, np.iinfo(np.int64).max], [0., 1.]), [0, 1])

    def test_complex_distances_rejected(self):
        with self.assertRaises(ValueError):
            bin_winners([0, 1], [1, 1], [1j, 2j])

    def test_r01_unsigned_guard_gap_reproduced_without_editing_it(self):
        from fast_curve_geometry import bin_winners as r01
        ids = np.array([0, 1]); bins = np.array([2, 1], np.uint64); distances = np.array([0., 1.])
        np.testing.assert_array_equal(r01(ids, bins, distances), [0, 1])
        with self.assertRaises(ValueError):
            bin_winners(ids, bins, distances)


class SavedBinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proof = json.loads((HERE / 'results_guard_r02/summary.json').read_text())
        cls.replay = json.loads((HERE / 'replay_r01/summary.json').read_text())

    def test_all_978_results_exact(self):
        rows = run.p.read_csv(HERE / 'results_guard_r02/equivalence.csv')
        self.assertEqual(len(rows), 978)
        self.assertEqual(len({r['session'] for r in rows}), 9)
        self.assertTrue(all(r['all_candidate_and_up_fields_exact'] == 'True' for r in rows))
        self.assertEqual(sum(r['accepted'] == 'True' for r in rows), 51)

    def test_all_frozen_sources_and_outputs_match(self):
        for folder in ('results_r01', 'results_guard_r02', 'replay_r01'):
            run.p.check_manifest(HERE / folder / 'summary.json')

    def test_checkpoint_batches_have_exact_spec_and_unique_image_keys(self):
        import hashlib
        folder = HERE / 'guard_equivalence_checkpoints_r02'
        spec = folder / 'run_spec.json'
        rows = []
        for path in sorted(folder.glob('batch_*.json')):
            record = json.loads(path.read_text())
            self.assertEqual(record['run_spec_sha256'], run.p.sha256(spec))
            self.assertEqual(record['checks_sha256'], hashlib.sha256(run.p.canonical(record['checks']).encode()).hexdigest())
            rows.extend(record['checks'])
        self.assertEqual(len(rows), 978)
        self.assertEqual(len({(r['session'], r['frame']) for r in rows}), 978)

    def test_balanced_paired_52_images_three_runs(self):
        from collections import Counter
        rows = run.p.read_csv(HERE / 'results_guard_r02/scene_stage_measurements.csv')
        self.assertEqual(len(rows), 312)
        counts = Counter((r['variant'], r['frame']) for r in rows)
        self.assertEqual(len(counts), 104)
        self.assertEqual(set(counts.values()), {3})
        self.assertEqual(self.proof['order_counts'], {'control': 78, 'fast': 78})

    def test_zero_cost_377_reference(self):
        self.assertEqual(self.replay['zero_cost_mismatches'], 0)
        selected = [r for r in run.p.read_csv(HERE / 'replay_r01/frame_metrics.csv') if r['variant'] == 'zero_service_reference']
        self.assertEqual(sum(r['diagnostic_available'] == 'True' for r in selected), 377)

    def test_pending_ttl_and_no_physical_output(self):
        for r in run.p.read_csv(HERE / 'replay_r01/frame_metrics.csv'):
            if r['diagnostic_available'] == 'True':
                self.assertEqual(r['newer_scene_input_pending'], 'False')
                self.assertTrue(0 <= float(r['source_age_sec']) <= 1.)
            else:
                self.assertEqual(r['diagnostic_z_m'], '')
            self.assertEqual(r['usable_for_ffb'], 'False')
            self.assertEqual(r['physical_metric_verified'], 'False')

    def test_no_production_or_tie_rule_change(self):
        self.assertFalse(self.proof['tie_rule_changed'])
        self.assertFalse(self.proof['approximate_minimum_used'])
        self.assertFalse(self.proof['production_changed'])
        self.assertFalse(self.proof['end_to_end_latency_measured'])


if __name__ == '__main__':
    unittest.main()
