"""保存座標からの局所差分。物理正解や画像点の採用を行わない。"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("floor_ranking_test",
    ROOT / "Experimental_results/2026-11-09/same_frame_floor_sensitivity_r01/rank_coordinates.py")
ranking = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ranking)


class FloorCoordinateRankingTests(unittest.TestCase):
    def setUp(self):
        self.b = dict(predicted_X_m=0., predicted_Z_m=2., height_m=.59)
        self.m = dict(predicted_X_m=-.01, predicted_Z_m=1.98, height_m=.585)
        self.p = dict(predicted_X_m=.01, predicted_Z_m=2.02, height_m=.595)

    def test_central_difference_and_actual_displacement_have_correct_units(self):
        r = ranking.pair_sensitivity(self.b, self.m, self.p, 1.)
        self.assertAlmostEqual(r["dX_m_per_px"], .01)
        self.assertAlmostEqual(r["dZ_m_per_px"], .02)
        self.assertAlmostEqual(r["max_center_shift_m"], .05**.5*.1)
        self.assertAlmostEqual(r["max_height_shift_m"], .005)

    def test_half_amplitude_scales_derivative_not_observed_displacement(self):
        a = ranking.pair_sensitivity(self.b, self.m, self.p, 1.)
        b = ranking.pair_sensitivity(self.b, self.m, self.p, .5)
        self.assertAlmostEqual(b["dZ_m_per_px"], 2*a["dZ_m_per_px"])
        self.assertEqual(a["max_center_shift_m"], b["max_center_shift_m"])

    def test_unavailable_is_not_zero_error(self):
        m = dict(self.m, predicted_Z_m="")
        r = ranking.pair_sensitivity(self.b, m, self.p, 1.)
        self.assertFalse(r["available"])
        self.assertIsNone(r["dZ_m_per_px"])

    def test_bad_amplitude_is_refused(self):
        for amp in (0., -1., float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ranking.pair_sensitivity(self.b, self.m, self.p, amp)

    def test_nonfinite_prediction_is_refused(self):
        p = dict(self.p, predicted_Z_m=float("nan"))
        with self.assertRaises(ValueError):
            ranking.pair_sensitivity(self.b, self.m, p, 1.)

    def test_distance_truth_is_not_an_input_and_source_is_unchanged(self):
        before = self.b.copy()
        ranking.pair_sensitivity(self.b, self.m, self.p, 1.)
        self.assertEqual(self.b, before)


if __name__ == "__main__":
    unittest.main()
