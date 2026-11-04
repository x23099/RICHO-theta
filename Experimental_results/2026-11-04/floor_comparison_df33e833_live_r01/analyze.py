"""Summarize submitted live rows and plot logged stability; no live hardware."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
from summarize_cone_distance_live import load_frames
from cone_fixed_floor_display import comparison_view_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    rows, truncated, hashed = load_frames(args.input, allow_truncated_last_line=True)
    if not rows or len({r["session"] for r in rows}) != 1:
        raise ValueError("nonempty one-session receiver log required")
    t0 = rows[0]["source_time_sec"]
    model_values, model_reasons = defaultdict(list), Counter()
    records, long_records, observed_edges = [], [], Counter()
    gui_reasons = Counter()
    for row in rows:
        shadow = row.get("fixed_floor_shadow") or {}
        models = shadow.get("models", [])
        values = []
        for model in models:
            value = model["horizontal_camera_foot_range_m"]
            if model["range_available"]:
                model_values[model["model_name"]].append(value)
                values.append(value)
            else:
                model_reasons[model["reason"]] += 1
            long_records.append(dict(frame=row["frame"], elapsed_sec=row["source_time_sec"]-t0,
                model_name=model["model_name"], range_available=model["range_available"],
                horizontal_camera_foot_range_m=value, reason=model["reason"]))
        point_present = row.get("base_pixel") is not None
        edges = (row["frame_evidence"]["support_observation"].get("mask_diagnostics") or {}).get("touching_edges", [])
        if not point_present:
            observed_edges["+".join(edges) or "none"] += 1
        records.append(dict(frame=row["frame"], elapsed_sec=row["source_time_sec"]-t0,
            frame_age_ms=row["frame_age_ms"], baseline_reason=row["reason"],
            baseline_marker_point_present=int(point_present), comparison_available=int(bool(values)),
            comparison_available_models=len(values), comparison_reason=shadow.get("reason"),
            comparison_quality_accepted=shadow.get("image_quality_accepted"),
            baseline_touching_edges="+".join(edges), loader_state=(row.get("fixed_floor_load") or {}).get("state")))
        gui_reasons[comparison_view_model(row,model_state=row.get("fixed_floor_load"),
            now=row["completed_time_sec"])["reason"]] += 1
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, data in (("frame_status.csv",records),("model_ranges.csv",long_records)):
        with (args.output_dir/name).open("x",newline="") as stream:
            writer = csv.DictWriter(stream,fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    count = len(rows)
    duration = rows[-1]["source_time_sec"]-t0
    present = sum(r["baseline_marker_point_present"] for r in records)
    numeric = sum(r["comparison_available"] for r in records)
    report = dict(status="LIVE_COMPARISON_STABLE_IN_SUBMITTED_WINDOW_NOT_METRIC_APPROVAL",
        input_sha256=hashed, input_path=str(args.input.resolve()), complete_rows=count,
        trailing_incomplete_json_dropped=truncated, session=rows[0]["session"],
        first_frame=rows[0]["frame"], last_frame=rows[-1]["frame"], source_span_sec=duration,
        processed_row_interval_rate_hz=(count-1)/duration if duration>0 else None,
        unlogged_source_sequence_numbers_in_span=rows[-1]["frame"]-rows[0]["frame"]+1-count,
        baseline_reasons=dict(Counter(r["baseline_reason"] for r in records)),
        baseline_distance_available_rows=sum(r["distance_available"] for r in rows),
        baseline_marker_point_present_rows=present, baseline_marker_point_absent_rows=count-present,
        baseline_marker_presence_transitions=sum(a["baseline_marker_point_present"]!=b["baseline_marker_point_present"]
            for a,b in zip(records,records[1:])),
        absent_marker_touching_edges=dict(observed_edges),
        absent_marker_baseline_reasons=dict(Counter(r["baseline_reason"] for r in records if not r["baseline_marker_point_present"])),
        comparison_numeric_rows=numeric, comparison_numeric_fraction=numeric/count,
        comparison_available_model_counts=dict(Counter(r["comparison_available_models"] for r in records)),
        comparison_reasons=dict(Counter(r["comparison_reason"] for r in records)),
        comparison_quality_accepted_rows=sum(r["comparison_quality_accepted"] is True for r in records),
        loader_states=dict(Counter(r["loader_state"] for r in records)),
        loader_generations=sorted({r["fixed_floor_load"]["generation"] for r in rows}),
        bundle_hashes=sorted({r["fixed_floor_load"]["bundle_sha256"] for r in rows}),
        comparison_support_pixels=sorted({tuple(r["fixed_floor_shadow"]["support_pixel"]) for r in rows}),
        model_statistics={k:dict(samples=len(v),min_m=min(v),median_m=statistics.median(v),max_m=max(v),
            stddev_m=statistics.pstdev(v)) for k,v in model_values.items()},
        model_withheld_reason_counts=dict(model_reasons), gui_reasons_at_logged_completion_time=dict(gui_reasons),
        timing_ms={k:dict(min=min(r[k] for r in rows),median=statistics.median(r[k] for r in rows),max=max(r[k] for r in rows))
            for k in ("frame_age_ms","predict_ms","support_geometry_ms","cone_service_ms")},
        independent_ground_truth_for_this_placement=False, physical_metric_verified=False, usable_for_ffb=False,
        gui_every_draw_recorded=False, logged_completion_time_check_not_current_live_replay=True,
        camera_gpu_ros_started_by_analysis=False)
    checks = dict(all_rows_have_numeric_comparison=numeric==count,
        comparison_quality_all_accepted=report["comparison_quality_accepted_rows"]==count,
        same_active_generation=report["loader_states"]=={"active":count} and len(report["loader_generations"])==1,
        all_missing_baseline_points_explained_by_roi_edge=report["absent_marker_baseline_reasons"]=={"colour_contour_reaches_roi_edge":count-present},
        gui_semantics_accept_all_logged_rows=gui_reasons==Counter({"unverified_comparison_only":count}))
    report["window_checks"] = checks
    if not all(checks.values()):
        report["status"]="REVIEW_WINDOW_CHECKS_NOT_METRIC_APPROVAL"
    report["source_sha256"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__).resolve(),ROOT/"src/summarize_cone_distance_live.py",ROOT/"src/cone_fixed_floor_display.py",ROOT/"src/cone_distance_core.py")}
    (args.output_dir/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
    # Chart uses the saved CSV as its plotted source, never a camera image.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with (args.output_dir/"model_ranges.csv").open(newline="") as stream:
        plot_models = defaultdict(list)
        for row in csv.DictReader(stream):
            if row["range_available"]=="True":
                plot_models[row["model_name"]].append((float(row["elapsed_sec"]),float(row["horizontal_camera_foot_range_m"])))
    with (args.output_dir/"frame_status.csv").open(newline="") as stream:
        plot_status=list(csv.DictReader(stream))
    fig, axes=plt.subplots(2,1,figsize=(11,6),sharex=True,gridspec_kw={"height_ratios":[2,1]})
    for name, points in plot_models.items():
        label=name.removeprefix("f002292_").replace("image_plane_plus_thickness","paper+thickness").replace("external_height_image_normal","external-height")
        axes[0].plot(*zip(*points),label=label,linewidth=1.3)
    axes[0].set_ylabel("Horizontal comparison range (m)")
    axes[0].legend(loc="upper right",fontsize=8)
    axes[0].set_title("Recorded live outputs (~20 s): stability, NOT distance accuracy")
    t=[float(r["elapsed_sec"]) for r in plot_status]
    axes[1].step(t,[int(r["baseline_marker_point_present"]) for r in plot_status],where="post",label="Baseline marker point present",color="darkorange")
    axes[1].step(t,[int(r["comparison_available"]) for r in plot_status],where="post",label="Fixed-floor comparison available",linestyle="--",color="tab:blue")
    axes[1].set_yticks([0,1],labels=["Absent","Present"])
    axes[1].set_ylim(-.15,1.15)
    axes[1].set_xlabel("Seconds since first submitted receiver row")
    axes[1].legend(loc="lower right",fontsize=8)
    for axis in axes: axis.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(args.output_dir/"live_stability.png",dpi=150)
    plt.close(fig)
    print(json.dumps({k:report[k] for k in ("status","complete_rows","source_span_sec","comparison_numeric_rows", "baseline_marker_point_absent_rows","window_checks","model_statistics")},indent=2))


if __name__=="__main__":
    main()
