"""既存ログを読取り専用で時系列監査。物理運動やGUI表示時間は推定しない。"""
import argparse
from collections import Counter
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest
from cone_self_body_shadow import checked_reference, compare_self_body
from report_driver_motion_logs import reject_constant, unique_object, validate_result
from timeline import summarize


def load(path):
    return json.loads(path.read_bytes(), parse_constant=reject_constant, object_pairs_hook=unique_object)


def run(output):
    if output.exists():
        raise ValueError("new output required")
    prior = ROOT / "Experimental_results/2026-11-10/self_body_boundary_shadow_r01"
    saved = load(prior / "results_r01/summary.json")
    inputs = dict(saved["input_sha256"])
    inputs.update(saved["source_sha256"])
    csv_path = prior / "results_r01/numeric_log_shadow.csv"
    numeric_csv = list(csv.DictReader(csv_path.open()))
    numeric = {int(r["frame"]): r for r in numeric_csv}
    if len(numeric) != len(numeric_csv) or len(numeric) != saved["existing_numeric_records"]:
        raise ValueError("numeric reference has missing or duplicate rows")
    ref = checked_reference(load(prior / "reference.json"))
    spec = importlib.util.spec_from_file_location("saved_boundary_audit", ROOT /
        "Experimental_results/2026-11-10/support_boundary_audit_r01/audit.py")
    audit = importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    inputs.update({str(p): digest(p) for p in (csv_path, Path(spec.origin),
                   prior / "results_r01/summary.json")})
    source = ROOT / "recordings/2026-11-10/driver_motion_171250_intake_r01/driver_motion_live_20261110_171250"
    old_report = load(ROOT / "Experimental_results/2026-11-10/driver_motion_171250_review_r01/full_run_report/summary.json")
    events_path = source / "motion_bridge_events.jsonl"
    if digest(events_path) != old_report["input_sha256"]["motion_bridge_events_jsonl"]:
        raise ValueError("bridge log mismatch")
    accepted = {}
    with events_path.open("rb") as stream:
        for line in stream:
            event = json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_object)
            key = validate_result(event["result"])
            if key in accepted or type(event["accepted_current_session_and_age"]) is not bool:
                raise ValueError("invalid event join")
            accepted[key] = event["accepted_current_session_and_age"]
    inputs[str(events_path)] = digest(events_path)
    if any(digest(Path(p)) != sha for p, sha in inputs.items()):
        raise ValueError("previous inputs or baseline implementation changed")
    evidence = ROOT / "recordings/2026-11-10/driver_motion_171250_intake_r01/motion_withheld_20261110_171250"
    index = [json.loads(line) for line in (evidence / "evidence_index.jsonl").read_bytes().splitlines()]
    image_frames = {r["frame"] for r in index}
    if digest(evidence / f"decoded_{ref['session']}_f{ref['source_frame']:06d}.png") != ref["source_png_sha256"]:
        raise ValueError("body boundary reference image mismatch")
    rows, reasons, seen_numeric = [], Counter(), set()
    path = source / "motion_distance_frames.jsonl"
    with path.open("rb") as stream:
        for line in stream:
            r = json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_object)
            key = validate_result(r)
            if key not in accepted or r["session"] != ref["session"]:
                raise ValueError("single session matched bridge event required")
            clearance = None
            if r["distance_available"]:
                recorded = numeric[r["frame"]]
                seen_numeric.add(r["frame"])
                if float(recorded["range_m"]) != r["horizontal_camera_foot_range_m"]:
                    raise ValueError("numeric result changed")
                review = compare_self_body(r["support_observation"], ref,
                    session=r["session"], reference_matches=True)
                if review["revoked"] != (recorded["proposed_revoke"] == "True"):
                    raise ValueError("shadow classification changed")
                state = "numeric_body_boundary_conflict" if review["revoked"] else "numeric_clear_of_body_boundary"
                clearance = review["min_clearance_px"]
            elif r["reason"] == "colour_contour_reaches_roi_edge":
                late = audit.candidate_audit(r)
                if "relation" in late:
                    obs = dict(point=late["relation"]["point"], support=late["logged_candidate_support"],
                        reason="logged_bbox_candidate_NOT_live_output", floor_contact_verified=False,
                        physical_metric_verified=False, controlling_distance=False, usable_for_ffb=False)
                    review = compare_self_body(obs, ref, session=r["session"], reference_matches=True)
                    state = "boundary_withheld_body_boundary_conflict" if review["revoked"] else "boundary_withheld_clear_candidate"
                    clearance = review["min_clearance_px"]
                else:
                    state = "boundary_withheld_unresolved"
                reasons[late["audit_reason"]] += 1
            else:
                state = "other_withheld:" + r["reason"]
            rows.append(dict(session=r["session"], frame=r["frame"], source_time_sec=r["source_time_sec"],
                media_time_sec=r["media_time_sec"], completed_time_sec=r["completed_time_sec"],
                state=state, reason=r["reason"], range_m=r["horizontal_camera_foot_range_m"],
                support_pixel=r["support_pixel"], min_clearance_px=clearance,
                bridge_accepted=accepted[key], evidence_png_saved=r["frame"] in image_frames))
    if set(numeric) != seen_numeric:
        raise ValueError("numeric join incomplete")
    result = summarize(rows)
    conflict = [r for r in rows if r["state"] in
                ("numeric_body_boundary_conflict", "boundary_withheld_body_boundary_conflict")]
    lo, hi = conflict[0]["source_time_sec"] - 1, conflict[-1]["source_time_sec"] + 1
    window = [dict(r, relative_source_sec=r["source_time_sec"]-rows[0]["source_time_sec"]) for r in rows
              if lo <= r["source_time_sec"] <= hi]
    result.update(boundary_candidate_audit_reasons=dict(reasons),
        conflict_bridge_accepted=sum(r["bridge_accepted"] for r in conflict),
        conflict_frame_count=len(conflict),
        saved_images_in_conflict=sum(r["evidence_png_saved"] for r in conflict),
        window_processed_records=len(window), source_log_sha256=digest(path),
        input_sha256=inputs, source_sha256={str(p): digest(p) for p in
            (Path(__file__), HERE / "timeline.py", ROOT / "tests/test_motion_boundary_timeline.py")},
        original_live_results_modified=False, physical_error_measured=False,
        new_camera_or_vehicle_operation=False)
    test_log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_motion_boundary_timeline.py")
    tests = unittest.TextTestRunner(stream=test_log, verbosity=2).run(suite)
    if not tests.wasSuccessful():
        raise ValueError(test_log.getvalue())
    result["tests"] = dict(run=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors))
    if any(digest(Path(p)) != sha for p, sha in inputs.items()):
        raise ValueError("inputs changed during analysis")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "timeline.json").open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False);stream.write("\n")
    with (output / "local_window.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(window[0]));writer.writeheader();writer.writerows(window)
    with (output / "tests.log").open("x") as stream:stream.write(test_log.getvalue())
    print(json.dumps({k: result[k] for k in ("processed_records", "state_counts", "conflict_episodes", "tests")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    run(parser.parse_args().output_dir)
