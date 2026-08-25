import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from analyze_hsv_value_thresholds import no_target_decision  # noqa: E402


class HsvValueThresholdTest(unittest.TestCase):
    def test_no_target_control_requires_zero_detection_and_tracking(self):
        self.assertEqual(no_target_decision(0.0, 0.0), "PASS")
        self.assertEqual(no_target_decision(0.01, 0.0), "FAIL")
        self.assertEqual(no_target_decision(0.0, 0.01), "FAIL")


if __name__ == "__main__":
    unittest.main()
