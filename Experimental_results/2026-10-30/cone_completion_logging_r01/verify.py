#!/usr/bin/env python3
"""診断ログ追加の回帰試験と、意図した変更・保護対象のハッシュ監査。"""
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
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    helper = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("logging_verify_helpers", helper)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    patterns = (*helpers.PATTERNS, "test_summarize_cone_distance_live.py", "test_theta_rtc_capture_recovery.py",
        "test_cone_colour_support_candidate.py", "test_cone_support_completion_candidate.py",
        "test_cone_completion_shadow_logging.py")
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir / "tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"))
        writer.writeheader()
        writer.writerows(result.rows)
    previous = json.loads((ROOT / "Experimental_results/2026-10-30/cone_lateral_completion_r01/evaluation_r01/summary.json").read_text())
    changed = {"cone_distance_core.py", "cone_distance_worker.py", "run_cone_distance_live.py", "summarize_cone_distance_live.py"}
    source_checks = []
    for name, expected in previous["source_sha256"].items():
        path = Path(name)
        intentional = path.parent == ROOT / "src" and path.name in changed
        audited = Path(__file__).with_name("source_snapshot") / path.name if intentional else path
        source_checks.append(dict(original_path=name, audited_path=str(audited), expected=expected,
                                  actual=sha(audited), intentionally_changed_active_source=intentional))
    protected_names = ("cone_colour_support_candidate.py", "cone_scene_diagnostic.py", "cone_support_quality.py",
        "cone_distance_diagnostic_config.json", "angular_fisheye_geometry.py", "fisheye_floor_geometry.py",
        "theta_rtc_frames.py", "theta_rtc_diagnostic.py", "webrtc_stream.py", "webrtc_receive_ui.py",
        "start_theta_stream_rtc.sh", "start_theta_receive_rtc.sh")
    protected = {name: hashlib.sha256(subprocess.check_output(["git", "show", "HEAD:src/"+name], cwd=ROOT)).hexdigest()
                      == sha(ROOT / "src" / name) for name in protected_names}
    checks = dict(tests_successful=result.wasSuccessful() and not result.skipped,
        old_evidence_matches_originals_or_explicit_source_snapshots=all(r["expected"] == r["actual"] for r in source_checks),
        protected_sources_unchanged=all(protected.values()))
    report = dict(status="PASS_LOGGING_SOFTWARE_ONLY" if all(checks.values()) else "FAIL", checks=checks,
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        patterns=patterns, protected_sources=protected, source_hash_checks=len(source_checks),
        intentional_source_changes={name: dict(before_sha256=sha(Path(__file__).with_name("source_snapshot")/name),
                                              after_sha256=sha(ROOT/"src"/name)) for name in sorted(changed)},
        physical_output=False, physical_metric_verified=False, usable_for_ffb=False,
        not_performed=["camera/network/ROS/FFB activation", "GPU inference", "physical accuracy test", "Git commit/push"])
    (args.output_dir / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
    (args.output_dir / "source_checks.json").write_text(json.dumps(source_checks, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
