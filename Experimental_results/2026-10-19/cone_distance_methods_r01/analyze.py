"""Frozen paper geometry transfer and bbox-area proxy; offline CSV audit only."""
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT/"Experimental_results/2026-10-15"
sys.path.insert(0, str(ROOT/"src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import CAMERA_KEYS, ConeGroundProjector, checked_bbox
from cone_observation_quality import ConeObservationQualityGate
from diagnose_box_contact_calibration import project_pixel
from area_baseline import FIT_CONDITIONS, area_fraction, fit_scale, predict_z

MODELS = ("recorded58", "height_only59", "paper_centre2")
ALL_MODELS = MODELS+("bbox_area",)
EXPECTED_FRAMES = {"static":3596, "sequence":1547}


def load_inputs():
    static, sequence = OLD/"cone_static_distance_r01", OLD/"floor_cone_same_pose_analysis_r01"
    paper = OLD/"paper_reference7_r01/analysis_r01"
    paths = [Path(__file__), HERE/"method.md", HERE/"area_baseline.py",
        paper/"centre2_offline_candidate.json", paper/"provenance.json",
        static/"session_conditions.csv", sequence/"scope.json", sequence/"analysis_r01/summary.json",
        OLD/"cone_geometry_candidates_r01/reference_update_r01/reference_conditions.csv",
        OLD/"cone_geometry_candidates_r01/cone_reference_confirmation.json",
        static/"manual_contact_candidates.csv", sequence/"contact_candidates.csv",
        ROOT/"src/cone_observation.py", ROOT/"src/cone_observation_quality.py",
        ROOT/"src/ground_contact.py", ROOT/"src/obstacle_tracking.py",
        ROOT/"src/diagnose_box_contact_calibration.py"]
    paths.extend(sorted((ROOT/"src").glob("bird_eye_config*.json")))
    sources = {}
    for name, directory in (("static",static), ("sequence",sequence)):
        frames = read_csv(directory/"inference_r01/frames.csv")
        predictions = read_csv(directory/"inference_r01/predictions.csv")
        paths.extend(directory/"inference_r01"/f for f in ("frames.csv","predictions.csv","provenance.json"))
        if len(frames) != EXPECTED_FRAMES[name]:
            raise ValueError("complete original frame tables required")
        sources[name] = (frames,predictions)
    old_summary = json.loads((sequence/"analysis_r01/summary.json").read_text())
    static_summary = json.loads((static/"analysis_r01/analysis_summary.json").read_text())
    paths.append(static/"analysis_r01/analysis_summary.json")
    # Verify only consumed CSVs against their already frozen upstream audit, not
    # unrelated archived helper revisions or unavailable raw videos.
    for name, directory, provenance in (("static",static,static_summary), ("sequence",sequence,old_summary)):
        for filename in ("frames.csv","predictions.csv"):
            path = directory/"inference_r01"/filename
            if sha256(path) != provenance["source_sha256"][str(path)]:
                raise ValueError("upstream frozen predictions changed")
    paper_provenance = json.loads((paper/"provenance.json").read_text())
    if sha256(paper/"centre2_offline_candidate.json") != paper_provenance["output_sha256"]["centre2_offline_candidate.json"]:
        raise ValueError("frozen paper candidate changed")
    parameters = old_summary["models"]["recorded58"]
    geometry = dict(recorded58=parameters, height_only59=dict(parameters,camera_height=.59),
        paper_centre2=json.loads((paper/"centre2_offline_candidate.json").read_text())["parameters"])
    geometry = {name:{k:p[k] for k in CAMERA_KEYS} for name,p in geometry.items()}
    refs = {r["condition"]:r for r in read_csv(OLD/"cone_geometry_candidates_r01/reference_update_r01/reference_conditions.csv")}
    conditions = {r["session"]:r["condition"] for r in read_csv(static/"session_conditions.csv")}
    phases = json.loads((sequence/"scope.json").read_text())["phase_windows"]
    return sources, geometry, refs, conditions, phases, {str(p):sha256(p) for p in paths}


def select_candidates(predictions, scope, central):
    result = []
    for row in predictions:
        try:
            x1,_,x2,_ = checked_bbox(row,1280,720)
            inside = 270 <= (x1+x2)/2 <= 350 if central else scope.centre_in_front_lens(row)
        except (ValueError,TypeError,KeyError):
            inside = True  # malformed predictions must not silently vanish
        if inside:
            result.append(row)
    return result


def make_ledger(sources, scope, refs, conditions, phases):
    ledger, selected_by_key = [], {}
    for dataset,(frames,predictions) in sources.items():
        index = defaultdict(list)
        for p in predictions:
            index[p["session"],int(p["frame"])].append(p)
        previous, times, keys = {}, {}, set()
        for row in frames:
            session,frame,t = row["session"],int(row["frame"]),float(row["time_sec"])
            if (frame != previous.get(session,0)+1 or not math.isfinite(t)
                    or t <= times.get(session,-1)):
                raise ValueError("consecutive frames and strictly increasing finite time required")
            previous[session],times[session] = frame,t
            key = dataset,session,frame
            if key in selected_by_key:
                raise ValueError("duplicate source frame")
            keys.add((session,frame))
            all_predictions = index[session,frame]
            if len(all_predictions) != int(row["detections"]):
                raise ValueError("prediction count mismatch")
            selected = select_candidates(all_predictions,scope,dataset=="sequence")
            if dataset == "static":
                condition = conditions[session]
                reference = refs.get(condition)
                x,z = (float(reference["reference_x_m"]),float(reference["reference_z_m"])) if reference else (None,None)
                role = "area_calibration" if condition in FIT_CONDITIONS else ("heldout" if reference else "no_target")
            else:
                windows = [p for p in phases if p["start_frame"]<=frame<=p["end_frame"]]
                if len(windows) != 1:
                    raise ValueError("source frame outside frozen sequence phases")
                condition,z = windows[0]["name"],windows[0]["reference_z_m"]
                x,role = (0.,"heldout") if z is not None else (None,"unlabelled_transition_or_floor")
            q, reason = None,""
            if len(selected)==1:
                try:
                    q = area_fraction(selected[0],scope)
                except (ValueError,TypeError,KeyError) as error:
                    reason = "area_input_rejected:"+str(error)
            else:
                reason = "no_candidate" if not selected else "ambiguous_candidates"
            ledger.append(dict(dataset=dataset,session=session,frame=frame,time_sec=t,condition=condition,
                reference_x_m=x,reference_z_m=z,area_role=role,all_view_predictions=len(all_predictions),
                candidates=len(selected),q=q,area_input_reason=reason))
            selected_by_key[key] = selected
        if set(index)-keys:
            raise ValueError("predictions without source frames")
    return ledger,selected_by_key


def calibrate_area(ledger):
    anchors = []
    for condition in sorted(FIT_CONDITIONS):
        group = [r for r in ledger if r["dataset"]=="static" and r["condition"]==condition]
        values = [r["q"] for r in group if r["q"] is not None]
        if not group or not values or len({r["session"] for r in group})!=1:
            raise ValueError("one complete session per frozen area fit condition required")
        anchors.append(dict(condition=condition,session=group[0]["session"],frames=len(group),
            valid_bbox_frames=len(values),q_median=float(np.median(values)),reference_z_m=group[0]["reference_z_m"]))
    return dict(model="Z=k/sqrt(q)",scale=fit_scale(anchors),anchors=anchors,
        fitted_conditions=sorted(FIT_CONDITIONS),fitted_from_group_medians=True,
        includes_holdouts=False,mask_area_used=False,usable_for_ffb=False)


def replay(ledger, selected, geometries, area_scale):
    projectors = {name:ConeGroundProjector(p,width=1280,height=720,front_lens="left",confidence_threshold=.5)
                  for name,p in geometries.items()}
    gates,rows = {},[]
    for source in ledger:
        key = source["dataset"],source["session"],source["frame"]
        candidates = selected[key]
        for name in ALL_MODELS:
            result = dict(**source,model=name,projection_candidate=False,reason="",x_m=None,z_m=None,
                unbounded_z_m=None,quality_accepted=False,quality_reason="not_implemented_for_area_baseline",
                quality_z_m=None,quality_x_m=None,floor_contact_verified=False,usable_for_ffb=False)
            if name=="bbox_area":
                if source["q"] is None:
                    result["reason"] = source["area_input_reason"]
                else:
                    value = predict_z(source["q"],area_scale)
                    in_range = .2 <= value <= 4.
                    result.update(unbounded_z_m=value,z_m=value if in_range else None,
                        projection_candidate=in_range,reason="empirical_bbox_area_proxy" if in_range else "outside_range_unbounded_value_retained")
            else:
                projector = projectors[name]
                gate_key = source["dataset"],source["session"],name
                gate = gates.setdefault(gate_key,ConeObservationQualityGate(projector))
                quality = gate.update(source["time_sec"],candidates,frame_width=1280,frame_height=720)
                if len(candidates)==1:
                    projection = projector.project(candidates[0],frame_width=1280,frame_height=720)
                    result.update(projection_candidate=projection["projection_candidate"],reason=projection["reason"],
                        x_m=projection["x_m"],z_m=projection["z_m"])
                else:
                    result["reason"] = "no_candidate" if not candidates else "ambiguous_candidates"
                result.update(quality_accepted=quality["quality_accepted"],quality_reason=quality["reason"],
                    quality_z_m=quality["observed_z_m"],quality_x_m=quality["observed_x_m"])
            rows.append(result)
    return rows


def estimate(row):
    # Area out-of-range estimates remain in primary error statistics; no clipping.
    return row["unbounded_z_m"] if row["model"]=="bbox_area" else row["z_m"]


def summarize(rows, *, common_only=False):
    groups = defaultdict(list)
    if common_only:
        by_frame = defaultdict(list)
        for r in rows:
            by_frame[r["dataset"],r["session"],r["frame"]].append(r)
        common_keys = {key for key,group in by_frame.items() if len(group)==4 and all(estimate(r) is not None for r in group)}
        rows = [r for r in rows if (r["dataset"],r["session"],r["frame"]) in common_keys]
    for r in rows:
        groups[r["dataset"],r["condition"],r["model"]].append(r)
    output = []
    for (dataset,condition,model),group in sorted(groups.items()):
        good = [r for r in group if estimate(r) is not None]
        values = [estimate(r) for r in good]
        reference = group[0]["reference_z_m"]
        differences = np.array(values)-reference if reference is not None and values else None
        xs = [r["x_m"] for r in good if r["x_m"] is not None]
        quality = [r["quality_z_m"] for r in group if r["quality_accepted"]]
        output.append(dict(dataset=dataset,condition=condition,model=model,area_role=group[0]["area_role"],
            common_only=common_only,frames=len(group),estimated_frames=len(good),
            range_accepted_frames=sum(r["projection_candidate"] for r in group),
            reference_z_m=reference,reference_x_m=group[0]["reference_x_m"],
            z_median_m=float(np.median(values)) if values else None,x_median_m=float(np.median(xs)) if xs else None,
            z_bias_m=float(np.median(differences)) if differences is not None else None,
            z_mae_m=float(np.mean(abs(differences))) if differences is not None else None,
            z_abs_error_p95_m=float(np.percentile(abs(differences),95)) if differences is not None else None,
            z_abs_error_max_m=float(max(abs(differences))) if differences is not None else None,
            quality_accepted_frames=len(quality),quality_z_median_m=float(np.median(quality)) if quality else None,
            missing_or_rejected_reasons=json.dumps(dict(Counter(r["reason"] for r in group if not r["projection_candidate"]))),
            quality_reasons=json.dumps(dict(Counter(r["quality_reason"] for r in group if not r["quality_accepted"]))),
            usable_for_ffb=False))
    return output


def area_screen(summary):
    groups = [r for r in summary if r["model"]=="bbox_area" and r["area_role"]=="heldout"]
    if len(groups)!=5:
        raise ValueError("all five prespecified area check conditions required")
    failures = [dict(dataset=r["dataset"],condition=r["condition"],bias=r["z_bias_m"],p95=r["z_abs_error_p95_m"])
                for r in groups if r["z_bias_m"] is None or abs(r["z_bias_m"])>.10 or r["z_abs_error_p95_m"]>.20]
    return dict(decision="DEFER_SIMPLE_BBOX_AREA" if failures else "KEEP_FOR_FURTHER_OFFLINE_CHECKS_ONLY",
        max_abs_group_bias_limit_m=.10,p95_abs_error_limit_m=.20,heldout_conditions=5,failures=failures,
        runtime_approval=False,usable_for_ffb=False)


def manual_comparison(geometries,refs):
    rows = []
    static = OLD/"cone_static_distance_r01"
    sequence = OLD/"floor_cone_same_pose_analysis_r01"
    for dataset,path in (("static",static/"manual_contact_candidates.csv"),("sequence",sequence/"contact_candidates.csv")):
        for point in read_csv(path):
            if dataset=="sequence" and point["kind"]!="cone":
                continue  # V-tip candidates remain uncertain; do not promote them.
            condition = point["condition"] if dataset=="static" else "cone_"+point["point_id"][1:]
            reference = refs[condition] if dataset=="static" else point
            for name,p in geometries.items():
                xy = project_pixel((float(point["pixel_x"]),float(point["pixel_y"])),p)
                rows.append(dict(dataset=dataset,condition=condition,frame=point["frame"],model=name,
                    pixel_x=point["pixel_x"],pixel_y=point["pixel_y"],reference_x_m=reference["reference_x_m"],
                    reference_z_m=reference["reference_z_m"],x_m=xy[0] if xy else None,z_m=xy[1] if xy else None,
                    error_z_m=xy[1]-float(reference["reference_z_m"]) if xy else None,
                    reference_kind="prior nonblind assistant base candidate, not human physical GT",
                    usable_for_ffb=False))
    return rows


def plot(summary,rows,output):
    os.environ.setdefault("MPLCONFIGDIR","/tmp/cone_distance_methods_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = [("static",c) for c in ("center_080","center_130","center_200","left_130","right_130")]
    order += [("sequence",c) for c in ("cone_130","cone_200")]
    fig,axes = plt.subplots(2,1,figsize=(12,7),layout="constrained")
    x = np.arange(len(order))
    for index,model in enumerate(ALL_MODELS):
        groups = [next(r for r in summary if (r["dataset"],r["condition"],r["model"])==(d,c,model)) for d,c in order]
        axes[0].bar(x+(index-1.5)*.19,[r["z_bias_m"] for r in groups],.19,label=model)
        axes[1].plot(x,[r["z_abs_error_p95_m"] for r in groups],"o-",label=model)
    for axis in axes:
        axis.set_xticks(x,[d+"\n"+c for d,c in order],fontsize=8)
        axis.grid(axis="y",alpha=.3)
        axis.axvline(4.5,color="gray",ls="--")
    axes[0].axhline(0,color="black",lw=.8)
    axes[0].set_ylabel("Median signed Z error [m]")
    axes[1].set_ylabel("p95 absolute Z error [m]")
    axes[0].legend(fontsize=8,ncol=4)
    axes[0].set_title("Frozen paper transfer vs bbox-area proxy; area calibrated on static080/200 only; NOT FFB approval")
    fig.savefig(output/"distance_method_comparison.png",dpi=150)
    plt.close(fig)
    fig,ax = plt.subplots(figsize=(11,4),layout="constrained")
    for model in ALL_MODELS:
        group = [r for r in rows if r["dataset"]=="sequence" and r["model"]==model and 1110<=r["frame"]<=1155]
        ax.plot([r["frame"] for r in group],[estimate(r) if estimate(r) is not None else np.nan for r in group],".-",label=model)
    ax.axhline(2,color="black",ls="--",label="nominal front-edge Z")
    ax.axvspan(1125,1134,color="orange",alpha=.15,label="previously reviewed occlusion")
    ax.set(xlabel="Original source frame",ylabel="Raw Z estimate [m]",
           title="Partial occlusion: raw estimates, no area temporal gate; no missing-value interpolation")
    ax.grid(alpha=.3)
    ax.legend(fontsize=8)
    fig.savefig(output/"occlusion_method_comparison.png",dpi=150)
    plt.close(fig)


def main():
    output = HERE/"results_r01"
    if output.exists():
        raise ValueError("new result directory required, frozen results cannot be overwritten")
    sources,geometries,refs,conditions,phases,hashes = load_inputs()
    scope = ConeGroundProjector(geometries["recorded58"],width=1280,height=720,front_lens="left",confidence_threshold=.5)
    ledger,selected = make_ledger(sources,scope,refs,conditions,phases)
    calibration = calibrate_area(ledger)
    rows = replay(ledger,selected,geometries,calibration["scale"])
    summary = summarize(rows)
    screen = area_screen(summary)
    contacts = manual_comparison(geometries,refs)
    assert len(ledger)==5143 and len(rows)==5143*4
    assert all(not r["usable_for_ffb"] for r in rows)
    output.mkdir()
    write_csv(output/"frame_ledger.csv",ledger)
    write_csv(output/"observations.csv",rows)
    write_csv(output/"summary.csv",summary)
    write_csv(output/"common_frame_summary.csv",summarize(rows,common_only=True))
    write_csv(output/"manual_base_comparison.csv",contacts)
    write_csv(output/"occlusion_rows.csv",[r for r in rows if r["dataset"]=="sequence" and 1110<=r["frame"]<=1155])
    (output/"area_calibration.json").write_text(json.dumps(calibration,indent=2)+"\n")
    (output/"area_screen.json").write_text(json.dumps(screen,indent=2)+"\n")
    plot(summary,rows,output)
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    provenance = dict(status="COMPLETED_OFFLINE_TRANSFER_AND_AREA_BASELINE_NOT_RUNTIME_APPROVAL",
        frames_retained=len(ledger),method_rows=len(rows),geometries=geometries,area_calibration=calibration,
        area_screen=screen,geometry_refitted=False,new_model_inference=False,physical_output=False,
        production_settings_changed=False,usable_for_ffb=False,source_sha256=hashes,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"provenance.json").write_text(json.dumps(provenance,indent=2)+"\n")
    for row in summary:
        if row["reference_z_m"] is not None:
            print(row["dataset"],row["condition"],row["model"],
                "n",row["estimated_frames"],"Z",round(row["z_median_m"],4),
                "bias",round(row["z_bias_m"],4),"p95abs",round(row["z_abs_error_p95_m"],4),flush=True)
    print(json.dumps(screen,indent=2))


if __name__=="__main__":
    main()
