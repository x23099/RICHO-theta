"""今回の保存済み測距ログの監査。画像・実機・ROSへアクセスしない。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from report_driver_motion_logs import (FRAME_FIELDS, distribution, read_jsonl,
                                      reject_constant, unique_object)


def load(path):
    return json.loads(path.read_bytes(), parse_constant=reject_constant,
                      object_pairs_hook=unique_object)


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.input_dir.resolve()
    report = load(args.report_dir / "summary.json")
    frame_path = source / "motion_distance_frames.jsonl"
    rows, digest = read_jsonl(frame_path, fields=FRAME_FIELDS)
    if digest != report["input_sha256"]["motion_distance_frames_jsonl"]:
        raise ValueError("report belongs to a different log")
    event_path = source / "motion_bridge_events.jsonl"
    if sha(event_path) != report["input_sha256"]["motion_bridge_events_jsonl"]:
        raise ValueError("report events differ")
    if len(report["sessions"]) != 1:
        raise ValueError("this audit requires one session")
    engine = load(source / "motion_engine_summary.json")
    bridge = load(source / "driver_motion_summary.json")
    current = report["sessions"][0]
    if engine["profile_sha256"] != current["profile_sha256"]:
        raise ValueError("profile mismatch")
    details, touches, completions = [], Counter(), Counter()
    with frame_path.open("rb") as stream:
        for line in stream:
            row = json.loads(line, parse_constant=reject_constant,
                             object_pairs_hook=unique_object)
            if row["reason"] != "colour_contour_reaches_roi_edge":
                continue
            obs = row.get("support_observation") or {}
            contexts = obs.get("contexts") or obs.get("upper_contexts") or [{}]
            component = contexts[0].get("component") or {}
            contact = component.get("touches") or {}
            pattern = "+".join(k for k in ("left", "right", "top", "bottom")
                               if contact.get(k) is True) or "unknown_or_none"
            touches[pattern] += 1
            completions[obs.get("completion_reason", "missing")] += 1
            details.append(dict(session=row["session"], frame=row["frame"],
                media_time_sec=row["media_time_sec"], touches=contact,
                completion_reason=obs.get("completion_reason"),
                upper_completion_reason=obs.get("upper_completion_reason"),
                selected_colours=obs.get("selected_colour"),
                detector_boxes=row.get("selected_detector_boxes"),
                native_pixels_available=False))
    bins = []
    origin = rows[0]["source_time_sec"]
    for index in range(int((rows[-1]["source_time_sec"] - origin) // 30) + 1):
        group = [r for r in rows if index * 30 <= r["source_time_sec"] - origin < (index + 1) * 30]
        if not group:
            continue
        bins.append(dict(relative_source_start_sec=index * 30, processed=len(group),
            numeric=sum(r["distance_available"] for r in group),
            withheld_reasons=dict(Counter(r["reason"] for r in group if not r["distance_available"])),
            distance_m=distribution([r["horizontal_camera_foot_range_m"] for r in group
                                     if r["distance_available"]]),
            physical_motion_observed=False))
    bursts, active = [], []
    for row in rows + [None]:
        if row is not None and row["reason"] == "colour_contour_reaches_roi_edge":
            active.append(row)
        elif active:
            bursts.append(dict(first_frame=active[0]["frame"], last_frame=active[-1]["frame"],
                count=len(active), completion_span_ms=1000 * (active[-1]["completed_time_sec"]
                                                           - active[0]["completed_time_sec"]),
                next_processed_reason=row["reason"] if row else None))
            active = []
    startup = [r for r in rows if r["reason"] == "frame_processing_too_old"]
    steady = [r for r in rows if r not in startup]
    evidence = engine.get("withheld_evidence", {})
    verification = None
    if args.evidence_dir is not None:
        from verify_driver_withheld_evidence import verify
        verification = verify(args.evidence_dir, frame_path)
    first_numeric = next((i for i, r in enumerate(rows) if r["distance_available"]), None)
    window = rows[first_numeric:] if first_numeric is not None else []
    payload = dict(schema="driver_motion_submitted_run_audit_v1", session=current["session"],
        input_sha256=report["input_sha256"], metadata=dict(engine=engine, bridge=bridge),
        metadata_sha256={p.name: sha(p) for p in source.iterdir() if p.is_file() and
                         p.name not in (frame_path.name, event_path.name)},
        frame_count_matches_bridge_returned=len(rows) == bridge.get("returned"),
        sent_minus_returned=bridge.get("sent", 0) - bridge.get("returned", 0),
        worker_error_reported=bridge.get("worker_error"),
        child_shutdown_confirmed=(bridge.get("child_stopped") is True and
                                  bridge.get("io_thread_stopped") is True),
        evidence_requested=evidence.get("requested"),
        evidence_recorder_started=evidence.get("recorder_started"),
        evidence_directory_on_gpu_pc=evidence.get("directory"),
        evidence_images_in_submission=verification["verified_pairs"] if verification else 0,
        evidence_index_in_submission=verification is not None,
        evidence_saved_pairs_verified=verification["verified_pairs"] if verification else None,
        evidence_archive_needed=verification is None,
        evidence_verification=verification,
        first_numeric_to_end_NOT_motion_window=dict(processed=len(window),
            numeric=sum(r["distance_available"] for r in window),
            first_frame=window[0]["frame"] if window else None,
            withheld_reasons=dict(Counter(r["reason"] for r in window if not r["distance_available"]))),
        startup_stale_records=[{k: r[k] for k in ("frame", "frame_age_ms", "predict_ms")} for r in startup],
        non_startup_timing_ms={k: distribution([r[k] for r in steady]) for k in
                              ("frame_age_ms", "predict_ms", "support_geometry_ms")},
        boundary_rejections=len(details), boundary_original_touches=dict(touches),
        boundary_completion_reasons=dict(completions), boundary_frames=details,
        boundary_processed_bursts=bursts, thirty_second_bins=bins,
        screen_recording_provided=False, motion_interval_identified=False,
        physical_accuracy_error_m=None, gui_time_withheld_fraction=None,
        actual_evidence_disk_load_measured=False, control_or_live_logic_changed=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: payload[k] for k in ("boundary_rejections", "boundary_original_touches",
        "boundary_completion_reasons", "child_shutdown_confirmed", "non_startup_timing_ms")}, indent=2))


if __name__ == "__main__":
    main()
