"""Offline one-factor geometry checks; no measured-error fitting."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('range_sensitivity_test',
    ROOT/'Experimental_results/2026-11-16/range_sensitivity_r01/analyze.py')
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


class SensitivityTests(unittest.TestCase):
    def setUp(self):
        self.model = dict(id='fixture', up_optical=[0., -1., 0.], height_m=.6)
        depression = math.radians(30)
        self.ray = np.array([0., math.sin(depression), math.cos(depression)])

    def test_horizontal_range_matches_independent_cotangent_formula(self):
        expected = .6/math.tan(math.radians(30))
        self.assertAlmostEqual(analysis.horizontal_range(self.ray, self.model), expected, places=12)

    def test_baseline_allows_roundoff_but_not_changed_recorded_value(self):
        self.assertLess(abs(analysis.checked_baseline(1.0051490635900897,
            1.0051490635900895, 1.0051490635900895)), 1e-12)
        for values in ((1.0052, 1.0051, 1.0051), (1.0051, 1.0051, math.nextafter(1.0051, math.inf))):
            with self.subTest(values=values), self.assertRaises(ValueError):
                analysis.checked_baseline(*values)

    def test_height_change_is_linear_without_changing_normal_or_ray(self):
        baseline = analysis.horizontal_range(self.ray, self.model)
        for dh in (-.01, .01):
            changed = dict(self.model, height_m=.6+dh)
            self.assertAlmostEqual(analysis.horizontal_range(self.ray, changed), baseline*(.6+dh)/.6, places=12)

    def test_tilt_matches_independent_depression_angle_and_preserves_unit_length(self):
        for angle in (-1., 0., 1.):
            changed = analysis.tilt_toward_ray(self.model, self.ray, angle)
            self.assertAlmostEqual(np.linalg.norm(changed['up_optical']), 1., places=12)
            self.assertAlmostEqual(analysis.horizontal_range(self.ray, changed),
                .6/math.tan(math.radians(30-angle)), places=12)

    def test_tilt_leaves_input_unchanged(self):
        prior = copy.deepcopy(self.model)
        ray = self.ray.copy()
        analysis.tilt_toward_ray(self.model, self.ray, 1.)
        self.assertEqual(self.model, prior)
        np.testing.assert_array_equal(self.ray, ray)

    def test_invalid_angle_nonunit_and_undefined_plane_rejected(self):
        for angle in (True, float('nan'), 6.):
            with self.subTest(angle=angle), self.assertRaises(ValueError):
                analysis.tilt_toward_ray(self.model, self.ray, angle)
        for ray in (self.ray*2, np.array([0., 1., 0.])):
            with self.subTest(ray=ray), self.assertRaises(ValueError):
                analysis.tilt_toward_ray(self.model, ray, 1.)

    def test_scenarios_change_one_input_at_a_time_and_do_not_mutate(self):
        from angular_fisheye_geometry import AngularCamera
        camera = AngularCamera([[150., 0., 320.], [0., 150., 360.], [0., 0., 1.]], [0., 0., 0., 0.], 1.6)
        point = [320, 435]
        prior = copy.deepcopy(self.model)
        cases = analysis.scenarios(point, camera, self.model)
        self.assertEqual(len(cases), 9)
        self.assertEqual(len({c['case'] for c in cases}), 9)
        self.assertEqual(cases[0]['delta_from_baseline_m'], 0.)
        for case in cases[1:]:
            self.assertEqual(sum(v != 0 for v in (case['dx_px'], case['dy_px'], case['height_change_m'],
                                                  case['normal_toward_ray_change_deg'])), 1)
            self.assertTrue(case['counterfactual_only'])
        self.assertEqual(self.model, prior)
        self.assertEqual(point, [320, 435])

    def fixture(self, path, rows, *, complete=True):
        blob = b''.join((json.dumps(row, separators=(',', ':'))+'\n').encode() for row in rows)
        if not complete:
            blob = blob[:-1]
        with path.open('xb') as stream:
            stream.write(blob)
        return blob, hashlib.sha256(blob).hexdigest()

    def test_exact_logged_line_hash_not_reserialized_json_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'main.jsonl'
            blob, digest = self.fixture(path, [dict(session='one', frame=10, value=1.)])
            found, hashes = analysis.verified_rows(path, digest, 'one', {10})
            self.assertEqual(found[10]['value'], 1.)
            self.assertEqual(hashes[10], hashlib.sha256(blob).hexdigest())
            self.assertNotEqual(hashes[10], hashlib.sha256((json.dumps(found[10])+'\n').encode()).hexdigest())

    def test_wrong_file_hash_missing_duplicate_and_wrong_session_rejected(self):
        fixtures = ([dict(session='one', frame=10)], [],
                    [dict(session='one', frame=10)]*2, [dict(session='two', frame=10)])
        for index, rows in enumerate(fixtures):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/'main.jsonl'
                _, digest = self.fixture(path, rows)
                with self.assertRaises(ValueError):
                    analysis.verified_rows(path, '0'*64 if index == 0 else digest, 'one', {10})

    def test_incomplete_line_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'main.jsonl'
            _, digest = self.fixture(path, [dict(session='one', frame=10)], complete=False)
            with self.assertRaises(ValueError):
                analysis.verified_rows(path, digest, 'one', {10})


if __name__ == '__main__':
    unittest.main()
