"""診断処理だけのテスト。人工配列はメモリ内のみで、実験画像として保存しない。"""
import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from audit_saved_frame import contour_details
from compare_capture_layout import compare


class ColourAuditTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((720, 1280, 3), np.uint8)
        self.box = dict(x1=100., y1=100., x2=160., y2=200.)
        cv2.rectangle(self.image, (110, 110), (150, 195), (0, 0, 255), -1)

    def test_red_is_complete_without_background(self):
        d = contour_details(self.image, self.box, 4, "red")
        self.assertFalse(any(d["touches"].values()))
        self.assertEqual(d["contour_bounds_xyxy"], [110, 110, 150, 195])
        self.assertTrue(d["point_in_trimmed_support"])
        self.assertFalse(d["floor_contact_verified"])

    def test_union_merges_different_colour_background(self):
        cv2.rectangle(self.image, (90, 190), (170, 215), (0, 255, 255), -1)
        joined = contour_details(self.image, self.box, 4)
        red = contour_details(self.image, self.box, 4, "red")
        self.assertTrue(joined["touches"]["bottom"])
        self.assertTrue(joined["touches"]["left"])
        self.assertTrue(joined["touches"]["right"])
        self.assertFalse(any(red["touches"].values()))

    def test_does_not_modify_pixels(self):
        before = self.image.copy()
        contour_details(self.image, self.box, 4)
        np.testing.assert_array_equal(before, self.image)

    def test_no_contour_does_not_invent_point(self):
        d = contour_details(self.image, self.box, 4, "yellow")
        self.assertEqual(d["contour_areas"], [])
        self.assertNotIn("diagnostic_point_xy", d)

    def test_image_boundary_is_not_clipped_to_make_acceptance(self):
        d = contour_details(self.image, dict(x1=1., y1=2., x2=20., y2=50.), 4)
        self.assertTrue(d["outside_image"])

    def test_explicit_colour_only(self):
        with self.assertRaises(ValueError):
            contour_details(self.image, self.box, 4, "automatic")

    def test_blank_platform_does_not_prove_calibration(self):
        blank = np.zeros((720, 1280, 3), np.uint8)
        result = compare(blank, blank)
        self.assertEqual(result["status"], "INSUFFICIENT_FIXED_PLATFORM_MATCHES")
        self.assertFalse(result["intrinsics_transfer_verified"])


if __name__ == "__main__":
    unittest.main()
