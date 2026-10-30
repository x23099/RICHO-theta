#!/usr/bin/env python3
"""Test the saved-live review and protect existing runtime/calibration."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("review_analysis", Path(__file__).with_name("analyze.py"))
    analysis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analysis)
    helper = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("review_test_helpers", helper)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    patterns = ("test_cone_support_live_review.py", "test_cone_colour_support_candidate.py",
        "test_cone_support_completion_candidate.py", "test_cone_support_quality*.py",
        "test_frame_evidence_logging.py", "test_summarize_cone_distance_live.py")
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir / "tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"))
        writer.writeheader()
        writer.writerows(result.rows)
    summary = json.loads((args.results_dir / "summary.json").read_text())
    mismatches = [name for name, expected in summary["source_sha256"].items() if analysis.sha(name) != expected]
    paths = [*sorted((ROOT / "src").glob("*.py")), *sorted((ROOT / "src").glob("*.json")),
             *sorted((ROOT / "src").glob("*.sh")), ROOT / "start_cone_distance.sh"]
    tracked = set(subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines())
    changed = [str(p.relative_to(ROOT)) for p in paths if str(p.relative_to(ROOT)) in tracked and
               subprocess.check_output(["git", "show", "HEAD:"+str(p.relative_to(ROOT))], cwd=ROOT) != p.read_bytes()]
    csv_rows = list(csv.DictReader((args.results_dir / "frame_review.csv").open()))
    checks = dict(tests_successful=result.wasSuccessful() and not result.skipped,
        unchanged_runtime_calibration_and_launchers=not changed,
        all_recorded_input_and_code_hashes_match=not mismatches,
        exact_partition=(summary["category_counts"] == dict(preserved=1636, completed=35, withheld=18)),
        all_frames_retained=(summary["processed_frames"] == len(csv_rows) == 1689),
        all_completions_checked=len(summary["completion_checks"]) == 35,
        saved_image_and_log_exact=(len(summary["saved_image_checks"]) == 3 and
            all(r.get("old_exact") and r.get("new_exact") and r.get("native_pixels_unchanged") for r in summary["saved_image_checks"])),
        no_physical_approval=all(summary.get(k) is False for k in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb", "physical_output")))
    proof = dict(status="PASS_SAVED_LIVE_CANDIDATE_REVIEW" if all(checks.values()) else "FAIL",
        checks=checks, tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        tracked_runtime_files_compared=len([p for p in paths if str(p.relative_to(ROOT)) in tracked]),
        changed_runtime_files=changed, source_hash_mismatches=mismatches,
        source_sha256={str(p.resolve()): analysis.sha(p) for p in (Path(__file__), Path(__file__).with_name("analyze.py"),
            ROOT / "tests/test_cone_support_live_review.py", args.results_dir / "summary.json",
            args.results_dir / "frame_review.csv", args.results_dir / "candidate_timeline.png")},
        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False,
        not_performed=["fresh YOLO inference", "distance recalculation", "camera/network/ROS/FFB", "Git commit/push"])
    (args.output_dir / "verification.json").write_text(json.dumps(proof, indent=2)+"\n")
    print(json.dumps(proof, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
