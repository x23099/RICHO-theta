"""合成対照・背景除外試験の検証。実測精度を承認するテストではない。"""
import csv
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("transfer_limits_test",
    ROOT / "Experimental_results/2026-11-09/background_transfer_limits_r01/analyze.py")
limits = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(limits)
from angular_fisheye_geometry import floor_from_rays, unproject
from cone_distance_core import load_config


class BackgroundTransferLimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load_config()[1]
        cls.controls = {r["case"]: r for r in limits.tracking_cases(cls.camera)}

    def test_synthetic_grid_has_no_duplicate_correspondences(self):
        self.assertEqual(len(limits.SOURCE_PIXELS), 35)
        self.assertEqual(len(np.unique(limits.SOURCE_PIXELS, axis=0)), 35)
        split = limits.transfer.spatial_train_mask(limits.SOURCE_PIXELS)
        self.assertEqual(int(split.sum()), 18)
        self.assertEqual(int((~split).sum()), 17)

    def test_identity_and_true_rotations_recover_targets(self):
        for vector in ([0., 0., 0.], [.01, 0., 0.], [0., .01, 0.]):
            case = limits.motion_case(self.camera, 5., [0., 0., 0.], vector)
            self.assertTrue(case["model"]["accepted_for_offline_diagnostic"])
            self.assertLess(case["max_planar_error_m"], 1e-10)

    def test_independent_true_pose_recovers_translation_and_rotation(self):
        # 並進を正しく使えば真値へ戻る。誤差が投影式の不具合ではないことを確認。
        shift = np.array([.05, -.03, .08])
        rotation = cv2.Rodrigues(np.array([.005, -.01, .002]))[0]
        t = limits.REFERENCE_T
        optical = ((limits.FLOOR_TARGETS-t[:3, 3]) @ t[:3, :3]-shift) @ rotation.T
        pixels = limits.project_checked(optical, self.camera)
        rays, valid = unproject(pixels, self.camera, image_size=(1280, 720))
        actual_t = t.copy()
        actual_t[:3, :3] = t[:3, :3] @ rotation.T
        actual_t[:3, 3] = t[:3, 3] + t[:3, :3] @ shift
        points, accepted = floor_from_rays(rays, valid, actual_t)
        self.assertTrue(accepted.all())
        np.testing.assert_allclose(points, limits.FLOOR_TARGETS, atol=1e-12)

    def test_lateral_translation_can_pass_but_distance_remains_wrong(self):
        case = limits.motion_case(self.camera, 5., [.05, 0., 0.], [0., 0., 0.])
        self.assertTrue(case["model"]["accepted_for_offline_diagnostic"])
        self.assertGreater(case["max_planar_error_m"], .03)
        self.assertFalse(case["physical_metric_verified"])
        self.assertFalse(case["usable_for_ffb"])

    def test_heldout_corruption_is_rejected_without_distance(self):
        case = self.controls["heldout_only_wrong_8px"]
        self.assertFalse(case["model"]["accepted_for_offline_diagnostic"])
        self.assertTrue(case["distance_withheld"])
        self.assertIsNone(case["max_planar_error_m"])
        self.assertEqual(case["target_results"], [])

    def test_heldout_corruption_does_not_change_training_rotation(self):
        a = self.controls["correct_identity"]["model"]
        b = self.controls["heldout_only_wrong_8px"]["model"]
        self.assertEqual(a["rotation_current_from_reference"], b["rotation_current_from_reference"])

    def test_training_corruption_is_rejected_by_independent_points(self):
        case = self.controls["training_only_wrong_8px"]
        self.assertFalse(case["model"]["accepted_for_offline_diagnostic"])
        self.assertTrue(case["distance_withheld"])

    def test_partial_outliers_are_rejected(self):
        self.assertFalse(self.controls["every_fifth_wrong_8px"]["model"]["accepted_for_offline_diagnostic"])

    def test_coherent_wrong_matches_cannot_be_detected_by_residual_alone(self):
        case = self.controls["coherent_wrong_rotation_0p8deg"]
        self.assertTrue(case["model"]["accepted_for_offline_diagnostic"])
        self.assertLess(case["model"]["test_p90_px"], 1e-8)
        self.assertGreater(case["max_planar_error_m"], .09)
        self.assertFalse(case["physical_metric_verified"])

    def test_feature_loss_never_invents_an_identity_rotation(self):
        case = self.controls["insufficient_10_matches"]
        self.assertIsNone(case["model"]["rotation_current_from_reference"])
        self.assertIsNone(case["max_planar_error_m"])
        self.assertTrue(case["distance_withheld"])

    def test_concentrated_features_are_rejected_despite_sufficient_count(self):
        model = self.controls["narrow_40px_coverage"]["model"]
        self.assertGreaterEqual(model["matches"], 20)
        self.assertFalse(model["conditions"]["horizontal_span"])
        self.assertFalse(model["accepted_for_offline_diagnostic"])

    def test_large_true_rotation_is_rejected_despite_perfect_fit(self):
        model = self.controls["true_rotation_6deg"]["model"]
        self.assertLess(model["test_median_px"], 1e-8)
        self.assertFalse(model["conditions"]["small_rotation"])
        self.assertFalse(model["accepted_for_offline_diagnostic"])

    def test_target_truth_is_not_used_to_estimate_background(self):
        baseline = limits.motion_case(self.camera, 5., [.03, 0., 0.], [0., 0., 0.])
        with patch.object(limits, "FLOOR_TARGETS", np.array([[1.6, .1, 0.]])):
            changed = limits.motion_case(self.camera, 5., [.03, 0., 0.], [0., 0., 0.])
        self.assertEqual(baseline["model"], changed["model"])
        self.assertNotEqual(len(baseline["target_results"]), len(changed["target_results"]))

    def test_controls_do_not_mutate_source_pixels_or_pose(self):
        pixels, pose = limits.SOURCE_PIXELS.copy(), limits.REFERENCE_T.copy()
        limits.motion_case(self.camera, "mixed_3_10", [.03, 0., 0.], [0., .01, 0.])
        np.testing.assert_array_equal(limits.SOURCE_PIXELS, pixels)
        np.testing.assert_array_equal(limits.REFERENCE_T, pose)

    def test_real_jackknife_preserves_original_heldout_count(self):
        track = limits.transfer.GEOMETRY / "same_frame_pose_r01/background_tracks.csv"
        with track.open() as stream:
            rows = list(csv.DictReader(stream))
        rows = [r for r in rows if int(r["frame"]) == 38231]
        results = limits.real_track_jackknife(self.camera, rows)
        self.assertEqual(len(results), 11)
        for row in results:
            self.assertGreater(row["removed_training"], 0)
            self.assertEqual(row["model"]["test_count"], row["original_test_count"])
            self.assertFalse(row["model"]["usable_for_ffb"])

    def test_saved_stress_results_have_no_metric_or_runtime_promotion(self):
        folder = ROOT / "Experimental_results/2026-11-09/background_transfer_limits_r01/results_r01"
        summary = json.loads((folder / "summary.json").read_text())
        self.assertEqual(summary["synthetic_motion_cases"], 120)
        for key in ("screens_changed", "thresholds_fitted_to_E", "actual_camera_translation_measured",
                    "mirror_verified", "physical_metric_verified", "usable_for_ffb", "model_selected",
                    "runtime_changed", "published_to_ros", "camera_images_edited_or_exported"):
            self.assertIs(summary[key], False, key)


if __name__ == "__main__":
    unittest.main()
