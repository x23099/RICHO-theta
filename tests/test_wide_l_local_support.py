"""連結の色差補助・画素階段・保留の対照。カメラ画像を書き出さない。"""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
FOLDER = ROOT/"Experimental_results/2026-11-09/wide_l_local_support_r01"
SPEC = importlib.util.spec_from_file_location("local_support_test", FOLDER/"analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def colored_bridge(neutral=False):
    image = np.full((720, 1280, 3), 180, np.uint8)
    image[388:391, 320:337] = 20
    image[379:391, 320:323] = 20
    image[389:391, 334:380] = [20, 20, 20] if neutral else [0, 20, 180]
    gray = audit.cv2.cvtColor(image, audit.cv2.COLOR_BGR2GRAY)
    return image, gray


class WideLLocalSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = audit.base.load_config()[1]

    def test_color_auxiliary_breaks_colored_connection_without_moving_original_corner(self):
        bgr, gray = colored_bridge()
        _, old, evidence, reason = audit.selected_component(bgr, gray, [320, 390], 110, None)
        self.assertEqual(reason, "component_reaches_roi_edge")
        self.assertTrue(evidence["grayscale_component_touches_border"])
        contour, selected, evidence, reason = audit.selected_component(bgr, gray, [320, 390], 110, 80)
        self.assertIsNone(reason)
        self.assertEqual(selected, old)
        self.assertLess(evidence["filtered_component_area"], evidence["grayscale_component_area"])
        self.assertGreater(len(contour), 10)

    def test_neutral_dark_connection_is_not_falsely_removed_by_color(self):
        bgr, gray = colored_bridge(neutral=True)
        contour, _, _, reason = audit.selected_component(bgr, gray, [320, 390], 110, 80)
        self.assertIsNone(contour)
        self.assertEqual(reason, "component_reaches_roi_edge")

    def test_removing_original_corner_does_not_relocate_to_nearby_black_object(self):
        bgr = np.full((720, 1280, 3), 180, np.uint8)
        bgr[388:391, 320:334] = [0, 20, 160]
        bgr[379:391, 320:323] = [0, 20, 160]
        bgr[387:390, 326:329] = 10
        gray = audit.cv2.cvtColor(bgr, audit.cv2.COLOR_BGR2GRAY)
        contour, selected, _, reason = audit.selected_component(bgr, gray, [320, 390], 110, 80)
        self.assertIsNotNone(selected)
        self.assertIsNone(contour)
        self.assertEqual(reason, "chroma_filter_removed_original_corner")

    def test_color_filter_uses_absolute_difference_without_uint8_wrap(self):
        bgr, gray = colored_bridge()
        _, _, evidence, _ = audit.selected_component(bgr, gray, [320, 390], 110, 80)
        self.assertEqual(evidence["grayscale_component_chroma_max"], 180)

    def test_nonpredeclared_chroma_is_refused(self):
        bgr, gray = colored_bridge()
        with self.assertRaises(ValueError):
            audit.selected_component(bgr, gray, [320, 390], 110, 255)

    def test_native_image_inputs_are_not_modified(self):
        bgr, gray = colored_bridge()
        b, g = bgr.copy(), gray.copy()
        audit.selected_component(bgr, gray, [320, 390], 110, 80)
        np.testing.assert_array_equal(bgr, b)
        np.testing.assert_array_equal(gray, g)

    def test_color_only_boundary_cannot_fake_a_grayscale_crossing(self):
        bgr, gray = colored_bridge()
        contour, selected, _, reason = audit.selected_component(bgr, gray, [320, 390], 110, 80)
        self.assertIsNone(reason)
        fake_gray = np.full((720, 1280), 50, np.uint8)
        result = audit.edge_intersection(fake_gray, contour, selected, 4, "principal_axis", 110, self.camera)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "threshold_crossing_not_unique")

    def test_edge_comparison_on_synthetic_marker_remains_non_authoritative(self):
        bgr, gray = colored_bridge()
        contour, selected, _, _ = audit.selected_component(bgr, gray, [320, 390], 110, 80)
        result = audit.edge_intersection(gray, contour, selected, 4, "principal_axis", 110, self.camera)
        self.assertTrue(result["available"])
        # Background=180/dark=20: level 110 is NOT the 100 half-contrast level.
        # The linear intensity crossing is .5625 px from the dark pixel centre.
        fraction = (110.-20.)/(180.-20.)
        expected_isocross = [320.-fraction, 390.+fraction]
        self.assertLess(np.linalg.norm(np.asarray(result["point"])-expected_isocross), .01)
        self.assertFalse(result["physical_metric_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_pixel_staircase_can_have_three_samples_despite_first_step_rejection(self):
        contour = np.array([[320,391], [321,390], [322,390], [323,391], [324,390], [325,390],
                            [325,389], [324,389], [323,389], [322,389], [321,389], [320,389], [319,390]], float)
        old, _ = audit.base.arm_samples(contour, [320,391], 1, 4)
        new, reason = audit.principal_arm_samples(contour, [320,391], 1, 4)
        self.assertIsNone(old)
        self.assertIsNone(reason)
        self.assertEqual(len(new), 3)

    def test_principal_sampling_preserves_three_sample_minimum(self):
        contour = np.array([[320,390], [321,390], [322,390], [322,391],
                            [321,391], [320,391], [319,391], [319,390]], float)
        samples, reason = audit.principal_arm_samples(contour, [320,390], 1, 4)
        self.assertIsNone(samples)
        self.assertIn(reason, ("insufficient_arm_span", "backtracking_principal_arm_support"))

    def test_repeated_support_does_not_inflate_sample_count(self):
        contour = np.array([[320,390], [321,390], [322,390], [321,390],
                            [323,390], [324,390], [324,389], [323,389], [322,389], [321,389]], float)
        samples, reason = audit.principal_arm_samples(contour, [320,390], 1, 4)
        self.assertIsNone(samples)
        self.assertEqual(reason, "repeated_arm_samples")

    def test_nonunique_corner_is_withheld(self):
        contour = np.array([[320,390], [321,390], [320,390], [320,389], [319,390], [319,391]], float)
        samples, reason = audit.principal_arm_samples(contour, [320,390], 1, 4)
        self.assertIsNone(samples)
        self.assertEqual(reason, "nonunique_contour_corner")

    def test_nonfinite_contour_is_refused(self):
        with self.assertRaises(ValueError):
            audit.principal_arm_samples([[320,390],[float("nan"),391],[322,390]], [320,390], 1, 4)

    def test_unknown_arm_method_is_refused(self):
        with self.assertRaises(ValueError):
            audit.edge_intersection(np.full((720,1280),180,np.uint8), None, None, 4, "auto_best_distance", 110, self.camera)

    def test_missing_E_never_triggers_pose_fit_or_fallback(self):
        points = {k: [300+i*10, 400] for i, k in enumerate(audit.original.FIXED)}
        points["E"] = None
        with patch.object(audit.original, "fit_fixed", side_effect=AssertionError("unexpected fit")):
            evaluations, withheld = audit.evaluate_proposals({(38231,110,100,"principal_axis",4): points}, self.camera)
        self.assertEqual(evaluations, [])
        self.assertEqual(withheld[0]["missing"], ["E"])

    def test_changing_E_coordinates_does_not_change_pose_fit_input(self):
        fixed = {k: [280+i*10, 380+i*5] for i, k in enumerate(audit.original.FIXED)}
        inputs = []
        def capture(points, hypothesis, camera):
            inputs.append(np.array(points))
            return dict(candidates=[])
        for e in ([320,390], [330,400]):
            with patch.object(audit.original, "fit_fixed", side_effect=capture):
                audit.evaluate_proposals({(38231,110,100,"principal_axis",4): dict(fixed,E=e)}, self.camera)
        self.assertEqual(len(inputs), 6)
        for a, b in zip(inputs[:3], inputs[3:]):
            self.assertEqual(a.shape, (4,2))
            np.testing.assert_array_equal(a,b)

    def test_historical_grayscale_control_is_exactly_reproduced(self):
        summary = json.loads((FOLDER/"results_r01/summary.json").read_text())
        self.assertEqual(summary["historical_controls"], 384)
        self.assertEqual(summary["historical_controls_reproduced"], 384)
        self.assertFalse(summary["grayscale_route_changed"])

    def test_retained_conditions_include_degraded_not_only_best_coverage(self):
        summary = json.loads((FOLDER/"results_r01/summary.json").read_text())
        self.assertEqual(len(summary["coverage"]), 16)
        self.assertEqual(summary["observations"], 3072)
        counts = [r["complete_later_frames_at_threshold110"] for r in summary["coverage"]]
        self.assertIn(0, counts)
        self.assertIn(8, counts)
        self.assertIsNone(summary["selected_chroma_limit"])

    def test_diagnostic_results_do_not_promote_physical_or_live_status(self):
        summary = json.loads((FOLDER/"results_r01/summary.json").read_text())
        for key in ("E_used_for_extraction", "E_target_used_for_parameter_selection", "runtime_changed",
                    "camera_images_edited_or_exported", "physical_metric_verified", "usable_for_ffb",
                    "original_corner_relocated_after_color_filter", "mask_used_to_fake_grayscale_crossings"):
            self.assertIs(summary[key], False)


if __name__ == "__main__":
    unittest.main()
