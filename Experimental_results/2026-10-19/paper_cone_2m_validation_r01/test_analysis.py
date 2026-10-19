"""Local reader guards and saved-recording consistency, without GPU/ROS."""
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

import analyze as diagnostic


class LocalReaderTests(unittest.TestCase):
    def test_paper_corner_is_actual_native_left_column(self):
        im = np.zeros((720, 1280, 3), np.uint8)
        im[360:372, 313:351] = 230
        original = im.copy()
        result = diagnostic.local_paper_corner(im, 170)
        self.assertTrue(result["candidate"])
        self.assertEqual((result["pixel_x"], result["pixel_y"]), (313, 371))
        self.assertFalse(result["usable_for_ffb"])
        np.testing.assert_array_equal(im, original)

    def test_paper_lower_roi_truncation_is_rejected(self):
        im = np.zeros((720, 1280, 3), np.uint8)
        im[360:390, 313:351] = 230
        self.assertFalse(diagnostic.local_paper_corner(im, 170)["candidate"])

    def test_blank_cannot_invent_paper_or_cone(self):
        im = np.zeros((720, 1280, 3), np.uint8)
        self.assertFalse(diagnostic.local_paper_corner(im, 170)["candidate"])
        self.assertIsNone(diagnostic.red_support(im)[0])

    def test_red_lower_support_not_interpolated(self):
        im = np.zeros((720, 1280, 3), np.uint8)
        im[310:373, 300:331] = (0, 0, 220)
        support, _ = diagnostic.red_support(im)
        self.assertTrue(len(support) >= 8)
        self.assertTrue(np.all(support[:, 1] == 372))
        self.assertTrue(np.equal(support, np.rint(support)).all())

    def test_red_roi_edge_truncation_is_rejected(self):
        im = np.zeros((720, 1280, 3), np.uint8)
        im[310:373, 285:331] = (0, 0, 220)
        support, reason = diagnostic.red_support(im)
        self.assertIsNone(support)
        self.assertEqual(reason, "red_roi_edge_truncation")

    def test_non_native_input_rejected(self):
        for reader in (lambda im: diagnostic.local_paper_corner(im, 170), diagnostic.red_support):
            with self.assertRaises(ValueError):
                reader(np.zeros((360, 640, 3), np.uint8))

    def test_saved_results_hashes_and_checks(self):
        output = Path(__file__).resolve().parent/"analysis_r01"
        result = json.loads((output/"summary.json").read_text())
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["frame_count"], 1733)
        self.assertLess(result["max_direct_pinhole_coordinate_difference_m"], 1e-9)
        self.assertFalse(result["yolo_reinference"])
        for name, digest in result["output_sha256"].items():
            self.assertEqual(diagnostic.sha256(output/name), digest)
        for name, digest in result["source_sha256"].items():
            self.assertEqual(diagnostic.sha256(Path(name)), digest)


if __name__ == "__main__":
    unittest.main()
