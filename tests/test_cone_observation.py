"""Synthetic projection checks. Not real-cone range/recognition validation."""
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cone_observation import CAMERA_KEYS, ConeGroundProjector, checked_bbox


PARAMETERS = dict(camera_height=.58, pitch_deg=0, roll_deg=0, yaw_deg=0,
                  radius_scale=.86, front_cx_offset=-80, front_cy_offset=-21,
                  back_cx_offset=82, back_cy_offset=-18)


def detection(box=(300, 340, 340, 430), **changes):
    row = dict(class_id=0, confidence=.8,
               **dict(zip(("x1", "y1", "x2", "y2"), box)))
    return dict(row, **changes)


class ConeObservationTest(unittest.TestCase):
    def projector(self, parameters=None, **kwargs):
        return ConeGroundProjector(parameters or PARAMETERS, width=1280, height=720,
                                   front_lens=kwargs.pop("front_lens", "left"), **kwargs)

    def project(self, row=None, projector=None, **kwargs):
        return (projector or self.projector()).project(
            row or detection(), frame_width=kwargs.get("width", 1280),
            frame_height=kwargs.get("height", 720))

    def test_bottom_centre_matches_analytic_floor_geometry(self):
        result = self.project()
        theta = (430-339)/(320*.86)*math.pi/2
        self.assertTrue(result["projection_candidate"])
        self.assertAlmostEqual(result["x_m"], 0)
        self.assertAlmostEqual(result["z_m"], .58/math.tan(theta))
        self.assertEqual((result["pixel_x"], result["pixel_y"]), (320, 430))

    def test_candidates_are_never_verified_or_ffb_eligible(self):
        for row in (detection(), detection((900, 340, 940, 430)),
                    detection(confidence=float("nan"))):
            result = self.project(row)
            self.assertFalse(result["floor_contact_verified"])
            self.assertFalse(result["usable_for_ffb"])

    def test_blue_and_bev_corrections_are_not_used(self):
        parameters = dict(PARAMETERS, blue_ground_contact_x_scale=30,
                          blue_ground_contact_x_offset_m=900,
                          blue_ground_contact_z_offset_m=-900,
                          blue_calibration_z_scale=50, car_offset_x=100, car_offset_z=200)
        self.assertEqual(self.project(), self.project(projector=self.projector(parameters)))

    def test_positive_x_is_right_and_z_forward(self):
        left = self.project(detection((260, 340, 300, 430)))
        right = self.project(detection((340, 340, 380, 430)))
        self.assertLess(left["x_m"], 0)
        self.assertGreater(right["x_m"], 0)
        self.assertAlmostEqual(left["z_m"], right["z_m"])

    def test_tilted_camera_round_trip_uses_existing_rotation_convention(self):
        parameters = dict(PARAMETERS, yaw_deg=3, pitch_deg=1, roll_deg=2)
        yaw, pitch, roll = np.deg2rad([3, 1, 2])
        ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0],
                       [-math.sin(yaw), 0, math.cos(yaw)]])
        rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)],
                       [0, math.sin(pitch), math.cos(pitch)]])
        rz = np.array([[math.cos(roll), -math.sin(roll), 0],
                       [math.sin(roll), math.cos(roll), 0], [0, 0, 1]])
        camera = rz @ rx @ ry @ np.array([.3, -.58, 1.3])
        camera /= np.linalg.norm(camera)
        theta = math.acos(camera[2])
        rho = 320*.86*theta/(math.pi/2)
        x, y = 320+rho*camera[0]/math.sin(theta), 339-rho*camera[1]/math.sin(theta)
        result = self.project(detection((x-10, y-40, x+10, y)), self.projector(parameters))
        self.assertTrue(result["projection_candidate"])
        self.assertAlmostEqual(result["x_m"], .3)
        self.assertAlmostEqual(result["z_m"], 1.3)

    def test_image_edge_truncation_is_rejected(self):
        result = self.project(detection((0, 340, 640, 430)))
        self.assertEqual(result["reason"], "image_edge_truncation")

    def test_right_image_can_be_explicit_front(self):
        p = self.projector(front_lens="right")
        result = self.project(detection((780, 340, 820, 430)), p)
        self.assertTrue(result["projection_candidate"])
        self.assertAlmostEqual(result["x_m"], 0)

    def test_rear_and_gap_are_not_front(self):
        for box in ((900, 340, 940, 430), (620, 340, 660, 430)):
            self.assertEqual(self.project(detection(box))["reason"], "outside_front_lens")

    def test_horizon_and_upward_are_rejected(self):
        for box in ((300, 250, 340, 300), (300, 280, 340, 339)):
            self.assertEqual(self.project(detection(box))["reason"], "no_downward_floor_ray")

    def test_range_is_not_clamped_into_validity(self):
        result = self.project(projector=self.projector(max_distance_m=.5))
        self.assertEqual(result["reason"], "outside_diagnostic_range")
        self.assertIsNone(result["z_m"])

    def test_front_circle_crossing_rejected_even_when_centre_inside(self):
        result = self.project(detection((50, 320, 120, 450)))
        self.assertEqual(result["reason"], "bbox_crosses_front_lens_boundary")

    def test_native_geometry_required(self):
        self.assertEqual(self.project(width=1920, height=1080)["reason"],
                         "calibration_resolution_mismatch")

    def test_bad_detections_and_foreign_classes(self):
        for box in ((0, 0, 0, 1), (-1, 2, 30, 40), (1, 2, 1281, 40),
                    (1, 2, 30, float("inf"))):
            self.assertEqual(self.project(detection(box))["reason"], "invalid_detection")
        for key, value in (("confidence", -1), ("confidence", 2),
                           ("confidence", float("nan")), ("class_id", 1),
                           ("class_id", float("inf"))):
            row = detection(); row[key] = value
            self.assertEqual(self.project(row)["reason"], "invalid_score_or_cone_class")
        row = detection(); del row["confidence"]
        self.assertEqual(self.project(row)["reason"], "invalid_detection")

    def test_threshold_inclusive_without_tuning(self):
        self.assertTrue(self.project(detection(confidence=.25))["projection_candidate"])
        self.assertEqual(self.project(detection(confidence=.249))["reason"], "below_confidence")

    def test_invalid_configuration_is_not_silently_defaulted(self):
        for key in CAMERA_KEYS:
            parameters = dict(PARAMETERS); del parameters[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.projector(parameters)
        for key in CAMERA_KEYS:
            with self.subTest(nonfinite=key), self.assertRaises(ValueError):
                self.projector(dict(PARAMETERS, **{key: float("nan")}))
        for changes in (dict(confidence_threshold=0), dict(min_distance_m=4, max_distance_m=1),
                        dict(max_distance_m=float("inf")), dict(front_lens="auto")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.projector(**changes)

    def test_camera_height_and_radius_must_be_positive_and_circle_fit(self):
        for changes in (dict(camera_height=0), dict(radius_scale=-1),
                        dict(front_cx_offset=-900)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.projector(dict(PARAMETERS, **changes))

    def test_input_immutable_and_multiple_cones_not_collapsed(self):
        p = self.projector(); rows = [detection(), detection((340, 340, 380, 430))]
        before = [dict(row) for row in rows]
        results = [self.project(row, p) for row in rows]
        self.assertEqual(rows, before)
        self.assertEqual(len(results), 2)
        self.assertNotEqual(results[0]["x_m"], results[1]["x_m"])


if __name__ == "__main__":
    unittest.main()
