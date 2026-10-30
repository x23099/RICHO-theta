"""Checks for the saved-data support-point physical-meaning evaluation.

These tests read only the frozen r01 outputs and saved input CSVs.  They do not
decode images, run inference, or touch the live cone-distance path.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "Experimental_results/2026-10-30/support_point_physical_eval_r01"
RESULTS = EVAL / "results_r01"

_spec = importlib.util.spec_from_file_location("support_point_analyze", EVAL / "analyze.py")
analyze = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyze)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ImpliedHeightAlgebraTests(unittest.TestCase):
    def test_identity_at_reference_distance(self):
        self.assertAlmostEqual(analyze.implied_height_mm(0.59, 2.0, 2.0), 590.0)
        self.assertAlmostEqual(analyze.implied_height_mm(0.59, 1.3, 1.3), 590.0)

    def test_scales_inversely_with_projected_range(self):
        # A support point projecting farther than the label implies a taller lens.
        self.assertAlmostEqual(analyze.implied_height_mm(0.59, 2.0, 4.0), 295.0)
        self.assertAlmostEqual(analyze.implied_height_mm(0.59, 2.0, 1.0), 1180.0)

    def test_rejects_invalid_projection(self):
        with self.assertRaises(ValueError):
            analyze.implied_height_mm(0.59, 2.0, 0.0)
        with self.assertRaises(ValueError):
            analyze.implied_height_mm(0.59, 2.0, None)


class KnownMedianTests(unittest.TestCase):
    EXPECTED = {
        ("sequence", "cone_130"): 589.9,
        ("sequence", "cone_200"): 592.7,
        ("static", "center_080"): 531.7,
        ("static", "center_130"): 502.0,
        ("static", "center_200"): 446.1,
        ("static", "left_130"): 538.3,
        ("static", "right_130"): 490.4,
    }

    @classmethod
    def setUpClass(cls):
        cls.rows = {
            (row["dataset"], row["condition"]): row
            for row in read_csv(RESULTS / "implied_height_by_condition.csv")
        }

    def test_medians_match_frozen_results(self):
        for key, expected in self.EXPECTED.items():
            with self.subTest(key=key):
                self.assertAlmostEqual(
                    float(self.rows[key]["colour_implied_height_median_mm"]), expected, places=1
                )

    def test_only_height_only_model_is_used(self):
        self.assertEqual({row["model"] for row in self.rows.values()}, {"height_only59"})

    def test_static_2m_offset_exceeds_base_side(self):
        row = self.rows[("static", "center_200")]
        self.assertEqual(row["required_offset_exceeds_base_side"], "True")
        self.assertGreater(float(row["offset_required_from_label_m"]), analyze.BASE_SIDE_M)
        # The smaller static offsets are inside the base side and cannot alone
        # be called a reference-point error.
        for key in (("static", "center_080"), ("static", "center_130")):
            self.assertEqual(self.rows[key]["required_offset_exceeds_base_side"], "False")


class SmoothnessVersusBiasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {
            (row["dataset"], row["condition"]): row
            for row in read_csv(RESULTS / "implied_height_by_condition.csv")
        }

    def test_static_2m_is_smooth_but_biased(self):
        continuous = self.rows[("sequence", "cone_200")]
        static = self.rows[("static", "center_200")]
        self.assertLess(float(continuous["adjacent_frame_abs_delta_median_mm"]), 1.0)
        self.assertLess(float(static["adjacent_frame_abs_delta_median_mm"]), 3.0)
        self.assertGreater(
            abs(
                float(continuous["colour_implied_height_median_mm"])
                - float(static["colour_implied_height_median_mm"])
            ),
            100.0,
        )

    def test_conclusion_states_smoothness_is_not_correctness(self):
        summary = json.loads((RESULTS / "summary.json").read_text())
        self.assertIn("smoothness is not correctness", summary["conclusion"]["temporal_smoothness"])


class WithinSessionFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {row["case"]: row for row in analyze.within_session_rows()}

    def test_c130_reference_is_the_floor_candidate(self):
        row = self.rows["C130"]
        self.assertEqual(row["reference_candidate_kind"], "floor")
        self.assertEqual(row["reference_pixel"], "(310,416)")
        self.assertEqual(row["cone_candidate_pixel"], "(310,417)")
        self.assertEqual(row["pixel_row_delta_cone_minus_floor"], 1.0)
        self.assertAlmostEqual(row["cone_minus_floor_equivalent_distance_m"], -0.01911, places=5)

    def test_c200_reference_is_the_floor_candidate(self):
        row = self.rows["C200"]
        self.assertEqual(row["reference_candidate_kind"], "floor")
        self.assertEqual(row["reference_pixel"], "(311,393)")
        self.assertEqual(row["pixel_row_delta_cone_minus_floor"], 0.0)
        self.assertAlmostEqual(row["cone_minus_floor_equivalent_distance_m"], 0.007803, places=6)

    def test_paper_corner_is_exact_same_column_identity(self):
        row = self.rows["paper_corner_same_column"]
        self.assertEqual(row["reference_pixel"], "(313,371)")
        self.assertEqual(row["cone_candidate_pixel"], "(313,371)")
        self.assertEqual(row["pixel_row_delta_cone_minus_floor"], 0)
        self.assertAlmostEqual(row["cone_implied_height_mm"], 330.604, places=3)

    def test_absolute_heights_differ_across_sessions(self):
        self.assertAlmostEqual(self.rows["C130"]["cone_implied_height_mm"], 589.91, places=2)
        self.assertAlmostEqual(self.rows["C200"]["cone_implied_height_mm"], 592.7, places=1)
        self.assertAlmostEqual(
            self.rows["paper_corner_same_column"]["cone_implied_height_mm"], 330.604, places=3
        )

    def test_no_row_is_physical_ground_truth(self):
        for row in self.rows.values():
            self.assertEqual(row["reference_is_physical_gt"], False)
            self.assertEqual(row["floor_contact_verified"], False)
            self.assertEqual(row["usable_for_ffb"], False)


class CategoryAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read_csv(RESULTS / "category_audit.csv")
        cls.by_category = {row["category"]: row for row in cls.rows}

    def test_required_categories_present(self):
        self.assertEqual(len(self.rows), 12)
        expected = {
            "baseline",
            "lateral",
            "same-session floor reference",
            "completion",
            "baseline still",
            "yellow + same-colour floor",
            "occluded",
            "small/distant",
            "multiple candidates",
            "crop/ROI edge",
            "top/bottom crop contact",
        }
        self.assertTrue(expected.issubset(set(self.by_category)))

    def test_unusable_cases_are_withheld(self):
        for category in (
            "yellow + same-colour floor",
            "occluded",
            "multiple candidates",
            "crop/ROI edge",
            "top/bottom crop contact",
        ):
            with self.subTest(category=category):
                self.assertEqual(self.by_category[category]["support_accepted_for_evaluation"], "False")

    def test_completion_is_accepted_only_as_conditional(self):
        row = self.by_category["completion"]
        self.assertEqual(row["support_accepted_for_evaluation"], "True")
        self.assertIn("not promote to controlling distance", row["interpretation"])


class YellowWithholdingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads((RESULTS / "summary.json").read_text())
        cls.row = next(
            row
            for row in read_csv(RESULTS / "category_audit.csv")
            if row["category"] == "yellow + same-colour floor"
        )

    def test_summary_does_not_rescue_yellow(self):
        self.assertIs(self.summary["yellow_rescued_by_red_subblob"], False)

    def test_red_subblob_is_not_a_support_point(self):
        self.assertEqual(self.row["support_accepted_for_evaluation"], "False")
        self.assertIn("red sub-blob bottom y=359", self.row["result"])
        self.assertIn("full yellow envelope bottom y=401", self.row["result"])


class FlagAndProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads((RESULTS / "summary.json").read_text())
        cls.provenance = json.loads((RESULTS / "provenance.json").read_text())

    def test_summary_flags_remain_false(self):
        for key in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb"):
            self.assertIs(self.summary[key], False)
        self.assertIs(self.summary["inputs_are_saved_data_only"], True)

    def test_all_csv_rows_deny_ffb(self):
        for name in ("implied_height_by_condition.csv", "within_session_floor_check.csv",
                     "category_audit.csv", "fixed_floor_1030.csv"):
            for row in read_csv(RESULTS / name):
                with self.subTest(name=name):
                    self.assertEqual(row["floor_contact_verified"], "False")
                    self.assertEqual(row["usable_for_ffb"], "False")
                    if "physical_metric_verified" in row:
                        self.assertEqual(row["physical_metric_verified"], "False")

    def test_input_hashes_match_current_files(self):
        for rel, expected in self.provenance["input_sha256"].items():
            self.assertEqual(sha256(ROOT / rel), expected, rel)

    def test_output_hashes_match_frozen_files(self):
        for name, expected in self.provenance["output_sha256"].items():
            self.assertEqual(sha256(RESULTS / name), expected, name)

    def test_method_and_analysis_hashes_match(self):
        self.assertEqual(sha256(EVAL / "method.md"), self.provenance["method_sha256"])
        self.assertEqual(sha256(EVAL / "analyze.py"), self.provenance["analysis_sha256"])


class SavedDataIsolationTests(unittest.TestCase):
    def test_analysis_does_not_decode_images_or_run_inference(self):
        source = (EVAL / "analyze.py").read_text()
        forbidden = (
            "cv2.imread",
            "VideoCapture",
            "ultralytics",
            "YOLO(",
            "torch",
            "yolov8",
            "imdecode",
            "Image.open",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_summary_declares_no_new_inference(self):
        summary = json.loads((RESULTS / "summary.json").read_text())
        for key in (
            "new_yolo_inference",
            "new_image_decoding",
            "hsv_reextraction",
            "calibration_or_pose_fit",
        ):
            self.assertIs(summary[key], False)

    def test_approximate_tile_is_not_used_for_selection(self):
        summary = json.loads((RESULTS / "summary.json").read_text())
        self.assertIs(summary["approximate_tile_used_for_model_selection"], False)
        for row in read_csv(RESULTS / "fixed_floor_1030.csv"):
            self.assertEqual(row["approximate_reference_used_for_selection"], "False")
        for value in summary["fixed_floor_1030_compatibility"].values():
            self.assertIs(value["used_for_model_selection"], False)

    def test_completion_shadow_is_not_controlling(self):
        summary = json.loads((RESULTS / "summary.json").read_text())
        self.assertIs(summary["completion_shadow_promoted_to_controlling_distance"], False)
        for row in read_csv(RESULTS / "fixed_floor_1030.csv"):
            self.assertEqual(row["status"], "CONDITIONAL_FIXED_FLOOR_RANGE_ONLY")


if __name__ == "__main__":
    unittest.main()
