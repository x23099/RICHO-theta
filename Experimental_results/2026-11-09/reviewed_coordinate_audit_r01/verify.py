"""Verify analysis helpers and immutable inputs, not live/physical accuracy."""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from review_physical_reference import read_json, validate_queue, load_decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    base = Path(__file__).resolve().parent
    result_dir = base / "results_r02"
    summary = read_json(result_dir / "summary.json")
    prep = base.parent / "physical_reference_review_r01"
    queue_path = prep / "prepared_r01/queue.json"
    queue = validate_queue(read_json(queue_path))
    queue_sha = digest(queue_path)
    decisions = load_decisions(prep / "prepared_r01/decisions", queue, queue_sha)
    # Also bind implementation and config/KB4/heading bytes, beyond the
    # imagery, labels and recording hashes already bound by analyze.py.
    config = load_config()[0]
    sources = dict(summary["source_sha256"])
    paths = [Path(__file__), base / "analyze.py", DEFAULT_CONFIG,
             ROOT / config["camera_candidate"], ROOT / config["floor_candidate"]]
    paths += [ROOT / "src" / name for name in (
        "review_physical_reference.py", "angular_fisheye_geometry.py",
        "cone_fixed_floor_candidate.py", "derive_fixed_floor_live_bundle.py",
        "cone_distance_core.py", "summarize_cone_distance_live.py")]
    paths += sorted(result_dir.iterdir())
    patterns = ["test_reviewed_coordinate_audit.py", "test_review_physical_reference.py",
                "test_cone_fixed_floor_candidate.py", "test_derive_fixed_floor_live_bundle.py",
                "test_floor_reference_pose.py"]
    paths += [ROOT / "tests" / name for name in patterns]
    mismatches = [path for path, sha in sources.items() if digest(ROOT / path) != sha]
    for path in paths:
        sources[str(path.relative_to(ROOT))] = digest(path)
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    previous_path = ROOT / "Experimental_results/2026-11-04/upper_support_live_r01/verification_r01/verification.json"
    previous = read_json(previous_path)
    runtime_changed = [p for p, sha in previous["source_sha256"].items() if digest(ROOT / p) != sha]
    bundles = [read_json(result_dir / (session + "_manual_visual_hypotheses_NOT_live.json"))
               for session in ("b559e424", "df33e833")]
    checks = dict(
        tests_pass=result.wasSuccessful() and not result.skipped,
        six_explicit_human_decisions=len(decisions) == 6 and all(
            d["status"] == "reviewed" and d["reviewer"] == "human_local"
            and d["confirmation_method"] == "explicit_manual_key" for d in decisions.values()),
        no_analysis_source_mismatch=not mismatches,
        no_input_or_decision_or_output_changed=all(digest(ROOT / p) == sha for p, sha in sources.items()),
        prior_runtime_unchanged=not runtime_changed,
        both_dimension_hypotheses_retained=all(len(b["models"]) == 8 for b in bundles),
        no_authority_granted=summary["selected_model"] is None and all(
            m["physical_metric_verified"] is False and m["usable_for_ffb"] is False
            and m["floor_contact_verified"] is False for b in bundles for m in b["models"]),
        no_live_load_bundle_exported=not (result_dir / "prepared_floor.json").exists(),
        recorded_values_crosschecked=summary["same_frame_integer_measurements_crosschecked"] == 32
            and summary["stored_same_frame_model_verdicts_crosschecked"] == 24)
    output = dict(status="PASS_ANALYSIS_SOFTWARE_ONLY" if all(checks.values()) else "FAIL",
                  tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  skipped=len(result.skipped), checks=checks, patterns=patterns,
                  source_sha256=sources, source_mismatches=mismatches,
                  prior_runtime_mismatches=runtime_changed, prior_software_tests_reused=previous["tests"],
                  original_images_modified=False, physical_metric_verified=False, usable_for_ffb=False)
    with (args.output_dir / "verification.json").open("x") as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in output.items() if k != "source_sha256"}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
