"""Check local evidence inventory and tests, not remote storage or accuracy."""
import argparse
import contextlib
import csv
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest


def read(path):
    with path.open() as stream:
        return json.load(stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    results = base / "results_r02"
    summary = read(results / "summary.json")
    sources = dict(summary["source_sha256"])
    def resolve(path):
        return Path(path) if Path(path).is_absolute() else ROOT/path
    changed = [p for p, sha in sources.items() if digest(resolve(p)) != sha]
    patterns = ["test_same_session_reference_audit.py", "test_paper_boundary_stability.py",
                "test_paper_corner_sensitivity.py", "test_reviewed_coordinate_audit.py",
                "test_review_physical_reference.py", "test_cone_fixed_floor_candidate.py",
                "test_derive_fixed_floor_live_bundle.py", "test_floor_reference_pose.py"]
    for path in [Path(__file__), *results.iterdir(), *[ROOT/"tests"/name for name in patterns]]:
        sources[str(path.relative_to(ROOT))] = digest(path)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    with (results/"paper_frame_geometry.csv").open() as stream:
        models = list(csv.DictReader(stream))
    groups = {}
    for row in models:
        groups.setdefault((row["paper_frame"], row["window"]), set()).add((row["assignment"], row["tracked_branch"], row["height_source"]))
    prior = read(ROOT/"Experimental_results/2026-11-04/upper_support_live_r01/verification_r01/verification.json")
    runtime_changed = [p for p, sha in prior["source_sha256"].items() if digest(ROOT/p) != sha]
    checks = dict(
        tests_pass=tests.wasSuccessful() and not tests.skipped,
        inputs_match=not changed,
        source_and_output_and_human_decisions_unchanged=all(digest(resolve(p)) == sha for p, sha in sources.items()),
        inventory_counts=summary["local_unique_frames"] == 13 and summary["local_decoded_paths"] == 14,
        visible_and_absent_counts=summary["visible_paper_frames"] == 3 and summary["absent_paper_frames"] == 10,
        geometry_count_and_families=len(models) == 64 and len(groups) == 8 and all(len(v) == 8 for v in groups.values()),
        probe_not_misrepresented_as_current_target=all(r["probe_is_actual_target_in_this_paper_frame"] == "False" for r in models),
        local_archive_checked_without_claiming_remote_access=summary["remote_school_storage_checked"] is False and summary["archive_member_rows"] == 10,
        no_physical_or_live_authority=summary["new_independent_physical_reference_found"] is False and summary["physical_metric_verified"] is False and summary["usable_for_ffb"] is False,
        prior_runtime_unchanged=not runtime_changed,
        no_live_bundle_export=not (results/"prepared_floor.json").exists())
    output = dict(status="PASS_LOCAL_EVIDENCE_AUDIT_NOT_PHYSICAL_APPROVAL" if all(checks.values()) else "FAIL",
                  checks=checks, tests=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors), skipped=len(tests.skipped),
                  patterns=patterns, source_sha256=sources, source_mismatches=changed,
                  runtime_mismatches=runtime_changed, prior_software_tests_reused=prior["tests"],
                  physical_metric_verified=False, usable_for_ffb=False)
    with (args.output_dir/"verification.json").open("x") as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
    print(json.dumps({k:v for k,v in output.items() if k != "source_sha256"}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
