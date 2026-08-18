import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from summarize_live_trials import find_session_dirs, summarize_session  # noqa: E402


class LiveTrialSummaryTest(unittest.TestCase):
    def test_summarizes_monotonic_odom_ttc_and_collision_fields(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            session = Path(temporary_dir) / "trial"
            session.mkdir()
            (session / "metadata.json").write_text(
                json.dumps({"experiment_label": "straight_center_v0p10_r01"})
            )
            fields = [
                "monotonic_time_sec",
                "detected",
                "measurement_accepted",
                "track_available",
                "filtered_z_m",
                "smoothed_vz_mps",
                "ttc_sec",
                "odom_available",
                "odom_linear_mps",
                "path_in_collision_corridor",
                "collision_risk_level",
            ]
            with (session / "detections.csv").open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "monotonic_time_sec": 0.0,
                            "detected": 1,
                            "measurement_accepted": 1,
                            "track_available": 1,
                            "filtered_z_m": 1.0,
                            "smoothed_vz_mps": -0.1,
                            "ttc_sec": 10.0,
                            "odom_available": 1,
                            "odom_linear_mps": 0.1,
                            "path_in_collision_corridor": 1,
                            "collision_risk_level": "PATH",
                        },
                        {
                            "monotonic_time_sec": 0.1,
                            "detected": 1,
                            "measurement_accepted": 1,
                            "track_available": 1,
                            "filtered_z_m": 0.99,
                            "smoothed_vz_mps": -0.1,
                            "ttc_sec": 9.9,
                            "odom_available": 1,
                            "odom_linear_mps": 0.1,
                            "path_in_collision_corridor": 1,
                            "collision_risk_level": "WARNING",
                        },
                    ]
                )

            summary = summarize_session(session)

            self.assertEqual(summary["experiment_label"], "straight_center_v0p10_r01")
            self.assertEqual(summary["frames"], 2)
            self.assertAlmostEqual(summary["effective_fps"], 10.0)
            self.assertAlmostEqual(summary["direction_correct_rate"], 1.0)
            self.assertAlmostEqual(summary["relative_speed_mae_mps"], 0.0)
            self.assertAlmostEqual(summary["ttc_vs_odom_mae_sec"], 0.0)
            self.assertEqual(summary["warning_or_critical_frames"], 1)
            self.assertEqual(summary["warning_hold_rate"], 0.0)
            self.assertEqual(summary["unknown_rate"], 0.0)
            self.assertEqual(find_session_dirs([Path(temporary_dir)]), [session])


if __name__ == "__main__":
    unittest.main()
