"""Synthetic-only checks for the offline corner stress audit."""
import copy
import importlib.util
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "paper_corner_sensitivity",
    ROOT / "Experimental_results/2026-11-09/paper_corner_sensitivity_r01/analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PaperCornerSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.settings, self.camera, _, _ = audit.load_config()
        rotation = np.array([[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]])
        world = np.array([[1.51, .148, .015], [1.51, -.148, .015],
                          [1.30, -.148, .015], [1.30, .148, .015]])
        self.pixels, valid = audit.audit.project((world - [0., 0., .59]) @ rotation, self.camera)
        self.assertTrue(valid.all())
        self.item = dict(session="synthetic", frame=1,
                         path=Path("synthetic/decoded_synthetic_f000001.png"), sha256="0" * 64)

    def models(self):
        return audit.fit(self.pixels, self.item, self.settings, self.camera)

    def test_all_unique_deterministic_perturbations_and_untouched_baseline(self):
        cases = list(audit.perturbations())
        self.assertEqual(len(cases), 573)
        self.assertEqual(len({c["id"] for c in cases}), 573)
        self.assertTrue(np.array_equal(cases[0]["offsets"], np.zeros((4, 2))))
        cases[1]["offsets"][0, 0] += 5
        self.assertTrue(np.array_equal(cases[0]["offsets"], np.zeros((4, 2))))

    def test_stress_vertices_cover_each_sign_combination_without_randomness(self):
        for amplitude in (.5, 1.):
            cases = [c for c in audit.perturbations() if c["kind"] == "all_coordinates_box_vertices" and c["amplitude"] == amplitude]
            self.assertEqual(len(cases), 256)
            self.assertEqual(len({tuple(c["offsets"].flat) for c in cases}), 256)
            self.assertTrue(all(np.all(np.abs(c["offsets"]) == amplitude) for c in cases))

    def test_single_coordinate_and_translation_offsets_are_not_mixed(self):
        for c in audit.perturbations():
            if c["kind"] == "one_coordinate":
                self.assertEqual(np.count_nonzero(c["offsets"]), 1)
                self.assertEqual(c["offsets"][c["corner"], "xy".index(c["axis"])], c["delta"])
            if c["kind"] == "translate_all_corners":
                self.assertEqual(np.count_nonzero(c["offsets"]), 4)
                self.assertTrue(np.all(c["offsets"][:, "xy".index(c["axis"])] == c["delta"]))

    def test_quad_order_is_image_only_and_winding_independent(self):
        expected = np.array([[1., 1.], [5., 1.], [5., 4.], [1., 4.]])
        for shift in range(4):
            for p in (expected, expected[::-1]):
                self.assertTrue(np.array_equal(audit.ordered_quad(np.roll(p, shift, axis=0)), expected))

    def test_malformed_and_nonconvex_quads_rejected(self):
        for p in ([[0, 0], [1, 1]], [[0, 0], [5, 0], [1, 1], [0, 5]],
                  [[0, 0], [5, 0], [5, float("nan")], [0, 5]]):
            with self.assertRaises(ValueError):
                audit.ordered_quad(p)

    def test_fit_keeps_both_dimensions_and_planar_solutions_without_authority(self):
        models = self.models()
        self.assertEqual(len(models), 8)
        for model in models:
            self.assertFalse(model["physical_metric_verified"])
            self.assertFalse(model["usable_for_ffb"])
            self.assertFalse(model["floor_contact_verified"])
        self.assertAlmostEqual(models[0]["camera_to_floor_m"], .59, places=7)

    def test_branch_tracking_detects_reversed_raw_indices(self):
        base = self.models()
        self.assertTrue(all(raw == family for (_, raw), family in audit.assignment_branch_map(base, base).items()))
        swapped = copy.deepcopy(base)
        for model in swapped:
            model["name"] = model["name"].replace("_s0_", "_TEMP_").replace("_s1_", "_s0_").replace("_TEMP_", "_s1_")
        result = audit.assignment_branch_map(swapped, base)
        self.assertTrue(all(raw != family for (_, raw), family in result.items()))
        self.assertEqual(len(result), 4)

    def test_external_height_is_control_not_a_corner_fitted_value(self):
        changed = self.pixels.copy()
        changed[0, 1] += .5
        models = audit.fit(changed, self.item, self.settings, self.camera)
        controls = [m for m in models if m["height_source"] == "external_height_image_normal"]
        self.assertEqual(len(controls), 4)
        self.assertTrue(all(m["camera_to_floor_m"] == .59 for m in controls))

    def test_local_height_derivative_converges_without_using_a_distance_label(self):
        values = []
        for step in (.125, .25):
            heights = []
            for sign in (-1, 1):
                changed = self.pixels.copy(); changed[0, 1] += sign * step
                heights.append(audit.fit(changed, self.item, self.settings, self.camera)[0]["camera_to_floor_m"])
            values.append((heights[1] - heights[0]) / (2 * step))
        self.assertLess(abs(values[0] - values[1]), 1e-5)

    def test_contour_scan_records_missing_or_nonquad_without_fallback(self):
        image = np.zeros((720, 1280, 3), np.uint8)
        quad, info = audit.contour_quad(image, (280, 390, 80, 40), 170, .02)
        self.assertIsNone(quad)
        self.assertEqual(info["reason"], "not_one_contour")
        image[397:415, 290:345] = 255
        quad, info = audit.contour_quad(image, (280, 390, 80, 40), 170, .02)
        self.assertEqual(info["reason"], "quad_observed")
        self.assertTrue(np.array_equal(quad, [[290, 397], [344, 397], [344, 414], [290, 414]]))


if __name__ == "__main__":
    unittest.main()
