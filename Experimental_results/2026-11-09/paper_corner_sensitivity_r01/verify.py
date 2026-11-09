"""Check stress bookkeeping, synthetic math and input/runtime immutability."""
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
    result_dir = base / "results_r02"
    summary = read(result_dir / "summary.json")
    sources = dict(summary["source_sha256"])
    initial_mismatches = [p for p, sha in sources.items() if digest(ROOT / p) != sha]
    patterns = ["test_paper_corner_sensitivity.py", "test_reviewed_coordinate_audit.py",
                "test_review_physical_reference.py", "test_cone_fixed_floor_candidate.py",
                "test_derive_fixed_floor_live_bundle.py", "test_floor_reference_pose.py"]
    for path in [Path(__file__), *result_dir.iterdir(), *[ROOT / "tests" / p for p in patterns]]:
        sources[str(path.relative_to(ROOT))] = digest(path)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    with (result_dir / "perturbation_metrics.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    per_case = {}
    for row in rows:
        per_case.setdefault((row["session"], row["id"]), set()).add((row["assignment"], row["tracked_branch"], row["height_source"]))
    previous = read(ROOT / "Experimental_results/2026-11-04/upper_support_live_r01/verification_r01/verification.json")
    changed_runtime = [p for p, sha in previous["source_sha256"].items() if digest(ROOT / p) != sha]
    checks = dict(
        tests_pass=tests.wasSuccessful() and not tests.skipped,
        two_sessions_573_cases_each=len(per_case) == 2 * 573,
        eight_distinct_hypotheses_per_case=all(len(h) == 8 for h in per_case.values()),
        row_count_matches=len(rows) == summary["perturbation_rows"] == 9168,
        old_baseline_and_extractor_reproduced=summary["previous_models_reproduced"] == 16 and summary["primary_contours_reproduced"] == 2,
        no_initial_input_change=not initial_mismatches,
        input_output_and_human_decisions_unchanged=all(digest(ROOT / p) == sha for p, sha in sources.items()),
        prior_runtime_unchanged=not changed_runtime,
        no_live_bundle_export=not (result_dir / "prepared_floor.json").exists(),
        no_accuracy_or_ffb_authority=summary["selected_model"] is None and summary["physical_metric_verified"] is False and summary["usable_for_ffb"] is False,
        no_statistics_or_global_bound_claim=summary["statistical_uncertainty_estimated"] is False and summary["global_error_bound_proven"] is False)
    output = dict(status="PASS_OFFLINE_SENSITIVITY_SOFTWARE_ONLY" if all(checks.values()) else "FAIL",
                  checks=checks, tests=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors),
                  skipped=len(tests.skipped), patterns=patterns, source_sha256=sources,
                  initial_source_mismatches=initial_mismatches, prior_runtime_mismatches=changed_runtime,
                  prior_software_tests_reused=previous["tests"], physical_metric_verified=False, usable_for_ffb=False)
    with (args.output_dir / "verification.json").open("x") as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
    print(json.dumps({k: v for k, v in output.items() if k != "source_sha256"}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
