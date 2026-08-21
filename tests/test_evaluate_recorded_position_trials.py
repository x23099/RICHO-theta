import math
import unittest

from evaluate_recorded_position_trials import (
    evaluate_position_rows,
    parse_expected_position,
)


class RecordedPositionTrialTest(unittest.TestCase):
    def test_parses_current_and_legacy_position_labels(self):
        self.assertEqual(
            parse_expected_position("x-0.22m_z0.95m_20260818_162502_015"),
            (-0.22, 0.95),
        )
        self.assertEqual(
            parse_expected_position("x0.0m_z1.3m_20260818_162247_135"),
            (0.0, 1.3),
        )
        self.assertEqual(
            parse_expected_position("holdout_xp0.15_z1.15_2"),
            (0.15, 1.15),
        )
        self.assertIsNone(parse_expected_position("static_center_z1p00_r01"))

    def test_evaluates_detected_position_and_completeness(self):
        rows = [
            {
                "monotonic_time_sec": "1.0",
                "detected": "1",
                "measurement_accepted": "1",
                "track_available": "1",
                "odom_available": "1",
                "x_m": "0.19",
                "z_m": "0.98",
            },
            {
                "monotonic_time_sec": "1.1",
                "detected": "1",
                "measurement_accepted": "1",
                "track_available": "1",
                "odom_available": "1",
                "x_m": "0.21",
                "z_m": "1.02",
            },
        ]

        result = evaluate_position_rows("x0.20m_z1.00m_trial", rows)

        self.assertEqual(result["frames"], 2)
        self.assertEqual(result["detection_rate"], 1.0)
        self.assertAlmostEqual(result["median_x_m"], 0.20)
        self.assertAlmostEqual(result["median_z_m"], 1.00)
        self.assertAlmostEqual(result["position_error_m"], 0.0)
        self.assertAlmostEqual(result["std_x_m"], 0.01)
        self.assertAlmostEqual(result["std_z_m"], 0.02)
        self.assertTrue(math.isfinite(result["duration_sec"]))


if __name__ == "__main__":
    unittest.main()
