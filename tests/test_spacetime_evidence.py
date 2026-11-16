"""Synthetic conditional clocks/geometry are not real calibration."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('spacetime_diagnostics', ROOT/
    'Experimental_results/2026-11-16/spacetime_evidence_r01/diagnostics.py')
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
R = [[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]]


class SpacetimeEvidenceTests(unittest.TestCase):
    def test_one_way_offset_and_delay_are_not_identifiable(self):
        out = d.one_way_examples([10., 11.], [100.02, 101.04], alternative_shift_sec=.1)
        a, b = out['examples']
        self.assertAlmostEqual(a['conditional_delay_min_sec'], 0.)
        self.assertAlmostEqual(b['conditional_delay_min_sec'], .1)
        self.assertFalse(out['true_offset_identified'])
        self.assertFalse(out['upper_latency_bound_identified'])

    def test_example_shift_is_not_a_latency_bound(self):
        for shift in (.001, 1., 100.):
            out = d.one_way_examples([10.], [100.], alternative_shift_sec=shift)
            self.assertAlmostEqual(out['examples'][1]['conditional_delay_max_sec'], shift)
            self.assertFalse(out['clock_alignment_verified'])

    def test_bad_or_reversed_one_way_input(self):
        for a, b, shift in (([], [], .1), ([1.], [], .1), ([2., 1.], [3., 4.], .1),
                            ([True], [1.], .1), ([1.], [float('nan')], .1), ([1.], [2.], 0)):
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                d.one_way_examples(a, b, alternative_shift_sec=shift)

    def test_asymmetric_four_stamp_exchange_bounds_true_offset(self):
        out = d.four_stamp_interval(100., 10.02, 10.025, 100.055)
        self.assertAlmostEqual(out['receiver_minus_sender_offset_lower_sec'], 89.98)
        self.assertAlmostEqual(out['receiver_minus_sender_offset_upper_sec'], 90.03)
        self.assertAlmostEqual(out['conditional_half_width_sec'], .025)
        self.assertNotAlmostEqual(out['midpoint_sec'], 90.)
        self.assertFalse(out['path_symmetry_assumed'])

    def test_invalid_four_stamp_local_order_and_negative_network_time(self):
        for values in ((100., 10.02, 10., 101.), (100., 10., 10.01, 99.),
                       (100., 10., 11., 100.1), (True, 10., 10., 101.),
                       (100., 10., float('inf'), 101.), (10**1000, 10., 10., 101.)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                d.four_stamp_interval(*values)

    def test_origin_translation_is_not_camera_foot_translation(self):
        out = d.conditional_body_geometry([.3, 0., 1.], [0., -1., 0.], .59, R, [.2, .1, .59])
        np.testing.assert_allclose(out['conditional_support_body_m'], [1.2, -.2, 0.], atol=1e-12)
        np.testing.assert_allclose(out['conditional_camera_plumb_foot_body_m'], [.2, .1, 0.], atol=1e-12)
        self.assertIsNone(out['vehicle_xy_m'])
        self.assertFalse(out['real_mount_transform_verified'])

    def test_same_normal_and_scalar_do_not_determine_body_heading(self):
        yaw = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        a = d.conditional_body_geometry([0., 0., 1.], [0., -1., 0.], .59, R, [0., 0., .59])
        b = d.conditional_body_geometry([0., 0., 1.], [0., -1., 0.], .59, yaw @ R, [0., 0., .59])
        np.testing.assert_allclose(a['conditional_support_body_m'], [1., 0., 0.])
        np.testing.assert_allclose(b['conditional_support_body_m'], [0., 1., 0.])

    def test_reflections_nonrigid_and_wrong_up_rejected(self):
        for bad in (np.diag([-1., 1., 1.]) @ R, np.array(R)*2, np.eye(3)):
            with self.subTest(bad=bad.tolist()), self.assertRaises(ValueError):
                d.conditional_body_geometry([0., 0., 1.], [0., -1., 0.], .59, bad, [0., 0., .59])

    def test_bad_geometry_not_silently_normalized(self):
        for q in ([False, 0., 1.], [0., .59, 1.], [0., 0., float('nan')], [0., 1.], ['0', '0', '1']):
            with self.subTest(q=q), self.assertRaises(ValueError):
                d.conditional_body_geometry(q, [0., -1., 0.], .59, R, [0., 0., .59])

    def test_input_arrays_not_changed(self):
        q, r = np.array([0., 0., 1.]), np.array(R)
        before = q.copy(), r.copy()
        d.conditional_body_geometry(q, [0., -1., 0.], .59, r, [0., 0., .59])
        np.testing.assert_array_equal(q, before[0]); np.testing.assert_array_equal(r, before[1])
