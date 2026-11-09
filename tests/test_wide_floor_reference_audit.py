"""床4点の合成回帰検証。実機の鏡像・測量・精度の承認ではない。"""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("wide_floor_audit",
    ROOT / "Experimental_results/2026-11-09/wide_floor_geometry_r01/analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
from angular_fisheye_geometry import project, unproject
from cone_distance_core import load_config


class WideFloorAuditTests(unittest.TestCase):
    def setUp(self):
        self.camera = load_config()[1]
        self.T = np.array([[0., 0., 1., .02], [-1., 0., 0., -.03],
                           [0., -1., 0., .59], [0., 0., 0., 1.]])
        self.hypothesis = audit.HYPOTHESES[2]
        world = audit.vehicle_world(self.hypothesis)
        pixels, valid = project((world - self.T[:3, 3]) @ self.T[:3, :3], self.camera)
        self.assertTrue(valid.all())
        self.mirrored = audit.hypothesis_pixels(pixels, self.hypothesis, self.camera)

    def test_reflection_changes_ray_x_only_without_mutating_inputs(self):
        before = self.mirrored.copy()
        output = audit.hypothesis_pixels(before, self.hypothesis, self.camera)
        rays, _ = unproject(before, self.camera, image_size=(1280, 720))
        reflected, _ = unproject(output, self.camera, image_size=(1280, 720))
        np.testing.assert_allclose(reflected[:, 0], -rays[:, 0], atol=1e-12)
        np.testing.assert_allclose(reflected[:, 1:], rays[:, 1:], atol=1e-12)
        np.testing.assert_array_equal(before, self.mirrored)

    def test_unsupported_hypothesis_is_not_silently_selected(self):
        with self.assertRaises(ValueError):
            audit.hypothesis_pixels(self.mirrored, "auto", self.camera)
        with self.assertRaises(ValueError):
            audit.vehicle_world("auto")

    def test_fifth_fit_point_is_refused(self):
        with self.assertRaises(ValueError):
            audit.fit_fixed(np.vstack([self.mirrored, self.mirrored[0]]),
                            self.hypothesis, self.camera)

    def test_mirrored_correspondence_without_ray_control_is_below_floor(self):
        result = audit.fit_fixed(self.mirrored, audit.HYPOTHESES[1], self.camera)
        self.assertEqual(result["solution_count"], 2)
        for candidate in result["candidates"]:
            self.assertLess(candidate["camera_height_above_floor_m"], 0)
            self.assertFalse(candidate["geometry_consistent"])
            withheld = audit.evaluate_E(self.mirrored[0], [0., 1.4], candidate,
                                         audit.HYPOTHESES[1], self.camera)
            self.assertFalse(withheld["available"])
            self.assertIsNone(withheld["planar_error_m"])

    def test_explicit_reflection_control_recovers_proper_rotation_not_reflected_T(self):
        result = audit.fit_fixed(self.mirrored, self.hypothesis, self.camera)
        closest = min(result["candidates"], key=lambda c: c["fit_native_rmse_px"])
        np.testing.assert_allclose(closest["transform_floor_from_optical"], self.T, atol=1e-8)
        self.assertAlmostEqual(np.linalg.det(np.array(closest["transform_floor_from_optical"])[:3, :3]), 1.)
        self.assertIsNone(result["selected_solution"])
        self.assertFalse(result["physical_metric_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_holdout_is_recovered_without_using_it_for_fit(self):
        result = audit.fit_fixed(self.mirrored, self.hypothesis, self.camera)
        closest = min(result["candidates"], key=lambda c: c["fit_native_rmse_px"])
        target = np.array([[1.4, .2, 0.]])
        uv, _ = project((target - self.T[:3, 3]) @ self.T[:3, :3], self.camera)
        mirrored = audit.hypothesis_pixels(uv, self.hypothesis, self.camera)
        record = audit.evaluate_E(mirrored[0], [-.2, 1.4], closest, self.hypothesis, self.camera)
        self.assertTrue(record["available"])
        self.assertLess(record["planar_error_m"], 1e-8)
        wrong_target = audit.evaluate_E(mirrored[0], [42., 71.], closest, self.hypothesis, self.camera)
        self.assertAlmostEqual(wrong_target["predicted_X_m"], record["predicted_X_m"])
        self.assertAlmostEqual(wrong_target["predicted_Z_m"], record["predicted_Z_m"])
        unchanged = audit.fit_fixed(self.mirrored, self.hypothesis, self.camera)
        self.assertEqual(result, unchanged)

    def test_point_proposal_is_image_only_and_does_not_mutate_pixels(self):
        image = np.full((720, 1280), 200, np.uint8)
        image[390:401, 300:303] = 0
        image[398:401, 300:315] = 0
        before = image.copy()
        point = audit.outer_corner_proposal(image, [300, 400], 110)
        np.testing.assert_array_equal(point, [300, 400])
        np.testing.assert_array_equal(image, before)

    def test_empty_roi_does_not_return_the_seed_as_observation(self):
        image = np.full((720, 1280), 200, np.uint8)
        self.assertIsNone(audit.outer_corner_proposal(image, [300, 400], 110))
        with self.assertRaises(ValueError):
            audit.outer_corner_proposal(image[:600], [300, 400], 110)


if __name__ == "__main__":
    unittest.main()
