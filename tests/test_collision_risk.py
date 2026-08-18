import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from collision_risk import (  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
