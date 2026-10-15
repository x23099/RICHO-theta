from copy import deepcopy
import unittest

from analyze import required_common_band, sampled_band


class PixelUncertaintyTest(unittest.TestCase):
    def setUp(self):
        self.p = dict(camera_height=.59, pitch_deg=1, roll_deg=2, yaw_deg=0,
                      radius_scale=.86, front_cx_offset=-80, front_cy_offset=-21,
                      back_cx_offset=82, back_cy_offset=-18)

    def test_overlap_minimum_and_symmetry(self):
        self.assertEqual(required_common_band([311, 387], [311, 393]), 3)
        self.assertEqual(required_common_band([311, 393], [311, 387]), 3)

    def test_x_and_y_both_matter(self):
        self.assertEqual(required_common_band([300, 400], [312, 402]), 6)

    def test_identical_points_need_no_band(self):
        self.assertEqual(required_common_band([300, 400], [300, 400]), 0)

    def test_invalid_points_rejected(self):
        for bad in ([float("nan"), 1], [1], [float("inf"), 2]):
            with self.assertRaises(ValueError):
                required_common_band(bad, [300, 400])

    def test_grid_count_and_conservation(self):
        r = sampled_band([311, 393], self.p, 3)
        self.assertEqual(r["attempted_samples"], 49)
        self.assertEqual(r["valid_samples"]+r["invalid_samples"], 49)

    def test_all_invalid_not_filled_with_zero(self):
        # Exact optical-centre pixel is excluded by the shared ray function.
        r = sampled_band([320, 339], self.p, 0)
        self.assertEqual(r["valid_samples"], 0)
        self.assertIsNone(r["sampled_z_min_m"])
        self.assertIsNone(r["sampled_x_min_m"])

    def test_nested_grids_have_nested_sampled_envelopes(self):
        small = sampled_band([311, 393], self.p, 1)
        wide = sampled_band([311, 393], self.p, 3)
        for axis in ("x", "z"):
            self.assertLessEqual(wide[f"sampled_{axis}_min_m"], small[f"sampled_{axis}_min_m"])
            self.assertGreaterEqual(wide[f"sampled_{axis}_max_m"], small[f"sampled_{axis}_max_m"])

    def test_bad_widths_and_outside_native_bands_rejected(self):
        for width in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                sampled_band([311, 393], self.p, width)
        with self.assertRaises(ValueError):
            sampled_band([1, 393], self.p, 3)

    def test_source_inputs_not_modified(self):
        pixel = [311, 393]
        original = deepcopy((pixel, self.p))
        sampled_band(pixel, self.p, 2)
        self.assertEqual(original, (pixel, self.p))

    def test_height_scale_preserved(self):
        first = sampled_band([311, 393], self.p, 2)
        second = sampled_band([311, 393], dict(self.p, camera_height=.58), 2)
        for key in ("sampled_z_min_m", "sampled_z_max_m"):
            self.assertAlmostEqual(first[key]/second[key], .59/.58)


if __name__ == "__main__":
    unittest.main()
