"""Verify image-only audit and preserve source/runtime hashes."""
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
    mismatches = [p for p, sha in sources.items() if digest(ROOT / p) != sha]
    patterns = ["test_paper_boundary_stability.py", "test_paper_corner_sensitivity.py",
                "test_reviewed_coordinate_audit.py", "test_review_physical_reference.py",
                "test_cone_fixed_floor_candidate.py", "test_derive_fixed_floor_live_bundle.py",
                "test_floor_reference_pose.py"]
    for path in [Path(__file__), *results.iterdir(), *[ROOT / "tests" / name for name in patterns]]:
        sources[str(path.relative_to(ROOT))] = digest(path)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    with (results / "conditional_geometry.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    groups = {}
    for row in rows:
        groups.setdefault(row["id"], set()).add((row["assignment"], row["tracked_branch"], row["height_source"]))
    prior = read(ROOT / "Experimental_results/2026-11-04/upper_support_live_r01/verification_r01/verification.json")
    changed_runtime = [p for p, sha in prior["source_sha256"].items() if digest(ROOT / p) != sha]
    checks = dict(
        tests_pass=tests.wasSuccessful() and not tests.skipped,
        source_hashes_match=not mismatches,
        source_and_output_and_decision_bytes_unchanged=all(digest(ROOT / p) == sha for p, sha in sources.items()),
        source_image_memory_unchanged=summary["original_image_memory_unchanged"] is True,
        old_extractors_reproduced=summary["primary_extractors_reproduced"] == 2,
        candidate_and_geometry_counts=len(groups) == summary["candidates"] == 52 and len(rows) == summary["geometry_rows"] == 416,
        all_eight_families_kept=all(len(values) == 8 for values in groups.values()),
        all_seed_trials_recorded=summary["seed_corner_records"] == 2*3*17*4 and summary["seed_stability_records"] == 24,
        no_human_seeding_or_metric_fit=summary["manual_clicks_used_for_seeding"] is False and summary["reference_distances_used"] is False,
        no_method_or_authority_selected=summary["selected_method"] is None and summary["physical_metric_verified"] is False and summary["usable_for_ffb"] is False,
        no_live_bundle_export=not (results / "prepared_floor.json").exists(),
        prior_runtime_unchanged=not changed_runtime)
    output = dict(status="PASS_IMAGE_ONLY_BOUNDARY_AUDIT_NOT_PHYSICAL_APPROVAL" if all(checks.values()) else "FAIL",
                  checks=checks, tests=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors), skipped=len(tests.skipped),
                  patterns=patterns, source_sha256=sources, source_mismatches=mismatches,
                  runtime_mismatches=changed_runtime, prior_software_tests_reused=prior["tests"],
                  physical_metric_verified=False, usable_for_ffb=False)
    with (args.output_dir / "verification.json").open("x") as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
    print(json.dumps({k: v for k, v in output.items() if k != "source_sha256"}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
