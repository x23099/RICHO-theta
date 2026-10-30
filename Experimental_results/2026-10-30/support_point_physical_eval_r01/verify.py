#!/usr/bin/env python3
"""Verification for the saved-data support-point physical-meaning evaluation.

Checks numerical transcription, provenance, isolation from inference, and that
no output promotes the support point to a verified contact or FFB input.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evaluation = args.evaluation_dir
    results = evaluation / "results_r01"
    summary = json.loads((results / "summary.json").read_text())
    provenance = json.loads((results / "provenance.json").read_text())
    implied = {(r["dataset"], r["condition"]): r for r in read_csv(
        results / "implied_height_by_condition.csv")}
    within = {r["case"]: r for r in read_csv(results / "within_session_floor_check.csv")}
    categories = read_csv(results / "category_audit.csv")
    fixed = read_csv(results / "fixed_floor_1030.csv")
    checks = {}

    checks["declared_saved_data_only"] = (
        summary["inputs_are_saved_data_only"] is True
        and summary["new_yolo_inference"] is False
        and summary["new_image_decoding"] is False
        and summary["hsv_reextraction"] is False
        and summary["calibration_or_pose_fit"] is False)

    checks["all_flags_false"] = all(
        summary[key] is False
        for key in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb")
    ) and all(
        row["floor_contact_verified"] == "False" and row["usable_for_ffb"] == "False"
        for rows in (implied.values(), within.values(), categories, fixed) for row in rows)

    checks["counts_match_files"] = (
        summary["counts"] == {
            "implied_height_rows": len(implied),
            "within_session_rows": len(within),
            "category_rows": len(categories),
            "fixed_floor_rows": len(fixed),
        })

    expected_medians = {
        ("sequence", "cone_130"): 589.9,
        ("sequence", "cone_200"): 592.7,
        ("static", "center_080"): 531.7,
        ("static", "center_130"): 502.0,
        ("static", "center_200"): 446.1,
        ("static", "left_130"): 538.3,
        ("static", "right_130"): 490.4,
    }
    deviations = {
        f"{key[0]}/{key[1]}": abs(
            float(implied[key]["colour_implied_height_median_mm"]) - value)
        for key, value in expected_medians.items()
    }
    checks["known_medians_reproduced_within_0p1mm"] = max(deviations.values()) <= 0.1

    checks["c130_uses_floor_candidate"] = (
        within["C130"]["reference_candidate_kind"] == "floor"
        and within["C130"]["reference_pixel"] == "(310,416)"
        and float(within["C130"]["pixel_row_delta_cone_minus_floor"]) == 1.0
        and abs(float(within["C130"]["cone_minus_floor_equivalent_distance_m"]) + 0.01911) < 1e-5)
    checks["c200_uses_floor_candidate"] = (
        within["C200"]["reference_candidate_kind"] == "floor"
        and within["C200"]["reference_pixel"] == "(311,393)"
        and float(within["C200"]["pixel_row_delta_cone_minus_floor"]) == 0.0)
    checks["paper_same_column_identity"] = (
        within["paper_corner_same_column"]["reference_pixel"] == "(313,371)"
        and within["paper_corner_same_column"]["cone_candidate_pixel"] == "(313,371)"
        and int(within["paper_corner_same_column"]["pixel_row_delta_cone_minus_floor"]) == 0)

    checks["smoothness_is_not_treated_as_correctness"] = (
        float(implied[("static", "center_200")]["adjacent_frame_abs_delta_median_mm"]) < 3.0
        and abs(
            float(implied[("sequence", "cone_200")]["colour_implied_height_median_mm"])
            - float(implied[("static", "center_200")]["colour_implied_height_median_mm"])
        ) > 100.0
        and "smoothness is not correctness" in summary["conclusion"]["temporal_smoothness"])

    checks["static_2m_offset_exceeds_base_side"] = (
        implied[("static", "center_200")]["required_offset_exceeds_base_side"] == "True")

    by_category = {row["category"]: row for row in categories}
    checks["yellow_occluded_multi_roi_withheld"] = all(
        by_category[name]["support_accepted_for_evaluation"] == "False"
        for name in ("yellow + same-colour floor", "occluded", "multiple candidates",
                     "crop/ROI edge", "top/bottom crop contact"))
    checks["no_yellow_rescue"] = summary["yellow_rescued_by_red_subblob"] is False

    checks["completion_not_promoted"] = (
        summary["completion_shadow_promoted_to_controlling_distance"] is False
        and all(row["status"] == "CONDITIONAL_FIXED_FLOOR_RANGE_ONLY" for row in fixed))

    checks["approximate_tile_not_used_for_selection"] = (
        summary["approximate_tile_used_for_model_selection"] is False
        and all(row["approximate_reference_used_for_selection"] == "False" for row in fixed)
        and all(entry["used_for_model_selection"] is False
                for entry in summary["fixed_floor_1030_compatibility"].values()))

    checks["input_hashes_current"] = all(
        sha256(ROOT / rel) == expected
        for rel, expected in provenance["input_sha256"].items())
    checks["output_hashes_current"] = all(
        sha256(results / name) == expected
        for name, expected in provenance["output_sha256"].items())
    checks["method_and_analysis_hashes_current"] = (
        sha256(evaluation / "method.md") == provenance["method_sha256"]
        and sha256(evaluation / "analyze.py") == provenance["analysis_sha256"])

    source = (evaluation / "analyze.py").read_text()
    forbidden = ("cv2.imread", "VideoCapture", "ultralytics", "YOLO(", "torch", "yolov8",
                 "imdecode", "Image.open")
    checks["analysis_has_no_inference_or_image_decoding"] = not any(
        token in source for token in forbidden)

    protected = (
        "src/cone_distance_core.py", "src/cone_distance_worker.py",
        "src/run_cone_distance_live.py", "src/summarize_cone_distance_live.py",
        "src/cone_distance_diagnostic_config.json", "src/cone_scene_diagnostic.py",
        "src/angular_fisheye_geometry.py", "src/fisheye_floor_geometry.py",
    )
    git_checks = {}
    for name in protected:
        run = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", name], cwd=ROOT)
        git_checks[name] = run.returncode == 0
    checks["live_and_protected_sources_unchanged_from_HEAD"] = all(git_checks.values())

    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests"), pattern="test_support_point_eval.py")
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    checks["focused_tests_passed"] = result.wasSuccessful() and not result.skipped

    report = {
        "status": "PASS_SAVED_DATA_ONLY" if all(checks.values()) else "FAIL",
        "checks": checks,
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "implied_height_abs_deviation_mm": deviations,
        "protected_sources": git_checks,
        "meaning": (
            "Numerical, provenance and isolation checks only; NOT physical "
            "accuracy, floor-contact proof, or FFB approval"),
        "not_performed": [
            "camera/network/ROS/FFB activation", "GPU inference", "new recording",
            "new image decoding", "physical distance truth measurement",
            "Git commit/push",
        ],
        "physical_metric_verified": False,
        "floor_contact_verified": False,
        "live_integrated": False,
        "usable_for_ffb": False,
    }
    (args.output_dir / "verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": checks}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
