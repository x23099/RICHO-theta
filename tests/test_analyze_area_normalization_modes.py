import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from analyze_area_normalization_modes import (  # noqa: E402
    normalized_area,
    summarize_session,
)


class AreaNormalizationModesTest(unittest.TestCase):
    def test_raw_ground_distance_does_not_inherit_forward_z_asymmetry(self):
        left = {
            "z_m": 0.90,
            "ground_distance_m": 0.98,
            "raw_ground_distance_m": 1.05,
        }
        right = {
            "z_m": 1.00,
            "ground_distance_m": 1.05,
            "raw_ground_distance_m": 1.05,
        }
        self.assertLess(
            normalized_area(2300.0, left, "forward_z"),
            normalized_area(2300.0, right, "forward_z"),
        )
        self.assertAlmostEqual(
            normalized_area(2300.0, left, "raw_ground_distance"),
            normalized_area(2300.0, right, "raw_ground_distance"),
        )

    def test_summary_uses_visible_inliers_and_rejects_position_outlier(self):
        rows = [
            {
                "session": "test",
                "detected": True,
                "phase_label": "visible",
                "x_m": 0.0,
                "z_m": 1.0,
                "raw_distance_m": 1.0,
                "area_px": 2200.0,
            },
            {
                "session": "test",
                "detected": True,
                "phase_label": "visible",
                "x_m": 0.01,
                "z_m": 1.0,
                "raw_distance_m": 1.0,
                "area_px": 2200.0,
            },
            {
                "session": "test",
                "detected": True,
                "phase_label": "partial_occlusion",
                "x_m": 0.4,
                "z_m": 0.5,
                "raw_distance_m": math.hypot(0.4, 0.5),
                "area_px": 500.0,
            },
        ]
        result = summarize_session(rows, "raw_ground_distance", 2000.0)
        self.assertEqual(result["stable_inlier_observations"], 2)
        self.assertEqual(result["stable_inlier_accepted"], 2)
        self.assertEqual(result["outlier_observations"], 1)
        self.assertEqual(result["outlier_rejected"], 1)
        self.assertEqual(result["stable_acceptance_decision"], "PASS")


if __name__ == "__main__":
    unittest.main()
