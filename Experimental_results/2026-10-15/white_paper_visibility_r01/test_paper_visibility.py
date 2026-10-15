import unittest

import cv2
import numpy as np

from analyze import paper_corner, ROI


class PaperVisibilityTest(unittest.TestCase):
    def image(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.rectangle(image, (308, 369), (346, 381), (230, 230, 230), -1)
        return image

    def test_known_orientation_near_left_corner(self):
        r = paper_corner(self.image(), 170)
        self.assertTrue(r["corner_candidate"])
        self.assertEqual((r["pixel_x"], r["pixel_y"]), (308, 381))

    def test_physical_corner_and_ffb_never_verified(self):
        r = paper_corner(self.image(), 170)
        self.assertFalse(r["physical_corner_verified"])
        self.assertFalse(r["usable_for_ffb"])

    def test_blank_not_interpolated(self):
        r = paper_corner(np.zeros((720, 1280, 3), np.uint8), 170)
        self.assertFalse(r["corner_candidate"])
        self.assertIsNone(r["pixel_x"])
        self.assertIsNone(r["pixel_y"])

    def test_multiple_contours_fail_closed(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.rectangle(image, (300, 365), (310, 375), (230, 230, 230), -1)
        cv2.rectangle(image, (325, 365), (340, 375), (230, 230, 230), -1)
        self.assertEqual(paper_corner(image, 170)["reason"], "ambiguous_paper_contours")

    def test_roi_boundary_rejected(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.rectangle(image, (295, 365), (340, 380), (230, 230, 230), -1)
        self.assertEqual(paper_corner(image, 170)["reason"], "roi_edge_truncation")

    def test_small_extent_rejected(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.rectangle(image, (310, 370), (317, 378), (230, 230, 230), -1)
        self.assertEqual(paper_corner(image, 170)["reason"], "insufficient_image_extent")

    def test_not_a_generic_detector_outside_roi(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.rectangle(image, (500, 365), (540, 380), (230, 230, 230), -1)
        self.assertFalse(paper_corner(image, 170)["corner_candidate"])

    def test_bad_thresholds_rejected(self):
        for threshold in (-1, 256, 170.5, True):
            with self.assertRaises(ValueError):
                paper_corner(self.image(), threshold)

    def test_bad_frame_shape_and_dtype_rejected(self):
        for image in (np.zeros((360, 640, 3), np.uint8), np.zeros((720, 1280, 3), float)):
            with self.assertRaises(ValueError):
                paper_corner(image, 170)

    def test_source_image_is_unchanged(self):
        image = self.image()
        before = image.copy()
        paper_corner(image, 170)
        np.testing.assert_array_equal(image, before)

    def test_no_choice_of_threshold_from_reference_distance(self):
        image = self.image()
        candidates = [paper_corner(image, t) for t in (140, 170, 200)]
        self.assertTrue(all(r["corner_candidate"] for r in candidates))
        self.assertEqual(len({(r["pixel_x"], r["pixel_y"]) for r in candidates}), 1)

    def test_invalid_roi_rejected(self):
        for roi in ((-1, 360, 60, 30), (295, 360, 0, 30), (1270, 360, 60, 30)):
            with self.assertRaises(ValueError):
                paper_corner(self.image(), 170, roi)


if __name__ == "__main__":
    unittest.main()
