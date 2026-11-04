"""Compare three user-reported placements, preserving genuine withheld rows."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"src"))
from summarize_cone_distance_live import load_frames
from cone_fixed_floor_display import comparison_view_model
from cone_fixed_floor_live_load import png_digest

PRIMARY = "f002292_as_listed_s0_image_plane_plus_thickness"


def stats(values):
    return dict(count=len(values),min=min(values),median=statistics.median(values),max=max(values)) if values else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",required=True,type=Path)
    args=parser.parse_args()
    manifest_path=Path(__file__).with_name("cases.json")
    spec=json.loads(manifest_path.read_text())
    reports, summaries, frames, pixel_groups = [], [], [], []
    for case in spec["cases"]:
        path=ROOT/case["input"]
        rows,truncated,hashed=load_frames(path,allow_truncated_last_line=True)
        if not rows or hashed!=case["sha256"] or truncated:
            raise ValueError("complete exact submitted log required")
        if any(r["session"]!=spec["session"] or r["fixed_floor_load"]["state"]!="active"
                or r["fixed_floor_load"]["generation"]!=1
                or r["fixed_floor_load"]["bundle_sha256"]!=spec["bundle_sha256"] for r in rows):
            raise ValueError("same active session/generation/model required")
        evidence=None
        if case["image"] is not None:
            if png_digest(ROOT/case["image"])!=case["image_sha256"]:
                raise ValueError("native image changed")
            matching=[r for r in rows if r["frame"]==case["image_frame"]]
            if len(matching)!=1:
                raise ValueError("exact PNG frame absent from submitted log")
            row=matching[0]
            evidence=dict(frame=row["frame"],support_pixel=row["fixed_floor_shadow"]["support_pixel"],
                selected_detector_boxes=row["selected_detector_boxes"],comparison_reason=row["fixed_floor_shadow"]["reason"])
        names=[m["model_name"] for m in rows[0]["fixed_floor_shadow"]["models"]]
        values=defaultdict(list)
        per_model_reasons=defaultdict(Counter)
        per_y=defaultdict(list)
        no_value_runs=[]
        numeric=0
        t0=rows[0]["source_time_sec"]
        gui=Counter()
        for row in rows:
            shadow=row["fixed_floor_shadow"]
            models=shadow["models"]
            if [m["model_name"] for m in models]!=names:
                raise ValueError("model order changed")
            count=sum(m["range_available"] for m in models)
            numeric+=bool(count)
            primary=next(m for m in models if m["model_name"]==PRIMARY)
            point=shadow["support_pixel"]
            for model in models:
                if model["range_available"]:
                    values[model["model_name"]].append(model["horizontal_camera_foot_range_m"])
                else:per_model_reasons[model["model_name"]][model["reason"]]+=1
            if primary["range_available"]:
                per_y[point[1]].append(primary["horizontal_camera_foot_range_m"])
            frames.append(dict(case=case["id"],frame=row["frame"],elapsed_sec=row["source_time_sec"]-t0,
                reference_m=case["reference_m"],available_models=count,comparison_reason=shadow["reason"],
                baseline_reason=row["reason"],support_x=point[0] if point else None,support_y=point[1] if point else None,
                primary_range_m=primary["horizontal_camera_foot_range_m"],frame_age_ms=row["frame_age_ms"]))
            gui[comparison_view_model(row,model_state=row["fixed_floor_load"],now=row["completed_time_sec"])["reason"]]+=1
            if not count:
                if not no_value_runs or no_value_runs[-1].get("recovered_sec") is not None:
                    no_value_runs.append(dict(first_frame=row["frame"],last_frame=row["frame"],
                        start_sec=row["source_time_sec"],end_sec=row["source_time_sec"],rows=1,recovered_sec=None))
                else:
                    no_value_runs[-1].update(last_frame=row["frame"],end_sec=row["source_time_sec"],rows=no_value_runs[-1]["rows"]+1)
            elif no_value_runs and no_value_runs[-1]["recovered_sec"] is None:
                no_value_runs[-1]["recovered_sec"]=row["source_time_sec"]
        for run in no_value_runs:
            run["first_to_last_withheld_sec"]=run["end_sec"]-run["start_sec"]
            run["first_to_recovery_sec"]=None if run["recovered_sec"] is None else run["recovered_sec"]-run["start_sec"]
        for name in names:
            v=values[name]
            summary=dict(case=case["id"],reference_m=case["reference_m"],model_name=name,
                rows=len(rows),available_rows=len(v),available_fraction=len(v)/len(rows),
                min_m=min(v) if v else None,median_m=statistics.median(v) if v else None,max_m=max(v) if v else None,
                median_minus_reference_m=statistics.median(v)-case["reference_m"] if v else None,
                matched_origin_and_target_verified=False,physical_metric_verified=False)
            summaries.append(summary)
        for y,v in per_y.items():pixel_groups.append(dict(case=case["id"],support_y=y,**stats(v)))
        reports.append(dict(case=case["id"],reference_m=case["reference_m"],input_sha256=hashed,
            rows=len(rows),first_frame=rows[0]["frame"],last_frame=rows[-1]["frame"],
            source_span_sec=rows[-1]["source_time_sec"]-t0,numeric_comparison_rows=numeric,
            comparison_reasons=dict(Counter(r["fixed_floor_shadow"]["reason"] for r in rows)),
            gui_reasons_at_logged_completion_time=dict(gui),
            baseline_reasons=dict(Counter(r["reason"] for r in rows)),
            frame_age_ms=stats([r["frame_age_ms"] for r in rows]),
            no_value_runs=no_value_runs,per_model_withholding_reasons={k:dict(v) for k,v in per_model_reasons.items()},
            completion_granted_rows=sum((r["support_completion_shadow"]["candidate"] or {}).get("completion_granted",False) for r in rows),
            image_frame_evidence=evidence))
    args.output_dir.mkdir(parents=True,exist_ok=False)
    for name,records in (("case_model_summary.csv",summaries),("frame_status.csv",frames),("support_y_sensitivity.csv",pixel_groups)):
        with (args.output_dir/name).open("x",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    result=dict(status="SAME_SESSION_MULTIDISTANCE_COMPARISON_NOT_METRIC_APPROVAL",session=spec["session"],
        bundle_sha256=spec["bundle_sha256"],cases=reports,total_validated_rows=len(frames),
        inputs_original_bytes_unchanged=True,reference_origin=spec["reference_origin"],reference_target=spec["reference_target"],
        estimated_quantity=spec["estimated_quantity"],origin_and_target_equivalence_verified=False,
        physical_metric_verified=False,model_selected=False,calibration_fitted=False,usable_for_ffb=False,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__).resolve(),manifest_path,ROOT/"src/cone_fixed_floor_display.py",ROOT/"src/summarize_cone_distance_live.py")})
    (args.output_dir/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with (args.output_dir/"case_model_summary.csv").open(newline="") as stream: plotted=list(csv.DictReader(stream))
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for name in sorted({r["model_name"] for r in plotted if r["median_m"]}):
        selected=[r for r in plotted if r["model_name"]==name]
        label=name.removeprefix("f002292_").replace("image_plane_plus_thickness","paper+thickness").replace("external_height_image_normal","external-height")
        axes[0].plot([float(r["reference_m"]) for r in selected],[float(r["median_m"]) if r["median_m"] else float("nan") for r in selected],marker="o",label=label)
    axes[0].plot([.9,2.1],[.9,2.1],"k--",label="Equal value (not point-equivalence proof)",alpha=.6)
    axes[0].set_xlabel("User-reported vehicle-center to near-base range (m)")
    axes[0].set_ylabel("Median camera-foot comparison range (m)")
    axes[0].legend(fontsize=7)
    rates=[100*r["numeric_comparison_rows"]/r["rows"] for r in reports]
    axes[1].bar([str(r["reference_m"]) for r in reports],rates,color="steelblue")
    for i,rate in enumerate(rates):axes[1].text(i,rate+1,f"{rate:.1f}%",ha="center")
    axes[1].set_ylim(0,110);axes[1].set_ylabel("Rows with any comparison value (%)")
    axes[1].set_xlabel("User-reported distance (m)")
    for ax in axes:ax.grid(alpha=.2)
    fig.suptitle("Three static placements, same floor model; NO fitting or physical approval")
    fig.tight_layout();fig.savefig(args.output_dir/"distance_comparison.png",dpi=150);plt.close(fig)
    print(json.dumps(dict(status=result["status"],total_validated_rows=len(frames),
        primary=[r for r in summaries if r["model_name"]==PRIMARY],
        case_available_rows={r["case"]:r["numeric_comparison_rows"] for r in reports}),indent=2))


if __name__=="__main__":
    main()
