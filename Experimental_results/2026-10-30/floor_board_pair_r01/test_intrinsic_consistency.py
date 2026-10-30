"""Synthetic geometry controls only. No saved synthetic camera evidence."""
import unittest

import numpy as np

from audit_intrinsic_consistency import (fit_plane, load_config, plane_project,
                                        tangent_basis)
from angular_fisheye_geometry import project


class IntrinsicConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.camera = load_config()[1]
        self.parameters = np.array([.02, -.01, np.log(.575), -.02, .95, .04, .32, 1.03, -.25])
        self.pixels, _, _, _, _ = plane_project(self.parameters, self.camera)

    def test_basis_orthonormal_and_points_to_optical_up(self):
        n, u, v = tangent_basis([.02, -.01])
        axes = np.array([u, v, n])
        np.testing.assert_allclose(axes@axes.T, np.eye(3), atol=1e-12)
        self.assertLess(n[1], 0)

    def test_both_rectangles_on_same_printed_plane(self):
        _, points, _, n, h = plane_project(self.parameters, self.camera)
        np.testing.assert_allclose(points@n, -h, atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(points[0, 1]-points[0, 0]), .296)
        self.assertAlmostEqual(np.linalg.norm(points[0, 2]-points[0, 1]), .210)

    def test_native_projection_agrees_with_existing_geometry(self):
        uv, points, _, _, _ = plane_project(self.parameters, self.camera)
        control, valid = project(points.reshape(-1, 3), self.camera)
        self.assertTrue(valid.all())
        np.testing.assert_allclose(uv.reshape(-1, 2), control, atol=1e-10)

    def test_known_free_plane_recovered(self):
        start = self.parameters.copy()
        start[:3] += [.02, -.02, -.05]
        result = fit_plane(self.pixels, self.camera, start)
        self.assertTrue(result["success"])
        self.assertLess(result["native_point_rmse_px"], 1e-7)
        self.assertAlmostEqual(result["camera_to_printed_plane_m"], .575, places=8)

    def test_fixed_height_labelled_as_external_input(self):
        result = fit_plane(self.pixels, self.camera, self.parameters, height_m=.575)
        self.assertTrue(result["height_is_fixed_input"])
        self.assertLess(result["native_point_rmse_px"], 1e-8)
        self.assertFalse(result["physical_metric_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_incorrect_fixed_height_does_not_return_zero_residual(self):
        result = fit_plane(self.pixels, self.camera, self.parameters, height_m=.61)
        self.assertGreater(result["native_point_rmse_px"], .1)
        self.assertEqual(result["camera_to_printed_plane_m"], .61)

    def test_inputs_and_intrinsics_unchanged(self):
        before = self.parameters.copy(), self.pixels.copy(), self.camera.K.copy(), self.camera.D.copy()
        fit_plane(self.pixels, self.camera, self.parameters)
        for actual, expected in zip((self.parameters, self.pixels, self.camera.K, self.camera.D), before):
            np.testing.assert_array_equal(actual, expected)

    def test_invalid_parameters_rejected(self):
        for bad in (np.zeros(8), np.full(9, np.nan)):
            with self.assertRaises(ValueError):
                plane_project(bad, self.camera)

    def test_nonpositive_height_refused(self):
        with self.assertRaises(ValueError):
            plane_project(np.r_[self.parameters[:2], self.parameters[3:]], self.camera, height_m=0)

    def test_incorrect_pixel_count_refused(self):
        with self.assertRaises(ValueError):
            fit_plane(self.pixels[:1], self.camera, self.parameters)

    def test_invalid_paper_size_refused(self):
        with self.assertRaises(ValueError):
            plane_project(self.parameters, self.camera, paper_size=(.296, 0))

    def test_invalid_slopes_refused(self):
        with self.assertRaises(ValueError):
            tangent_basis([float("nan"), 0])


if __name__ == "__main__":
    unittest.main()
