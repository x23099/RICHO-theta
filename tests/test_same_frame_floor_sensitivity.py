"""同一画像の床4点感度の数値・分離・両解保持を検証。精度承認ではない。"""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("paired_sensitivity_test",
    ROOT / "Experimental_results/2026-11-09/same_frame_floor_sensitivity_r01/analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
from cone_distance_core import load_config


class SameFrameFloorSensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load_config()[1]
        cls.points = audit.read_observations(audit.PRIOR / "corner_identity_r01/corner_identity_comparison.csv")
        cls.h = audit.original.HYPOTHESES[2]
        cls.fixed = np.array([cls.points[43924][k] for k in audit.original.FIXED])
        cls.candidates = audit.original.fit_fixed(cls.fixed, cls.h, cls.camera)["candidates"]

    def test_perturbation_counts_and_baseline(self):
        variants = list(audit.fixed_variants())
        self.assertEqual(len(variants), 545)
        self.assertEqual(sum(r[0] == "single_coordinate" for r in variants), 32)
        self.assertEqual(sum(r[0] == "all_corner_box_vertices" for r in variants), 512)
        np.testing.assert_array_equal(variants[0][3], np.zeros((4, 2)))

    def test_all_box_vertices_are_distinct_and_have_declared_amplitude(self):
        for amp in (.5, 1.):
            values = [r[3] for r in audit.fixed_variants() if r[0] == "all_corner_box_vertices" and r[1] == amp]
            self.assertEqual(len({tuple(v.flat) for v in values}), 256)
            self.assertTrue(all(np.array_equal(abs(v), np.full((4, 2), amp)) for v in values))

    def test_single_coordinate_has_only_one_nonzero_component(self):
        for case, amp, _, delta in audit.fixed_variants():
            if case == "single_coordinate":
                self.assertEqual(np.count_nonzero(delta), 1)
                self.assertEqual(abs(delta).max(), amp)

    def test_E_zero_and_four_box_vertices_remain_separate_from_fit(self):
        p = self.points[43924]["E"]
        np.testing.assert_array_equal(audit.evaluation_pixels(p, 0.), [p])
        expanded = audit.evaluation_pixels(p, 1.)
        self.assertEqual(expanded.shape, (5, 2))
        np.testing.assert_array_equal(expanded[0], p)
        with patch.object(audit.original, "fit_fixed", side_effect=AssertionError("unexpected pose refit")):
            predicted = audit.predict_e_pixels(expanded, self.candidates[0], self.h, self.camera)
        self.assertEqual(len(predicted), 5)

    def test_negative_E_amplitude_is_refused(self):
        with self.assertRaises(ValueError):
            audit.evaluation_pixels([320., 390.], -1.)

    def test_batch_prediction_matches_previous_single_point_geometry(self):
        p = self.points[43924]["E"]
        result = audit.predict_e_pixels([p], self.candidates[0], self.h, self.camera)[0]
        old = audit.original.evaluate_E(p, [0., 2.], self.candidates[0], self.h, self.camera)
        np.testing.assert_allclose(result, [old["predicted_X_m"], old["predicted_Z_m"]], atol=1e-12)

    def test_inconsistent_pose_never_gets_floor_coordinates(self):
        wrong = dict(self.candidates[0], geometry_consistent=False)
        self.assertEqual(audit.predict_e_pixels([[320., 390.]], wrong, self.h, self.camera), [None])

    def test_branch_matching_survives_solver_order_reversal(self):
        matches, margin = audit.branch_matches(self.candidates, list(reversed(self.candidates)))
        self.assertEqual(matches, [1, 0])
        self.assertGreater(margin, 0.)

    def test_identical_branches_are_reported_ambiguous_not_selected(self):
        same = [self.candidates[0], self.candidates[0]]
        matches, margin = audit.branch_matches(same, same)
        self.assertEqual(matches, [None, None])
        self.assertEqual(margin, 0.)

    def test_missing_branch_does_not_invent_a_second_solution(self):
        matches, margin = audit.branch_matches(self.candidates, self.candidates[:1])
        self.assertEqual(matches, [None])
        self.assertIsNone(margin)

    def test_changing_target_affects_only_error_not_prediction_or_branch(self):
        predicted = audit.predict_e_pixels([[318., 371.]], self.candidates[0], self.h, self.camera)
        a = audit.candidate_row(43924, "P2", self.h, "baseline", 0., "zero", self.candidates[0],
                                0, 1., predicted, predicted[0], [0., 2.])
        b = audit.candidate_row(43924, "P2", self.h, "baseline", 0., "zero", self.candidates[0],
                                0, 1., predicted, predicted[0], [1., 4.])
        for key in ("predicted_X_m", "predicted_Z_m", "matched_reference_branch", "native_rmse_px", "height_m"):
            self.assertEqual(a[key], b[key])
        self.assertNotEqual(a["center_planar_error_m"], b["center_planar_error_m"])
        self.assertFalse(a["selected"])
        self.assertFalse(b["physical_metric_verified"])

    def test_all_raw_permutations_keep_both_solutions_and_do_not_adopt(self):
        group = [("P2", [43924], [318., 371.], [0., 2.])]
        with patch.object(audit.original, "GROUPS", [("P0", [], None, None)] + group):
            rows = audit.raw_assignment_rows(self.points, self.camera)
        self.assertEqual(len(rows), 48)
        self.assertEqual(len({r["permutation"] for r in rows}), 24)
        self.assertEqual({r["solution_index"] for r in rows}, {0, 1})
        self.assertTrue(all(not r["mapping_adopted"] for r in rows))

    def test_assignment_lower_bound_is_explicitly_more_permissive_than_real_selection(self):
        rows = [dict(permutation="0-1-2-3", frame=frame, available=True, native_rmse_px=.2,
                     planar_error_m=error) for frame, error in ((1, .01), (1, .5), (2, .4), (2, .02))]
        result = audit.permissive_assignment_summary(rows)
        self.assertEqual(result[0]["best_possible_maximum_error_m"], .02)
        self.assertFalse(result[0]["assignment_or_solution_adopted"])
        self.assertTrue(result[0]["E_used_to_choose_per_frame_solution_FOR_DIAGNOSTIC_ONLY"])

    def test_incomplete_assignment_has_no_complete_error_bound(self):
        rows = [dict(permutation="0-1-2-3", frame=1, available=True, native_rmse_px=.2, planar_error_m=.01),
                dict(permutation="0-1-2-3", frame=2, available=False, native_rmse_px=3., planar_error_m=None)]
        result = audit.permissive_assignment_summary(rows)
        self.assertTrue(all(r["best_possible_maximum_error_m"] is None for r in result))

    def test_prediction_and_fit_leave_input_coordinates_unchanged(self):
        before = self.fixed.copy()
        points = audit.evaluation_pixels(self.points[43924]["E"], 1.)
        original_points = points.copy()
        audit.original.fit_fixed(self.fixed, self.h, self.camera)
        audit.predict_e_pixels(points, self.candidates[0], self.h, self.camera)
        np.testing.assert_array_equal(self.fixed, before)
        np.testing.assert_array_equal(points, original_points)

    def test_saved_results_are_complete_unselected_and_not_a_confidence_interval(self):
        path = ROOT / "Experimental_results/2026-11-09/same_frame_floor_sensitivity_r01/results_r01/summary.json"
        summary = json.loads(path.read_text())
        self.assertEqual(summary["pose_evaluation_rows"], 9872)
        self.assertEqual(summary["raw_assignment_rows"], 384)
        self.assertEqual(summary["incomplete_variants"], [])
        for key in ("E_used_for_pose_fit", "E_used_for_branch_matching", "confidence_interval",
                    "continuous_box_upper_bound_certified", "height_fitted_to_reported_590mm",
                    "physical_metric_verified", "runtime_changed", "usable_for_ffb", "mirror_verified"):
            self.assertIs(summary[key], False, key)
        self.assertIsNone(summary["selected_solution"])
        self.assertIsNone(summary["selected_assignment"])


if __name__ == "__main__":
    unittest.main()
