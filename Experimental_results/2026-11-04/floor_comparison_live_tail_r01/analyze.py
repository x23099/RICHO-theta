"""Analyze submitted native receiver rows; no camera/GPU/ROS/control activity."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_fixed_floor_display import comparison_view_model
from summarize_cone_distance_live import validate_row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    payload = args.input.read_bytes()
    lines = payload.splitlines()
    rows, dropped_tail = [], False
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if number == len(lines) and not payload.endswith(b"\n"):
                dropped_tail = True
                break
            raise
        validate_row(row)
        rows.append(row)
    if not rows:
        raise ValueError("no complete validated rows")
    sessions = sorted({r["session"] for r in rows})
    if len(sessions) != 1:
        raise ValueError("one continuous receiver session required")
    for before, after in zip(rows, rows[1:]):
        if after["frame"] <= before["frame"] or after["source_time_sec"] <= before["source_time_sec"]:
            raise ValueError("nonincreasing source sequence/time")
    values, unavailable = defaultdict(list), Counter()
    frame_records, patched_views = [], []
    original_tuple_validation_errors = Counter()
    for row in rows:
        shadow = row.get("fixed_floor_shadow") or {}
        for model in shadow.get("models", []):
            if model["range_available"]:
                values[model["model_name"]].append(model["horizontal_camera_foot_range_m"])
            else:
                unavailable[model["reason"]] += 1
            frame_records.append(dict(frame=row["frame"], source_time_sec=row["source_time_sec"],
                model_name=model["model_name"], range_available=model["range_available"],
                horizontal_camera_foot_range_m=model["horizontal_camera_foot_range_m"], reason=model["reason"]))
        view = comparison_view_model(row, model_state=row.get("fixed_floor_load"), now=row["completed_time_sec"])
        patched_views.append(view)
        # Reconstruct ONLY the live ROI representation. Never edit submitted rows.
        if isinstance(row.get("target_roi_native_xyxy"), list):
            memory_row = dict(row, target_roi_native_xyxy=tuple(row["target_roi_native_xyxy"]))
            try:
                validate_row(memory_row)
            except ValueError as exc:
                original_tuple_validation_errors[str(exc)] += 1
            memory_view = comparison_view_model(memory_row, model_state=row.get("fixed_floor_load"),
                now=row["completed_time_sec"])
            if memory_view != view:
                raise ValueError("fixed GUI differs between live ROI and saved ROI")
    def count(key):
        return dict(Counter(r.get(key) for r in rows))
    def nested_count(key, field):
        return dict(Counter((r.get(key) or {}).get(field) for r in rows))
    report = dict(status="LOGGED_COMPARISON_CONFIRMED_NOT_PHYSICAL_APPROVAL",
        input_path=str(args.input.resolve()), input_sha256=hashlib.sha256(payload).hexdigest(),
        complete_rows=len(rows), trailing_incomplete_json_dropped=dropped_tail, sessions=sessions,
        first_frame=rows[0]["frame"], last_frame=rows[-1]["frame"],
        source_span_sec=rows[-1]["source_time_sec"]-rows[0]["source_time_sec"],
        baseline_reasons=count("reason"), baseline_available_rows=sum(r["distance_available"] for r in rows),
        inference_sources=count("inference_source"), loader_states=nested_count("fixed_floor_load", "state"),
        comparison_reasons=nested_count("fixed_floor_shadow", "reason"),
        numeric_comparison_rows=sum(v["range_span_m"] is not None for v in patched_views),
        model_unavailable_reasons=dict(unavailable),
        original_in_memory_roi_validation_errors=dict(original_tuple_validation_errors),
        model_statistics={name:dict(samples=len(v), min_m=min(v), median_m=statistics.median(v),
            max_m=max(v), stddev_m=statistics.pstdev(v)) for name, v in values.items()},
        timing_ms={key:dict(min=min(r[key] for r in rows), median=statistics.median(r[key] for r in rows),
            max=max(r[key] for r in rows)) for key in ("frame_age_ms", "predict_ms", "support_geometry_ms", "cone_service_ms")},
        support_pixels=sorted({tuple(r["fixed_floor_shadow"]["support_pixel"]) for r in rows}),
        comparison_bundle_sha256=sorted({r["fixed_floor_shadow"]["model_bundle_sha256"] for r in rows}),
        independent_ground_truth_available=False, physical_metric_verified=False,
        floor_contact_verified=False, usable_for_ffb=False,
        gui_rechecked_at_logged_completion_time_only=True, actual_live_gui_verified=False,
        camera_gpu_ros_started_by_this_analysis=False)
    report["source_sha256"] = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__).resolve(), ROOT/"src/cone_fixed_floor_display.py", ROOT/"src/summarize_cone_distance_live.py")}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir/"model_ranges.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(frame_records[0]))
        writer.writeheader()
        writer.writerows(frame_records)
    (args.output_dir/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
