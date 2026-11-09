"""相対回転の方向・検査分離・保留を合成入力で検証。物理承認ではない。"""
import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
SPEC = importlib.util.spec_from_file_location("background_transfer_test",
    ROOT/"Experimental_results/2026-11-09/background_rotation_transfer_r01/analyze.py")
transfer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transfer)
from angular_fisheye_geometry import floor_from_rays, project, unproject
from cone_distance_core import load_config


def synthetic_translation_control(camera):
    """5cm並進は背景回転検査を通り得る、という識別不能性の対照。"""
    pixels = np.array([[x, y] for x in (170, 230, 290, 350, 410, 470)
                       for y in (90, 150, 210)], float)
    pixels = np.vstack([pixels, pixels + [.2, .2]])
    rays, _ = unproject(pixels, camera, image_size=(1280, 720))
    background = rays * (5. / rays[:, 2, None])
    shift = np.array([.05, 0., 0.])
    current, _ = project(background - shift, camera)
    model = transfer.estimate_background_rotation(pixels, current, camera)
    transform = np.array([[0., 0., 1., .02], [-1., 0., 0., -.03],
                          [0., -1., 0., .59], [0., 0., 0., 1.]])
    target = np.array([[2., 0., 0.]])
    pixels_E, _ = project((target-transform[:3, 3]) @ transform[:3, :3] - shift, camera)
    candidate = transfer.transfer_floor_pose(dict(transform_floor_from_optical=transform.tolist(),
        geometry_consistent=True), model["rotation_current_from_reference"])
    metric = transfer.original.evaluate_E(pixels_E[0], [0., 2.], candidate,
                                          transfer.original.HYPOTHESES[0], camera)
    return dict(synthetic=True, physical_trial=False, camera_translation_m=shift.tolist(),
                background_optical_z_m=5., model=model, target_metric=metric)


class BackgroundRotationTransferTests(unittest.TestCase):
    def setUp(self):
        self.camera = load_config()[1]
        self.pixels = np.array([[x, y] for x in (170, 230, 290, 350, 410, 470)
                                for y in (90, 150, 210)], float)
        self.rotation = cv2.Rodrigues(np.array([.003, -.009, .001]))[0]
        rays, valid = unproject(self.pixels, self.camera, image_size=(1280, 720))
        self.assertTrue(valid.all())
        self.current, valid = project(rays @ self.rotation.T, self.camera)
        self.assertTrue(valid.all())
        self.T = np.array([[0., 0., 1., .02], [-1., 0., 0., -.03],
                           [0., -1., 0., .59], [0., 0., 0., 1.]])
        self.source = dict(transform_floor_from_optical=self.T.tolist(), geometry_consistent=True)

    def test_known_rotation_is_recovered_and_test_points_pass(self):
        # Repeat source points in another spatial cell pattern, not an E input.
        model = transfer.estimate_background_rotation(
            np.vstack([self.pixels, self.pixels + [.2, .2]]),
            np.vstack([self.current, self.current + [.2, .2]]), self.camera)
        self.assertTrue(model["accepted_for_offline_diagnostic"])
        np.testing.assert_allclose(model["rotation_current_from_reference"], self.rotation, atol=3e-5)
        self.assertFalse(model["translation_estimated"])
        self.assertFalse(model["usable_for_ffb"])

    def test_heldout_targets_cannot_change_the_fitted_rotation(self):
        p = np.vstack([self.pixels, self.pixels + [.2, .2]])
        q = np.vstack([self.current, self.current + [.2, .2]])
        baseline = transfer.estimate_background_rotation(p, q, self.camera)
        changed = q.copy()
        changed[~transfer.spatial_train_mask(p), 0] += 8
        rejected = transfer.estimate_background_rotation(p, changed, self.camera)
        self.assertFalse(rejected["accepted_for_offline_diagnostic"])
        self.assertEqual(baseline["rotation_current_from_reference"], rejected["rotation_current_from_reference"])

    def test_too_few_matches_does_not_invent_rotation(self):
        model = transfer.estimate_background_rotation(self.pixels[:5], self.current[:5], self.camera)
        self.assertFalse(model["accepted_for_offline_diagnostic"])
        self.assertIsNone(model["rotation_current_from_reference"])

    def test_floor_markers_cannot_be_passed_as_background(self):
        p, q = self.pixels.copy(), self.current.copy()
        p[0, 1] = 390
        with self.assertRaises(ValueError):
            transfer.estimate_background_rotation(p, q, self.camera)

    def test_spatial_partition_is_deterministic_and_input_unchanged(self):
        p = self.pixels.copy()
        before = p.copy()
        first = transfer.spatial_train_mask(p)
        np.testing.assert_array_equal(first, transfer.spatial_train_mask(p))
        self.assertTrue(first.any())
        self.assertTrue((~first).any())
        np.testing.assert_array_equal(p, before)

    def test_inverse_relative_rotation_preserves_known_world_intersection(self):
        target = np.array([[1.7, .1, 0.]])
        reference_optical = (target - self.T[:3, 3]) @ self.T[:3, :3]
        current_optical = reference_optical @ self.rotation.T
        current_rays = current_optical / np.linalg.norm(current_optical, axis=1)[:, None]
        new = transfer.transfer_floor_pose(self.source, self.rotation)
        points, valid = floor_from_rays(current_rays, np.array([True]), new["transform_floor_from_optical"])
        self.assertTrue(valid.all())
        np.testing.assert_allclose(points, target, atol=1e-12)

    def test_wrong_rotation_direction_does_not_recover_world_point(self):
        target = np.array([[1.7, .1, 0.]])
        optical = ((target - self.T[:3, 3]) @ self.T[:3, :3]) @ self.rotation.T
        rays = optical / np.linalg.norm(optical, axis=1)[:, None]
        wrong = transfer.transfer_floor_pose(self.source, self.rotation.T)
        points, valid = floor_from_rays(rays, np.array([True]), wrong["transform_floor_from_optical"])
        self.assertTrue(valid.all())
        self.assertGreater(np.linalg.norm(points-target), .01)

    def test_camera_position_and_height_are_not_refitted(self):
        before = np.array(self.source["transform_floor_from_optical"])
        model = transfer.transfer_floor_pose(self.source, self.rotation)
        actual = np.array(model["transform_floor_from_optical"])
        np.testing.assert_array_equal(actual[:3, 3], before[:3, 3])
        self.assertFalse(model["selected"])
        self.assertFalse(model["current_floor_points_used"])
        np.testing.assert_array_equal(self.source["transform_floor_from_optical"], before)

    def test_identity_keeps_source_pose(self):
        model = transfer.transfer_floor_pose(self.source, np.eye(3))
        np.testing.assert_array_equal(model["transform_floor_from_optical"], self.T)

    def test_reflection_or_scale_is_not_a_rotation(self):
        for bad in (np.diag([-1., 1., 1.]), np.eye(3)*2, np.zeros((2, 2))):
            with self.assertRaises(ValueError):
                transfer.checked_rotation(bad)

    def test_mirror_basis_uses_conjugation_not_improper_TF(self):
        reflected = transfer.rotation_for_hypothesis(self.rotation, transfer.original.HYPOTHESES[2])
        s = np.diag([-1., 1., 1.])
        np.testing.assert_allclose(reflected, s @ self.rotation @ s)
        self.assertAlmostEqual(np.linalg.det(reflected), 1.)

    def test_below_floor_source_is_not_promoted(self):
        source = dict(self.source, geometry_consistent=False)
        source["transform_floor_from_optical"] = self.T.copy()
        source["transform_floor_from_optical"][2, 3] = -.59
        model = transfer.transfer_floor_pose(source, self.rotation)
        self.assertFalse(model["geometry_consistent"])
        self.assertLess(model["camera_height_above_floor_m"], 0)

    def test_background_gate_can_pass_translation_without_physical_approval(self):
        control = synthetic_translation_control(self.camera)
        self.assertTrue(control["model"]["accepted_for_offline_diagnostic"])
        self.assertGreater(control["target_metric"]["planar_error_m"], .03)
        self.assertFalse(control["model"]["translation_estimated"])
        self.assertFalse(control["model"]["physical_metric_verified"])
        self.assertFalse(control["model"]["usable_for_ffb"])


if __name__ == "__main__":
    unittest.main()
