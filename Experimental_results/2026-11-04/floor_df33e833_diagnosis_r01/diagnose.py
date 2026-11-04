"""Causal support replay and counterfactual geometry audit, never runtime tuning."""
import argparse
from collections import Counter, defaultdict
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"src"))
from cone_distance_core import load_config, observe_support, digest
from cone_fixed_floor_candidate import measure_support
from cone_support_completion_candidate import observe_lateral_completion
from cone_support_quality import ConeSupportQualityGate
from summarize_cone_distance_live import load_frames

PRIMARY="f002292_as_listed_s0_image_plane_plus_thickness"
FLOOR=ROOT/"Experimental_results/2026-11-04/floor_reference_df33e833_r01"
CASES=ROOT/"Experimental_results/2026-11-04/floor_df33e833_multidistance_r01/cases.json"


def write_csv(path, rows):
    with path.open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def replay_quality(rows):
    gate=ConeSupportQualityGate()
    compared=[]
    for index,row in enumerate(rows):
        candidate=row["support_completion_shadow"]["candidate"] or {}
        result=gate.update(row["source_time_sec"],[dict(
            support=candidate.get("support") if candidate.get("point") is not None else None,
            unavailable_reason=candidate.get("reason","no_selected_support"))])
        actual=row["fixed_floor_shadow"]
        compared.append(dict(frame=row["frame"],index=index,
            warmup=index<gate.settings.confirmation_frames-1,
            expected_reason=actual["image_quality_reason"],replayed_reason=result["reason"],
            expected_accepted=actual["image_quality_accepted"],replayed_accepted=result["quality_accepted"],
            replayed_confirmation_count=result["confirmation_count"],
            match=(result["reason"],result["quality_accepted"])==(actual["image_quality_reason"],actual["image_quality_accepted"])))
    return compared


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",required=True,type=Path)
    args=parser.parse_args()
    spec=json.loads(CASES.read_text())
    settings,camera,heading,_=load_config()
    model_paths={name:FLOOR/f"derived_{name}_r01/explicit_floor_models.json"
        for name in ("primary","control_t150","control_t190","control_e030")}
    bundles={name:json.loads(path.read_text()) for name,path in model_paths.items()}
    models={m["name"]:m for m in bundles["primary"]["models"]}
    controls={name:next(m for m in b["models"] if m["name"]==PRIMARY) for name,b in bundles.items()}
    data={}
    input_hashes={str(CASES.relative_to(ROOT)):digest(CASES),**{str(p.relative_to(ROOT)):digest(p) for p in model_paths.values()}}
    for case in spec["cases"]:
        rows,truncated,hashed=load_frames(ROOT/case["input"])
        if truncated or hashed!=case["sha256"] or any(r["session"]!=spec["session"] for r in rows):
            raise ValueError("exact same-session input required")
        data[case["id"]]=rows
        input_hashes[case["input"]]=hashed
    quality,unavailable,same_frame,box_controls,pixels,plane_controls,height_controls=[],[],[],[],[],[],[]
    geometry_errors=[]
    geometry_count=0
    cache={}
    def measured(point, model):
        key=(json.dumps(model,sort_keys=True),tuple(point))
        if key not in cache:
            cache[key]=measure_support(point,model,camera,heading,session=spec["session"],diagnostic_range_m=settings["diagnostic_range_m"])
        return cache[key]
    for case in spec["cases"]:
        rows=data[case["id"]]
        quality.extend(dict(case=case["id"],**r) for r in replay_quality(rows))
        for row in rows:
            candidate=row["support_completion_shadow"]["candidate"] or {}
            if candidate.get("point") is None:
                contexts=candidate.get("contexts") or []
                touches=(contexts[0].get("component") or {}).get("touches") if contexts else None
                outside=candidate.get("completion_reason")=="completed_point_outside_original_bbox"
                completed=contexts[1]["observation"]["point"] if outside else None
                box=row["selected_detector_boxes"][0]
                unavailable.append(dict(case=case["id"],frame=row["frame"],
                    completion_reason=candidate.get("completion_reason"),
                    original_touching_edges="+".join(k for k,v in (touches or {}).items() if v),
                    attempted=candidate.get("completion_attempted"),granted=candidate.get("completion_granted"),
                    completed_point_x=completed[0] if completed else None,
                    completed_point_y=completed[1] if completed else None,
                    original_bbox_bottom=box["y2"],point_below_bbox_px=completed[1]-box["y2"] if completed else None))
            shadow=row["fixed_floor_shadow"]
            for m in shadow["models"]:
                if not m["range_available"]:continue
                replay=measured(shadow["support_pixel"],models[m["model_name"]])
                error=abs(replay["horizontal_camera_foot_range_m"]-m["horizontal_camera_foot_range_m"])
                if not replay["range_available"] or error>1e-10:
                    raise ValueError("logged geometry does not reproduce")
                geometry_count+=1;geometry_errors.append(error)
        valid=[r for r in rows if next(m for m in r["fixed_floor_shadow"]["models"] if m["model_name"]==PRIMARY)["range_available"]]
        point=list(Counter(tuple(r["fixed_floor_shadow"]["support_pixel"]) for r in valid).most_common(1)[0][0])
        base=measured(point,controls["primary"])["horizontal_camera_foot_range_m"]
        for axis in (0,1):
            for offset in (-2,-1,0,1,2):
                altered=point.copy();altered[axis]+=offset
                m=measured(altered,controls["primary"])
                value=m["horizontal_camera_foot_range_m"]
                pixels.append(dict(case=case["id"],reference_m=case["reference_m"],axis="x" if axis==0 else "y",
                    offset_px=offset,base_x=point[0],base_y=point[1],tested_x=altered[0],tested_y=altered[1],
                    conditional_range_m=value,minus_base_cm=100*(value-base),actual_observation=False,usable_for_ffb=False))
        for name,model in controls.items():
            m=measured(point,model)
            plane_controls.append(dict(case=case["id"],reference_m=case["reference_m"],control=name,
                model_camera_to_floor_m=model["camera_to_floor_m"],conditional_range_m=m["horizontal_camera_foot_range_m"],
                minus_primary_cm=100*(m["horizontal_camera_foot_range_m"]-base),selected_or_installed=False))
        h=controls["primary"]["camera_to_floor_m"]
        height_controls.append(dict(case=case["id"],reported_reference_m=case["reference_m"],
            base_range_m=base,original_model_height_m=h,
            hypothetical_height_if_same_point_quantity_m=h*case["reference_m"]/base,
            reference_equivalence_assumed_for_algebra_only=True,height_measured_or_fitted=False))
        if case["image"] is None:continue
        path=ROOT/case["image"]
        if digest(path)!=case["image_sha256"]:raise ValueError("source PNG changed")
        input_hashes[case["image"]]=digest(path)
        image=cv2.imread(str(path));before=image.copy()
        row=next(r for r in rows if r["frame"]==case["image_frame"])
        box=row["selected_detector_boxes"][0]
        observed=observe_lateral_completion(image,box,camera)
        if observed!=row["support_completion_shadow"]["candidate"]:
            raise ValueError("same-frame support observation not reproduced")
        baseline=observe_support(image,box,camera,evidence=True)
        original=row["frame_evidence"]["support_observation"]
        point_keys=("point","support","reason","floor_contact_verified")
        diagnostic={k:v for k,v in baseline.items() if k not in point_keys}
        if any(baseline[k]!=original[k] for k in point_keys) or diagnostic!=original["mask_diagnostics"]:
            raise ValueError("same-frame baseline observation not reproduced")
        same_frame.append(dict(case=case["id"],frame=row["frame"],baseline_and_comparison_exact=True,
            image_original_bytes_unchanged=True,source_sha256=digest(path),observed_point=observed["point"]))
        for dy1 in (-1,0,1):
            for dy2 in (-1,0,1):
                changed=dict(box,y1=box["y1"]+dy1,y2=box["y2"]+dy2)
                cf=observe_lateral_completion(image,changed,camera)
                box_controls.append(dict(case=case["id"],frozen_image_frame=row["frame"],dy1=dy1,dy2=dy2,
                    point_present=cf["point"] is not None,reason=cf["reason"],completion_reason=cf["completion_reason"],
                    actual_live_observation=False,original_box=(dy1==dy2==0)))
        if not np.array_equal(image,before) or digest(path)!=case["image_sha256"]:
            raise ValueError("source image mutated")
    args.output_dir.mkdir(parents=True,exist_ok=False)
    for name,rows in (("quality_replay.csv",quality),("unavailable_support.csv",unavailable),
        ("bbox_counterfactual.csv",box_controls),("pixel_sensitivity.csv",pixels),
        ("plane_corner_controls.csv",plane_controls),("height_only_algebra.csv",height_controls)):
        write_csv(args.output_dir/name,rows)
    after_warmup=[r for r in quality if not r["warmup"]]
    checks=dict(quality_replay_matches_after_explicit_cold_start=all(r["match"] for r in after_warmup),
        all_logged_geometry_reproduced=geometry_count==5076 and max(geometry_errors)<1e-10,
        both_exact_image_frames_reproduced=len(same_frame)==2,
        original_input_hashes_preserved=all(digest(ROOT/p)==h for p,h in input_hashes.items()))
    report=dict(status="DIAGNOSIS_CONFIRMED_NO_RUNTIME_OR_PHYSICAL_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks,quality_rows=len(quality),quality_compared_after_cold_start=len(after_warmup),
        cold_start_rows=[r for r in quality if r["warmup"]],
        support_unavailable_rows=len(unavailable),unavailable_reasons=dict(Counter(r["completion_reason"] for r in unavailable)),
        unavailable_edge_combinations=dict(Counter(r["original_touching_edges"] for r in unavailable)),
        reconfirmation_pending_rows=[r for r in quality if r["expected_reason"]=="support_confirmation_pending"],
        logged_geometry_values_reproduced=geometry_count,max_absolute_geometry_difference_m=max(geometry_errors),
        same_frame_image_reproduction=same_frame,input_sha256=input_hashes,
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__).resolve(),
            *[ROOT/"src"/n for n in ("cone_support_quality.py","cone_support_completion_candidate.py",
              "cone_colour_support_candidate.py","cone_distance_core.py","cone_fixed_floor_candidate.py")]]},
        counterfactual_images_or_points_are_not_real_additional_frames=True,
        physical_metric_verified=False,calibration_fitted=False,model_selected=False,
        runtime_modified=False,usable_for_ffb=False,camera_gpu_ros_started=False)
    (args.output_dir/"diagnosis.json").write_text(json.dumps(report,indent=2)+"\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with (args.output_dir/"pixel_sensitivity.csv").open(newline="") as stream:pix=list(csv.DictReader(stream))
    with (args.output_dir/"plane_corner_controls.csv").open(newline="") as stream:planes=list(csv.DictReader(stream))
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for case in spec["cases"]:
        subset=[r for r in pix if r["case"]==case["id"] and r["axis"]=="y"]
        axes[0].plot([int(r["offset_px"]) for r in subset],[float(r["minus_base_cm"]) for r in subset],"o-",label=f"{case['reference_m']:.1f} m placement")
    for control in ("control_t150","control_t190","control_e030"):
        subset=[r for r in planes if r["control"]==control]
        axes[1].plot([float(r["reference_m"]) for r in subset],[float(r["minus_primary_cm"]) for r in subset],"o-",label=control)
    axes[0].set_xlabel("Counterfactual support Y offset (px)");axes[0].set_ylabel("Range change vs original point (cm)")
    axes[1].set_xlabel("User-reported placement distance (m)");axes[1].set_ylabel("Range change vs primary floor model (cm)")
    for ax in axes:ax.axhline(0,color="grey",linewidth=.7);ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle("Sensitivity only: NO new frames, model selection, or calibrated correction")
    fig.tight_layout();fig.savefig(args.output_dir/"geometry_sensitivity.png",dpi=150);plt.close(fig)
    print(json.dumps({k:report[k] for k in ("status","checks","quality_compared_after_cold_start","unavailable_reasons","unavailable_edge_combinations","logged_geometry_values_reproduced","max_absolute_geometry_difference_m")},indent=2))
    return 0 if all(checks.values()) else 1


if __name__=="__main__":
    raise SystemExit(main())
