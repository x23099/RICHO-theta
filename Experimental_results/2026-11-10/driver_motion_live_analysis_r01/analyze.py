"""提出済みログと画面録画の対応監査。実機・推論・ネットワークは起動しない。"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from report_driver_motion_logs import FRAME_FIELDS, read_jsonl, summarize

SESSION = "7f33c225af3948c2aa61d66d52765c2e"
WINDOWS = {"static_screen_source_bounds": (10031, 10300),
           "motion_screen_source_bounds": (33809, 34379)}


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024*1024), b""):
            sha.update(data)
    return sha.hexdigest()


def save_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    if output.exists() or output == source or source in output.parents:
        raise ValueError("new output outside source required")
    frames, frame_sha = read_jsonl(source/"motion_distance_frames.jsonl", fields=FRAME_FIELDS)
    events, event_sha = read_jsonl(source/"motion_bridge_events.jsonl")
    full, _ = summarize(frames, events)
    if {r["session"] for r in frames} != {SESSION}:
        raise ValueError("this analysis is for the submitted 7f33c225 run only")
    metadata_names = ("driver_motion_summary.json", "motion_engine_summary.json", "motion_profile_used.json")
    metadata = {name: json.loads((source/name).read_text()) for name in metadata_names}
    shutdown = metadata["driver_motion_summary.json"]
    if not len(frames) == len(events) == shutdown["sent"] == shutdown["returned"]:
        raise ValueError("final summary/log counts mismatch")
    engine = metadata["motion_engine_summary.json"]
    if digest(source/"motion_profile_used.json") != engine["profile_sha256"]:
        raise ValueError("profile bytes do not match logged SHA")
    if {r["profile_sha256"] for r in frames} != {engine["profile_sha256"]}:
        raise ValueError("frame/engine profile mismatch")
    if sum(not e["accepted_current_session_and_age"] for e in events) != shutdown["retired_results"]:
        raise ValueError("retired result count mismatch")

    windows = {}
    for name, (lo, hi) in WINDOWS.items():
        subset = [r for r in frames if lo <= r["frame"] <= hi]
        event_subset = [e for e in events if lo <= e["result"]["frame"] <= hi]
        summary, _ = summarize(subset, event_subset)
        windows[name] = dict(source_frame_bounds_inclusive=[lo, hi],
                             bounds_are_screenshot_source_frames_NOT_exact_screen_PTS=True,
                             summary=summary)

    observations_path = ROOT/"Experimental_results/2026-11-10/driver_motion_live_review_r01/screen_observations.csv"
    indexed = {r["frame"]: r for r in frames}
    matches = []
    with observations_path.open() as stream:
        for obs in csv.DictReader(stream):
            if not obs["source_frame"]:
                continue  # WITHHELD screen does not show a source frame.
            row = indexed[int(obs["source_frame"])]
            if (not SESSION.startswith(obs["source_session_prefix"]) or not row["distance_available"]
                    or f'{row["horizontal_camera_foot_range_m"]:.3f}' != obs["display_distance_m"]):
                raise ValueError("screen/log identity or rounded value mismatch")
            if int(obs["display_receive_age_ms"]) + 1 < row["frame_age_ms"]:
                raise ValueError("display age precedes processing completion")
            matches.append(dict(sample=obs["sample"], source_frame=row["frame"],
                                screen_value_m=obs["display_distance_m"],
                                log_value_m=row["horizontal_camera_foot_range_m"], matched=True))

    # Keep only the diagnostic scalar evidence for the twenty rejected frames.
    rejections = []
    lo, hi = WINDOWS["motion_screen_source_bounds"]
    with (source/"motion_distance_frames.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if not (lo <= row["frame"] <= hi) or row["distance_available"]:
                continue
            observation = row.get("support_observation") or {}
            contexts = observation.get("upper_contexts") or []
            first = contexts[0] if contexts else {}
            component = first.get("component") or {}
            rejections.append(dict(frame=row["frame"], source_time_sec=row["source_time_sec"],
                reason=row["reason"], touches=component.get("touches"),
                crop_xyxy=first.get("crop_xyxy"), colour_bounds_xyxy=component.get("bounds_xyxy"),
                completion_reason=observation.get("completion_reason"),
                upper_completion_reason=observation.get("upper_completion_reason"),
                selected_detector_boxes=row.get("selected_detector_boxes")))
    touched = Counter(side for row in rejections for side, yes in (row["touches"] or {}).items() if yes)

    sha = {name: digest(source/name) for name in (*metadata_names, "motion_worker_stderr.log")}
    if digest(source/"motion_distance_frames.jsonl") != frame_sha or digest(source/"motion_bridge_events.jsonl") != event_sha:
        raise ValueError("input changed during analysis; use closed logs")
    sha.update({"motion_distance_frames.jsonl": frame_sha, "motion_bridge_events.jsonl": event_sha})
    output.mkdir(parents=True, exist_ok=False)
    save_json(output/"analysis.json", dict(schema="driver_live_submitted_run_analysis_v1",
        input_dir=str(source), input_sha256=sha, full_run=full, windows=windows,
        screen_observations_sha256=digest(observations_path), screen_numeric_matches=matches,
        rejection_boundary_counts=dict(touched), runtime_metadata=metadata,
        exact_ground_truth_available=False, gui_time_withheld_fraction=None,
        control_or_end_to_end_latency_measured=False))
    save_json(output/"motion_window_rejections.json", rejections)
    rows = [r for r in frames if lo <= r["frame"] <= hi]
    fields = ["frame", "source_elapsed_sec", "distance_available", "horizontal_camera_foot_range_m",
              "reason", "frame_age_ms", "predict_ms", "support_geometry_ms"]
    with (output/"motion_window_frames.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            values = {k: row[k] for k in fields if k != "source_elapsed_sec"}
            values["source_elapsed_sec"] = row["source_time_sec"]-rows[0]["source_time_sec"]
            writer.writerow(values)
    print("Validated closed logs; screen/log numeric matches:", len(matches))
    print("Motion withheld boundary contacts:", dict(touched))


if __name__ == "__main__":
    main()
