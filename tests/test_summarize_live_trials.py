import csv
import json
import math
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from summarize_live_trials import (  # noqa: E402
    find_session_dirs,
    summarize_inputs,
    summarize_session,
)


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
                "odom_received_count",
                "path_in_collision_corridor",
                "collision_risk_level",
                "collision_ffb_publish_enabled",
                "collision_ffb_publish_success",
                "collision_ffb_reason",
                "collision_ffb_challenge_received_count",
                "collision_ffb_challenge_age_sec",
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
                            "odom_received_count": 10,
                            "path_in_collision_corridor": 1,
                            "collision_risk_level": "PATH",
                            "collision_ffb_publish_enabled": 1,
                            "collision_ffb_publish_success": 1,
                            "collision_ffb_reason": "no_alert",
                            "collision_ffb_challenge_received_count": 20,
                            "collision_ffb_challenge_age_sec": 0.01,
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
                            "odom_received_count": 15,
                            "path_in_collision_corridor": 1,
                            "collision_risk_level": "WARNING",
                            "collision_ffb_publish_enabled": 1,
                            "collision_ffb_publish_success": 0,
                            "collision_ffb_reason": "challenge_unavailable",
                            "collision_ffb_challenge_received_count": 25,
                            "collision_ffb_challenge_age_sec": 0.07,
                        },
                    ]
                )

            summary = summarize_session(session)

            self.assertEqual(summary["experiment_label"], "straight_center_v0p10_r01")
            self.assertEqual(summary["frames"], 2)
            self.assertAlmostEqual(summary["effective_fps"], 10.0)
            self.assertEqual(summary["motion_detection_rate"], 1.0)
            self.assertEqual(summary["motion_measurement_acceptance_rate"], 1.0)
            self.assertEqual(summary["motion_track_rate"], 1.0)
            self.assertAlmostEqual(summary["direction_correct_rate"], 1.0)
            self.assertAlmostEqual(summary["relative_speed_mae_mps"], 0.0)
            self.assertAlmostEqual(summary["ttc_vs_odom_mae_sec"], 0.0)
            self.assertEqual(summary["warning_or_critical_frames"], 1)
            self.assertEqual(summary["warning_hold_rate"], 0.0)
            self.assertEqual(summary["unknown_rate"], 0.0)
            self.assertEqual(summary["odom_callback_count_delta"], 5.0)
            self.assertEqual(summary["challenge_callback_count_delta"], 5.0)
            self.assertAlmostEqual(summary["challenge_age_p95_sec"], 0.067)
            self.assertEqual(summary["challenge_age_max_sec"], 0.07)
            self.assertEqual(summary["ffb_publish_success_rate"], 0.5)
            self.assertEqual(summary["ffb_challenge_unavailable_frames"], 1)
            self.assertEqual(find_session_dirs([Path(temporary_dir)]), [session])

            archive_path = Path(temporary_dir) / "trial.tar.xz"
            with tarfile.open(archive_path, mode="w:xz") as archive:
                archive.add(session, arcname=session.name)
            archive_summary = summarize_inputs([archive_path])
            self.assertEqual(len(archive_summary), 1)
            self.assertEqual(
                archive_summary[0]["experiment_label"],
                "straight_center_v0p10_r01",
            )
            self.assertIn("trial.tar.xz::trial", archive_summary[0]["session_dir"])


if __name__ == "__main__":
    unittest.main()
