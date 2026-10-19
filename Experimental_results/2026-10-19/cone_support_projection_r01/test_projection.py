import copy
import json
from pathlib import Path
import unittest

import numpy as np

import run_projection as run
from cone_dataset import read_csv, sha256
from diagnose_box_contact_calibration import project_pixel
from metric_support import RANGE_FIELDS, bounds, compare_columns, project_columns


def simple_parameters():
    return dict(camera_height=.59, pitch_deg=0., roll_deg=0., yaw_deg=0., radius_scale=1.,
                front_cx_offset=0., front_cy_offset=0., back_cx_offset=0., back_cy_offset=0.)


def strings(rows):
    return [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows]


class ColumnProjectionTests(unittest.TestCase):
    def test_known_horizontal_ground_and_height_scaling(self):
        p = simple_parameters()
        a = project_columns([(400, 520)], p)[0]
        b = project_columns([(400, 520)], dict(p, camera_height=1.18))[0]
        self.assertEqual(a["reason"], "valid")
        self.assertAlmostEqual(a["x_m"], 0.)
        self.assertAlmostEqual(a["z_m"], .59)
        self.assertAlmostEqual(b["z_m"], 2*a["z_m"])

    def test_actual_columns_not_line_or_mean_projection(self):
        columns = [(390, 510), (400, 530), (410, 510)]
        result = project_columns(columns, simple_parameters())
        self.assertEqual([(r["pixel_x"], r["pixel_y"]) for r in result], columns)
        summary = bounds(result)
        self.assertTrue(summary["projection_complete"])
        self.assertGreater(summary["z_span_m"], .1)
        self.assertAlmostEqual(result[0]["x_m"], -result[2]["x_m"])
        self.assertAlmostEqual(summary["z_min_m"], min(r["z_m"] for r in result))
        self.assertFalse(any(r["floor_contact_verified"] or r["usable_for_ffb"] for r in result))

    def test_incomplete_projection_never_truncates_range(self):
        result = project_columns([(400, 520), (1200, 520)], simple_parameters())
        summary = bounds(result)
        self.assertEqual(len(result), 2)
        self.assertEqual(summary["valid_columns"], 1)
        self.assertEqual(summary["invalid_columns"], 1)
        self.assertFalse(summary["projection_complete"])
        self.assertTrue(all(summary[k] is None for k in RANGE_FIELDS))
        self.assertIn("outside_front_lens_or_optical_centre", summary["invalid_reasons"])

    def test_horizon_backwards_and_radial_range_reasons(self):
        p = simple_parameters()
        result = project_columns([(390, 350), (400, 370), (410, 660)], p)
        self.assertEqual(result[0]["reason"], "not_downward_floor_ray")
        self.assertEqual(result[1]["reason"], "outside_radial_diagnostic_range")
        self.assertEqual(result[2]["reason"], "outside_radial_diagnostic_range")
        self.assertGreater(result[1]["z_m"], 4.)  # unbounded value retained, not clipped
        self.assertIsNone(bounds(result)["z_min_m"])
        reverse = project_columns([(400, 520)], dict(p, yaw_deg=180))[0]
        self.assertEqual(reverse["reason"], "invalid_or_nonforward_floor_intersection")

    def test_bad_native_columns_rejected(self):
        cases = [[(1, 2.5)], [(1, float("nan"))], [(-1, 520)], [(1280, 520)], [(400, 720)],
                 [(400, 520), (400, 521)], [(401, 520), (400, 521)], [1, 2], [[]], [(1, 2, 3)]]
        for points in cases:
            with self.subTest(points=points), self.assertRaises(ValueError):
                project_columns(points, simple_parameters())

    def test_incomplete_or_bad_geometry_rejected(self):
        for key, value in (("camera_height", 0), ("radius_scale", -1), ("pitch_deg", float("inf"))):
            with self.assertRaises(ValueError):
                project_columns([(400, 520)], dict(simple_parameters(), **{key: value}))
        p = simple_parameters()
        del p["front_cy_offset"]
        with self.assertRaises(ValueError):
            project_columns([], p)

    def test_missing_curve_stays_missing(self):
        result = bounds(project_columns([], simple_parameters()))
        self.assertEqual(result["input_columns"], 0)
        self.assertEqual(result["projection_reason"], "no_observed_curve")
        self.assertFalse(result["projection_complete"])
        self.assertIsNone(result["z_median_m"])

    def test_pairwise_model_difference_is_same_pixel_not_extent_matching(self):
        pixels = [(390, 510), (400, 530), (410, 510)]
        a = project_columns(pixels, simple_parameters())
        b = project_columns(pixels, dict(simple_parameters(), camera_height=.60))
        comparison = compare_columns(a, b)
        self.assertEqual(comparison["compared_columns"], 3)
        self.assertAlmostEqual(comparison["dz_median_m"], np.median([q["z_m"]-p["z_m"] for p, q in zip(a, b)]))
        with self.assertRaises(ValueError):
            compare_columns(a, b[::-1])
        self.assertFalse(compare_columns([], [])["comparison_complete"])
        bad = project_columns([(390, 510), (400, 530), (1200, 510)], simple_parameters())
        self.assertFalse(compare_columns(bad, bad)["comparison_complete"])

    def test_input_not_mutated_and_no_hidden_temporal_state(self):
        columns, p = [(390, 510), (400, 530)], simple_parameters()
        before = copy.deepcopy((columns, p))
        first = project_columns(columns, p)
        project_columns([(400, 350)], p)
        self.assertEqual(project_columns(columns, p), first)
        self.assertEqual((columns, p), before)


class FullReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.curves, cls.status, cls.models, cls.refs, cls.hashes = run.load_inputs()
        cls.records, cls.differences, cls.samples = run.project_frames(cls.source, cls.curves, cls.status, cls.models)
        cls.summary = run.summarize(cls.records, cls.refs)
        cls.directory = run.HERE / "results_r01"

    def test_all_original_frames_in_each_model_and_pair_saved_exactly(self):
        self.assertEqual(len(self.records), 5143*3)
        self.assertEqual(len(self.differences), 5143*3)
        self.assertEqual(strings(self.records), read_csv(self.directory / "projected_ranges.csv"))
        self.assertEqual(strings(self.differences), read_csv(self.directory / "same_column_geometry_differences.csv"))
        self.assertEqual(strings(self.samples), read_csv(self.directory / "representative_columns.csv"))

    def test_summaries_saved_exactly_and_same_denominators(self):
        self.assertEqual(strings(self.summary), read_csv(self.directory / "summary.csv"))
        self.assertEqual(strings(run.summarize_differences(self.differences)), read_csv(self.directory / "geometry_difference_summary.csv"))
        self.assertEqual(strings(run.compare_sessions(self.summary)), read_csv(self.directory / "unpaired_session_comparison.csv"))
        for population in run.POPULATIONS:
            for model in run.MODELS:
                rows = [r for r in self.summary if r["population"] == population and r["model"] == model]
                self.assertEqual(sum(r["total_frames"] for r in rows), 5143)

    def test_withheld_or_missing_never_becomes_metric_observation(self):
        for r in self.records:
            self.assertFalse(r["usable_for_ffb"] or r["floor_contact_verified"])
            self.assertEqual(r["metric_observation_available"], r["quality_accepted"] and r["projection_complete"])
            if not r["metric_observation_available"]:
                self.assertTrue(all(r["observed_" + field] is None for field in RANGE_FIELDS))
        occlusion = [r for r in self.records if r["dataset"] == "sequence" and 1125 <= r["frame"] <= 1134]
        self.assertEqual(len(occlusion), 30)
        self.assertFalse(any(r["metric_observation_available"] for r in occlusion))
        self.assertTrue(any(r["projection_complete"] for r in occlusion))

    def test_projection_equals_existing_point_geometry_for_all_example_columns(self):
        for r in self.samples:
            old = project_pixel((r["pixel_x"], r["pixel_y"]), self.models[r["model"]])
            if r["reason"] == "valid":
                self.assertIsNotNone(old)
                np.testing.assert_allclose([r["x_m"], r["z_m"]], old, rtol=1e-12, atol=1e-12)

    def test_geometry_and_point_inputs_cannot_be_fitted_to_reference_labels(self):
        subset = self.source[:5]
        curves = {run.quality.key(r): self.curves[run.quality.key(r)] for r in subset}
        before = copy.deepcopy((subset, curves, self.models))
        first = run.project_frames(subset, curves, self.status, self.models)[0]
        changed = [dict(r, condition="NOT_USED_FOR_PROJECTION", reference_z_m=99) for r in subset]
        second = run.project_frames(changed, curves, self.status, self.models)[0]
        self.assertEqual([{k: v for k, v in r.items() if k != "condition"} for r in first],
                         [{k: v for k, v in r.items() if k != "condition"} for r in second])
        self.assertEqual((subset, curves, self.models), before)

    def test_mismatched_duplicate_orphan_sources_rejected(self):
        subset = self.source[:3]
        curves = {run.quality.key(r): self.curves[run.quality.key(r)] for r in subset}
        for rows, points in ((subset+[subset[-1]], curves), (subset, {}),
                             (subset, {**curves, ("orphan", "orphan", 1): [(1, 2)]})):
            with self.assertRaises(ValueError):
                run.project_frames(rows, points, self.status, self.models)

    def test_frozen_input_output_and_production_geometry_unchanged(self):
        provenance = json.loads((self.directory / "provenance.json").read_text())
        run.check_hashes(self.hashes)
        self.assertEqual(provenance["geometries"], self.models)
        for name, digest in provenance["output_sha256"].items():
            self.assertEqual(sha256(self.directory / name), digest)
        for flag in ("geometry_refitted", "physical_contact_inferred", "floor_contact_verified", "usable_for_ffb",
                     "runtime_integration_performed", "physical_output", "new_camera_images_saved"):
            self.assertIs(provenance[flag], False)


if __name__ == "__main__":
    unittest.main()
