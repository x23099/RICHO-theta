#!/usr/bin/env python3
"""同一session・過去限定の再生結果を検証。実機は起動しない。"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
BASE = "ccf5665"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("causal_bootstrap_replay", Path(__file__).with_name("run.py"))
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    previous = json.loads((ROOT / "Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/verification_r02/verification.json").read_text())
    helper = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("bootstrap_test_helpers", helper)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    suite = unittest.TestSuite()
    patterns = [*previous["patterns"], "test_fixed_floor_causal_bootstrap.py"]
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir / "tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.rows)
    summary = json.loads((args.results_dir / "summary.json").read_text())
    with (args.results_dir / "frame_comparison.csv").open(newline="") as stream:
        flat = list(csv.DictReader(stream))
    from summarize_cone_distance_live import load_frames
    rows, truncated, _ = load_frames(args.results_dir / "recorded_comparison/distance_frames.jsonl")
    control, _, _ = load_frames(args.results_dir / "recorded_union_control/distance_frames.jsonl")
    run.verify_releases(summary["bootstrap"], rows)
    run.verify_releases(summary["bootstrap"], control)
    changed = []
    tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "src"], cwd=ROOT, text=True).splitlines()
    for path in tracked:
        if Path(path).suffix not in (".py", ".json", ".sh"):
            continue
        expected = subprocess.check_output(["git", "show", BASE+":"+path], cwd=ROOT)
        if (ROOT / path).read_bytes() != expected:
            changed.append(path)
    mismatches = [p for p, h in summary["source_sha256"].items() if sha(p) != h]
    no_control_differences = all({k: v for k, v in a.items() if k != "fixed_floor_shadow"}
                               == {k: v for k, v in b.items() if k != "fixed_floor_shadow"} for a, b in zip(rows, control))
    checks = dict(tests_pass=result.wasSuccessful() and not result.skipped,
        runtime_sources_unchanged=not changed, source_hashes_match=not mismatches,
        complete_native_ledger=len(rows) == len(control) == len(flat) == summary["frames"] == 1547 and not truncated,
        baseline_fields_unchanged=summary["baseline_fields_unchanged"] == 1547,
        both_support_paths_preserve_baseline=no_control_differences,
        scene_accepted_and_rejected_reconstructed=summary["scene_checks"] == 52 and not summary["scene_acceptance_mismatches"],
        original_source_files_unchanged=not mismatches,
        no_physical_or_live_approval=all(summary[k] is False for k in ("physical_metric_verified", "usable_for_ffb", "physical_output", "new_capture", "fresh_detector_inference")),
        positive_real_frame_comparison=summary["fixed_horizontal_range_frames"] > 0 and summary["fixed_union_control_frames"] > 0)
    report = dict(status="PASS_PAST_ONLY_REPLAY_NOT_PHYSICAL_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks, tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        baseline_commit=BASE, changed_runtime_sources=changed, source_hash_mismatches=mismatches,
        source_sha256={str(p.resolve()): sha(p) for p in (Path(__file__), Path(__file__).with_name("run.py"),
            ROOT / "tests/test_fixed_floor_causal_bootstrap.py", args.results_dir / "summary.json",
            args.results_dir / "frame_comparison.csv", args.results_dir / "bootstrap_models.json",
            args.results_dir / "conditional_range_timeline.png")},
        git_commit_or_push_performed=False, physical_metric_verified=False, usable_for_ffb=False)
    (args.output_dir / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
