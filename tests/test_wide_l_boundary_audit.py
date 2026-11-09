"""L字の辺交点・保留・補正の不成立を合成画像で検証。画像を書き出さない。"""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FOLDER = ROOT / "Experimental_results/2026-11-09/wide_l_boundary_audit_r01"
SPEC = importlib.util.spec_from_file_location("l_boundary_test_reliability", FOLDER / "audit_reliability.py")
reliability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reliability)
expanded, base = reliability.expanded, reliability.base


class LBoundaryAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = base.load_config()[1]

    def test_native_gray_contract_refuses_resized_or_float_images(self):
        for image in (np.zeros((360, 640), np.uint8), np.zeros((720, 1280), float)):
            with self.assertRaises(ValueError):
                base.native_gray(image)

    def test_extended_roi_can_recover_clipped_component_without_changing_corner_id(self):
        image = np.full((720, 1280), 200, np.uint8)
        image[389:392, 300:319] = 20
        image[379:392, 300:303] = 20
        seed = [300., 391.]
        _, old, reason = base.contour_and_corner(image, seed, 110)
        self.assertEqual(reason, "contour_reaches_local_roi_edge")
        contour, new, reason = expanded.expanded_contour(image, seed, 110, (24, 16))
        self.assertIsNone(reason)
        self.assertEqual(old, new)
        self.assertGreater(len(contour), 10)

    def test_expanded_roi_uses_only_the_selected_component(self):
        image, seed = reliability.synthetic_l(3., 0.)
        image[380:385, 338:342] = 0  # Separate dark object inside ROI.
        c, _, reason = expanded.expanded_contour(image, seed, 110, (24, 16))
        self.assertIsNone(reason)
        self.assertLess(c[:, 0].max(), 338)

    def test_nonpredeclared_roi_is_refused(self):
        image = np.zeros((720, 1280), np.uint8)
        with self.assertRaises(ValueError):
            expanded.expanded_contour(image, [320., 390.], 110, (60, 40))

    def test_constant_image_does_not_invent_convex_corner(self):
        image = np.full((720, 1280), 200, np.uint8)
        _, selected, _ = expanded.expanded_contour(image, [320., 390.], 110, (24, 16))
        self.assertIsNone(selected)

    def test_positive_threshold_crossing_recovers_known_offset(self):
        image = np.tile(np.clip(110+40*(np.arange(1280)-320), 0, 255), (720, 1)).astype(np.uint8)
        points, evidence, reason = base.threshold_crossings(image, [[320., 390.]], np.array([1., 0.]), 110)
        self.assertIsNone(reason)
        np.testing.assert_allclose(points, [[320., 390.]])
        self.assertAlmostEqual(evidence[0]["positive_gradient"], 40.)

    def test_weak_gradient_is_withheld_not_guessed(self):
        image = np.tile(np.clip(110+10*(np.arange(1280)-320), 0, 255), (720, 1)).astype(np.uint8)
        points, _, reason = base.threshold_crossings(image, [[320., 390.]], np.array([1., 0.]), 110)
        self.assertIsNone(points)
        self.assertEqual(reason, "weak_outward_gradient")

    def test_no_crossing_is_withheld(self):
        image = np.full((720, 1280), 200, np.uint8)
        point, _, reason = base.threshold_crossings(image, [[320., 390.]], np.array([1., 0.]), 110)
        self.assertIsNone(point)
        self.assertEqual(reason, "threshold_crossing_not_unique")

    def test_multiple_positive_crossings_are_not_resolved_by_nearest_distance(self):
        image = np.full((720, 1280), 200, np.uint8)
        image[:, 319] = 0
        image[:, 320] = 200
        image[:, 321] = 0
        image[:, 322] = 200
        points, _, reason = base.threshold_crossings(image, [[320., 390.]], np.array([1., 0.]), 90)
        self.assertIsNone(points)
        self.assertEqual(reason, "threshold_crossing_not_unique")

    def test_two_edge_ray_planes_recover_the_known_native_intersection(self):
        seed = np.array([320., 390.])
        rays, _ = base.unproject([seed], self.camera, image_size=(1280, 720))
        planes = []
        for direction in (np.array([1., 0., 0.]), np.array([0., 1., 0.])):
            rays_line = rays[0] + np.array([-.03, 0., .03])[:, None]*direction
            pixels, _ = base.project(rays_line, self.camera)
            normal, rms = base.ray_plane(pixels, self.camera)
            self.assertLess(rms, 1e-8)
            planes.append(normal)
        point, _, reason = base.intersect_planes(*planes, seed, self.camera)
        self.assertIsNone(reason)
        np.testing.assert_allclose(point, seed, atol=1e-8)

    def test_parallel_edges_do_not_invent_an_intersection(self):
        point, _, reason = base.intersect_planes(np.array([1., 0., 0.]), np.array([1., 0., 0.]),
                                                  np.array([320., 390.]), self.camera)
        self.assertIsNone(point)
        self.assertEqual(reason, "near_parallel_edge_planes")

    def test_too_few_edge_samples_are_refused(self):
        with self.assertRaises(ValueError):
            base.ray_plane([[320., 390.], [322., 390.]], self.camera)

    def test_sampling_never_extrapolates_outside_front_lens_rectangle(self):
        image = np.full((720, 1280), 200, np.uint8)
        for p in ([[-1., 390.]], [[650., 390.]]):
            with self.assertRaises(ValueError):
                base.sample_gray(image, p)

    def test_synthetic_outer_corner_is_approximately_recovered_without_image_changes(self):
        image, seed = reliability.synthetic_l(3., 0.)
        before = image.copy()
        contour, selected, reason = expanded.expanded_contour(image, seed, 110, (24, 16))
        self.assertIsNone(reason)
        result = base.edge_corner(image, contour, selected, 4, True, 110, self.camera)
        self.assertTrue(result["available"])
        self.assertLess(np.linalg.norm(np.asarray(result["point"])-seed), .15)
        self.assertFalse(result["physical_outer_corner_identity_verified"])
        np.testing.assert_array_equal(image, before)

    def test_returning_every_input_unchanged_is_not_seed_consistency_success(self):
        point = np.array([320., 390.])
        rows = [dict(available=True, point=(point+d).tolist(), seed_offset=d)
                for d in ([0., 0.], [.5, 0.], [-.5, 0.], [0., .5], [0., -.5])]
        result = reliability.classify_refinement(rows, point)
        self.assertEqual(result["input_returned_count"], 5)
        self.assertFalse(result["passed_seed_consistency_only"])

    def test_seed_stable_result_is_still_not_physical_approval(self):
        point = [320., 390.]
        rows = [dict(available=True, point=[320.2, 390.3], seed_offset=d)
                for d in ([0., 0.], [.5, 0.], [-.5, 0.], [0., .5], [0., -.5])]
        result = reliability.classify_refinement(rows, point)
        self.assertTrue(result["passed_seed_consistency_only"])
        self.assertFalse(result["physical_metric_verified"])
        self.assertFalse(result["usable_for_ffb"])

    def test_multiple_convergence_basins_are_withheld(self):
        rows = [dict(available=True, point=[320.2+i*.3, 390.3], seed_offset=[0., i*.5]) for i in range(3)]
        result = reliability.classify_refinement(rows, [320., 390.])
        self.assertEqual(result["reason"], "multiple_seed_dependent_outputs")
        self.assertFalse(result["passed_seed_consistency_only"])

    def test_two_expanded_rois_agree_on_shared_component_coordinates(self):
        rows = json.loads((FOLDER/"expanded_roi_r01/boundary_observations.json").read_text())
        lookup = {(r["frame"], r["label"], r["threshold"], r["method"]): r for r in rows}
        compared = 0
        for r in rows:
            if r["method"].endswith("roi24x16"):
                other = lookup[r["frame"], r["label"], r["threshold"], r["method"].replace("roi24x16", "roi32x20")]
                self.assertEqual(r["available"], other["available"])
                if r["available"]:
                    np.testing.assert_allclose(r["point"], other["point"], atol=1e-10)
                    compared += 1
        self.assertGreater(compared, 100)

    def test_missing_markers_do_not_fall_back_to_integer_coordinates(self):
        withheld = json.loads((FOLDER/"expanded_roi_r01/withheld_methods.json").read_text())
        self.assertGreater(len(withheld), 0)
        self.assertTrue(all(len(r["missing"]) > 0 for r in withheld))

    def test_results_do_not_select_by_known_range_or_promote_live(self):
        for sub in ("results_r01", "expanded_roi_r01", "reliability_r01"):
            summary = json.loads((FOLDER/sub/"summary.json").read_text())
            self.assertIsNone(summary["selected_method"])
            for key in ("camera_images_edited_or_exported", "runtime_changed", "physical_metric_verified", "usable_for_ffb"):
                self.assertIs(summary[key], False)


if __name__ == "__main__":
    unittest.main()
