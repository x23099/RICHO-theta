#!/usr/bin/env python3
"""Software/input regression only. Never an accuracy or hardware verdict."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    helper = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("completion_test_helpers", helper)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    suite = unittest.TestSuite()
    patterns = (*helpers.PATTERNS, "test_summarize_cone_distance_live.py", "test_theta_rtc_capture_recovery.py",
                "test_cone_colour_support_candidate.py", "test_cone_support_completion_candidate.py")
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as f:
        result = unittest.TextTestRunner(stream=f, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir / "tests.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=("test", "status", "detail"))
        writer.writeheader()
        writer.writerows(result.rows)
    evaluation = json.loads(args.evaluation.read_text())
    source_checks = [dict(path=p, expected=h, actual=sha(Path(p))) for p, h in evaluation["source_sha256"].items()]
    mismatches = [r for r in source_checks if r["actual"] != r["expected"]]
    names = ("cone_colour_support_candidate.py", "cone_distance_core.py", "cone_distance_worker.py",
             "run_cone_distance_live.py", "summarize_cone_distance_live.py", "cone_scene_diagnostic.py",
             "cone_support_quality.py", "cone_distance_diagnostic_config.json", "angular_fisheye_geometry.py",
             "fisheye_floor_geometry.py", "theta_rtc_frames.py", "theta_rtc_diagnostic.py", "webrtc_stream.py",
             "webrtc_receive_ui.py", "start_theta_stream_rtc.sh", "start_theta_receive_rtc.sh")
    protected = {name: hashlib.sha256(subprocess.check_output(["git", "show", "HEAD:src/"+name], cwd=ROOT)).hexdigest()
                  == sha(ROOT / "src" / name) for name in names}
    groups = evaluation["groups"].values()
    checks = dict(tests_successful=result.wasSuccessful() and not result.skipped,
        protected_runtime_calibration_and_existing_shadow_unchanged=all(protected.values()),
        no_input_hash_mismatches=not mismatches,
        frozen_original_observations_match=evaluation["default_extraction_mismatches"] == 0,
        prior_points_never_removed_or_moved=all(g["lost"] == 0 and g["prior_points_changed"] == 0 for g in groups),
        translated_prior_points_never_changed=all(g["jitter_prior_points_changed"] == 0 for g in evaluation["groups"].values()),
        runtime_not_integrated=evaluation["runtime_integrated"] is False,
        no_physical_approval=evaluation["physical_metric_verified"] is False and evaluation["usable_for_ffb"] is False)
    paths = [Path(__file__).resolve(), helper, args.evaluation,
             ROOT / "src/cone_support_completion_candidate.py", ROOT / "tests/test_cone_support_completion_candidate.py"]
    report = dict(status="PASS_OFFLINE_CANDIDATE_ONLY" if all(checks.values()) else "FAIL", checks=checks,
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        protected_sources_unchanged=protected, source_hash_checks=len(source_checks), source_hash_mismatches=mismatches,
        source_sha256={str(p.resolve()): sha(p) for p in paths},
        physical_metric_verified=False, physical_output=False, live_integrated=False, usable_for_ffb=False,
        not_performed=["GPU or detector inference", "camera/network/ROS/FFB activation", "live integration", "Git commit/push"])
    with (args.output_dir / "verification.json").open("x") as f:
        json.dump(report, f, indent=2, allow_nan=False)
        f.write("\n")
    with (args.output_dir / "source_checks.json").open("x") as f:
        json.dump(source_checks, f, indent=2)
        f.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "source_sha256"}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
