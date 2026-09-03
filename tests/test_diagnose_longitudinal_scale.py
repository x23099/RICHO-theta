import math
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diagnose_longitudinal_scale import _linear_scale, diagnose_session


def row(time_sec, odom_speed, raw_z, filtered_z, smoothed_vz):
    return {
        "monotonic_time_sec": str(time_sec),
        "odom_available": "1",
        "odom_linear_mps": str(odom_speed),
        "track_available": "1",
        "calibration_valid": "1",
        "detected": "1",
        "raw_z_m": str(raw_z),
        "filtered_z_m": str(filtered_z),
        "smoothed_vz_mps": str(smoothed_vz),
    }


class LongitudinalScaleTests(unittest.TestCase):
    def test_linear_scale_recovers_shrunken_range(self):
        scale, r2 = _linear_scale([0.0, 0.1, 0.2, 0.3], [1.2, 1.115, 1.03, 0.945])
        self.assertAlmostEqual(scale, 0.85)
        self.assertAlmostEqual(r2, 1.0)

    def test_approach_session_reports_position_and_speed_scale(self):
        rows = [
            row(0.0, 0.1, 1.20, 1.20, -0.08),
            row(1.0, 0.1, 1.12, 1.12, -0.08),
            row(2.0, 0.1, 1.04, 1.04, -0.08),
            row(3.0, 0.1, 0.96, 0.96, -0.08),
        ]
        result = diagnose_session("approach_center_v0p10_r01", "trial", rows, 0.03)
        self.assertEqual(result["expected_motion"], "approach")
        self.assertAlmostEqual(result["odom_path_m"], 0.3)
        self.assertAlmostEqual(result["raw_z_scale_vs_odom"], 0.8)
        self.assertAlmostEqual(result["filtered_z_scale_vs_odom"], 0.8)
        self.assertAlmostEqual(result["median_speed_scale_vs_odom"], 0.8)
        self.assertAlmostEqual(result["raw_z_correction_multiplier"], 1.25)

    def test_retreat_uses_same_positive_scale_convention(self):
        rows = [
            row(0.0, -0.1, 0.80, 0.80, 0.09),
            row(1.0, -0.1, 0.89, 0.89, 0.09),
            row(2.0, -0.1, 0.98, 0.98, 0.09),
        ]
        result = diagnose_session("retreat_center_v0p10_r01", "trial", rows, 0.03)
        self.assertAlmostEqual(result["raw_z_scale_vs_odom"], 0.9)
        self.assertAlmostEqual(result["median_speed_scale_vs_odom"], 0.9)

    def test_short_or_static_session_is_excluded(self):
        rows = [row(0.0, 0.0, 1.0, 1.0, 0.0)]
        self.assertIsNone(
            diagnose_session("static_center_ttc_r01", "trial", rows, 0.03)
        )
        self.assertTrue(math.isnan(_linear_scale([0.0], [1.0])[0]))


if __name__ == "__main__":
    unittest.main()
