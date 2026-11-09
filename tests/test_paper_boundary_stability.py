"""Synthetic image-only tests; do not write camera frames or human labels."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "paper_boundary_stability",
    ROOT / "Experimental_results/2026-11-09/paper_boundary_stability_r01/analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PaperBoundaryStabilityTests(unittest.TestCase):
    def setUp(self):
        self.gray = np.zeros((720, 1280), np.uint8)
        self.gray[397:415, 290:345] = 255
        self.quad = np.array([[290., 397.], [344., 397.], [344., 414.], [290., 414.]])
        self.camera = audit.load_config()[1]

    def test_refinement_preserves_image_and_seed(self):
        before = self.gray.copy(); seed = self.quad.copy()
        refined = audit.refine(self.gray, self.quad, 3)
        self.assertTrue(np.array_equal(before, self.gray))
        self.assertTrue(np.array_equal(seed, self.quad))
        self.assertTrue(np.isfinite(refined).all())
        self.assertLess(np.max(np.linalg.norm(refined-seed, axis=1)), 2.)

    def test_flat_image_unchanged_output_does_not_prove_a_corner(self):
        gray = np.zeros_like(self.gray)
        refined = audit.refine(gray, self.quad, 2)
        self.assertTrue(np.array_equal(refined, self.quad))
        covariance = audit.covariance(gray, self.quad[0], 2)
        self.assertEqual(covariance["gradient_min_eigenvalue"], 0.)
        self.assertIsNone(covariance["gradient_eigenvalue_ratio"])
        for edge in audit.boundary_evidence(gray, self.quad, self.camera):
            self.assertEqual(edge["positive_peak_fraction"], 0.)
            self.assertIsNone(edge["median_strongest_positive_gradient_offset_px"])

    def test_reversed_nonfinite_or_off_lens_quads_rejected_without_reordering(self):
        for points in (self.quad[::-1], self.quad+700,
                       np.array([[290., 397.], [344., 397.], [float("nan"), 414.], [290., 414.]])):
            with self.assertRaises(ValueError):
                audit.checked_quad(points)

    def test_invalid_window_type_or_image_contract_rejected(self):
        for window in (True, 1, 5, 2.):
            with self.assertRaises(ValueError):
                audit.refine(self.gray, self.quad, window)
        with self.assertRaises(ValueError):
            audit.refine(self.gray.astype(float), self.quad, 2)

    def test_sample_coordinates_do_not_extrapolate_border(self):
        for points in ([[-1., 400.]], [[640., 400.]], [[300., float("inf")]]):
            with self.assertRaises(ValueError):
                audit.sample_gray(self.gray, points)

    def test_edge_locus_follows_kb4_rays_and_interior_normal(self):
        uv, normal = audit.edge_locus(self.quad[:2], self.camera)
        self.assertEqual(uv.shape, (33, 2))
        self.assertTrue(np.all(normal[:, 1] > 0))
        self.assertTrue(np.allclose(np.linalg.norm(normal, axis=1), 1.))
        with self.assertRaises(ValueError):
            audit.edge_locus(self.quad[[0, 0]], self.camera)

    def test_white_rectangle_provides_positive_inward_contrast(self):
        records = audit.boundary_evidence(self.gray, self.quad, self.camera)
        self.assertEqual(len(records), 4)
        for edge in records:
            self.assertGreater(edge["contrast_1px_median"], 100)
            self.assertGreater(edge["positive_1px_fraction"], .9)
            self.assertFalse(edge["physical_edge_verified"])

    def test_seed_trials_are_17_explicit_offsets_not_random_or_human(self):
        offsets = list(audit.seed_offsets())
        self.assertEqual(len(offsets), 17)
        self.assertEqual(len({name for name, _ in offsets}), 17)
        self.assertTrue(np.array_equal(offsets[0][1], np.zeros((4, 2))))
        self.assertTrue(all(np.count_nonzero(delta) == 1 for _, delta in offsets[1:]))


if __name__ == "__main__":
    unittest.main()
