"""Colour shadow checks; synthetic pixels never represent camera evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_colour_support_candidate import ColourSeedSettings, observe_separated_support
from cone_distance_core import ConeDistanceEngine, load_config, observe_support, support_from_colour_mask
from cone_distance_core import DEFAULT_CONFIG
from cone_distance_worker import DistanceWorker
from theta_rtc_frames import NativeFrame, LatestNativeFrame
from run_cone_distance_live import build_parser

BOX = dict(x1=290., y1=305., x2=350., y2=405., confidence=.9, class_id=0)


def cone(colour=(0, 0, 255)):
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], colour)
    return image


class ColourShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load_config()[1]

    def test_red_supported_without_changing_input(self):
        image = cone()
        before = image.copy()
        result = observe_separated_support(image, BOX, self.camera)
        self.assertEqual(result["selected_colour"], "red")
        self.assertEqual(result["point"], [320, 400])
        self.assertIn(result["point"], result["support"])
        self.assertFalse(result["controlling_distance"])
        self.assertFalse(result["floor_contact_verified"])
        self.assertFalse(result["usable_for_ffb"])
        np.testing.assert_array_equal(before, image)

    def test_yellow_is_not_dropped_from_model_scope(self):
        result = observe_separated_support(cone((0, 255, 255)), BOX, self.camera)
        self.assertEqual(result["selected_colour"], "yellow")
        self.assertEqual(result["point"], [320, 400])

    def test_red_over_yellow_background_is_split(self):
        image = cone()
        cv2.rectangle(image, (280, 395), (360, 420), (0, 255, 255), -1)
        image[395:401, 315:326] = (0, 0, 255)
        self.assertEqual(observe_support(image, BOX, self.camera)["reason"], "colour_contour_reaches_roi_edge")
        shadow = observe_separated_support(image, BOX, self.camera)
        self.assertEqual(shadow["selected_colour"], "red")
        self.assertIsNotNone(shadow["point"])

    def test_yellow_background_stays_rejected_no_red_sticker_fallback(self):
        image = cone((0, 255, 255))
        cv2.rectangle(image, (280, 395), (360, 420), (0, 255, 255), -1)
        cv2.rectangle(image, (316, 370), (324, 380), (0, 0, 255), -1)
        result = observe_separated_support(image, BOX, self.camera)
        self.assertEqual(result["selected_colour"], "yellow")
        self.assertIsNone(result["point"])
        self.assertEqual(result["reason"], "colour_contour_reaches_roi_edge")

    def test_missing_seed_does_not_guess_from_base(self):
        image = np.zeros((720, 1280, 3), np.uint8)
        cv2.rectangle(image, (300, 385), (340, 400), (0, 0, 255), -1)
        result = observe_separated_support(image, BOX, self.camera)
        self.assertIsNone(result["point"])
        self.assertEqual(result["reason"], "insufficient_upper_body_colour_evidence")

    def test_mixed_seed_stays_ambiguous(self):
        image = cone()
        image[325:345, 320:324] = (0, 255, 255)
        result = observe_separated_support(image, BOX, self.camera)
        self.assertIsNone(result["point"])
        self.assertEqual(result["reason"], "ambiguous_upper_body_colour")

    def test_rear_box_not_mapped_to_front(self):
        result = observe_separated_support(cone(), dict(BOX, x1=930., x2=990.), self.camera)
        self.assertEqual(result["reason"], "bbox_crosses_front_angular_domain")

    def test_no_resize(self):
        with self.assertRaises(ValueError):
            observe_separated_support(np.zeros((960, 1920, 3), np.uint8), BOX, self.camera)

    def test_settings_reject_nonfinite_and_relaxed_ambiguity(self):
        for values in (dict(min_dominant_fraction=.5), dict(central_width_fraction=float("nan")),
                       dict(min_coloured_pixels=True), dict(upper_y_end_fraction=.1)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ColourSeedSettings(**values)

    def test_shared_mask_guards_bounds(self):
        with self.assertRaises(ValueError):
            support_from_colour_mask(np.zeros((100, 100), np.uint8), 1250, 700)

    def test_default_engine_does_not_enable_candidate(self):
        engine = ConeDistanceEngine()
        engine.reset("test")
        frame = NativeFrame("test", 1, 0., 0., cone())
        result = engine.measure(frame, [BOX], .01)
        self.assertNotIn("colour_support_shadow", result)
        self.assertNotIn("selected_detector_boxes", result)

    def test_shadow_cannot_initialize_pose_or_grant_distance(self):
        engine = ConeDistanceEngine(colour_support_shadow=True)
        engine.reset("test")
        result = engine.measure(NativeFrame("test", 1, 0., 0., cone()), [BOX], .01)
        self.assertIsNotNone(result["colour_support_shadow"]["candidate"]["point"])
        self.assertFalse(result["distance_available"])
        self.assertFalse(result["scene_initialized"])
        self.assertIsNone(result["distance_forward_m"])
        self.assertFalse(result["colour_support_shadow"]["controlling_distance"])
        self.assertEqual(result["selected_detector_boxes"][0]["x1"], BOX["x1"])

    def test_shadow_cannot_replace_rejected_baseline_even_with_initialized_pose(self):
        engine = ConeDistanceEngine(colour_support_shadow=True)
        engine.reset("test")
        for index in range(4):
            frame = NativeFrame("test", index*30+1, float(index), float(index), cone())
            ticket = engine.begin_scene(frame)
            engine.complete_scene(ticket, dict(accepted=True, reason="synthetic_only",
                up=engine.prior_up.tolist()), index+.1)
        image = cone()
        cv2.rectangle(image, (280, 395), (360, 420), (0, 255, 255), -1)
        image[395:401, 315:326] = (0, 0, 255)
        result = engine.measure(NativeFrame("test", 100, 3.1, 3.1, image), [BOX], 3.11)
        self.assertTrue(result["scene_initialized"])
        self.assertIsNotNone(result["colour_support_shadow"]["candidate"]["point"])
        self.assertEqual(result["colour_reason"], "colour_contour_reaches_roi_edge")
        self.assertFalse(result["distance_available"])
        self.assertIsNone(result["distance_forward_m"])

    def test_worker_serializes_shadow_and_original_bbox_without_distance(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = LatestNativeFrame()
            slot.begin("synthetic")
            slot.publish("synthetic", cone(), 0., 10.)
            path = Path(directory)/"frames.jsonl"
            worker = DistanceWorker(slot, DEFAULT_CONFIG, lambda frame: [BOX], path,
                clock=lambda: 10., colour_support_shadow=True,
                scene_function=lambda *args: dict(accepted=False, reason="synthetic_only"))
            worker.start()
            try:
                self.assertTrue(worker.updated.wait(1))
            finally:
                worker.close()
            row = json.loads(path.read_text().splitlines()[0])
            self.assertEqual(row["selected_detector_boxes"][0]["x1"], BOX["x1"])
            self.assertIsNotNone(row["colour_support_shadow"]["candidate"]["point"])
            self.assertFalse(row["distance_available"])
            self.assertFalse(row["usable_for_ffb"])

    def test_same_time_inputs_have_same_controlling_results(self):
        engines = [ConeDistanceEngine(colour_support_shadow=value) for value in (False, True)]
        for engine in engines:
            engine.reset("test")
        for i in range(1, 5):
            frame = NativeFrame("test", i, i/30, i/30, cone())
            plain, shadow = [e.measure(frame, [BOX], i/30+.01) for e in engines]
            shadow.pop("colour_support_shadow")
            shadow.pop("selected_detector_boxes")
            self.assertEqual(plain, shadow)

    def test_shadow_failure_is_not_invalid_detector_and_does_not_alter_gates(self):
        engine = ConeDistanceEngine(colour_support_shadow=True)
        engine.reset("test")
        with patch("cone_colour_support_candidate.observe_separated_support", side_effect=RuntimeError("test only")):
            result = engine.measure(NativeFrame("test", 1, 0., 0., cone()), [BOX], .01)
        self.assertEqual(result["colour_reason"], "unverified_visible_colour_support")
        self.assertEqual(result["colour_support_shadow"]["candidate"]["reason"], "shadow_observation_error")
        self.assertNotIn("invalid_detector_output", result["blockers"])

    def test_cli_requires_explicit_shadow_flag(self):
        base = ["--weights", "dummy.pt", "--output-dir", "dummy"]
        self.assertFalse(build_parser().parse_args(base).colour_support_shadow)
        self.assertTrue(build_parser().parse_args([*base, "--colour-support-shadow"]).colour_support_shadow)


if __name__ == "__main__":
    unittest.main()
