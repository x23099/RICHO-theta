#!/usr/bin/env python3
"""Numerical, provenance and isolation checks for the explicit floor candidate."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evaluation = args.evaluation_dir
    summary = json.loads((evaluation / "summary.json").read_text())
    models = json.loads((evaluation / "explicit_floor_models.json").read_text())
    ranges = list(csv.DictReader((evaluation / "ranges.csv").open(newline="")))
    heights = list(csv.DictReader((evaluation / "height_sensitivity.csv").open(newline="")))
    checks = {}

    checks["reported_input_hashes_unchanged"] = all(
        sha(Path(path)) == expected for path, expected in summary["source_sha256"].items())
    checks["three_primary_models_and_one_frame_control"] = (
        len(models["models"]) == 3 and len(models["per_frame_models"]) == 2)
    checks["all_models_deny_physical_approval"] = all(
        all(model[key] is False for key in ("physical_metric_verified", "floor_contact_verified",
                                            "usable_for_ffb", "controlling_distance",
                                            "live_integrated"))
        for model in models["models"] + models["per_frame_models"])
    checks["no_ffb_or_contact_claim_in_ranges"] = all(
        row["controlling_distance"] == "False" and row["physical_metric_verified"] == "False"
        and row["floor_contact_verified"] == "False" and row["usable_for_ffb"] == "False"
        and row["yaw_measured"] == "False" for row in ranges)
    checks["all_ranges_are_conditional_only"] = all(
        row["status"] == "CONDITIONAL_FIXED_FLOOR_RANGE_ONLY"
        and row["reason"] == "EXPLICIT_FLOOR_MODEL_NOT_PHYSICALLY_VERIFIED" for row in ranges)

    source_counts = {(row["frame"], row["support_source"]) for row in ranges}
    checks["both_frames_and_both_1655_support_sources"] = source_counts == {
        ("1259", "lateral_completion_shadow"),
        ("1655", "baseline_colour_shadow"),
        ("1655", "lateral_completion_shadow")}
    checks["user_approximate_range_not_used_for_selection"] = (
        models["user_reference"]["used_to_fit_or_select_model"] is False
        and models["user_reference"]["precise_measurement"] is False)

    previous = list(csv.DictReader((ROOT / "Experimental_results/2026-10-30/floor_board_pair_r01/"
        "cone_same_session_r01/comparison_r01/conditional_ranges.csv").open(newline="")))
    previous = {row["model"]: float(row["horizontal_range_m"]) for row in previous}
    previous_name = {
        "shared_free_plane_plus_approx_board_thickness":
            "shared_plane_height_free_plus_approx_board",
        "externally_anchored_height_and_normal":
            "externally_anchored_height_and_normal",
        "external_height_only_free_fit_normal":
            "external_height_only_free_fit_normal_counterfactual"}
    reproduced = {}
    for row in ranges:
        if row["frame"] == "1655" and row["support_source"] == "baseline_colour_shadow" \
                and row["model"] in previous_name:
            old = previous_name[row["model"]]
            reproduced[old] = abs(float(row["horizontal_camera_foot_range_m"]) - previous[old])
    checks["frame1655_three_models_reproduce_saved_ranges"] = (
        len(reproduced) == 3 and max(reproduced.values()) <= 1e-9)

    primary = [row for row in ranges if row["model_role"] == "conditional_primary"
               and row["support_1px_control_min_m"]]
    checks["one_pixel_control_brackets_primary_range"] = all(
        float(row["support_1px_control_min_m"]) <= float(row["horizontal_camera_foot_range_m"])
        <= float(row["support_1px_control_max_m"]) for row in primary)

    monotone = {}
    for key in {(row["frame"], row["support_source"]) for row in heights}:
        values = sorted((float(row["camera_to_floor_m"]), float(row["horizontal_camera_foot_range_m"]))
                        for row in heights if (row["frame"], row["support_source"]) == key)
        monotone[key] = all(b[1] > a[1] for a, b in zip(values, values[1:]))
    checks["height_sensitivity_is_strictly_increasing"] = all(monotone.values())

    protected = ("src/cone_distance_core.py", "src/cone_distance_worker.py",
                 "src/run_cone_distance_live.py", "src/summarize_cone_distance_live.py",
                 "src/cone_distance_diagnostic_config.json", "src/cone_scene_diagnostic.py",
                 "src/angular_fisheye_geometry.py", "src/fisheye_floor_geometry.py")
    git_checks = {}
    for name in protected:
        run = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", name], cwd=ROOT)
        git_checks[name] = run.returncode == 0
    checks["existing_controlling_sources_unchanged_from_HEAD"] = all(git_checks.values())

    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"),
                                                pattern="test_cone_fixed_floor_candidate.py")
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    checks["focused_tests_passed"] = result.wasSuccessful() and not result.skipped

    report = dict(status="PASS_ISOLATED_SOFTWARE_ONLY" if all(checks.values()) else "FAIL",
        checks=checks, tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped),
        reproduced_frame1655_abs_error_m=reproduced,
        height_sensitivity_groups={f"{k[0]}/{k[1]}": v for k, v in monotone.items()},
        protected_sources=git_checks,
        meaning="Numerical consistency, provenance and software isolation only; NOT physical accuracy or contact approval",
        not_performed=["camera/network/ROS/FFB activation", "GPU inference", "new recording",
                       "physical distance truth measurement", "Git commit/push"],
        physical_metric_verified=False, floor_contact_verified=False,
        live_integrated=False, usable_for_ffb=False)
    (args.output_dir / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(dict(status=report["status"], checks=checks), indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
