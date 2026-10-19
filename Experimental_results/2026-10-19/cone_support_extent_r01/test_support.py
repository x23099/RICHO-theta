import copy
from pathlib import Path
import unittest

import numpy as np

import analyze_support as audit
from support import SETTINGS, describe_support, line_y_at, lower_envelope


def horizontal():
    return np.array([[x, 40] for x in range(41)])


class SupportGeometryTests(unittest.TestCase):
    def test_lower_envelope_keeps_max_y_per_column_without_filling_missing_columns(self):
        points = np.array([[1, 2], [1, 4], [3, 5], [5, 7], [3, 3]])
        before = points.copy()
        np.testing.assert_array_equal(lower_envelope(points), [[1, 4], [3, 5], [5, 7]])
        np.testing.assert_array_equal(points, before)

    def test_horizontal_support_is_interval_not_leftmost_bottom_subset(self):
        result, envelope, selected = describe_support(horizontal())
        self.assertTrue(result["line_consistent"])
        self.assertEqual((result["x_lo"], result["x_hi"]), (4, 36))
        self.assertEqual(len(selected), 33)
        self.assertEqual(len(envelope), 41)
        self.assertAlmostEqual(result["line_y_lo"], 40)
        self.assertAlmostEqual(result["line_y_hi"], 40)

    def test_sloped_boundary_is_retained_as_sloped_line(self):
        points = np.array([[x, 20+x//5] for x in range(41)])
        result, _, _ = describe_support(points)
        self.assertTrue(result["line_consistent"])
        self.assertAlmostEqual(result["slope"], .2, delta=.02)
        self.assertGreater(result["line_y_hi"], result["line_y_lo"])

    def test_input_order_and_duplicates_do_not_change_lower_envelope(self):
        points = horizontal()
        rng = np.random.default_rng(19)
        expected = describe_support(points)[0]
        actual = describe_support(rng.permutation(np.vstack((points, points))))[0]
        self.assertEqual(expected, actual)

    def test_horizontal_reflection_swaps_endpoints_not_support_side(self):
        points = np.array([[x, 20+x//5] for x in range(41)])
        mirrored = points.copy()
        mirrored[:, 0] = -mirrored[:, 0]
        a, b = describe_support(points)[0], describe_support(mirrored)[0]
        self.assertEqual((b["x_lo"], b["x_hi"]), (-a["x_hi"], -a["x_lo"]))
        self.assertAlmostEqual(a["slope"], -b["slope"], delta=.001)
        self.assertAlmostEqual(a["line_y_lo"], b["line_y_hi"], delta=.03)

    def test_translation_preserves_span_shape_and_y_difference(self):
        a, b = describe_support(horizontal())[0], describe_support(horizontal()+[100, -17])[0]
        self.assertEqual(a["span_px"], b["span_px"])
        self.assertEqual(a["slope"], b["slope"])
        self.assertAlmostEqual(b["line_y_lo"], a["line_y_lo"]-17)
        self.assertEqual(b["x_lo"], a["x_lo"]+100)

    def test_disconnected_support_is_not_interpolated_into_a_line(self):
        points = np.array([[x, 40] for x in list(range(15))+list(range(25, 41))])
        result, envelope, _ = describe_support(points)
        self.assertFalse(result["line_fitted"])
        self.assertEqual(result["reason"], "disconnected_support")
        self.assertFalse(any(15 <= p[0] <= 24 for p in envelope))

    def test_bent_lower_boundary_is_saved_even_when_single_line_is_inconsistent(self):
        points = np.array([[x, 20+abs(x-20)] for x in range(41)])
        result, envelope, _ = describe_support(points)
        self.assertTrue(result["envelope_available"])
        self.assertTrue(result["line_fitted"])
        self.assertFalse(result["line_consistent"])
        self.assertEqual(result["reason"], "nonlinear_or_multiedge_lower_boundary")
        self.assertEqual(len(envelope), 41)

    def test_narrow_support_keeps_extent_without_fabricating_line(self):
        result, envelope, selected = describe_support(np.array([[0, 1], [1, 1], [2, 1], [3, 1]]))
        self.assertTrue(result["envelope_available"])
        self.assertFalse(result["line_fitted"])
        self.assertGreater(len(selected), 0)
        self.assertIsNotNone(result["x_lo"])

    def test_interpolation_only_inside_observed_support(self):
        result = describe_support(horizontal())[0]
        self.assertIsNone(line_y_at(result, result["x_lo"]-1))
        self.assertIsNone(line_y_at(result, result["x_hi"]+1))
        self.assertIsNone(line_y_at(result, float("nan")))
        self.assertEqual(line_y_at(result, 20), 40)

    def test_steep_boundary_is_not_called_consistent_floor_edge(self):
        result = describe_support(np.array([[x, 2*x] for x in range(41)]))[0]
        self.assertFalse(result["line_consistent"])
        self.assertFalse(result["floor_contact_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_bad_floating_nonfinite_complex_and_shape_inputs_rejected(self):
        for p in ([], [[1, 2], [2, 3]], np.zeros((3, 3)), [[0, 0], [1, .5], [2, 1]],
                  [[0, 0], [1, 2], [2, float("inf")]], np.ones((3, 2), complex)):
            with self.assertRaises(ValueError):
                lower_envelope(p)


class ImageSupportTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((720, 1280, 3), np.uint8)
        self.image[304:397, 304:337] = (0, 0, 200)
        self.box = dict(x1=300, y1=300, x2=340, y2=400)

    def test_native_image_and_source_box_not_modified(self):
        before, box = self.image.copy(), copy.deepcopy(self.box)
        result, envelope, support = audit.inspect_image(self.image, [self.box])
        self.assertTrue(result["line_consistent"])
        self.assertGreater(len(envelope), 1)
        self.assertGreater(len(support), 1)
        np.testing.assert_array_equal(self.image, before)
        self.assertEqual(self.box, box)

    def test_missing_and_multiple_candidates_have_no_invented_support(self):
        for candidates in ([], [self.box, self.box]):
            result, envelope, support = audit.inspect_image(self.image, candidates)
            self.assertFalse(result["envelope_available"])
            self.assertEqual(envelope, [])
            self.assertEqual(support, [])

    def test_frozen_guard_failures_are_preserved(self):
        blank = np.zeros_like(self.image)
        edge = self.image.copy()
        edge[304:397, 296:337] = (0, 0, 200)
        for image in (blank, edge):
            frozen = audit.extract_bottoms(image, self.box)["legacy"]
            result, _, _ = audit.inspect_image(image, [self.box])
            self.assertFalse(result["envelope_available"])
            self.assertEqual(result["reason"], frozen["reason"])

    def test_visible_upper_fragment_can_have_a_line_but_is_not_verified_contact(self):
        image = np.zeros_like(self.image)
        image[320:351, 304:337] = (0, 0, 200)
        result, _, _ = audit.inspect_image(image, [self.box])
        self.assertTrue(result["line_consistent"])
        self.assertFalse(result["floor_contact_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_known_distance_labels_do_not_affect_support(self):
        self.assertEqual(audit.inspect_image(self.image, [self.box]),
                         audit.inspect_image(self.image, [dict(self.box, reference_z_m=999, frame=1134, condition="not_used")]))

    def test_native_resolution_dtype_required_even_with_no_candidates(self):
        for image in (self.image[:600], self.image.astype(float)):
            with self.assertRaises(ValueError):
                audit.inspect_image(image, [])


if __name__ == "__main__":
    unittest.main()
