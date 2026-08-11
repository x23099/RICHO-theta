import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from compare_observation_gates import external_rejection_reason  # noqa: E402


class ObservationGateTest(unittest.TestCase):
    def setUp(self):
        self.row = {
            "detected": True,
            "area_px": 1000.0,
            "bbox_fill_ratio": 0.8,
            "contour_solidity": 0.9,
        }

    def test_normalized_area_uses_predicted_range(self):
        reason = external_rejection_reason(
            self.row, {"min_normalized_area": 3000.0}, predicted_z_m=1.0
        )
        self.assertEqual(reason, "normalized_area_gate")
        self.assertEqual(
            external_rejection_reason(
                self.row,
                {"min_normalized_area": 3000.0},
                predicted_z_m=2.0,
            ),
            "",
        )

    def test_shape_gate_reports_first_failed_feature(self):
        self.row["bbox_fill_ratio"] = 0.5
        reason = external_rejection_reason(
            self.row,
            {"min_fill_ratio": 0.6, "min_solidity": 0.7},
            predicted_z_m=1.0,
        )
        self.assertEqual(reason, "fill_ratio_gate")


if __name__ == "__main__":
    unittest.main()
