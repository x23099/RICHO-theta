import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from compare_area_normalization_replays import decide  # noqa: E402


class AreaNormalizationReplayTest(unittest.TestCase):
    def test_decision_uses_predeclared_combined_gate_limits(self):
        summary = {
            "stable_inlier_acceptance_rate": 0.98,
            "outlier_rejection_rate": 0.95,
            "max_abs_vz_mps": 0.30,
            "occlusion_events": 2,
            "events_track_expired": 2,
            "events_reacquired": 2,
        }
        self.assertEqual(decide(summary), "PASS")
        summary["stable_inlier_acceptance_rate"] = 0.979
        self.assertEqual(decide(summary), "FAIL")

    def test_missing_outliers_are_allowed_for_clean_recordings(self):
        summary = {
            "stable_inlier_acceptance_rate": 1.0,
            "outlier_rejection_rate": math.nan,
            "max_abs_vz_mps": 0.01,
            "occlusion_events": 0,
            "events_track_expired": 0,
            "events_reacquired": 0,
        }
        self.assertEqual(decide(summary), "PASS")


if __name__ == "__main__":
    unittest.main()
