"""Input contracts and exact same-frame subset reuse, no hardware calls."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_comparison as run
import cached_curve_geometry as cached
import curve_geometry as baseline
import scene_geometry as scene
from angular_fisheye_geometry import unproject


class RayReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = run.camera_from_candidate(json.loads(run.CAMERA.read_text()))
        cls.pixels = np.column_stack((np.full(100, 320.), np.arange(100., 300., 2.)))
        cls.rays, cls.valid = unproject(cls.pixels, cls.camera, image_size=(1280, 720))
        cls.ids = np.arange(100, dtype=int)
        rows = run.read_csv(run.UNIFORM / 'scene_results_r01/image_diagnostics.csv')
        row = next(r for r in rows if r['session'] == run.SESSION and int(r['frame']) == 302)
        cls.image = cv2.imread(row['source_native_png'])
        cv2.setNumThreads(1)

    def test_full_subset_matches_original_plane_exactly(self):
        self.assertTrue(self.valid.all())
        self.assertEqual(run.canonical(cached._plane_from_subset(self.pixels, self.rays, self.ids)),
                         run.canonical(scene.plane_from_pixels(self.pixels, self.camera)))

    def test_noncontiguous_subset_matches(self):
        ids = self.ids[::2]
        self.assertEqual(run.canonical(cached._plane_from_subset(self.pixels, self.rays, ids)),
                         run.canonical(scene.plane_from_pixels(self.pixels[ids], self.camera)))

    def test_reversed_subset_preserves_order(self):
        ids = self.ids[::-1]
        self.assertEqual(run.canonical(cached._plane_from_subset(self.pixels, self.rays, ids)),
                         run.canonical(scene.plane_from_pixels(self.pixels[ids], self.camera)))

    def test_short_input_rejected(self):
        with self.assertRaises(ValueError):
            cached._plane_from_subset(self.pixels, self.rays, self.ids[:29])

    def test_float_indices_rejected(self):
        with self.assertRaises(ValueError):
            cached._plane_from_subset(self.pixels, self.rays, self.ids.astype(float))

    def test_negative_indices_rejected(self):
        with self.assertRaises(ValueError):
            cached._plane_from_subset(self.pixels, self.rays, -self.ids)

    def test_out_of_range_indices_rejected(self):
        with self.assertRaises(ValueError):
            cached._plane_from_subset(self.pixels, self.rays, self.ids + 1)

    def test_unpaired_pool_lengths_rejected(self):
        with self.assertRaises(ValueError):
            cached._plane_from_subset(self.pixels, self.rays[:-1], self.ids)

    def test_fractional_pixels_rejected(self):
        with self.assertRaises(ValueError):
            cached._plane_from_subset(self.pixels + .1, self.rays, self.ids)

    def test_nonfinite_pixels_rejected(self):
        p = self.pixels.copy(); p[0, 0] = np.nan
        with self.assertRaises(ValueError):
            cached._plane_from_subset(p, self.rays, self.ids)

    def test_nonfinite_rays_rejected(self):
        rays = self.rays.copy(); rays[0, 0] = np.nan
        with self.assertRaises(ValueError):
            cached._plane_from_subset(self.pixels, rays, self.ids)

    def test_angular_exclusion_kept(self):
        rays = np.tile([1., 0., 0.], (100, 1))
        self.assertEqual(cached._plane_from_subset(self.pixels, rays, self.ids)['reason'],
                         'outside_75degree_scene_domain')

    def test_insufficient_span_kept(self):
        rays = np.tile([0., 0., 1.], (100, 1))
        self.assertEqual(cached._plane_from_subset(self.pixels, rays, self.ids)['reason'],
                         'insufficient_ray_span')

    def test_blank_native_image_exact(self):
        image = np.zeros((720, 1280, 3), np.uint8)
        self.assertEqual(cached.extract_cached_curve_planes(image, self.camera), [])
        self.assertEqual(baseline.extract_curve_planes(image, self.camera), [])

    def test_wrong_resolution_rejected(self):
        with self.assertRaises(ValueError):
            cached.extract_cached_curve_planes(np.zeros((360, 640, 3), np.uint8), self.camera)

    def test_wrong_dtype_rejected(self):
        with self.assertRaises(ValueError):
            cached.extract_cached_curve_planes(self.image.astype(float), self.camera)

    def test_actual_curves_all_fields_and_order_exact(self):
        old = baseline.extract_curve_planes(self.image, self.camera)
        new = cached.extract_cached_curve_planes(self.image, self.camera)
        self.assertGreater(len(old), 0)
        self.assertEqual(run.canonical(old), run.canonical(new))
        self.assertTrue(any(r['reason'] == 'duplicate_ray_plane' for r in old))

    def test_single_unproject_per_frame(self):
        with patch.object(cached, 'unproject', wraps=unproject) as mock:
            cached.extract_cached_curve_planes(self.image, self.camera)
            self.assertEqual(mock.call_count, 1)

    def test_original_repeated_calls_confirmed(self):
        with patch.object(baseline, 'unproject', wraps=unproject) as pool:
            with patch.object(scene, 'unproject', wraps=unproject) as subsets:
                rows = baseline.extract_curve_planes(self.image, self.camera)
                self.assertEqual(pool.call_count, 1)
                self.assertEqual(subsets.call_count, len(rows))

    def test_image_and_calibration_unmodified(self):
        before = self.image.copy(); K = self.camera.K.copy(); D = self.camera.D.copy()
        cached.extract_cached_curve_planes(self.image, self.camera)
        np.testing.assert_array_equal(self.image, before)
        np.testing.assert_array_equal(self.camera.K, K)
        np.testing.assert_array_equal(self.camera.D, D)

    def test_no_cross_frame_cache(self):
        cached.extract_cached_curve_planes(self.image, self.camera)
        blank = np.zeros_like(self.image)
        self.assertEqual(cached.extract_cached_curve_planes(blank, self.camera), [])

    def test_camera_change_has_no_stale_reuse(self):
        K = self.camera.K.copy(); K[0, 0] *= 1.01
        other = replace(self.camera, K=K)
        self.assertEqual(run.canonical(cached.extract_cached_curve_planes(self.image, other)),
                         run.canonical(baseline.extract_curve_planes(self.image, other)))

    def test_right_lens_pixels_not_newly_used(self):
        other = self.image.copy(); other[:, 640:] = 0
        self.assertEqual(run.canonical(cached.extract_cached_curve_planes(self.image, self.camera)),
                         run.canonical(cached.extract_cached_curve_planes(other, self.camera)))


if __name__ == '__main__':
    unittest.main()
