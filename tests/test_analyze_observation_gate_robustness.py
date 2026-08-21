import math
import unittest

from analyze_observation_gate_robustness import (
    live_area_acceptance_rates,
    threshold_decision,
)


class ObservationGateRobustnessTest(unittest.TestCase):
    def test_live_area_rate_uses_detected_finite_values_only(self):
        sessions = [
            (
                "left",
                "source",
                {},
                [
                    {"detected": "1", "normalized_area": "1999"},
                    {"detected": "true", "normalized_area": "2000"},
                    {"detected": "yes", "normalized_area": "2100"},
                    {"detected": "0", "normalized_area": "9999"},
                    {"detected": "1", "normalized_area": "nan"},
                ],
            )
        ]
        self.assertEqual(live_area_acceptance_rates(sessions, 2000), [("left", 2 / 3)])

    def test_decision_fails_closed_on_live_lateral_rejection(self):
        row = {
            "live_min_area_acceptance_rate": 0.97,
            "stable_inlier_min_acceptance_rate": 0.99,
            "outlier_min_rejection_rate": 1.0,
            "max_abs_vz_mps": 0.20,
            "occlusion_events": 2,
            "events_track_expired": 2,
            "events_reacquired": 2,
        }
        self.assertEqual(threshold_decision(row), "FAIL")
        row["live_min_area_acceptance_rate"] = 0.98
        self.assertEqual(threshold_decision(row), "PASS")

    def test_missing_outliers_do_not_fail_otherwise_complete_trial(self):
        row = {
            "live_min_area_acceptance_rate": 1.0,
            "stable_inlier_min_acceptance_rate": 1.0,
            "outlier_min_rejection_rate": math.nan,
            "max_abs_vz_mps": 0.10,
            "occlusion_events": 1,
            "events_track_expired": 1,
            "events_reacquired": 1,
        }
        self.assertEqual(threshold_decision(row), "PASS")


if __name__ == "__main__":
    unittest.main()
