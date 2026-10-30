"""Synthetic in-memory inputs only; no generated camera evidence saved."""
import unittest

import cv2
import numpy as np

from refine_paper_edges import (boundary_observations, canonical, intersect_lines,
                               load_config, planar_floor_pose_candidates, project,
                               refine_quad, tls_line)


class EdgeRefinementTests(unittest.TestCase):
    def setUp(self):
        self.camera = load_config()[1]
        self.world = np.array([[1., .15, 0], [1., -.146, 0], [.79, -.146, 0], [.79, .15, 0]])
        self.transform = np.array([[0., 0., 1., 0.], [-1., 0., 0., 0.],
                                   [0., -1., 0., .59], [0., 0., 0., 1.]])
        optical = (self.world-self.transform[:3, 3]) @ self.transform[:3, :3]
        self.seed, valid = project(optical, self.camera)
        self.assertTrue(valid.all())
        samples = []
        for a, b in zip(optical, np.roll(optical, -1, axis=0)):
            uv, valid = project(a+np.linspace(.05, .95, 50)[:, None]*(b-a), self.camera)
            self.assertTrue(valid.all())
            samples.extend(uv)
        self.samples = np.asarray(samples)

    def test_tls_exact_line(self):
        p = np.column_stack((np.arange(10), 2*np.arange(10)+1))
        line = tls_line(p)
        np.testing.assert_allclose(p@line[:2]+line[2], 0, atol=1e-12)

    def test_tls_bad_samples_refused(self):
        for bad in (np.zeros((10, 2)), np.zeros((5, 2)), np.full((8, 2), np.nan)):
            with self.assertRaises(ValueError):
                tls_line(bad)

    def test_parallel_lines_refused(self):
        with self.assertRaises(ValueError):
            intersect_lines([1, 0, -2], [1, 0, -3])

    def test_line_intersection(self):
        np.testing.assert_allclose(intersect_lines([1, 0, -2], [0, 1, -3]), [2, 3])

    def test_fisheye_curved_edges_recover_known_corners(self):
        before = self.samples.copy()
        result = refine_quad(self.samples, self.seed, self.camera)
        np.testing.assert_allclose(result["corners_native_xy"], self.seed, atol=1e-8)
        np.testing.assert_array_equal(self.samples, before)
        self.assertFalse(result["physical_paper_edge_identity_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_known_plane_height_and_both_solutions_retained(self):
        result = refine_quad(self.samples, self.seed, self.camera)
        poses = planar_floor_pose_candidates(result["corners_native_xy"], self.world, self.camera)
        self.assertEqual(poses["solution_count"], 2)
        n, h = canonical(poses["candidates"][0])
        self.assertAlmostEqual(h, .59, places=9)
        np.testing.assert_allclose(n, [0, -1, 0], atol=1e-8)
        self.assertFalse(poses["physical_metric_verified"])

    def test_small_seed_shift_not_fitted_as_measurement(self):
        refined = refine_quad(self.samples, self.seed+[.7, -.4], self.camera)
        np.testing.assert_allclose(refined["corners_native_xy"], self.seed, atol=1e-8)

    def test_missing_observed_edge_refused(self):
        with self.assertRaises(ValueError):
            refine_quad(self.samples[:150], self.seed, self.camera)

    def test_rear_edge_samples_not_reinterpreted_as_front(self):
        with self.assertRaises(ValueError):
            refine_quad(self.samples+[640, 0], self.seed+[640, 0], self.camera)

    def test_invalid_trim_refused(self):
        with self.assertRaises(ValueError):
            refine_quad(self.samples, self.seed, self.camera, trim_fraction=.4)

    def test_sampling_gate_explicit_and_bounded(self):
        for gate in (0, -1, 7, float("nan")):
            with self.assertRaises(ValueError):
                refine_quad(self.samples, self.seed, self.camera, seed_edge_gate_px=gate)

    def test_exact_geometry_unchanged_by_sampling_gate_control(self):
        narrow = refine_quad(self.samples, self.seed, self.camera, seed_edge_gate_px=2.5)
        wide = refine_quad(self.samples, self.seed, self.camera, seed_edge_gate_px=4.)
        np.testing.assert_allclose(narrow["corners_native_xy"], wide["corners_native_xy"], atol=1e-8)
        self.assertTrue(all(e["excluded_by_seed_gate_count"] == 0 for e in wide["edges"]))

    def test_external_crossings_are_subpixel_and_exclude_ink_holes(self):
        gray = np.full((60, 80), 40, np.uint8)
        gray[15:46, 20:61] = 240
        gray[25:35, 30:40] = 40
        seed = [[20, 15], [60, 15], [60, 45], [20, 45]]
        original = gray.copy()
        points = boundary_observations(gray, (0, 0, 80, 60), seed, 140)["intensity_crossings"]
        on_external_edge = (np.isclose(points[:, 0], 19.5) | np.isclose(points[:, 0], 60.5)
                            | np.isclose(points[:, 1], 14.5) | np.isclose(points[:, 1], 45.5))
        self.assertTrue(on_external_edge.all())
        self.assertGreater(len(points), 100)
        np.testing.assert_array_equal(gray, original)

    def test_blank_image_is_not_paper(self):
        with self.assertRaises(ValueError):
            boundary_observations(np.zeros((60, 80), np.uint8), (0, 0, 80, 60),
                                  [[20, 15], [60, 15], [60, 45], [20, 45]], 170)

    def test_clipped_contour_refused(self):
        gray = np.zeros((60, 80), np.uint8)
        cv2.rectangle(gray, (0, 15), (60, 45), 240, -1)
        with self.assertRaises(ValueError):
            boundary_observations(gray, (0, 0, 80, 60),
                                  [[0, 15], [60, 15], [60, 45], [0, 45]], 170)


if __name__ == "__main__":
    unittest.main()
