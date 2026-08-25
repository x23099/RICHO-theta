import math
import unittest

import cv2
import numpy as np

from evaluate_ground_contact import (
    apply_ground_contact_model,
    fit_lateral_calibration,
    parse_expected_position,
)
from ground_contact import blue_hsv_mask, dual_fisheye_pixels_to_vehicle_rays


PARAMETERS = {
    "camera_height": 0.58,
    "pitch_deg": 1.0,
    "roll_deg": 2.0,
    "yaw_deg": 0.0,
    "radius_scale": 0.86,
    "front_cx_offset": -80.0,
    "front_cy_offset": -21.0,
}


def project_vehicle_ray_to_front_pixel(ray, width=1920, height=960):
    """Forward equation matching the dual-fisheye model in bird_eye.py."""
    yaw, pitch, roll = np.deg2rad(
        [
            PARAMETERS["yaw_deg"],
            PARAMETERS["pitch_deg"],
            PARAMETERS["roll_deg"],
        ]
    )
    rotation_yaw = np.array(
        [
            [math.cos(yaw), 0.0, math.sin(yaw)],
            [0.0, 1.0, 0.0],
            [-math.sin(yaw), 0.0, math.cos(yaw)],
        ]
    )
    rotation_pitch = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(pitch), -math.sin(pitch)],
            [0.0, math.sin(pitch), math.cos(pitch)],
        ]
    )
    rotation_roll = np.array(
        [
            [math.cos(roll), -math.sin(roll), 0.0],
            [math.sin(roll), math.cos(roll), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    vehicle_ray = np.asarray(ray, dtype=np.float64)
    camera_ray = (
        rotation_roll @ rotation_pitch @ rotation_yaw @ vehicle_ray
    )
    camera_ray /= np.linalg.norm(camera_ray)
    lens_x, lens_y, lens_z = camera_ray
    theta = math.acos(float(lens_z))
    sin_theta = math.sin(theta)
    radius = min(width / 4.0, height / 2.0) * PARAMETERS["radius_scale"]
    center_x = width * 0.3125 + PARAMETERS["front_cx_offset"]
    center_y = height / 2.0 + PARAMETERS["front_cy_offset"]
    radial = radius * theta / (math.pi / 2.0)
    return np.array(
        [
            center_x + radial * lens_x / sin_theta,
            center_y - radial * lens_y / sin_theta,
        ]
    )


class GroundContactGeometryTest(unittest.TestCase):
    def test_blue_hsv_value_threshold_is_configurable(self):
        hsv = np.array([[[110, 200, 25], [110, 200, 35]]], dtype=np.uint8)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        default_mask = blue_hsv_mask(frame, {})
        lowered_mask = blue_hsv_mask(
            frame, {"blue_ground_contact_hsv_v_min": 20}
        )

        self.assertEqual(default_mask.tolist(), [[0, 255]])
        self.assertEqual(lowered_mask.tolist(), [[255, 255]])

    def test_front_pixel_round_trip_recovers_vehicle_ray(self):
        original = np.array([0.22, -PARAMETERS["camera_height"], 1.20])
        original /= np.linalg.norm(original)
        pixel = project_vehicle_ray_to_front_pixel(original)

        valid_pixels, recovered = dual_fisheye_pixels_to_vehicle_rays(
            pixel.reshape(1, 2), 1920, 960, PARAMETERS
        )

        self.assertEqual(len(valid_pixels), 1)
        np.testing.assert_allclose(recovered[0], original, atol=1e-9)

    def test_ray_floor_intersection_recovers_metric_ground_point(self):
        expected_x = -0.22
        expected_z = 0.95
        original = np.array(
            [expected_x, -PARAMETERS["camera_height"], expected_z]
        )
        pixel = project_vehicle_ray_to_front_pixel(original)
        _, recovered = dual_fisheye_pixels_to_vehicle_rays(
            pixel.reshape(1, 2), 1920, 960, PARAMETERS
        )
        scale = -PARAMETERS["camera_height"] / recovered[0, 1]

        self.assertAlmostEqual(scale * recovered[0, 0], expected_x, places=9)
        self.assertAlmostEqual(scale * recovered[0, 2], expected_z, places=9)


class HeadlessEvaluationTest(unittest.TestCase):
    def test_parse_expected_position(self):
        self.assertEqual(
            parse_expected_position("holdout_xm0.22_z1.20_2"), (-0.22, 1.20)
        )
        self.assertEqual(
            parse_expected_position("cal_xp0.15_z0.80"), (0.15, 0.80)
        )
        self.assertIsNone(parse_expected_position("20260807_170000"))

    def test_lateral_fit_does_not_modify_geometric_z(self):
        calibration = [
            {"raw_x_m": -0.4, "raw_z_m": 0.8, "expected_x_m": -0.2},
            {"raw_x_m": 0.0, "raw_z_m": 1.0, "expected_x_m": 0.0},
            {"raw_x_m": 0.4, "raw_z_m": 1.2, "expected_x_m": 0.2},
        ]
        coefficients = fit_lateral_calibration(calibration)
        row = {
            "raw_x_m": 0.3,
            "raw_z_m": 1.17,
            "expected_x_m": 0.15,
            "expected_z_m": 1.20,
        }

        evaluated = apply_ground_contact_model([row], coefficients)[0]

        self.assertAlmostEqual(evaluated["estimated_x_m"], 0.15, places=9)
        self.assertEqual(evaluated["estimated_z_m"], 1.17)


if __name__ == "__main__":
    unittest.main()
