#!/usr/bin/env python3
"""Audit real rejection and synthetic success separately. No hardware."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT/"src"), str(HERE)]
from cone_distance_core import digest
from summarize_cone_distance_live import load_frames
from replay import audit_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("lifecycle_test_helpers",
        ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    suite = unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern="test_fixed_floor_lifecycle_replay.py")
    with (args.output_dir/"tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir/"tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.rows)

    summary_path = args.results_dir/"summary.json"
    summary = json.loads(summary_path.read_text())
    inventory = json.loads((args.results_dir/"data_inventory.json").read_text())
    real = args.results_dir/"real_wrong_session"
    synthetic = args.results_dir/"synthetic_lifecycle"
    real_input = ROOT.parent/"recordings/2026-10-30/live_frame_evidence_r02_20261030_185348/distance_frames.jsonl"
    real_original, _, _ = load_frames(real_input)
    synthetic_original, _, _ = load_frames(args.results_dir/"synthetic_inputs/distance_frames.jsonl")
    real_rows, _, _ = load_frames(real/"distance_frames.jsonl")
    synthetic_rows, _, _ = load_frames(synthetic/"distance_frames.jsonl")
    audit_rows(real_original, real_rows)
    audit_rows(synthetic_original, synthetic_rows)
    real_events = [json.loads(line) for line in (real/"fixed_floor_model_events.jsonl").read_text().splitlines()]
    events = [json.loads(line) for line in (synthetic/"fixed_floor_model_events.jsonl").read_text().splitlines()]
    mismatches = [p for p, h in summary["original_source_sha256"].items() if digest(Path(p)) != h]
    mismatches += [r["path"] for r in inventory["inspected_logs"] if digest(r["path"]) != r["sha256"]]
    previous_path = HERE.parent/"fixed_floor_derivation_r01/verification_r03/verification.json"
    previous = json.loads(previous_path.read_text())
    previous_mismatches = [p for p,h in previous["source_sha256"].items() if digest(ROOT/p) != h]
    old_derivation = HERE.parent/"fixed_floor_derivation_r01/results_r02/derivation_report.json"
    for path, h in json.loads(old_derivation.read_text())["source_sha256"].items():
        if digest(path) != h:
            previous_mismatches.append(path)
    synthetic_only = all(r["session"] == "synthetic_lifecycle_only" for r in synthetic_rows)
    def available(row):
        return any(m["range_available"] for m in row.get("fixed_floor_shadow", {}).get("models", []))
    checks = dict(new_tests_pass=result.wasSuccessful() and not result.skipped,
        reuse_360_tests_by_unchanged_sources=previous["tests"] == 360 and not previous_mismatches
            and all(previous["checks"].values()),
        complete_real_processed_rows=len(real_rows) == len(real_original) == 1689,
        real_model_never_accepted=all(e["action"] != "accepted" for e in real_events),
        real_requests_rejected_by_session=sum(e["action"] == "rejected" and "session mismatch" in e.get("detail", "") for e in real_events) == 3,
        real_comparison_output_zero=not any(available(r) for r in real_rows),
        complete_synthetic_rows=len(synthetic_rows) == 180,
        synthetic_positive_path_separate=synthetic_only and sum(available(r) for r in synthetic_rows) == 88,
        synthetic_model_activations=sum(e["action"] == "accepted" for e in events) == 3,
        synthetic_occlusion_withheld=all(not available(r) for r in synthetic_rows[34:46]),
        synthetic_stale_withheld=not available(synthetic_rows[59]),
        synthetic_bad_reload_no_fallback=all("fixed_floor_shadow" not in r for r in synthetic_rows[110:132]),
        synthetic_disconnect_withheld=all("fixed_floor_shadow" not in r for r in synthetic_rows[160:]),
        both_baseline_field_sets_preserved=summary["real"]["original_fields_unchanged"] == 1689
            and summary["synthetic"]["original_fields_unchanged"] == 180,
        real_positive_not_claimed=summary["real_model_positive_continuous_output_verified"] is False
            and summary["same_session_real_post_load_images"] == 0 and summary["same_session_real_post_load_log_rows"] == 0,
        missing_real_future_data_recorded=not inventory["existing_model_positive_time_series_available"],
        original_hashes_unchanged=not mismatches,
        no_physical_approval=summary["physical_metric_verified"] is False and summary["usable_for_ffb"] is False)
    paths = [Path(__file__).resolve(), HERE/"replay.py", HERE/"run.py", ROOT/"tests/test_fixed_floor_lifecycle_replay.py",
             summary_path, args.results_dir/"data_inventory.json", args.results_dir/"lifecycle_timeline.png", previous_path]
    for directory in (real, synthetic):
        paths += [directory/name for name in ("distance_frames.jsonl", "fixed_floor_model_events.jsonl", "timeline.csv", "summary.json")]
    report = dict(status="PASS_FUNCTIONAL_CHECKS_REAL_POSITIVE_INCOMPLETE" if all(checks.values()) else "FAIL",
        checks=checks, new_tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        previous_360_tests_reused_not_rerun=True, previous_source_hash_mismatches=previous_mismatches,
        original_input_hash_mismatches=mismatches,
        source_sha256={str(p.resolve().relative_to(ROOT)): digest(p) for p in paths},
        real_model_positive_continuous_output_verified=False, physical_metric_verified=False,
        usable_for_ffb=False, camera_gpu_ros_started=False, git_commit_or_push_performed=False)
    (args.output_dir/"verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k: report[k] for k in ("status", "checks", "new_tests", "failures", "errors", "skipped")}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
