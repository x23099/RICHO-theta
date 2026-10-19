import json
from pathlib import Path
import unittest

import numpy as np

import analyze


class SavedAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = Path(__file__).resolve().parent/"results_r01"
        cls.summary = json.loads((cls.output/"summary.json").read_text())

    def test_all_frames_preserved_and_withheld_stays_missing(self):
        rows = analyze.read_csv(self.output/"all_frame_comparison.csv")
        self.assertEqual(len(rows), 1733*3)
        for name in ("recorded58", "height_only59", "paper_centre2"):
            group = [r for r in rows if r["model"] == name]
            self.assertEqual([int(r["frame"]) for r in group], list(range(1, 1734)))
        self.assertTrue(all(r["new_complete"] == "False" for r in rows if r["input_withheld"] == "True"))
        self.assertTrue(all(r["usable_for_ffb"] == "False" for r in rows))

    def test_legacy_equivalence_not_physical_accuracy(self):
        self.assertLess(self.summary["max_coordinate_difference_m"], 1e-9)
        self.assertEqual(self.summary["compared_columns"], 43614)
        self.assertEqual(self.summary["reason_disagreements"], 0)
        self.assertFalse(self.summary["calibration_fitted"])
        self.assertFalse(self.summary["live_tf_published"])
        self.assertFalse(self.summary["production_calls_changed"])

    def test_one_point_rank_recomputes_without_reference_distance_fit(self):
        previous = json.loads((analyze.PREVIOUS/"summary.json").read_text())
        result = analyze.sensitivity(previous["paper_reference_native_xy"], previous["models"]["height_only59"])
        self.assertEqual(result["rank"], 2)
        self.assertEqual(result["nullity"], 4)
        np.testing.assert_allclose(result["jacobian_scaled"], self.summary["sensitivity"]["jacobian_scaled"], atol=1e-12)
        self.assertLess(result["nullspace_residual_abs_max"], 1e-12)
        self.assertEqual(self.summary["independent_current_reference_points"], 1)
        self.assertFalse(self.summary["prior_seven_points_pooled"])

    def test_diagnostic_transform_is_not_base_link_measurement(self):
        transforms = json.loads((self.output/"diagnostic_transforms.json").read_text())
        for item in transforms.values():
            self.assertFalse(item["measured_extrinsics"])
            self.assertFalse(item["base_link_transform"])
            self.assertFalse(item["physical_output_permitted"])
            self.assertEqual(item["target_frame"], "camera_ground_reference_diagnostic")

    def test_source_and_outputs_unchanged(self):
        for path, digest in self.summary["source_sha256"].items():
            self.assertEqual(analyze.sha256(Path(path)), digest)
        for name, digest in self.summary["output_sha256"].items():
            self.assertEqual(analyze.sha256(self.output/name), digest)


if __name__ == "__main__":
    unittest.main()
