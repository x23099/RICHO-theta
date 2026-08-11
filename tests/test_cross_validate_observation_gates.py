import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from cross_validate_observation_gates import (  # noqa: E402
    decide,
    fit_normalized_area_threshold,
)


class ObservationGateCrossValidationTest(unittest.TestCase):
    @staticmethod
    def _rows(session, area, z):
        return [
            {
                "session": session,
                "detected": True,
                "phase_label": "visible",
                "x_m": 0.0,
                "z_m": z,
                "area_px": area,
            }
            for _ in range(10)
        ]

    def test_threshold_uses_most_conservative_training_session(self):
        threshold = fit_normalized_area_threshold(
            {
                "near": self._rows("near", 4000.0, 1.0),
                "far": self._rows("far", 2000.0, 2.0),
            },
            safety_factor=0.75,
        )
        self.assertAlmostEqual(threshold, 3000.0)

    def test_decision_requires_all_predeclared_limits(self):
        summary = {
            "stable_inlier_acceptance_rate": 0.99,
            "outlier_rejection_rate": 0.96,
            "max_abs_vz_mps": 0.29,
            "events_track_expired": 2,
            "events_reacquired": 2,
            "occlusion_events": 2,
        }
        self.assertEqual(decide(summary), "PASS")
        summary["max_abs_vz_mps"] = 0.31
        self.assertEqual(decide(summary), "FAIL")


if __name__ == "__main__":
    unittest.main()
