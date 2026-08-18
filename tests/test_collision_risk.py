import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from collision_risk import (  # noqa: E402
    CollisionRiskHysteresis,
    assess_path_collision,
    classify_candidate_risk,
    predict_unicycle_path,
)


class CollisionRiskTest(unittest.TestCase):
    def test_straight_path_separates_center_and_side_obstacles(self):
        path = predict_unicycle_path(0.1, 0.0)

        center = assess_path_collision(path, 1.0, 0.0, 0.354, 0.10)
        side = assess_path_collision(path, 1.0, 0.40, 0.354, 0.10)

        self.assertTrue(center["in_collision_corridor"])
        self.assertFalse(side["in_collision_corridor"])
        self.assertAlmostEqual(center["path_distance_m"], 1.0, places=2)

    def test_turning_path_selects_obstacle_on_inside_curve(self):
        path = predict_unicycle_path(
            0.2,
            math.radians(20.0),
            prediction_time_sec=4.0,
            min_distance_m=0.0,
        )
        path_midpoint = path[len(path) // 2]

        on_path = assess_path_collision(
            path,
            path_midpoint[0],
            path_midpoint[1],
            0.354,
            0.05,
        )
        mirrored = assess_path_collision(
            path,
            path_midpoint[0],
            -path_midpoint[1] - 0.4,
            0.354,
            0.05,
        )

        self.assertTrue(on_path["in_collision_corridor"])
        self.assertFalse(mirrored["in_collision_corridor"])

    def test_risk_requires_both_path_overlap_and_short_ttc(self):
        self.assertEqual(classify_candidate_risk(False, 1.0), "CLEAR")
        self.assertEqual(classify_candidate_risk(True, None), "PATH")
        self.assertEqual(classify_candidate_risk(True, 3.0), "WARNING")
        self.assertEqual(classify_candidate_risk(True, 1.5), "CRITICAL")

    def test_warning_requires_confirmation_and_uses_ttc_exit_hysteresis(self):
        hysteresis = CollisionRiskHysteresis(
            warning_confirm_frames=3,
            warning_clear_frames=2,
        )

        first = hysteresis.update("WARNING", 0.0, True, True, True, 3.9)
        second = hysteresis.update("WARNING", 0.1, True, True, True, 3.9)
        entered = hysteresis.update("WARNING", 0.2, True, True, True, 3.9)
        between = hysteresis.update("PATH", 0.3, True, True, True, 4.5)
        clearing = hysteresis.update("PATH", 0.4, True, True, True, 5.1)
        cleared = hysteresis.update("PATH", 0.5, True, True, True, 5.1)

        self.assertEqual(first["risk_level"], "PATH")
        self.assertEqual(second["risk_level"], "PATH")
        self.assertEqual(entered["risk_level"], "WARNING")
        self.assertEqual(between["risk_level"], "WARNING")
        self.assertEqual(clearing["risk_level"], "WARNING")
        self.assertEqual(cleared["risk_level"], "PATH")

    def test_invalid_measurement_has_finite_hold_then_unknown(self):
        hysteresis = CollisionRiskHysteresis(
            warning_confirm_frames=1,
            warning_hold_sec=0.8,
        )
        entered = hysteresis.update("WARNING", 1.0, True, True, True, 3.9)
        held = hysteresis.update("PATH", 1.5, False, True, True, None)
        expired = hysteresis.update("PATH", 1.9, False, True, True, None)

        self.assertEqual(entered["risk_level"], "WARNING")
        self.assertEqual(held["risk_level"], "WARNING_HOLD")
        self.assertEqual(expired["risk_level"], "UNKNOWN")
        self.assertAlmostEqual(expired["hold_age_sec"], 0.9)

    def test_false_warning_is_not_latched_forever(self):
        hysteresis = CollisionRiskHysteresis(
            warning_confirm_frames=1,
            warning_clear_frames=2,
            warning_hold_sec=0.2,
        )
        hysteresis.update("WARNING", 0.0, True, True, True, 3.0)
        hysteresis.update("PATH", 0.3, False, True, True, None)
        unknown = hysteresis.update("PATH", 1.0, False, True, True, None)
        first_clear = hysteresis.update("CLEAR", 1.1, True, True, False, None)
        cleared = hysteresis.update("CLEAR", 1.2, True, True, False, None)

        self.assertEqual(unknown["risk_level"], "UNKNOWN")
        self.assertEqual(first_clear["risk_level"], "UNKNOWN")
        self.assertEqual(cleared["risk_level"], "CLEAR")

    def test_missing_ttc_does_not_clear_alert_while_ego_moves(self):
        hysteresis = CollisionRiskHysteresis(
            warning_confirm_frames=1,
            warning_clear_frames=2,
            warning_hold_sec=0.2,
        )
        hysteresis.update("WARNING", 0.0, True, True, True, 3.0)
        held = hysteresis.update("PATH", 0.1, True, True, True, None)
        unknown = hysteresis.update("PATH", 0.3, True, True, True, None)

        self.assertEqual(held["risk_level"], "WARNING_HOLD")
        self.assertEqual(unknown["risk_level"], "UNKNOWN")

    def test_valid_critical_bypasses_warning_confirmation(self):
        hysteresis = CollisionRiskHysteresis(warning_confirm_frames=5)

        result = hysteresis.update("CRITICAL", 0.0, True, True, True, 1.5)

        self.assertEqual(result["risk_level"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
