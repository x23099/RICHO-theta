"""Offline/shadow completion tests; synthetic pixels are not camera evidence."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_colour_support_candidate import observe_separated_support
from cone_distance_core import ConeDistanceEngine, load_config
from cone_support_completion_candidate import _context, observe_lateral_completion
from theta_rtc_frames import NativeFrame

BOX = dict(x1=301., y1=305., x2=339., y2=405., class_id=0, confidence=.9)
WIDE = dict(BOX, x1=290., x2=350.)


def cone(colour=(0, 0, 255)):
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], colour)
    return image


class SupportCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load_config()[1]

    def test_lateral_clipped_component_completed_in_two_closed_contexts(self):
        image = cone()
        self.assertIsNone(observe_separated_support(image, BOX, self.camera)["point"])
        result = observe_lateral_completion(image, BOX, self.camera)
        self.assertTrue(result["completion_granted"])
        self.assertEqual(result["point"], [320, 400])
        first, second = result["contexts"][-2:]
        self.assertEqual(first["component"]["pixel_sha256"], second["component"]["pixel_sha256"])
        self.assertEqual(first["observation"], second["observation"])
        self.assertTrue(all(c["vertical_padding_px"] == 4 for c in result["contexts"]))

    def test_existing_red_and_yellow_points_preserved(self):
        for colour in ((0, 0, 255), (0, 255, 255)):
            image = cone(colour)
            before = observe_separated_support(image, WIDE, self.camera)
            after = observe_lateral_completion(image, WIDE, self.camera)
            for key in ("point", "support", "reason", "selected_colour"):
                self.assertEqual(after[key], before[key])
            self.assertEqual(after["contexts"], [])
            self.assertFalse(after["completion_granted"])

    def test_no_physical_or_controlling_authority(self):
        result = observe_lateral_completion(cone(), BOX, self.camera)
        for key in ("controlling_distance", "physical_metric_verified", "floor_contact_verified", "usable_for_ffb"):
            self.assertFalse(result[key])

    def test_bottom_connection_is_not_rescued(self):
        image = cone()
        cv2.rectangle(image, (280, 395), (360, 430), (0, 0, 255), -1)
        result = observe_lateral_completion(image, BOX, self.camera)
        self.assertIsNone(result["point"])
        self.assertFalse(result["completion_attempted"])
        self.assertEqual(result["completion_reason"], "not_lateral_only_contact")

    def test_yellow_floor_not_replaced_by_red_sticker(self):
        image = cone((0, 255, 255))
        cv2.rectangle(image, (280, 395), (360, 430), (0, 255, 255), -1)
        cv2.rectangle(image, (316, 370), (324, 380), (0, 0, 255), -1)
        result = observe_lateral_completion(image, BOX, self.camera)
        self.assertEqual(result["selected_colour"], "yellow")
        self.assertIsNone(result["point"])

    def test_lateral_background_still_open_is_rejected(self):
        image = cone()
        cv2.rectangle(image, (250, 390), (390, 400), (0, 0, 255), -1)
        result = observe_lateral_completion(image, BOX, self.camera)
        self.assertTrue(result["completion_attempted"])
        self.assertIsNone(result["point"])
        self.assertIn("context_rejected", result["completion_reason"])

    def test_competitor_in_outer_context_is_not_ignored(self):
        image = cone()
        cv2.rectangle(image, (285, 305), (292, 403), (0, 0, 255), -1)
        result = observe_lateral_completion(image, BOX, self.camera)
        self.assertIsNone(result["point"])
        self.assertIn("ambiguous_competing_colour_contours", result["completion_reason"])

    def test_completed_point_outside_original_bbox_is_rejected(self):
        result = observe_lateral_completion(cone(), dict(BOX, y2=398.), self.camera)
        self.assertIsNone(result["point"])
        self.assertEqual(result["completion_reason"], "completed_point_outside_original_bbox")

    def test_absent_or_mixed_seed_preserves_rejection(self):
        for image in (np.zeros((720, 1280, 3), np.uint8), cone()):
            if image.any():
                image[325:345, 320:324] = (0, 255, 255)
            old = observe_separated_support(image, BOX, self.camera)
            result = observe_lateral_completion(image, BOX, self.camera)
            self.assertIsNone(result["point"])
            self.assertEqual(result["reason"], old["reason"])
            self.assertFalse(result["completion_attempted"])

    def test_context_beyond_image_is_not_clamped(self):
        box = dict(BOX, x1=2., x2=40.)
        result, pixels, _ = _context(cone(), box, self.camera, "red", [10, 320, 15, 340], 8)
        self.assertEqual(result["reason"], "context_outside_native_image")
        self.assertIsNone(pixels)

    def test_rear_pixels_not_mapped_to_front(self):
        result = observe_lateral_completion(cone(), dict(BOX, x1=941., x2=979.), self.camera)
        self.assertEqual(result["reason"], "bbox_crosses_front_angular_domain")
        self.assertFalse(result["completion_attempted"])

    def test_no_resize_or_image_modification(self):
        image = cone()
        before = image.copy()
        observe_lateral_completion(image, BOX, self.camera)
        np.testing.assert_array_equal(image, before)
        with self.assertRaises(ValueError):
            observe_lateral_completion(np.zeros((360, 640, 3), np.uint8), BOX, self.camera)

    def test_repeatability_and_bounded_padding(self):
        image = cone()
        a = observe_lateral_completion(image, BOX, self.camera)
        b = observe_lateral_completion(image, BOX, self.camera)
        self.assertEqual(a, b)
        self.assertEqual([c["lateral_padding_px"] for c in a["contexts"]], [4, 8, 16])

    def test_new_module_is_not_used_by_current_engine(self):
        engine = ConeDistanceEngine(colour_support_shadow=True)
        engine.reset("synthetic")
        with patch("cone_support_completion_candidate.observe_lateral_completion", side_effect=AssertionError("must not control live")):
            row = engine.measure(NativeFrame("synthetic", 1, 0., 0., cone()), [BOX], .01)
        self.assertFalse(row["distance_available"])
        self.assertIsNone(row["colour_support_shadow"]["candidate"]["point"])
        self.assertNotIn("support_completion", row)


if __name__ == "__main__":
    unittest.main()
