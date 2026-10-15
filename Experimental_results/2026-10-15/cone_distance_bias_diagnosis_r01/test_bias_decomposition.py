from copy import deepcopy
import unittest

import numpy as np

from analyze import decompose, project_pixels_to_floor, project_floor_to_pixels, REGIONS, match_region


class BiasDecompositionTest(unittest.TestCase):
    def setUp(self):
        self.geometry = dict(camera_height=.59, pitch_deg=1, roll_deg=2, yaw_deg=0,
                             radius_scale=.86, front_cx_offset=-80, front_cy_offset=-21,
                             back_cx_offset=82, back_cy_offset=-18)
        self.pixels = [[311, 393], [310, 393], [310.7, 395]]

    def test_terms_telescope(self):
        r = decompose(self.geometry, 2, *self.pixels)
        self.assertAlmostEqual(r["term_sum_m"], r["total_error_m"], places=14)

    def test_identical_points_remove_contact_and_bbox_terms(self):
        r = decompose(self.geometry, 2, *([self.pixels[0]]*3))
        self.assertEqual(r["manual_minus_floor_m"], 0)
        self.assertEqual(r["bbox_minus_manual_m"], 0)

    def test_zero_pixel_sensitivity_collapses_ranges(self):
        r = decompose(self.geometry, 2, *self.pixels, half_width=0)
        for key in ("floor_error", "manual_minus_floor", "bbox_minus_manual"):
            self.assertEqual(r[key+"_hypothetical_min_m"], r[key+"_hypothetical_max_m"])

    def test_height_changes_scale_not_pixel_labels(self):
        other = dict(self.geometry, camera_height=.58)
        first = project_pixels_to_floor(self.pixels, self.geometry)
        second = project_pixels_to_floor(self.pixels, other)
        np.testing.assert_allclose(first/second, .59/.58, rtol=1e-12)

    def test_moving_bbox_down_reduces_forward_projection(self):
        down = deepcopy(self.pixels)
        down[2][1] += 2
        first = decompose(self.geometry, 2, *self.pixels)
        second = decompose(self.geometry, 2, *down)
        self.assertLess(second["bbox_z_m"], first["bbox_z_m"])

    def test_reference_change_only_shifts_reference_term(self):
        first = decompose(self.geometry, 2, *self.pixels)
        second = decompose(self.geometry, 1.3, *self.pixels)
        self.assertAlmostEqual(second["total_error_m"]-first["total_error_m"], .7)
        self.assertEqual(first["manual_minus_floor_m"], second["manual_minus_floor_m"])
        self.assertEqual(first["bbox_minus_manual_m"], second["bbox_minus_manual_m"])

    def test_inputs_unchanged(self):
        original = deepcopy((self.geometry, self.pixels))
        decompose(self.geometry, 2, *self.pixels)
        self.assertEqual(original, (self.geometry, self.pixels))

    def test_world_round_trip(self):
        expected = np.array([[0, .8], [0, 1.3], [0, 2], [-.4, 1.3], [.4, 1.3]])
        pixels = project_floor_to_pixels(expected, self.geometry)
        np.testing.assert_allclose(project_pixels_to_floor(pixels, self.geometry), expected, atol=1e-12)

    def test_invalid_pixel_not_clamped(self):
        for value in (float("nan"), -1, 2000):
            bad = deepcopy(self.pixels)
            bad[2][0] = value
            with self.assertRaises(ValueError):
                decompose(self.geometry, 2, *bad)

    def test_wide_search_preserves_self_match_controls(self):
        # Nonperiodic synthetic native data: no source camera image transformed.
        image = np.random.default_rng(421).integers(0, 256, (720, 1280), dtype=np.uint8)
        for region in REGIONS:
            result = match_region(image, image, region, margin=40)
            self.assertTrue(result["reliable_for_local_feature_comparison"])
            self.assertEqual(result["delta_x_current_minus_reference_px"], 0)
            self.assertEqual(result["delta_y_current_minus_reference_px"], 0)


if __name__ == "__main__":
    unittest.main()
