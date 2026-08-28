import csv
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from diagnose_lateral_gate_asymmetry import load_sessions  # noqa: E402
from evaluate_collision_hysteresis_replay import replay_rows, replay_session  # noqa: E402


class CollisionHysteresisReplayTest(unittest.TestCase):
    def test_replay_holds_then_marks_invalid_forward_measurement_unknown(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            session = Path(temporary_dir) / "trial"
            session.mkdir()
            (session / "metadata.json").write_text(
                json.dumps(
                    {
                        "parameters": {
                            "blue_collision_warning_ttc_sec": 4.0,
                            "blue_collision_critical_ttc_sec": 2.0,
                        }
                    }
                )
            )
            fields = [
                "monotonic_time_sec",
                "ttc_sec",
                "path_in_collision_corridor",
                "odom_linear_mps",
                "track_available",
                "track_predicted",
                "measurement_accepted",
                "calibration_valid",
            ]
            with (session / "detections.csv").open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                for index in range(3):
                    writer.writerow(
                        {
                            "monotonic_time_sec": index * 0.1,
                            "ttc_sec": 3.9,
                            "path_in_collision_corridor": 1,
                            "odom_linear_mps": 0.2,
                            "track_available": 1,
                            "track_predicted": 0,
                            "measurement_accepted": 1,
                            "calibration_valid": 1,
                        }
                    )
                writer.writerow(
                    {
                        "monotonic_time_sec": 0.5,
                        "ttc_sec": "",
                        "path_in_collision_corridor": 1,
                        "odom_linear_mps": 0.2,
                        "track_available": 1,
                        "track_predicted": 0,
                        "measurement_accepted": 1,
                        "calibration_valid": 0,
                    }
                )
                writer.writerow(
                    {
                        "monotonic_time_sec": 1.1,
                        "ttc_sec": "",
                        "path_in_collision_corridor": 1,
                        "odom_linear_mps": 0.2,
                        "track_available": 1,
                        "track_predicted": 0,
                        "measurement_accepted": 1,
                        "calibration_valid": 0,
                    }
                )

            result = replay_session(
                session,
                {
                    "blue_collision_warning_exit_ttc_sec": 5.0,
                    "blue_collision_warning_confirm_frames": 3,
                    "blue_collision_warning_clear_frames": 3,
                    "blue_collision_warning_hold_sec": 0.8,
                },
            )

            self.assertEqual(result["raw_warning_frames"], 3)
            self.assertGreaterEqual(result["warning_hold_frames"], 1)
            self.assertEqual(result["unknown_frames"], 1)
            self.assertEqual(result["raw_critical_frames"], 0)
            self.assertEqual(result["filtered_critical_frames"], 0)
            self.assertAlmostEqual(result["first_raw_warning_ttc_sec"], 3.9)
            self.assertEqual(result["path_while_forward_after_warning_frames"], 0)

            archive_path = Path(temporary_dir) / "trial.tar.xz"
            with tarfile.open(archive_path, mode="w:xz") as archive:
                archive.add(session, arcname=session.name)
            label, _source, metadata, rows = load_sessions([archive_path])[0]
            archive_result = replay_rows(
                label,
                metadata,
                rows,
                {
                    "blue_collision_warning_exit_ttc_sec": 5.0,
                    "blue_collision_warning_confirm_frames": 3,
                    "blue_collision_warning_clear_frames": 3,
                    "blue_collision_warning_hold_sec": 0.8,
                },
            )
            self.assertEqual(archive_result, result)


if __name__ == "__main__":
    unittest.main()
