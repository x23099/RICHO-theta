"""Offline geometry only; synthetic vectors are not vehicle calibration."""
import ast
import copy
import math
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_motion_spatial import camera_floor_offset


class CameraFloorOffsetTests(unittest.TestCase):
    def test_level_optical_floor_and_known_vector(self):
        result = camera_floor_offset([0., .6, .8], up_optical=[0., -1., 0.], height_m=.6)
        np.testing.assert_allclose(result['offset_optical_m'], [0., 0., .8], atol=1e-15)
        self.assertAlmostEqual(result['horizontal_range_m'], .8)
        self.assertAlmostEqual(result['plane_residual_m'], 0.)
        self.assertIsNone(result['vehicle_xy_m'])
        self.assertTrue(result['replay_only'])
        for key in ('physical_metric_verified', 'floor_contact_verified', 'controlling_distance',
                    'usable_for_ffb', 'published_to_ros', 'target_association_verified'):
            self.assertIs(result[key], False)

    def test_tilted_floor_equation_and_scalar_equivalence(self):
        up = np.array([.1, -.98, .15]); up /= np.linalg.norm(up)
        ray = np.array([-.1, .5, .8]); ray /= np.linalg.norm(ray)
        h = .59
        result = camera_floor_offset(ray, up_optical=up, height_m=h)
        q = np.array(result['offset_optical_m'])
        p = q-h*up
        self.assertAlmostEqual(float(up @ p), -h)
        self.assertAlmostEqual(float(up @ q), 0.)
        np.testing.assert_allclose(p/np.linalg.norm(p), ray, atol=1e-14)
        scalar = math.sqrt((h/(-up @ ray))**2-h*h)
        self.assertAlmostEqual(result['horizontal_range_m'], scalar, places=13)

    def test_nadir_is_zero_vector_not_an_invalid_range(self):
        result = camera_floor_offset([0., 1., 0.], up_optical=[0., -1., 0.], height_m=.6)
        self.assertEqual(result['offset_optical_m'], [0., 0., 0.])
        self.assertEqual(result['horizontal_range_m'], 0.)

    def test_grazing_and_upward_are_unavailable(self):
        for ray in ([0., 0., 1.], [0., -1., 0.], [0., .029, math.sqrt(1-.029**2)]):
            self.assertIsNone(camera_floor_offset(ray, up_optical=[0., -1., 0.], height_m=.6))

    def test_incidence_boundary_matches_existing_range_policy(self):
        result = camera_floor_offset([0., .03, math.sqrt(1-.03**2)],
                                     up_optical=[0., -1., 0.], height_m=.6)
        self.assertIsNotNone(result)

    def test_bad_vectors_not_normalized_or_cast_from_booleans(self):
        for bad in ([0., 2., 0.], [0., 0., 0.], [True, False, False], [0., True, 0.],
                    [0., float('nan'), 1.], [0., float('inf'), 1.],
                    [0j, 1+0j, 0j], ['0', '1', '0'], [[0., 1., 0.]], [0., 1.]):
            for field in ('ray', 'up'):
                with self.subTest(bad=bad, field=field), self.assertRaises(ValueError):
                    camera_floor_offset(bad if field == 'ray' else [0., 1., 0.],
                        up_optical=bad if field == 'up' else [0., -1., 0.], height_m=.6)

    def test_bad_height_is_not_defaulted(self):
        for height in (0, -1, 3, True, '0.6', None, float('nan'), float('inf')):
            with self.subTest(height=height), self.assertRaises(ValueError):
                camera_floor_offset([0., .6, .8], up_optical=[0., -1., 0.], height_m=height)

    def test_input_not_changed(self):
        ray, up = [0., .6, .8], [0., -1., 0.]
        before = copy.deepcopy((ray, up))
        camera_floor_offset(ray, up_optical=up, height_m=.6)
        self.assertEqual((ray, up), before)

    def test_floor_normal_does_not_determine_vehicle_heading(self):
        # Two possible vehicle headings give different XY for the same
        # optical point and identical floor normal/radius. Neither is adopted.
        q = np.array(camera_floor_offset([0., .6, .8], up_optical=[0., -1., 0.],
                                       height_m=.6)['offset_optical_m'])
        rotation = np.array([[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]])
        yaw90 = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        a, b = rotation @ q, yaw90 @ rotation @ q
        np.testing.assert_allclose(a, [.8, 0., 0.], atol=1e-15)
        np.testing.assert_allclose(b, [0., .8, 0.], atol=1e-15)
        self.assertAlmostEqual(np.linalg.norm(a), np.linalg.norm(b))
        np.testing.assert_allclose(rotation @ [0., -1., 0.], yaw90 @ rotation @ [0., -1., 0.])

    def test_pure_geometry_module_not_connected_to_live_callers(self):
        tree = ast.parse((ROOT/'src/driver_motion_spatial.py').read_text())
        imports = [n.module if isinstance(n, ast.ImportFrom) else a.name
                   for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in (n.names if isinstance(n, ast.Import) else [None])]
        self.assertEqual(set(imports), {'math', 'numpy'})
        for path in (ROOT/'src').glob('*.py'):
            if path.name != 'driver_motion_spatial.py':
                self.assertNotIn('driver_motion_spatial', path.read_text(), str(path))


if __name__ == '__main__':
    unittest.main()
