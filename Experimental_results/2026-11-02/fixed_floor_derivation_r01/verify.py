#!/usr/bin/env python3
"""Saved floor geometry/export/local-loader checks. Never opens a receiver."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_fixed_floor_live_load import LocalFloorModelLoader, validate_live_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    previous = json.loads((HERE.parent/"fixed_floor_live_load_r01/verification_r04/verification.json").read_text())
    patterns = [*previous["patterns"], "test_floor_reference_pose.py", "test_diagnose_floor_board_pose.py",
                "test_fisheye_intrinsic_calibration.py", "test_derive_fixed_floor_live_bundle.py"]
    spec = importlib.util.spec_from_file_location("derivation_test_helpers",
        ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir/"tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.rows)

    report = json.loads((args.results_dir/"derivation_report.json").read_text())
    oldfile = ROOT/"Experimental_results/2026-10-30/floor_board_pair_r01/white_paper_quad_measured_r01.json"
    old = json.loads(oldfile.read_text())
    differences = []
    for row in report["poses"]:
        reference = next(r for r in old["rows"] if r["frame"] == row["frame"] and r["threshold"] == 170)
        name = "image_far_edge_long" if row["assignment"] == "as_listed" else "image_far_edge_short"
        saved = reference["quads"][0]["poses"][name]["candidates"]
        for solution in row["pose"]["candidates"]:
            expected = saved[solution["solution_index"]]
            differences.append(max(abs(solution["camera_height_above_floor_m"]-expected["camera_height_above_floor_m"]),
                float(np.max(np.abs(np.array(solution["up_optical"])-expected["up_optical"]))),
                abs(solution["fit_native_rmse_px"]-expected["fit_native_rmse_px"])))
    modelpath = args.results_dir/"prepared_floor.json"
    payload = modelpath.read_bytes()
    settings = load_config()[0]
    images = ROOT/"Experimental_results/2026-10-30/floor_board_pair_r01/originals"
    session = report["session"]
    adapter, evidence = validate_live_payload(payload, settings, digest(DEFAULT_CONFIG), images,
                                              session, 1700, "support_completion_shadow")
    rejected_other = False
    try:
        validate_live_payload(payload, settings, digest(DEFAULT_CONFIG), images,
                              "another_session", 1700, "support_completion_shadow")
    except ValueError:
        rejected_other = True
    # Fake frame metadata, NOT extra captured images and NOT a live connection.
    now = [10.]
    loader = LocalFloorModelLoader(modelpath, settings, digest(DEFAULT_CONFIG), images,
        args.output_dir/"simulated_local_load_events.jsonl", "support_completion_shadow", clock=lambda: now[0])
    try:
        accepted = loader.request(SimpleNamespace(session=session, sequence=1700, received_at=10.))[0]
        deadline = time.monotonic()+2
        while not loader.future.done() and time.monotonic() < deadline:
            time.sleep(.005)
        if not loader.future.done():
            raise RuntimeError("bounded local file load wait expired")
        now[0] = 10.1
        active = loader.step(SimpleNamespace(session=session, sequence=1701, received_at=10.1))
        state = loader.snapshot()
        invalidated = loader.step(SimpleNamespace(session="another_session", sequence=1, received_at=10.2)) is None
    finally:
        shutdown = loader.close()
    input_mismatches = [p for p, h in report["source_sha256"].items() if digest(Path(p)) != h]
    test_path = "tests/test_cone_fixed_floor_live_load.py"
    test_snapshot = HERE/"source_snapshot/test_cone_fixed_floor_live_load.py"
    previous_mismatches = [p for p, h in previous["source_sha256"].items()
                           if digest(test_snapshot if p == test_path else ROOT/p) != h]
    checks = dict(tests_pass=result.wasSuccessful() and not result.skipped,
        all_eight_saved_planar_solutions_reproduced=len(differences) == 8 and max(differences) < 1e-9,
        all_hypotheses_kept=len(adapter.bundle["models"]) == report["model_count"] == 16,
        all_source_bytes_unchanged=not input_mismatches,
        prior_runtime_preserved_and_test_prechange_snapshot_matches=not previous_mismatches,
        no_solution_selected=report["selected_solution"] is None and all(r["pose"]["selected_solution"] is None for r in report["poses"]),
        explicit_evidence_frames=[e["frame"] for e in evidence["source_frames"]] == [1259, 1655],
        other_session_rejected=rejected_other,
        simulated_local_load_accepted=accepted and active is not None and state["activated_frame"] == 1701,
        simulated_reconnect_invalidates=invalidated,
        local_load_finished=not shutdown["model_load_running"],
        no_physical_approval=all(report[k] is False for k in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb", "original_images_modified", "intrinsics_refitted")))
    files = [Path(__file__).resolve(), HERE/"references.json", args.results_dir/"prepared_floor.json",
             args.results_dir/"derivation_report.json", oldfile, ROOT/"src/derive_fixed_floor_live_bundle.py",
             ROOT/"tests/test_derive_fixed_floor_live_bundle.py", ROOT/test_path, test_snapshot]
    output = dict(status="PASS_SAVED_IMAGE_DERIVATION_NOT_LIVE_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks, tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        patterns=patterns, maximum_saved_solution_numerical_difference=max(differences),
        input_hash_mismatches=input_mismatches, previous_source_hash_mismatches=previous_mismatches,
        intentional_test_only_change="fake GUI key-routing cleanup uses inline stub, not real asyncio thread pool; runtime untouched",
        old_test_hash_checked_against=str(test_snapshot.relative_to(ROOT)),
        source_sha256={str(p.resolve().relative_to(ROOT)): digest(p) for p in files},
        simulated_frame_numbers_not_camera_frames=[1700, 1701], physical_metric_verified=False,
        usable_for_ffb=False, camera_gpu_ros_started=False, git_commit_or_push_performed=False)
    (args.output_dir/"verification.json").write_text(json.dumps(output, indent=2)+"\n")
    print(json.dumps({k: output[k] for k in ("status", "checks", "tests", "failures", "errors", "skipped")}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
