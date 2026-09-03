import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analyze_ttc_velocity_sources import replace_velocity_source


def row(visual_vz="-0.1", odom="0.2", available="1", track="1", z="1.0"):
    return {
        "smoothed_vz_mps": visual_vz,
        "relative_vz_mps": visual_vz,
        "odom_linear_mps": odom,
        "odom_available": available,
        "track_available": track,
        "filtered_z_m": z,
        "ttc_sec": "10.0",
    }


class TtcVelocitySourceTests(unittest.TestCase):
    def test_visual_is_unchanged(self):
        source = row()
        result = replace_velocity_source([source], "visual", 0.03)[0]
        self.assertEqual(result, source)
        self.assertIsNot(result, source)

    def test_static_odom_uses_negative_ego_speed(self):
        result = replace_velocity_source([row()], "odom_static", 0.03)[0]
        self.assertAlmostEqual(float(result["smoothed_vz_mps"]), -0.2)
        self.assertAlmostEqual(float(result["relative_vz_mps"]), -0.1)
        self.assertAlmostEqual(float(result["ttc_sec"]), 5.0)

    def test_conservative_selects_faster_closing_source(self):
        visual_dominates = replace_velocity_source(
            [row(visual_vz="-0.3")], "conservative", 0.03
        )[0]
        odom_dominates = replace_velocity_source(
            [row(visual_vz="-0.1")], "conservative", 0.03
        )[0]
        self.assertAlmostEqual(float(visual_dominates["smoothed_vz_mps"]), -0.3)
        self.assertAlmostEqual(float(odom_dominates["smoothed_vz_mps"]), -0.2)

    def test_missing_odom_preserves_visual_result(self):
        source = row(available="0")
        result = replace_velocity_source([source], "odom_static", 0.03)[0]
        self.assertEqual(result, source)

    def test_deadband_clears_ttc(self):
        result = replace_velocity_source(
            [row(odom="0.02")], "odom_static", 0.03
        )[0]
        self.assertEqual(result["ttc_sec"], "")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            replace_velocity_source([row()], "unknown", 0.03)


if __name__ == "__main__":
    unittest.main()
