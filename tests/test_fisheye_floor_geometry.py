import copy
import math
import unittest

import numpy as np

from fisheye_floor_geometry import (EquidistantCamera, checked_transform, intersect_floor,
                                    legacy_front_diagnostic_geometry, optical_rays)
from ground_contact import dual_fisheye_pixels_to_vehicle_rays


PARAMETERS = dict(camera_height=.59, pitch_deg=1., roll_deg=2., yaw_deg=0., radius_scale=.86,
                  front_cx_offset=-80., front_cy_offset=-21.)


class FisheyeFloorTests(unittest.TestCase):
    def setUp(self):
        self.camera = EquidistantCamera(1001, 1001, 500., 500., 450.)
        self.transform = np.array([[0., 0., 1., 0.], [-1., 0., 0., 0.],
                                   [0., -1., 0., .59], [0., 0., 0., 1.]])
        self.pixel = [[500., 500.+450/(math.pi/2)*math.atan2(.59, 2.)]]

    def floor(self, pixels=None, transform=None, **kwargs):
        return intersect_floor(self.pixel if pixels is None else pixels, self.camera,
                               self.transform if transform is None else transform,
                               image_size=(1001, 1001), **kwargs)

    def test_known_floor_point_subpixel_without_rectification(self):
        row = self.floor()[0]
        np.testing.assert_allclose(row["point_target_m"], (2., 0., 0.), atol=1e-12)
        self.assertAlmostEqual(row["ray_distance_m"], math.hypot(2., .59))
        self.assertFalse(row["usable_for_ffb"])
        self.assertFalse(row["floor_contact_verified"])

    def test_translation_applies_to_origin_not_direction(self):
        t = self.transform.copy()
        t[:2, 3] = [3., -2.]
        row = self.floor(transform=t)[0]
        np.testing.assert_allclose(row["point_target_m"], (5., -2., 0.), atol=1e-12)
        self.assertAlmostEqual(row["ray_distance_m"], math.hypot(2., .59))

    def test_target_rotation_does_not_change_physical_intersection(self):
        angle = .4
        r = np.array([[math.cos(angle), -math.sin(angle), 0.], [math.sin(angle), math.cos(angle), 0.], [0., 0., 1.]])
        t = self.transform.copy()
        t[:3, :3] = r @ t[:3, :3]
        np.testing.assert_allclose(self.floor(transform=t)[0]["point_target_m"], r @ [2., 0., 0.], atol=1e-12)

    def test_tilted_floor_plane_and_nonzero_offset(self):
        n = np.array([.05, -.02, 1.])
        n /= np.linalg.norm(n)
        result = self.floor(plane_normal=n, plane_offset_m=.1)[0]
        self.assertAlmostEqual(float(n @ result["point_target_m"]+.1), 0., places=12)

    def test_optical_centre_limiting_ray(self):
        rays, valid = optical_rays([[500., 500.]], self.camera)
        self.assertTrue(valid[0])
        np.testing.assert_array_equal(rays, [[0., 0., 1.]])
        self.assertIsNone(self.floor([[500., 500.]])[0]["point_target_m"])

    def test_upward_and_grazing_rays_do_not_intersect(self):
        rows = self.floor([[500., 450.], [500., 500.1]])
        self.assertTrue(all(r["point_target_m"] is None for r in rows))

    def test_invalid_lens_pixels_keep_order_and_duplicates(self):
        pixels = [self.pixel[0], [-1., 500.], [1002., 500.], [500., 950.], self.pixel[0]]
        rows = self.floor(pixels)
        self.assertEqual([r["input_index"] for r in rows], list(range(5)))
        self.assertEqual(rows[0]["point_target_m"], rows[4]["point_target_m"])
        self.assertTrue(all(rows[i]["point_target_m"] is None for i in (1, 2, 3)))

    def test_empty_input(self):
        self.assertEqual(self.floor([]), [])

    def test_nonfinite_and_complex_pixels_rejected(self):
        for pixels in ([[np.nan, 1.]], [[1., np.inf]], [[1j, 2]], [1., 2.]):
            with self.assertRaises(ValueError):
                self.floor(pixels)

    def test_bad_transform_and_reflection_rejected(self):
        for scale in (-1., 1.001, 0.):
            t = self.transform.copy()
            t[:3, 0] *= scale
            with self.assertRaises(ValueError):
                self.floor(transform=t)
        with self.assertRaises(ValueError):
            checked_transform(np.full((4, 4), np.nan))
        with self.assertRaises(ValueError):
            checked_transform(np.eye(4, dtype=complex))

    def test_bad_plane_and_camera_side_rejected(self):
        for kwargs in (dict(plane_normal=(0, 0, 2)), dict(plane_normal=(0, 0, -1)),
                       dict(plane_offset_m=float("nan")), dict(min_incidence_cos=0), dict(plane_offset_m=-1.)):
            with self.assertRaises(ValueError):
                self.floor(**kwargs)

    def test_actual_image_size_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            intersect_floor(self.pixel, self.camera, self.transform, image_size=(1280, 720))

    def test_invalid_intrinsics_not_defaulted(self):
        for radius in (0., -1., float("nan"), True):
            with self.assertRaises(ValueError):
                EquidistantCamera(1001, 1001, 500., 500., radius)
        with self.assertRaises(ValueError):
            legacy_front_diagnostic_geometry({})

    def test_legacy_equivalence_with_general_angles_and_no_ui_offset(self):
        for angles in ((0, 0, 0), (1, 2, 0), (7, -4, 5)):
            p = dict(PARAMETERS, pitch_deg=angles[0], roll_deg=angles[1], yaw_deg=angles[2])
            camera, transform = legacy_front_diagnostic_geometry(p)
            pixels = np.array([(x, y) for x in range(220, 421, 25) for y in range(380, 521, 20)], float)
            selected, rays = dual_fisheye_pixels_to_vehicle_rays(pixels, 1280, 720, p)
            by_pixel = {tuple(pixel): ray for pixel, ray in zip(selected, rays)}
            rows = intersect_floor(pixels, camera, transform, image_size=(1280, 720))
            for pixel, row in zip(pixels, rows):
                ray = by_pixel.get(tuple(pixel))
                if ray is not None and ray[1] < -.03:
                    old = -.59/ray[1]*ray
                    np.testing.assert_allclose(row["point_target_m"], [old[2], -old[0], 0.], atol=1e-12)
            other_camera, other_transform = legacy_front_diagnostic_geometry(dict(p, car_offset_x=200., car_offset_z=-50.))
            self.assertEqual(camera, other_camera)
            np.testing.assert_array_equal(transform, other_transform)

    def test_inputs_not_mutated(self):
        original_parameters = copy.deepcopy(PARAMETERS)
        original_transform = self.transform.copy()
        pixels = np.asarray(self.pixel)
        original_pixels = pixels.copy()
        self.floor(pixels)
        legacy_front_diagnostic_geometry(PARAMETERS)
        np.testing.assert_array_equal(pixels, original_pixels)
        np.testing.assert_array_equal(self.transform, original_transform)
        self.assertEqual(PARAMETERS, original_parameters)


if __name__ == "__main__":
    unittest.main()
