#!/usr/bin/env python3
"""前段177試験はsource hashが同じ場合のみ再利用し、新規の床姿勢15試験を追加。"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    base = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("floor_pose_verification_helpers", base)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    prior_path = ROOT / "Experimental_results/2026-10-30/cone_colour_shadow_r01/verification_r01/summary.json"
    prior = json.loads(prior_path.read_text())
    mismatch = [name for name, expected in prior["source_sha256"].items()
                if helpers.sha256(Path(name)) != expected]
    suite = unittest.TestSuite()
    for pattern in ("test_floor_reference_pose.py", "test_diagnose_floor_board_pose.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    import csv
    with (args.output_dir/"tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"))
        writer.writeheader()
        writer.writerows(result.rows)
    sources = [Path(__file__).resolve(), prior_path]
    sources += [ROOT/"src"/name for name in ("floor_reference_pose.py", "diagnose_floor_board_pose.py",
                "angular_fisheye_geometry.py", "fisheye_intrinsic_calibration.py")]
    sources += [ROOT/"tests"/name for name in ("test_floor_reference_pose.py", "test_diagnose_floor_board_pose.py")]
    evidence = Path(__file__).parent
    sources += [evidence/name for name in ("evaluation_r01/summary.json", "evaluation_r01/point_evaluation.csv",
                "no_board_control_r01/floor_board_report.json", "handheld_board_control_r01/floor_board_report.json")]
    ok = result.wasSuccessful() and not result.skipped and not mismatch and prior["status"] == "PASS_SOFTWARE_SHADOW_ONLY"
    summary = dict(status="PASS_OFFLINE_FLOOR_POSE_SOFTWARE_ONLY" if ok else "FAIL", new_tests=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   unchanged_prior_tests_reused=prior["tests"] if not mismatch else 0,
                   reused_source_mismatches=mismatch, verified_tests_total=result.testsRun+(prior["tests"] if not mismatch else 0),
                   source_sha256={str(p.resolve()): helpers.sha256(p) for p in sources},
                   physical_metric_verified=False, current_live_application_allowed=False,
                   camera_opened=False, network_started=False, ros_started=False, physical_output=False)
    (args.output_dir/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
