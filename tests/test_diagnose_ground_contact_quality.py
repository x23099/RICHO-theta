import math
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from diagnose_ground_contact_quality import (adjacent_features, box_iou, contact_distribution,
                                            describe_frame, phase_at, phase_intervals, summarize)
from ground_contact import estimate_ground_contact


P = {"camera_height": .58, "blue_ground_contact_max_aspect_ratio": 1.5}


def frame_with_rectangle(width=40, value=255):
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.rectangle(image, (400 - width // 2, 450), (400 + width // 2, 510), (value, 0, 0), -1)
    return image


class GroundContactQualityTests(unittest.TestCase):
    def test_contact_distribution_matches_shared_estimator(self):
        contour = np.array([[[380, 450]], [[420, 450]], [[420, 510]], [[380, 510]]], np.int32)
        for fraction in (.02, .08, .16, .5):
            p = dict(P, blue_ground_contact_fraction=fraction)
            metrics = contact_distribution(contour, (720, 1280, 3), p)
            expected = estimate_ground_contact(contour, (720, 1280, 3), p, contact_fraction=fraction)
            self.assertAlmostEqual(metrics["contact_z_m"], expected["z_m"])
            self.assertEqual(metrics["contact_samples"], expected["contact_samples"])

    def test_no_downward_ground_rays_have_no_contact_distribution(self):
        contour = np.array([[[380, 100]], [[420, 100]], [[420, 150]], [[380, 150]]], np.int32)
        self.assertIsNone(contact_distribution(contour, (720, 1280, 3), P))

    def test_detected_frame_has_finite_quality(self):
        row = describe_frame(frame_with_rectangle(), P)
        self.assertEqual(row["detector_reason"], "detected")
        self.assertEqual(row["feature_contour_role"], "selected")
        for key in ("bbox_fill_ratio", "contour_solidity", "contact_z_iqr_m", "fraction_z_sensitivity_m"):
            self.assertTrue(math.isfinite(row[key]))
        self.assertEqual(row["dark_blue_hs_fraction"], 0)

    def test_aspect_rejection_is_not_given_a_contact(self):
        row = describe_frame(frame_with_rectangle(width=160), P)
        self.assertEqual(row["detector_reason"], "only_aspect_rejected")
        self.assertEqual(row["feature_contour_role"], "pre_aspect_reference")
        self.assertGreater(row["bbox_aspect_ratio"], 1.5)
        self.assertIsNone(row["contact_z_m"])
        self.assertIsNone(row["contact_z_iqr_m"])

    def test_blank_frame_reports_no_eligible_contour(self):
        row = describe_frame(np.zeros((720, 1280, 3), np.uint8), P)
        self.assertEqual(row["detector_reason"], "no_front_roi_contour_above_area")
        self.assertEqual(row["video_detected"], 0)
        self.assertIsNone(row["bbox_fill_ratio"])

    def test_none_aspect_limit_matches_unrestricted_production_behavior(self):
        row = describe_frame(frame_with_rectangle(width=160), dict(P, blue_ground_contact_max_aspect_ratio=None))
        self.assertEqual(row["detector_reason"], "detected")
        self.assertIsNotNone(row["contact_z_m"])

    def test_dark_hs_ratio_counts_pixels_lost_by_value_threshold(self):
        image = frame_with_rectangle()
        image[465:485, 390:410] = (20, 0, 0)
        row = describe_frame(image, P)
        self.assertEqual(row["video_detected"], 1)
        self.assertGreater(row["dark_blue_hs_fraction"], 0)
        self.assertLess(row["dark_blue_hs_fraction"], 1)

    def test_disappearing_detection_is_not_bridged_as_temporal_pair(self):
        base = dict(describe_frame(frame_with_rectangle(), P), time_sec=0, odom_available=1, odom_linear_mps=0)
        missing = dict(base, video_detected=0, time_sec=.033)
        current = dict(base, time_sec=.066)
        self.assertIsNone(adjacent_features(base, missing)["adjacent_motion_residual_m"])
        self.assertIsNone(adjacent_features(missing, current)["adjacent_motion_residual_m"])
        self.assertIsNone(adjacent_features(None, current)["adjacent_bbox_iou"])

    def test_ego_motion_residual_and_unavailable_odom(self):
        base = dict(describe_frame(frame_with_rectangle(), P), time_sec=0, odom_available=1, odom_linear_mps=.2)
        current = dict(base, time_sec=.1, contact_z_m=base["contact_z_m"] - .02)
        result = adjacent_features(base, current)
        self.assertAlmostEqual(result["adjacent_motion_residual_m"], 0)
        self.assertEqual(result["adjacent_bbox_iou"], 1)
        current["odom_available"] = 0
        self.assertIsNone(adjacent_features(base, current)["adjacent_motion_residual_m"])

    def test_box_iou(self):
        self.assertEqual(box_iou((0, 0, 2, 2), (0, 0, 2, 2)), 1)
        self.assertEqual(box_iou((0, 0, 2, 2), (2, 2, 2, 2)), 0)

    def test_phase_windows_follow_logged_forward_motion(self):
        rows = [{"time_sec": i, "odom_available": 1, "odom_linear_mps": .2 if i in (2, 3) else 0} for i in range(5)]
        interval = phase_intervals(rows)
        self.assertEqual(interval, (2, 3))
        self.assertEqual(phase_at(1.9, interval), "before_motion")
        self.assertEqual(phase_at(3, interval), "moving")
        self.assertEqual(phase_at(3.4, interval), "after_stop_transition")
        self.assertEqual(phase_at(3.6, interval), "after_stop_plus_0p5")
        self.assertEqual(phase_at(0, None), "no_forward_motion")

    def test_empty_summary_keeps_missing_metrics_not_zero(self):
        summary = summarize("empty", "empty", [])
        self.assertEqual(summary["frames"], 0)
        self.assertEqual(summary["contact_z_iqr_m_n"], 0)
        self.assertIsNone(summary["contact_z_iqr_m_median"])


if __name__ == "__main__":
    unittest.main()
