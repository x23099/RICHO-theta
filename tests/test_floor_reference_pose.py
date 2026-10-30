"""Synthetic geometry tests only; do not represent real floor calibration."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from angular_fisheye_geometry import project, unproject, floor_from_rays
from cone_distance_core import load_config
from floor_reference_pose import planar_floor_pose_candidates


class FloorPoseTests(unittest.TestCase):
    def setUp(self):
        self.camera = load_config()[1]
        self.world = np.array([[.8, 0, 0], [1.3, 0, 0], [2., 0, 0],
                               [1.3, .4, 0], [1.3, -.4, 0]], float)
        self.transform = np.array([[0., 0., 1., .02], [-1., 0., 0., -.03],
                                   [0., -1., 0., .59], [0., 0., 0., 1.]])
        optical = (self.world-self.transform[:3, 3]) @ self.transform[:3, :3]
        self.pixels, valid = project(optical, self.camera)
        self.assertTrue(valid.all())

    def test_known_pose_recovered_without_height_constraint(self):
        before = self.pixels.copy()
        result = planar_floor_pose_candidates(self.pixels, self.world, self.camera)
        self.assertEqual(result["solution_count"], 2)
        closest = min(result["candidates"], key=lambda c: c["fit_native_rmse_px"])
        self.assertTrue(closest["geometry_consistent"])
        np.testing.assert_allclose(closest["transform_floor_from_optical"], self.transform, atol=1e-8)
        self.assertIsNone(result["selected_solution"])
        self.assertFalse(result["physical_metric_verified"])
        self.assertFalse(result["published_to_ros"])
        self.assertFalse(result["usable_for_ffb"])
        np.testing.assert_array_equal(before, self.pixels)

    def test_holdout_ray_intersection_uses_same_transform(self):
        result = planar_floor_pose_candidates(self.pixels, self.world, self.camera)
        candidate = min(result["candidates"], key=lambda c: c["fit_native_rmse_px"])
        holdout = np.array([[1., .1, 0], [1.6, -.2, 0]])
        pixels, _ = project((holdout-self.transform[:3, 3]) @ self.transform[:3, :3], self.camera)
        rays, valid = unproject(pixels, self.camera, image_size=(1280, 720))
        recovered, valid = floor_from_rays(rays, valid, candidate["transform_floor_from_optical"])
        self.assertTrue(valid.all())
        np.testing.assert_allclose(recovered, holdout, atol=1e-8)

    def test_less_than_four_references_refused(self):
        with self.assertRaises(ValueError):
            planar_floor_pose_candidates(self.pixels[:3], self.world[:3], self.camera)

    def test_collinear_floor_points_refused(self):
        with self.assertRaises(ValueError):
            planar_floor_pose_candidates(self.pixels[:4], np.array([[.8, 0, 0], [1., 0, 0],
                [1.3, 0, 0], [2., 0, 0]]), self.camera)

    def test_nonfloor_point_refused_not_projected_to_floor_silently(self):
        changed = self.world.copy()
        changed[0, 2] = .01
        with self.assertRaises(ValueError):
            planar_floor_pose_candidates(self.pixels, changed, self.camera)

    def test_duplicate_correspondences_refused(self):
        with self.assertRaises(ValueError):
            planar_floor_pose_candidates(np.vstack((self.pixels, self.pixels[0])),
                np.vstack((self.world, self.world[0])), self.camera)

    def test_rear_pixel_not_remapped_to_front(self):
        changed = self.pixels.copy()
        changed[0, 0] += 640
        with self.assertRaises(ValueError):
            planar_floor_pose_candidates(changed, self.world, self.camera)

    def test_nonfinite_inputs_refused(self):
        changed = self.pixels.copy()
        changed[0, 0] = np.nan
        with self.assertRaises(ValueError):
            planar_floor_pose_candidates(changed, self.world, self.camera)


if __name__ == "__main__":
    unittest.main()
