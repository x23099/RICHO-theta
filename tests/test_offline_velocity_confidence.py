import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from offline_velocity_confidence import ConfidenceSettings, OfflineVelocityConfidence, robust_line


def sample(gate, t, z, vz=-.2, **overrides):
    kwargs = dict(timestamp=t, raw_z_m=z, visual_vz_mps=vz,
                  measurement_valid=True, track_available=True)
    kwargs.update(overrides)
    return gate.update(**kwargs)


class OfflineVelocityConfidenceTests(unittest.TestCase):
    def test_mature_constant_velocity_is_trusted_without_odom(self):
        gate = OfflineVelocityConfidence()
        for i in range(8):
            result = sample(gate, i / 30, 1.3 - .2 * i / 30)
        self.assertTrue(result["trusted"])
        self.assertAlmostEqual(result["robust_vz_mps"], -.2)

    def test_constant_retreat_is_not_misclassified_as_closing(self):
        gate = OfflineVelocityConfidence()
        for i in range(8):
            result = sample(gate, i / 30, 1 + .2 * i / 30, vz=.2)
        self.assertTrue(result["trusted"])
        self.assertAlmostEqual(result["robust_vz_mps"], .2)

    def test_short_maturity_only_history_is_not_trusted(self):
        gate = OfflineVelocityConfidence(ConfidenceSettings(fast_critical_evidence=False))
        for i in range(3):
            result = sample(gate, i / 30, 1 - i / 30, vz=-1, critical_requested=True)
        self.assertFalse(result["trusted"])

    def test_consistent_fast_critical_trusted_at_two_intervals(self):
        gate = OfflineVelocityConfidence()
        results = [sample(gate, i / 30, 1 - i / 30, vz=-1, critical_requested=True) for i in range(3)]
        self.assertFalse(results[0]["trusted"])
        self.assertFalse(results[1]["trusted"])
        self.assertTrue(results[2]["trusted"])
        self.assertEqual(results[2]["reason"], "fast_consistent_critical_evidence")

    def test_reinitialization_jump_then_rebound_is_not_fast_evidence(self):
        gate = OfflineVelocityConfidence()
        result = None
        for t, z, vz in [(0, 1.1708, 0), (.043057, 1.0510, -.287), (.069478, 1.0951, -.512), (.097637, 1.0387, -.543)]:
            result = sample(gate, t, z, vz, critical_requested=True)
        self.assertFalse(result["trusted"])

    def test_one_final_outlier_cannot_be_hidden_by_median_residual(self):
        gate = OfflineVelocityConfidence()
        for i in range(9):
            sample(gate, i / 30, 1.3 - .2 * i / 30)
        result = sample(gate, 9 / 30, 1.7)
        self.assertFalse(result["trusted"])
        self.assertEqual(result["reason"], "position_trend_inconsistent")

    def test_velocity_disagreement_is_not_trusted(self):
        gate = OfflineVelocityConfidence()
        for i in range(8):
            result = sample(gate, i / 30, 1.3 - .2 * i / 30, vz=-.7)
        self.assertFalse(result["trusted"])
        self.assertEqual(result["reason"], "velocity_disagreement")

    def test_missing_measurement_breaks_fast_evidence(self):
        gate = OfflineVelocityConfidence()
        sample(gate, 0, 1, -1, critical_requested=True)
        sample(gate, .033, .967, -1, critical_requested=True)
        sample(gate, .066, None, measurement_valid=False)
        result = sample(gate, .1, .9, -1, critical_requested=True)
        self.assertFalse(result["trusted"])

    def test_no_track_and_reinitialization_discard_old_evidence(self):
        gate = OfflineVelocityConfidence()
        for i in range(8):
            sample(gate, i / 30, 1.3 - .2 * i / 30)
        self.assertFalse(sample(gate, .3, None, track_available=False)["trusted"])
        result = sample(gate, .4, 1, initialized=True)
        self.assertFalse(result["trusted"])
        self.assertEqual(result["samples"], 1)

    def test_reversed_and_duplicate_time_clear_evidence(self):
        for final in [0, 7 / 30]:
            gate = OfflineVelocityConfidence()
            for i in range(8):
                sample(gate, i / 30, 1.3 - .2 * i / 30)
            result = sample(gate, final, 1)
            self.assertFalse(result["trusted"])
            self.assertEqual(result["reason"], "non_increasing_time_reset")

    def test_long_gap_discards_stale_evidence(self):
        gate = OfflineVelocityConfidence()
        for i in range(8):
            sample(gate, i / 30, 1.3 - .2 * i / 30)
        result = sample(gate, .5, 1)
        self.assertFalse(result["trusted"])
        self.assertEqual(result["samples"], 1)

    def test_nan_is_not_trusted_and_invalid_time_is_rejected(self):
        gate = OfflineVelocityConfidence()
        self.assertFalse(sample(gate, 0, float("nan"))["trusted"])
        with self.assertRaises(ValueError):
            sample(gate, float("nan"), 1)

    def test_pair_slope_robustness_and_large_absolute_timestamps(self):
        points = [(1000000 + i / 30, 1 - .2 * i / 30) for i in range(10)]
        points[3] = (points[3][0], 2)
        fit = robust_line(points, .06)
        self.assertAlmostEqual(fit[0], -.2, places=7)

    def test_bound_storage(self):
        gate = OfflineVelocityConfidence()
        for i in range(100):
            sample(gate, i / 1000, 1 - .2 * i / 1000)
        self.assertLessEqual(len(gate.points), 32)

    def test_bad_settings_rejected(self):
        for kwargs in [{"minimum_samples": 2}, {"minimum_span_sec": 1}, {"window_sec": float("inf")}, {"maximum_samples": 10000}]:
            with self.assertRaises(ValueError):
                ConfidenceSettings(**kwargs)


if __name__ == "__main__":
    unittest.main()
