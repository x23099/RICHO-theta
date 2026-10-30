#!/usr/bin/env python3
"""変更した診断経路の回帰試験と、保護対象・比較入力のhash照合。実機なし。"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evaluation", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    base = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("prior_runtime_test_helpers", base)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    patterns = (*helpers.PATTERNS, "test_summarize_cone_distance_live.py",
                "test_theta_rtc_capture_recovery.py", "test_cone_colour_support_candidate.py")
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir / "tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"))
        writer.writeheader()
        writer.writerows(result.rows)
    protected = {}
    for name in ("cone_scene_diagnostic.py", "angular_fisheye_geometry.py", "fisheye_floor_geometry.py",
                 "cone_support_quality.py", "cone_distance_diagnostic_config.json", "scene_sampling_clock.py",
                 "theta_rtc_frames.py", "theta_rtc_diagnostic.py", "webrtc_stream.py", "webrtc_receive_ui.py",
                 "start_theta_stream_rtc.sh", "start_theta_receive_rtc.sh"):
        old = subprocess.check_output(["git", "show", "HEAD:src/"+name])
        protected[name] = hashlib.sha256(old).hexdigest() == sha(ROOT / "src" / name)
    evaluation = json.loads(args.evaluation.read_text())
    checks = [{"file": path, "expected": expected, "actual": sha(Path(path))}
              for path, expected in evaluation["source_sha256"].items()]
    mismatches = [r for r in checks if r["expected"] != r["actual"]]
    (args.output_dir / "evaluation_source_checks.json").write_text(json.dumps(checks, indent=2)+"\n")
    paths = [ROOT / "src" / name for name in ("cone_distance_core.py", "cone_colour_support_candidate.py",
             "cone_distance_worker.py", "run_cone_distance_live.py", "summarize_cone_distance_live.py")]
    paths += [ROOT / "tests/test_cone_colour_support_candidate.py", ROOT / "tests/test_summarize_cone_distance_live.py",
              Path(__file__).resolve(), args.evaluation]
    ok = (result.wasSuccessful() and not result.skipped and all(protected.values())
          and not mismatches and evaluation["baseline_mismatches"] == 0)
    summary = dict(status="PASS_SOFTWARE_SHADOW_ONLY" if ok else "FAIL", work_date="2026-10-30",
                   tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   protected_sources_unchanged=protected, evaluation_source_checks=len(checks),
                   evaluation_source_mismatches=mismatches, default_support_comparisons=evaluation["evaluated_boxes"],
                   default_support_mismatches=evaluation["baseline_mismatches"],
                   source_sha256={str(p.resolve()): sha(p) for p in paths},
                   new_distance_accuracy_measured=False, physical_output=False, usable_for_ffb=False)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
