"""Yaw-free plane/ray algebra and rejection tests, not real accuracy tests."""
import unittest
import numpy as np
from compare_same_session_cone import horizontal_range


class SameSessionRangeTests(unittest.TestCase):
    def setUp(self):
        self.height = .59
        self.normal = np.array([0., -1., 0.])
        self.point = np.array([.2, self.height, 1.5])
        self.ray = self.point/np.linalg.norm(self.point)

    def test_known_ground_range_not_slant_distance(self):
        result = horizontal_range(self.ray, self.normal, self.height)
        self.assertAlmostEqual(result["horizontal_camera_foot_range_m"], np.hypot(.2, 1.5))
        self.assertAlmostEqual(result["lens_slant_range_m"], np.linalg.norm(self.point))

    def test_point_lies_in_supplied_plane(self):
        result = horizontal_range(self.ray, self.normal, self.height)
        self.assertAlmostEqual(self.normal@result["point_optical_m"]+self.height, 0)

    def test_no_physical_approval(self):
        result = horizontal_range(self.ray, self.normal, self.height)
        for key in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb"):
            self.assertFalse(result[key])

    def test_horizon_or_upward_ray_refused(self):
        for ray in ([0, 0, 1], [0, -1, 0]):
            with self.assertRaises(ValueError):
                horizontal_range(ray, self.normal, self.height)

    def test_nonunit_ray_or_normal_refused(self):
        for ray, normal in ((self.ray*2, self.normal), (self.ray, self.normal*2)):
            with self.assertRaises(ValueError):
                horizontal_range(ray, normal, self.height)

    def test_nonpositive_or_nonfinite_height_refused(self):
        for height in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                horizontal_range(self.ray, self.normal, height)

    def test_range_scales_with_external_height_without_hidden_refit(self):
        a = horizontal_range(self.ray, self.normal, self.height)
        b = horizontal_range(self.ray, self.normal, 2*self.height)
        self.assertAlmostEqual(b["horizontal_camera_foot_range_m"], 2*a["horizontal_camera_foot_range_m"])

    def test_rotation_of_optical_axes_leaves_range_unchanged(self):
        rotation = np.array([[0., 0., 1.], [0., 1., 0.], [-1., 0., 0.]])
        a = horizontal_range(self.ray, self.normal, self.height)
        b = horizontal_range(rotation@self.ray, rotation@self.normal, self.height)
        self.assertAlmostEqual(a["horizontal_camera_foot_range_m"], b["horizontal_camera_foot_range_m"])


if __name__ == "__main__":
    unittest.main()
