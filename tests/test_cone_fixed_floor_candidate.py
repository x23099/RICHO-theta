"""Synthetic-only tests for the isolated explicit floor candidate."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from angular_fisheye_geometry import project, unproject
from cone_distance_core import load_config
from cone_fixed_floor_candidate import (
    COORDINATE_FRAME, SCHEMA, build_explicit_floor_transform, checked_explicit_floor_model,
    measure_support)


def base_transform():
    return np.array([[0., 0., 1., .02], [-1., 0., 0., -.03],
                     [0., -1., 0., .59], [0., 0., 0., 1.]])


def model_for(transform, *, height=None, session="synthetic_session", name="synthetic"):
    rotation = transform[:3, :3]
    normal = rotation.T @ np.array([0., 0., 1.])
    return dict(
        schema=SCHEMA, name=name, session=session,
        normal_optical=normal.tolist(),
        camera_to_floor_m=float(transform[2, 3]) if height is None else float(height),
        coordinate_frame=COORDINATE_FRAME,
        heading_reference=dict(path="synthetic/transform.json", sha256="0" * 64),
        evidence=["synthetic known transform"],
        assumptions=["synthetic plane is the floor"],
        invalidation_conditions=["synthetic pose changes"],
        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False)


class ExplicitFloorCandidateTests(unittest.TestCase):
    def setUp(self):
        self.camera = load_config()[1]
        self.transform = base_transform()
        self.model = model_for(self.transform)
        self.point = np.array([1.5, .1, 0.])
        optical = self.transform[:3, :3].T @ (self.point - np.array([0., 0., self.transform[2, 3]]))
        self.pixel, valid = project(optical[None, :], self.camera)
        self.assertTrue(valid[0])
        self.pixel = np.rint(self.pixel[0]).astype(int)

    def direct(self, pixel, model=None):
        model = self.model if model is None else model
        ray, valid = unproject([[float(pixel[0]), float(pixel[1])]], self.camera,
                               image_size=(1280, 720))
        self.assertTrue(valid[0])
        normal = np.asarray(model["normal_optical"], float)
        height = float(model["camera_to_floor_m"])
        incidence = -float(normal @ ray[0])
        slant = height/incidence
        optical_point = slant*ray[0]
        point = optical_point @ self.transform[:3, :3].T + np.array([0., 0., height])
        return dict(radial=float(np.hypot(point[0], point[1])),
                    forward=float(point[0]), lateral=float(-point[1]), slant=slant)

    def measure(self, model=None, transform=None, pixel=None):
        return measure_support(self.pixel if pixel is None else pixel,
                               self.model if model is None else model,
                               self.camera, self.transform if transform is None else transform,
                               session="synthetic_session")

    def test_known_point_recovered_without_selecting_a_solution(self):
        expected = self.direct(self.pixel)
        result = self.measure()
        self.assertTrue(result["range_available"])
        self.assertEqual(result["status"], "CONDITIONAL_FIXED_FLOOR_RANGE_ONLY")
        self.assertAlmostEqual(result["horizontal_camera_foot_range_m"],
                               expected["radial"], places=9)
        self.assertAlmostEqual(result["forward_heading_reference_m"],
                               expected["forward"], places=9)
        self.assertAlmostEqual(result["lateral_right_heading_reference_m"],
                               expected["lateral"], places=9)
        self.assertAlmostEqual(result["lens_slant_range_m"], expected["slant"], places=9)
        self.assertLess(abs(expected["radial"]-float(np.hypot(*self.point[:2]))), .02)
        self.assertTrue(result["model_name"] == "synthetic")
        self.assertFalse(result["yaw_measured"])
        self.assertFalse(result["controlling_distance"])
        self.assertFalse(result["physical_metric_verified"])
        self.assertFalse(result["floor_contact_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_radial_range_is_invariant_to_heading_reference_yaw(self):
        angle = np.deg2rad(25.)
        rotation = np.array([[np.cos(angle), -np.sin(angle), 0.],
                             [np.sin(angle), np.cos(angle), 0.],
                             [0., 0., 1.]])
        yaw = np.eye(4)
        yaw[:3, :3] = rotation
        rotated = yaw @ self.transform
        first = self.measure()
        second = self.measure(transform=rotated)
        self.assertTrue(first["range_available"] and second["range_available"])
        self.assertAlmostEqual(first["horizontal_camera_foot_range_m"],
                               second["horizontal_camera_foot_range_m"], places=10)
        self.assertNotAlmostEqual(first["forward_heading_reference_m"],
                                  second["forward_heading_reference_m"], places=3)

    def test_heading_reference_translation_is_not_carried_into_origin(self):
        shifted = self.transform.copy()
        shifted[:2, 3] = [.7, -.4]
        result = self.measure(transform=shifted)
        self.assertTrue(result["range_available"])
        self.assertAlmostEqual(result["horizontal_camera_foot_range_m"],
                               self.direct(self.pixel)["radial"], places=9)

    def test_height_scales_the_same_ray_linearly(self):
        low = self.measure()
        doubled = self.measure(model=model_for(self.transform, height=2*self.transform[2, 3]))
        self.assertTrue(low["range_available"] and doubled["range_available"])
        self.assertAlmostEqual(doubled["horizontal_camera_foot_range_m"],
                               2*low["horizontal_camera_foot_range_m"], places=10)

    def test_model_normal_matches_transform_up(self):
        transform = build_explicit_floor_transform(self.model, self.transform)
        up = transform[:3, :3].T @ np.array([0., 0., 1.])
        np.testing.assert_allclose(up, self.model["normal_optical"], atol=1e-10)
        self.assertAlmostEqual(transform[2, 3], self.transform[2, 3], places=12)

    def test_session_scope_is_enforced(self):
        with self.assertRaises(ValueError):
            measure_support(self.pixel, self.model, self.camera, self.transform,
                            session="another_session")

    def test_physically_approved_model_is_refused(self):
        for key in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb"):
            model = dict(self.model, **{key: True})
            with self.subTest(key=key), self.assertRaises(ValueError):
                checked_explicit_floor_model(model)

    def test_non_unit_normal_and_nonpositive_height_refused(self):
        bad = dict(self.model, normal_optical=[0., -2., 0.])
        with self.assertRaises(ValueError):
            checked_explicit_floor_model(bad)
        for height in (0., -0.1, float("inf")):
            with self.subTest(height=height), self.assertRaises(ValueError):
                checked_explicit_floor_model(dict(self.model, camera_to_floor_m=height))

    def test_missing_explicit_evidence_refused(self):
        for key in ("evidence", "assumptions", "invalidation_conditions"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                checked_explicit_floor_model(dict(self.model, **{key: []}))

    def test_support_outside_front_domain_withheld_not_raised(self):
        result = self.measure(pixel=[700, 360])
        self.assertFalse(result["range_available"])
        self.assertEqual(result["reason"], "support_outside_front_angular_domain")

    def test_inputs_are_not_mutated(self):
        model, transform = dict(self.model), self.transform.copy()
        self.measure()
        self.assertEqual(model, self.model)
        np.testing.assert_array_equal(transform, self.transform)

    def test_not_imported_by_controlling_distance_paths(self):
        for name in ("cone_distance_core.py", "cone_distance_worker.py",
                     "run_cone_distance_live.py", "summarize_cone_distance_live.py"):
            text = (ROOT / "src" / name).read_text()
            self.assertNotIn("cone_fixed_floor_candidate", text, name)


if __name__ == "__main__":
    unittest.main()
