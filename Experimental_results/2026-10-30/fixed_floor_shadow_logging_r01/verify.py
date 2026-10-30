#!/usr/bin/env python3
"""固定床比較ログの関連回帰。実機・GPU・ネットワークは起動しない。"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
BASELINE_COMMIT = "9392487"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    helper = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("fixed_log_tests", helper)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    patterns = (*helpers.PATTERNS, "test_summarize_cone_distance_live.py", "test_theta_rtc_capture_recovery.py",
        "test_cone_colour_support_candidate.py", "test_cone_support_completion_candidate.py",
        "test_cone_completion_shadow_logging.py", "test_frame_evidence_logging.py",
        "test_cone_fixed_floor_candidate.py", "test_cone_fixed_floor_shadow.py", "test_cone_support_live_review.py")
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir / "tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"))
        writer.writeheader()
        writer.writerows(result.rows)
    summary = json.loads((args.evaluation_dir / "summary.json").read_text())
    mismatches = [p for p, h in summary["source_sha256"].items() if sha(p) != h]
    names = ("cone_scene_diagnostic.py", "cone_support_quality.py", "cone_fixed_floor_candidate.py",
        "cone_colour_support_candidate.py", "cone_support_completion_candidate.py", "cone_distance_diagnostic_config.json",
        "angular_fisheye_geometry.py", "fisheye_floor_geometry.py", "theta_rtc_frames.py", "theta_rtc_diagnostic.py",
        "webrtc_stream.py", "webrtc_receive_ui.py", "start_theta_stream_rtc.sh", "start_theta_receive_rtc.sh")
    protected = {name: (ROOT / "src" / name).read_bytes() == subprocess.check_output(
        ["git", "show", BASELINE_COMMIT+":src/"+name], cwd=ROOT) for name in names}
    frozen = {p.name: p.read_bytes() == subprocess.check_output(["git", "show", BASELINE_COMMIT+":src/"+p.name], cwd=ROOT)
              for p in Path(__file__).with_name("source_snapshot").glob("*.py")}
    checks = dict(tests_pass=result.wasSuccessful() and not result.skipped,
        source_hashes_match=not mismatches, protected_algorithms_and_calibration_unchanged=all(protected.values()),
        prechange_snapshots_match_head=all(frozen.values()),
        recorded_session_rejected=(summary["recorded_frames"] == summary["baseline_fields_unchanged"] == 1689
                                   and summary["comparison_range_frames"] == 0),
        no_fabricated_live_success=summary["report_status"] == "INCOMPLETE_CAPTURE")
    report = dict(status="PASS_LOG_ONLY_SOFTWARE" if all(checks.values()) else "FAIL", checks=checks,
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        baseline_commit=BASELINE_COMMIT,
        protected_sources=protected, prechange_snapshots=frozen, source_hash_mismatches=mismatches,
        patterns=patterns, physical_metric_verified=False, usable_for_ffb=False,
        source_sha256={str(p.resolve()): sha(p) for p in (Path(__file__), args.evaluation_dir / "summary.json",
                         ROOT / "src/cone_fixed_floor_shadow.py", ROOT / "tests/test_cone_fixed_floor_shadow.py")})
    (args.output_dir / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
