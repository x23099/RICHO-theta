"""Synthetic pixels only. Bottom closure is NOT proof of the floor contact."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
PATH = ROOT/"Experimental_results/2026-11-10/bottom_extension_probe_r01/probe.py"
spec = importlib.util.spec_from_file_location("bottom_extension_probe", PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
from cone_distance_core import load_config
from cone_upper_support_candidate import observe_upper_completion

BOX = dict(x1=290., y1=305., x2=350., y2=395., class_id=0, confidence=.95)


def cone(colour=(0, 0, 255)):
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], colour)
    return image


class BottomExtensionProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load_config()[1]

    def test_clipped_cone_closes_but_new_lower_support_is_not_accepted(self):
        r = probe.probe_bottom_extension(cone(), BOX, self.camera)
        self.assertEqual(r["closure_only_point_NOT_safe"], [320, 400])
        self.assertFalse(r["guarded_candidate"])
        self.assertEqual(r["reason"], "original_lower_support_changed")

    def test_finite_connected_tail_also_closes_so_closure_alone_is_unsafe(self):
        image = cone()
        cv2.rectangle(image, (310, 397), (330, 408), (0, 0, 255), -1)
        r = probe.probe_bottom_extension(image, BOX, self.camera)
        self.assertEqual(r["closure_only_point_NOT_safe"], [320, 408])
        self.assertFalse(r["guarded_candidate"])
        self.assertEqual(r["reason"], "original_lower_support_changed")

    def test_peripheral_tail_may_close_only_if_original_support_unchanged(self):
        image = cone()
        cv2.rectangle(image, (296, 398), (298, 414), (0, 0, 255), -1)
        r = probe.probe_bottom_extension(image, dict(BOX, y2=405.), self.camera)
        self.assertTrue(r["guarded_candidate"])
        self.assertEqual(r["guarded_observation"]["point"], [320, 400])
        self.assertEqual(r["contexts"][0]["component"]["observed_lower_support"], r["guarded_observation"]["support"])
        self.assertFalse(r["live_authorized"])

    def test_long_tail_not_extended_unboundedly(self):
        image = cone()
        cv2.rectangle(image, (310, 397), (330, 480), (0, 0, 255), -1)
        r = probe.probe_bottom_extension(image, BOX, self.camera)
        self.assertFalse(r["guarded_candidate"])
        self.assertIsNone(r["closure_only_point_NOT_safe"])
        self.assertTrue(all(c["bottom_padding_px"] <= 32 for c in r["contexts"]))

    def test_existing_acceptances_verbatim_preserved(self):
        for colour in ((0, 0, 255), (0, 255, 255)):
            image, box = cone(colour), dict(BOX, y2=405.)
            old = observe_upper_completion(image, box, self.camera)
            r = probe.probe_bottom_extension(image, box, self.camera)
            self.assertEqual(r["guarded_observation"], old)
            self.assertFalse(r["guarded_candidate"])

    def test_blank_and_mixed_seed_not_rescued(self):
        for image in (np.zeros((720, 1280, 3), np.uint8), cone()):
            if image.any():
                image[325:345, 320:324] = (0, 255, 255)
            r = probe.probe_bottom_extension(image, BOX, self.camera)
            self.assertFalse(r["guarded_candidate"])
            self.assertIsNone(r["closure_only_point_NOT_safe"])

    def test_joint_bottom_and_side_not_rescued(self):
        r = probe.probe_bottom_extension(cone(), dict(BOX, x1=301., x2=339.), self.camera)
        self.assertEqual(r["reason"], "not_bottom_only_contact")

    def test_competing_patch_in_expanded_context_not_accepted(self):
        image = cone()
        cv2.rectangle(image, (288, 402), (352, 413), (0, 0, 255), -1)
        r = probe.probe_bottom_extension(image, BOX, self.camera)
        self.assertFalse(r["guarded_candidate"])

    def test_input_image_and_bbox_unchanged(self):
        image, box = cone(), copy.deepcopy(BOX)
        previous = image.copy()
        image.flags.writeable = False
        probe.probe_bottom_extension(image, box, self.camera)
        np.testing.assert_array_equal(image, previous)
        self.assertEqual(box, BOX)

    def test_wrong_resolution_rejected(self):
        with self.assertRaises(ValueError):
            probe.probe_bottom_extension(np.zeros((360, 640, 3), np.uint8), BOX, self.camera)

    def test_no_live_entrypoint_import(self):
        for name in ("driver_motion_process.py", "cone_motion_range.py", "run_cone_motion_live.py"):
            self.assertNotIn("bottom_extension_probe", (ROOT/"src"/name).read_text())


if __name__ == "__main__":
    unittest.main()
