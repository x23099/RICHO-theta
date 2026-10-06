import csv
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate_raw_velocity_confidence_replay import (
    OfflineBluePipeline, live_observation, main, predicted_motion, replay_session, validate_rows,
)
from evaluate_velocity_confidence_replay import evaluate_rows


def motion(i=0, **extra):
    return dict(frame=i + 1, time_sec=i / 30, monotonic_time_sec=i / 30,
                odom_available=1, odom_linear_mps=.2, odom_angular_radps=0,
                cmd_linear_mps=0, cmd_angular_radps=0, **extra)


def params(**extra):
    return dict(blue_ground_contact_x_scale=1, blue_ground_contact_x_offset_m=0,
                blue_observation_normalized_area_min=100, blue_ttc_deadband_mps=.03,
                blue_ttc_velocity_source="conservative", **extra)


class RawVelocityReplayTests(unittest.TestCase):
    def test_strict_frame_and_time_alignment(self):
        rows = [motion(i) for i in range(3)]
        validate_rows(rows)
        for key, value in [("frame", 7), ("monotonic_time_sec", 0), ("odom_linear_mps", "nan"), ("cmd_angular_radps", "")]:
            invalid = [dict(r) for r in rows]
            invalid[1][key] = value
            with self.assertRaises(ValueError):
                validate_rows(invalid)

    def test_empty_alignment_rejected(self):
        with self.assertRaises(ValueError):
            validate_rows([])

    def test_motion_matches_camera_prediction_method(self):
        # Invoke only the pure path method on a stub; no Qt object or ROS bridge.
        from bird_eye import CalibrationWindow
        for v, w, cv, cw, recent in [(.2, 0, 0, 0, True), (.2, .02, 0, 0, True),
                                     (0, 0, .2, .55, True), (.2, 0, 0, .55, True),
                                     (0, 0, 0, 0, True), (.2, .02, .1, -.55, False)]:
            r = motion()
            r.update(odom_linear_mps=v, odom_angular_radps=w, cmd_linear_mps=cv, cmd_angular_radps=cw, odom_available=int(recent))
            obj = SimpleNamespace(odometry_is_recent=lambda: recent, odom_linear_x=v, odom_angular_z=w,
                                  cmd_linear_x=cv, cmd_angular_z=cw, prediction_min_speed=.01, prediction_angular_deadband=.005)
            expected = CalibrationWindow.predict_path_points(obj)
            pv, pw, source, actual = predicted_motion(r)
            self.assertEqual(actual, expected)
            self.assertEqual(pv, obj.last_prediction_speed_mps)
            self.assertEqual(pw, obj.last_prediction_angular_radps)
            self.assertEqual(source, obj.last_prediction_source)

    def test_calibration_limits_and_offsets(self):
        processor = OfflineBluePipeline(params(blue_ground_contact_z_offset_m=.1))
        for x, z, valid in [(0, .55, True), (.5, 1.25, True), (.501, 1, False), (0, .54, False), (0, 1.26, False)]:
            self.assertEqual(processor.calibrate_contact(dict(x_m=x, z_m=z, area_px=1000))["calibration_valid"], valid)

    def test_confirmation_and_calibration_rejection(self):
        processor = OfflineBluePipeline(params())
        contact = dict(x_m=0, z_m=1, area_px=1000)
        a = processor.update_observation(processor.calibrate_contact(contact), motion(0))
        b = processor.update_observation(processor.calibrate_contact(contact), motion(1))
        self.assertEqual(a["rejection_reason"], "reacquisition_confirmation")
        self.assertEqual(b["rejection_reason"], "initialized")
        self.assertEqual(b["measurement_accepted"], 1)
        contact["z_m"] = 1.5
        c = processor.update_observation(processor.calibrate_contact(contact), motion(2))
        self.assertEqual(c["rejection_reason"], "calibration_range_gate")
        self.assertEqual(c["track_predicted"], 1)

    def test_path_and_ttc_recomputed_not_copied_from_log(self):
        processor = OfflineBluePipeline(params())
        for i in range(4):
            r = motion(i)
            r.update(ttc_sec=.01, path_in_collision_corridor=0, relative_vz_mps=-100)
            row = processor.update_observation(dict(x_m=0, z_m=1, area_px=1000, raw_distance_m=1, calibration_valid=True), r)
        self.assertEqual(row["path_in_collision_corridor"], 1)
        self.assertAlmostEqual(row["ttc_sec"], 5)
        self.assertAlmostEqual(row["relative_vz_mps"], 0)
        self.assertEqual(row["ttc_velocity_source"], "conservative_odom")
        self.assertEqual(row["cmd_linear_mps"], 0)
        self.assertEqual(row["prediction_linear_mps"], .2)

    def test_nis_gate_rejects_jump_inside_calibration_range(self):
        processor = OfflineBluePipeline(params())
        for i in range(20):
            processor.update_observation(dict(x_m=0, z_m=1, area_px=1000, raw_distance_m=1, calibration_valid=True), motion(i))
        row = processor.update_observation(dict(x_m=0, z_m=1.3, area_px=1000, raw_distance_m=1.3, calibration_valid=True), motion(20))
        self.assertEqual(row["calibration_valid"], 1)
        self.assertEqual(row["measurement_accepted"], 0)
        self.assertGreater(row["observation_nis"], 9.21)
        self.assertEqual(row["track_predicted"], 1)

    def test_command_fallback_motion_used_by_state_filter(self):
        rows = [{"frame": 1, "time_sec": 0, "track_available": 1, "track_predicted": 1,
                 "measurement_accepted": 0, "calibration_valid": 0, "path_in_collision_corridor": 1,
                 "odom_available": 1, "odom_linear_mps": 0, "prediction_linear_mps": .2}]
        _, result = evaluate_rows("cmd_fallback", {}, rows, candidate=False)
        self.assertEqual(result[0]["risk"], "UNKNOWN")

    def test_live_measurement_control_requires_complete_observations(self):
        self.assertIsNone(live_observation(dict(detected=0)))
        with self.assertRaises(ValueError):
            live_observation(dict(detected=1))

    def test_disabled_or_other_detector_explicitly_rejected(self):
        for settings in [dict(blue_position_method="bev"), dict(blue_tracking_enabled=0), dict(detect_blue_obstacle=0)]:
            with self.assertRaises(ValueError):
                OfflineBluePipeline(params(**settings))

    def test_cli_does_not_silently_skip_an_input_without_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(sys, "argv", ["replay", "--input", str(root), "--output-dir", str(root / "output")]), \
                 patch("sys.stderr"):
                with self.assertRaises(SystemExit) as error:
                    main()
            self.assertEqual(error.exception.code, 2)
            self.assertFalse((root / "output").exists())

    def test_video_frame_count_and_dimensions_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "metadata.json").write_text(json.dumps(dict(parameters=params(), requested_camera_height=60, requested_camera_width=80)))
            with (root / "detections.csv").open("w", newline="") as f:
                rows = [motion(i, detected=0) for i in range(2)]
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            for length, shape, expected_error in [(2, (60, 80, 3), None), (1, (60, 80, 3), "shorter"),
                                                   (3, (60, 80, 3), "longer"), (2, (61, 80, 3), "dimensions")]:
                video = unittest.mock.Mock()
                video.isOpened.return_value = True
                video.read.side_effect = [(True, np.zeros(shape, np.uint8)) for _ in range(length)] + [(False, None)]
                with patch("evaluate_raw_velocity_confidence_replay.cv2.VideoCapture", return_value=video), \
                     patch("evaluate_raw_velocity_confidence_replay.detect_blue_ground_contact", return_value=(None, None)):
                    if expected_error:
                        with self.assertRaisesRegex(ValueError, expected_error):
                            replay_session(root)
                    else:
                        _, _, control, raw = replay_session(root)
                        self.assertEqual(control, raw)
                video.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
