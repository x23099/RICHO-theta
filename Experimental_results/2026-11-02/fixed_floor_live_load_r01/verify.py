#!/usr/bin/env python3
"""Local loader regression and saved-real-PNG provenance check. No camera/GPU/ROS."""
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
HERE = Path(__file__).resolve().parent
BASE = "ccf5665"
CHANGED = ("cone_distance_worker.py", "run_cone_distance_live.py",
           "summarize_cone_distance_live.py", "cone_fixed_floor_shadow.py")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT / "src"))
    from cone_distance_core import DEFAULT_CONFIG, digest, load_config
    from cone_fixed_floor_live_load import validate_live_payload
    from prepare_fixed_floor_live_bundle import prepare
    from summarize_cone_distance_live import load_frames

    previous = json.loads((ROOT / "Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/verification_r02/verification.json").read_text())
    patterns = [*previous["patterns"], "test_fixed_floor_causal_bootstrap.py", "test_cone_fixed_floor_live_load.py"]
    helper = ROOT / "Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("loader_test_helpers", helper)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    with (args.output_dir / "tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir / "tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.rows)

    # Reuse the exact old bytes; no new image, fitting or session renaming.
    models = ROOT / "Experimental_results/2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/explicit_floor_models.json"
    originals = ROOT / "Experimental_results/2026-10-30/floor_board_pair_r01/originals"
    session = "15ae673c24484d119952ae391df611aa"
    pngs = [originals / f"decoded_{session}_f{n:06d}.png" for n in (1259, 1655)]
    hashes_before = {str(p.relative_to(ROOT)): sha(p) for p in [models, *pngs]}
    payload = prepare(models, pngs, DEFAULT_CONFIG, board_on_floor=True, rigid_board=True, static_camera=True)
    (args.output_dir / "prepared_historical_bundle.json").write_bytes(payload)
    settings = load_config()[0]
    adapter, evidence = validate_live_payload(payload, settings, digest(DEFAULT_CONFIG), originals, session, 1655,
                                              "support_completion_shadow")
    different_session_rejected = False
    try:
        validate_live_payload(payload, settings, digest(DEFAULT_CONFIG), originals,
                              "f860e50d1c4e485a98cbc1a2f6138cdf", 1689, "support_completion_shadow")
    except ValueError as exc:
        different_session_rejected = "session mismatch" in str(exc)

    unexpected_changes = []
    protected = {}
    tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "src"], cwd=ROOT, text=True).splitlines()
    for path in tracked:
        if Path(path).suffix not in (".py", ".json", ".sh"):
            continue
        before = subprocess.check_output(["git", "show", BASE+":"+path], cwd=ROOT)
        if Path(path).name not in CHANGED:
            protected[path] = (ROOT / path).read_bytes() == before
            if not protected[path]:
                unexpected_changes.append(path)
    snapshots = {name: (HERE / "source_snapshot" / name).read_bytes()
                 == subprocess.check_output(["git", "show", BASE+":src/"+name], cwd=ROOT) for name in CHANGED}
    replay = ROOT / "Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/results_r02"
    old_summary = json.loads((replay / "summary.json").read_text())
    old_hash_mismatches = []
    snapshot_substitutions = []
    for filename, expected in old_summary["source_sha256"].items():
        path = Path(filename)
        if path.parent == ROOT / "src" and path.name in CHANGED:
            path = HERE / "source_snapshot" / path.name
            snapshot_substitutions.append(filename)
        if sha(path) != expected:
            old_hash_mismatches.append(filename)
    rows, truncated, _ = load_frames(replay / "recorded_comparison/distance_frames.jsonl")
    original_hashes_stable = all(sha(ROOT / name) == value for name, value in hashes_before.items())
    checks = dict(tests_pass=result.wasSuccessful() and not result.skipped,
        unmodified_sources_preserved=all(protected.values()), original_snapshots_match_base=all(snapshots.values()),
        old_replay_hashes_preserved_with_explicit_prechange_snapshots=not old_hash_mismatches,
        old_logs_still_readable=len(rows) == 1547 and not truncated,
        real_png_same_session_bundle_parses=len(adapter.bundle["models"]) == 3,
        real_evidence_frames_preserved=[r["frame"] for r in evidence["source_frames"]] == [1259, 1655],
        real_png_other_session_rejected=different_session_rejected,
        original_images_and_model_bytes_unchanged=original_hashes_stable)
    files = [Path(__file__).resolve(), ROOT / "tests/test_cone_fixed_floor_live_load.py",
             ROOT / "src/cone_fixed_floor_live_load.py", ROOT / "src/prepare_fixed_floor_live_bundle.py",
             *[ROOT / "src" / name for name in CHANGED]]
    report = dict(status="PASS_OFFLINE_LOCAL_LOAD_NOT_HARDWARE_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks, tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        baseline_commit=BASE, patterns=patterns, protected_sources=protected, prechange_snapshots=snapshots,
        unexpected_changes=unexpected_changes, old_hash_mismatches=old_hash_mismatches,
        old_manifest_not_rewritten=True, old_manifest_snapshot_substitutions=snapshot_substitutions,
        historical_png_input_sha256=hashes_before, prepared_bundle_sha256=hashlib.sha256(payload).hexdigest(),
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in files},
        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False,
        camera_or_gpu_started=False, git_commit_or_push_performed=False)
    (args.output_dir / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k: report[k] for k in ("status", "checks", "tests", "failures", "errors", "skipped")}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
