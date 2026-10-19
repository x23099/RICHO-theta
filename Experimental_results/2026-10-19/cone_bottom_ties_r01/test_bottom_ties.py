import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from bottom_points import extract_bottoms, select_bottom

spec = importlib.util.spec_from_file_location("frozen_legacy_colour_pixels", HERE.parent / "cone_contact_reuse_r01/contact_pixels.py")
legacy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy_module)


class BottomSelectionTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((720, 1280, 3), np.uint8)
        self.image[304:397, 304:337] = (0, 0, 200)
        self.box = dict(x1=300, y1=300, x2=340, y2=400)
        binary = np.zeros((120, 80), np.uint8)
        binary[10:103, 10:43] = 255
        self.points = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0][0][:, 0, :]

    def test_symmetric_rectangle_reproduces_legacy_left_bias_and_fixes_it(self):
        result = extract_bottoms(self.image, self.box)
        self.assertEqual(result["legacy"]["pixel_x"], 313.5)
        self.assertEqual(result["tie_inclusive"]["pixel_x"], 320)
        self.assertEqual(result["legacy"]["pixel_y"], result["tie_inclusive"]["pixel_y"])
        self.assertEqual(result["legacy"]["excluded_cutoff_ties"], 13)
        self.assertEqual(result["tie_inclusive"]["excluded_cutoff_ties"], 0)

    def test_horizontal_mirror_equivariance_and_legacy_violation(self):
        mirrored = self.points.copy()
        mirrored[:, 0] = -mirrored[:, 0]
        for mode in ("legacy", "tie_inclusive"):
            a, b = select_bottom(self.points, mode), select_bottom(mirrored, mode)
            if mode == "tie_inclusive":
                self.assertEqual(a["pixel_x"], -b["pixel_x"])
                self.assertEqual(a["pixel_y"], b["pixel_y"])
            else:
                self.assertNotEqual(a["pixel_x"], -b["pixel_x"])

    def test_input_permutation_and_translation_invariance(self):
        rng = np.random.default_rng(19)
        point = select_bottom(self.points, "tie_inclusive")
        for _ in range(10):
            shuffled = rng.permutation(self.points)
            self.assertEqual(select_bottom(shuffled, "tie_inclusive"), point)
        shifted = select_bottom(self.points+[33, -11], "tie_inclusive")
        self.assertEqual((shifted["pixel_x"], shifted["pixel_y"]), (point["pixel_x"]+33, point["pixel_y"]-11))

    def test_complete_cutoff_row_is_included_and_min_three_points(self):
        p = select_bottom(self.points, "tie_inclusive")
        self.assertEqual(p["selected_points"], sum(self.points[:, 1] >= p["cutoff_y"]))
        small = select_bottom(np.array([[0, 0], [1, 1], [2, 0]]), "tie_inclusive")
        self.assertEqual(small["selected_points"], 3)

    def test_sloped_no_cutoff_tie_keeps_legacy_point(self):
        points = np.column_stack((np.arange(100), np.arange(100)))
        old, new = select_bottom(points, "legacy"), select_bottom(points, "tie_inclusive")
        self.assertEqual((old["pixel_x"], old["pixel_y"]), (new["pixel_x"], new["pixel_y"]))

    def test_arbitrary_asymmetric_contour_still_mirrors_without_known_centre(self):
        points = np.array([[0, 0], [0, 4], [1, 5], [2, 5], [3, 5], [4, 4], [6, 2], [5, 1]])
        mirrored = points.copy()
        mirrored[:, 0] *= -1
        a, b = select_bottom(points, "tie_inclusive"), select_bottom(mirrored, "tie_inclusive")
        self.assertEqual(a["pixel_x"], -b["pixel_x"])
        self.assertEqual(a["pixel_y"], b["pixel_y"])

    def test_bad_points_and_unknown_mode_rejected(self):
        for points in ([], [[1, 2], [3, 4]], np.zeros((3, 3)), [[1, 2], [2, 3], [float("nan"), 4]]):
            with self.assertRaises(ValueError):
                select_bottom(points, "tie_inclusive")
        with self.assertRaises(ValueError):
            select_bottom(self.points, "arbitrary")

    def test_red_yellow_and_unmodified_source(self):
        for colour in ((0, 0, 200), (0, 200, 200)):
            image = self.image.copy()
            image[304:397, 304:337] = colour
            before = image.copy()
            result = extract_bottoms(image, self.box)
            self.assertTrue(result["tie_inclusive"]["colour_candidate"])
            self.assertFalse(result["tie_inclusive"]["usable_for_ffb"])
            self.assertFalse(result["tie_inclusive"]["floor_contact_verified"])
            np.testing.assert_array_equal(image, before)

    def test_reference_fields_do_not_move_point(self):
        self.assertEqual(extract_bottoms(self.image, self.box), extract_bottoms(self.image, dict(self.box, reference_z_m=99, frame=1134)))

    def test_guard_failure_matches_frozen_legacy(self):
        blank = np.zeros_like(self.image)
        competing = blank.copy()
        competing[304:397, 304:317] = (0, 0, 200)
        competing[304:397, 324:337] = (0, 0, 200)
        edge = self.image.copy()
        edge[304:397, 296:337] = (0, 0, 200)
        tiny = blank.copy()
        tiny[304:397, 318:321] = (0, 0, 200)
        dim = blank.copy()
        dim[304:397, 304:337] = (0, 0, 25)
        for image, box in ((blank, self.box), (competing, self.box), (edge, self.box),
                           (tiny, self.box), (dim, self.box), (blank, dict(x1=1, y1=300, x2=40, y2=400))):
            expected = legacy_module.colour_bottom(image, box, 30)
            for actual in extract_bottoms(image, box).values():
                self.assertEqual(actual["colour_candidate"], expected["colour_candidate"])
                self.assertEqual(actual["reason"], expected["reason"])

    def test_legacy_matches_frozen_helper_on_synthetic_shapes(self):
        for height in (20, 50, 93):
            for width in (7, 20, 33):
                image = np.zeros_like(self.image)
                image[304:304+height, 304:304+width] = (0, 0, 200)
                expected = legacy_module.colour_bottom(image, self.box, 30)
                actual = extract_bottoms(image, self.box)["legacy"]
                for field in ("colour_candidate", "reason", "pixel_x", "pixel_y"):
                    self.assertEqual(actual[field], expected[field])

    def test_native_size_dtype_bbox_errors(self):
        for image in (self.image[:600], self.image.astype(float)):
            with self.assertRaises(ValueError):
                extract_bottoms(image, self.box)
        with self.assertRaises(ValueError):
            extract_bottoms(self.image, dict(self.box, x1=350))


if __name__ == "__main__":
    unittest.main()
