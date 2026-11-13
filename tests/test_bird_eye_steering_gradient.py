import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from bird_eye import (  # noqa: E402
    CalibrationWindow,
    remap_command_angular,
)
from collision_ffb_publisher import FFB_RECORDING_FIELDS  # noqa: E402
from collision_risk import SteeringGradientFilter  # noqa: E402


def gradient_params(**overrides):
    params = {
        "car_width": 0.354,
        "blue_collision_safety_margin_m": 0.10,
        "collision_ffb_direction_enabled": 1,
        "collision_ffb_gradient_delta_radps": 0.15,
        "collision_ffb_gradient_g_scale": 1.0,
        # alpha=1 makes the wiring test independent of the EMA transient.
        "collision_ffb_gradient_ema_alpha": 1.0,
        "collision_ffb_gradient_deadband": 0.1,
        "collision_ffb_gradient_prediction_time_sec": 3.5,
        "collision_ffb_gradient_step_sec": 0.05,
    }
    params.update(overrides)
    return params


def make_window(**overrides):
    window = CalibrationWindow.__new__(CalibrationWindow)
    window.params = gradient_params(**overrides)
    window.last_blue_track = {"z_m": 1.0, "x_m": -0.30}
    window.last_prediction_speed_mps = 0.2
    window.last_prediction_angular_radps = 0.0
    window.cmd_angular_z = 0.0
    window.steering_gradient_filter = SteeringGradientFilter(
        ema_alpha=window.params["collision_ffb_gradient_ema_alpha"],
        deadband=window.params["collision_ffb_gradient_deadband"],
    )
    window.last_steering_gradient = None
    window._last_steering_gradient_error = ""
    return window


class _FakePublisher:
    def __init__(self):
        self.calls = []

    def publish_risk(
        self,
        risk_level,
        *,
        measurement_valid=None,
        direction=0,
    ):
        self.calls.append((risk_level, measurement_valid, direction))
        return {
            "collision_ffb_sequence": 1,
            "collision_ffb_publish_enabled": 1,
            "collision_ffb_publish_success": 1,
            "collision_ffb_risk_level": risk_level,
            "collision_ffb_active": 1,
            "collision_ffb_requested_magnitude": 0.25,
            "collision_ffb_pattern": "steady",
            "collision_ffb_direction": direction,
            "collision_ffb_reason": "test",
            "collision_ffb_publish_error": "",
        }


class SteeringGradientWiringTest(unittest.TestCase):
    def test_left_obstacle_produces_left_danger(self):
        window = make_window()

        result = window.update_steering_gradient("WARNING", True)

        self.assertIsNotNone(result)
        self.assertGreater(result["gradient_raw"], 0.0)
        self.assertGreater(result["gradient_filtered"], 0.0)
        self.assertEqual(result["direction"], -1)
        self.assertIs(window.last_steering_gradient, result)

    def test_right_obstacle_produces_right_danger(self):
        window = make_window()
        window.last_blue_track = {"z_m": 1.0, "x_m": 0.30}

        result = window.update_steering_gradient("WARNING", True)

        self.assertLess(result["gradient_raw"], 0.0)
        self.assertLess(result["gradient_filtered"], 0.0)
        self.assertEqual(result["direction"], 1)

    def test_direction_disabled_resets_state(self):
        window = make_window(collision_ffb_direction_enabled=0)
        window.steering_gradient_filter.value = 0.5

        result = window.update_steering_gradient("WARNING", True)

        self.assertIsNone(result)
        self.assertIsNone(window.last_steering_gradient)
        self.assertEqual(window.steering_gradient_filter.value, 0.0)

    def test_missing_track_resets_state(self):
        window = make_window()
        window.last_blue_track = None

        result = window.update_steering_gradient("WARNING", True)

        self.assertIsNone(result)
        self.assertIsNone(window.last_steering_gradient)

    def test_invalid_measurement_resets_filter(self):
        window = make_window()
        window.update_steering_gradient("WARNING", True)

        result = window.update_steering_gradient("WARNING", False)

        self.assertEqual(result["gradient_filtered"], 0.0)
        self.assertEqual(result["direction"], 0)

    def test_clear_risk_level_suppresses_gradient(self):
        window = make_window()

        result = window.update_steering_gradient("CLEAR", True)

        self.assertEqual(result["gradient_raw"], 0.0)
        self.assertEqual(result["direction"], 0)

    def test_remap_command_angular_matches_display_formula(self):
        target_yaw_deg = 90.0 * ((0.55 / 0.8) ** (1.0 / 0.60))
        target_yaw_rad = math.radians(min(360.0, target_yaw_deg))
        expected = (target_yaw_rad / 3.5) * (0.2 / 0.8)

        self.assertAlmostEqual(
            remap_command_angular(0.2, 0.55, 3.5),
            expected,
        )
        self.assertAlmostEqual(
            remap_command_angular(0.2, -0.55, 3.5),
            -expected,
        )
        self.assertEqual(remap_command_angular(0.2, 0.0, 3.5), 0.0)

    def test_predict_path_points_uses_shared_remap(self):
        obj = SimpleNamespace(
            odometry_is_recent=lambda: True,
            odom_linear_x=0.2,
            odom_angular_z=0.0,
            cmd_linear_x=0.2,
            cmd_angular_z=0.55,
            prediction_min_speed=0.01,
            prediction_angular_deadband=0.005,
        )

        points = CalibrationWindow.predict_path_points(obj)

        self.assertGreater(len(points), 1)
        self.assertAlmostEqual(
            obj.last_prediction_angular_radps,
            remap_command_angular(0.2, 0.55, 3.5),
        )


class PublishGradientRecordTest(unittest.TestCase):
    def test_publish_passes_direction_and_records_gradient(self):
        window = CalibrationWindow.__new__(CalibrationWindow)
        publisher = _FakePublisher()
        window.collision_ffb_publisher = publisher
        window.last_blue_collision = {
            "risk_level": "WARNING",
            "measurement_valid": True,
        }
        window.last_steering_gradient = {
            "gradient_raw": 0.65,
            "gradient_normalized": 0.65,
            "gradient_filtered": 0.6,
            "direction": -1,
            "reason": "ok",
        }

        record = window.publish_collision_ffb()

        self.assertEqual(publisher.calls, [("WARNING", True, -1)])
        self.assertEqual(record["collision_ffb_direction"], -1)
        self.assertEqual(record["collision_ffb_gradient_raw"], 0.65)
        self.assertEqual(
            record["collision_ffb_gradient_normalized"], 0.65
        )
        self.assertEqual(record["collision_ffb_gradient_filtered"], 0.6)
        self.assertEqual(record["collision_ffb_gradient_reason"], "ok")

    def test_publish_without_gradient_uses_zero_direction(self):
        window = CalibrationWindow.__new__(CalibrationWindow)
        publisher = _FakePublisher()
        window.collision_ffb_publisher = publisher
        window.last_blue_collision = {
            "risk_level": "WARNING",
            "measurement_valid": True,
        }

        record = window.publish_collision_ffb()

        self.assertEqual(publisher.calls, [("WARNING", True, 0)])
        self.assertEqual(record["collision_ffb_direction"], 0)

    def test_publish_without_publisher_records_gradient(self):
        window = CalibrationWindow.__new__(CalibrationWindow)
        window.collision_ffb_publisher = None
        window.last_blue_collision = {
            "risk_level": "WARNING",
            "measurement_valid": True,
        }
        window.last_steering_gradient = {
            "gradient_raw": -0.4,
            "gradient_normalized": -0.4,
            "gradient_filtered": -0.3,
            "direction": 1,
            "reason": "ok",
        }

        record = window.publish_collision_ffb()

        self.assertEqual(record["collision_ffb_publish_enabled"], 0)
        self.assertEqual(record["collision_ffb_direction"], 1)
        self.assertEqual(record["collision_ffb_gradient_raw"], -0.4)
        self.assertEqual(record["collision_ffb_gradient_filtered"], -0.3)

    def test_recording_fields_include_gradient_columns(self):
        for field in (
            "collision_ffb_direction",
            "collision_ffb_gradient_raw",
            "collision_ffb_gradient_normalized",
            "collision_ffb_gradient_filtered",
            "collision_ffb_gradient_reason",
        ):
            self.assertIn(field, FFB_RECORDING_FIELDS)


if __name__ == "__main__":
    unittest.main()
