"""Native-size SYNTHETIC pixels, offline comparison only. No model or ROS."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from cone_bbox_boundary_shadow import POLICIES, boundary_contains, compare_boundary_observations
from cone_distance_core import load_config
from cone_upper_support_candidate import observe_upper_completion

BOX = dict(x1=301., y1=305., x2=339., y2=399.6, confidence=.95, class_id=0)


def cone(colour=(0, 0, 255)):
    pixels = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(pixels, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], colour)
    return pixels


class BboxBoundaryShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load_config()[1]

    def test_half_pixel_case_observed_point_is_never_clamped(self):
        r = compare_boundary_observations(cone(), BOX, self.camera)
        self.assertIsNone(r["baseline"]["point"])
        for item in r["comparisons"].values():
            self.assertTrue(item["changed"])
            self.assertEqual(item["observation"]["point"], [320, 400])
            self.assertGreater(item["observation"]["point"][1], BOX["y2"])

    def test_half_pixel_and_outward_integer_are_not_equivalent(self):
        r = compare_boundary_observations(cone(), dict(BOX, y2=399.4), self.camera)
        self.assertFalse(r["comparisons"]["half_pixel_overlap"]["changed"])
        self.assertTrue(r["comparisons"]["outward_integer_inclusive"]["changed"])

    def test_more_than_one_pixel_is_not_rescued(self):
        r = compare_boundary_observations(cone(), dict(BOX, y2=398.9), self.camera)
        self.assertTrue(all(not item["changed"] for item in r["comparisons"].values()))

    def test_old_red_yellow_acceptances_are_verbatim_preserved(self):
        for colour in ((0, 0, 255), (0, 255, 255)):
            for box in (dict(BOX, y2=405.), dict(BOX, x1=290., x2=350., y2=405.)):
                pixels = cone(colour)
                old = observe_upper_completion(pixels, box, self.camera)
                self.assertIsNotNone(old["point"])
                r = compare_boundary_observations(pixels, box, self.camera)
                self.assertEqual(r["baseline"], old)
                for item in r["comparisons"].values():
                    self.assertFalse(item["changed"])
                    self.assertEqual(item["observation"], old)

    def test_yellow_late_bbox_candidate_keeps_colour(self):
        r = compare_boundary_observations(cone((0, 255, 255)), BOX, self.camera)
        self.assertEqual(r["comparisons"]["half_pixel_overlap"]["observation"]["selected_colour"], "yellow")
        self.assertTrue(r["comparisons"]["half_pixel_overlap"]["changed"])

    def test_bottom_connection_never_rescued(self):
        pixels = cone()
        cv2.rectangle(pixels, (280, 395), (360, 430), (0, 0, 255), -1)
        r = compare_boundary_observations(pixels, BOX, self.camera)
        for item in r["comparisons"].values():
            self.assertFalse(item["changed"])
            self.assertIsNone(item["observation"]["point"])

    def test_competing_contour_never_rescued(self):
        pixels = cone()
        cv2.rectangle(pixels, (285, 305), (292, 403), (0, 0, 255), -1)
        r = compare_boundary_observations(pixels, BOX, self.camera)
        self.assertTrue(all(not item["changed"] for item in r["comparisons"].values()))

    def test_mixed_seed_never_rescued(self):
        pixels = cone()
        pixels[325:345, 320:324] = (0, 255, 255)
        r = compare_boundary_observations(pixels, BOX, self.camera)
        self.assertEqual(r["baseline"]["reason"], "ambiguous_upper_body_colour")
        self.assertTrue(all(not item["changed"] for item in r["comparisons"].values()))

    def test_still_open_lateral_background_never_rescued(self):
        pixels = cone()
        cv2.rectangle(pixels, (250, 390), (390, 400), (0, 0, 255), -1)
        r = compare_boundary_observations(pixels, BOX, self.camera)
        self.assertTrue(all(not item["changed"] for item in r["comparisons"].values()))

    def test_blank_frame_never_rescued(self):
        r = compare_boundary_observations(np.zeros((720, 1280, 3), np.uint8), BOX, self.camera)
        self.assertTrue(all(not item["changed"] for item in r["comparisons"].values()))

    def test_top_only_failure_is_not_a_lateral_bbox_candidate(self):
        pixels = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillPoly(pixels, [np.array([[320, 300], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
        r = compare_boundary_observations(pixels, dict(BOX, x1=290., x2=350.), self.camera)
        self.assertEqual(r["baseline"]["upper_completion_reason"], "upper_point_outside_original_bbox")
        self.assertTrue(all(not item["changed"] for item in r["comparisons"].values()))

    def test_new_results_never_grant_physical_or_control_authority(self):
        r = compare_boundary_observations(cone(), BOX, self.camera)
        self.assertFalse(r["live_authorized"])
        for item in r["comparisons"].values():
            for flag in ("controlling_distance", "physical_metric_verified", "floor_contact_verified", "usable_for_ffb"):
                self.assertIs(item["observation"][flag], False)

    def test_native_pixels_box_and_baseline_unchanged(self):
        pixels, box = cone(), copy.deepcopy(BOX)
        before = pixels.copy()
        pixels.flags.writeable = False
        baseline = observe_upper_completion(pixels, box, self.camera)
        old = copy.deepcopy(baseline)
        with patch("cone_bbox_boundary_shadow.observe_upper_completion", return_value=baseline):
            r = compare_boundary_observations(pixels, box, self.camera)
        r["comparisons"][POLICIES[0]]["observation"]["support"].clear()
        self.assertEqual(baseline, old)
        self.assertEqual(box, BOX)
        np.testing.assert_array_equal(pixels, before)

    def test_wrong_geometry_invalid_policy_and_noninteger_point_rejected(self):
        with self.assertRaises(ValueError):
            compare_boundary_observations(np.zeros((360, 640, 3), np.uint8), BOX, self.camera)
        for policy, point in (("unknown", [320, 400]), (POLICIES[0], [320, True])):
            with self.assertRaises(ValueError):
                boundary_contains(BOX, point, policy)

    def test_live_entry_points_have_no_import_of_offline_comparator(self):
        for name in ("driver_motion_process.py", "run_cone_motion_live.py", "cone_motion_range.py"):
            self.assertNotIn("cone_bbox_boundary_shadow", (ROOT/"src"/name).read_text())


if __name__ == "__main__":
    unittest.main()
