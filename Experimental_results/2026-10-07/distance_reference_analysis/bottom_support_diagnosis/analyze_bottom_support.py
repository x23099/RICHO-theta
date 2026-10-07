"""Frozen-mask bottom-column diagnosis; offline only, no fitted corrections.

The reported Z is joined AFTER point extraction and never selects pixels.
These colour-mask samples are not independently labelled physical contacts.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
REPO = HERE.parents[3]
sys.path.insert(0, str(PARENT))
sys.path.insert(0, str(REPO / "src"))
from analyze_distance_reference import CONDITIONS, REFERENCE, read, write_csv
from diagnose_distance_geometry import nominal_pixel_y
from evaluate_raw_velocity_confidence_replay import sha256
from ground_contact import dual_fisheye_pixels_to_vehicle_rays, blue_hsv_mask, blue_preprocessed_hsv
from offline_box_contact_candidates import BoxCandidateSettings, seeded_components, select_component


def bottom_columns(component, fraction):
    if component is None:
        return np.empty((0,2), dtype=float), np.empty(0, dtype=int)
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0,1]")
    mask = component["mask"]
    ox, oy = component["origin"]
    margin = int(math.floor(mask.shape[1]*(1-fraction)/2))
    end = mask.shape[1]-margin
    points, zones = [], []
    for col in range(margin,end):
        ys = np.flatnonzero(mask[:,col])
        if len(ys):
            points.append((ox+col,oy+int(ys[-1])))
            # Three fixed spatial thirds of the predeclared central width.
            zones.append(min(2,3*(col-margin)//(end-margin)))
    return np.asarray(points,dtype=float).reshape(-1,2), np.asarray(zones,dtype=int)


def project_columns(points, zones, parameters, shape):
    if len(points) != len(zones):
        raise ValueError("point/zone lengths differ")
    if not len(points):
        return None
    pixels,rays = dual_fisheye_pixels_to_vehicle_rays(points,shape[1],shape[0],parameters)
    # Align zone labels to any pixels removed by the lens-validity check.
    zone_by_pixel = {tuple(point):int(zone) for point,zone in zip(points,zones)}
    aligned = np.array([zone_by_pixel[tuple(point)] for point in pixels],dtype=int)
    downward = rays[:,1] < -.03
    pixels,rays,aligned = pixels[downward],rays[downward],aligned[downward]
    if len(rays) < 3:
        return None
    scale = -float(parameters["camera_height"])/rays[:,1]
    ground = np.column_stack((scale*rays[:,0],scale*rays[:,2]))
    distance = np.linalg.norm(ground,axis=1)
    valid = (scale > 0) & (ground[:,1] > 0) & (distance >= .2) & (distance <= 4.)
    pixels,ground,aligned = pixels[valid],ground[valid],aligned[valid]
    if len(ground) < max(3,math.ceil(len(points)/2)):
        return None
    return pixels,ground,aligned


def support_statistics(pixels,ground,nominal):
    if len(ground)==0:
        return dict(points=0)
    if len(ground)!=len(pixels) or not np.isfinite(ground).all():
        raise ValueError("invalid support data")
    z=ground[:,1]
    return dict(points=len(z),pixel_y_min=float(pixels[:,1].min()),pixel_y_max=float(pixels[:,1].max()),
        pixel_x_min=float(pixels[:,0].min()),pixel_x_max=float(pixels[:,0].max()),
        z_min_m=float(z.min()),z_p05_m=float(np.percentile(z,5)),z_median_m=float(np.median(z)),
        z_p95_m=float(np.percentile(z,95)),z_max_m=float(z.max()),
        nominal_inside_point_envelope=int(z.min() <= nominal <= z.max()),
        support_points_ge_reported_z=int(np.sum(z>=nominal)),
        nearest_support_gap_m=float(np.min(np.abs(z-nominal))))


def zone_rows(condition,session,frame,time,pixels,ground,zones,nominal):
    result=[]
    for name,selection in (("all",np.ones(len(ground),dtype=bool)),("left",zones==0),
                           ("centre",zones==1),("right",zones==2)):
        result.append(dict(condition=condition,session=session,frame=frame,time_sec=time,zone=name,
            reported_z_m=nominal,**support_statistics(pixels[selection],ground[selection],nominal)))
    return result


def summarize(rows):
    grouped=defaultdict(list)
    for r in rows:
        if float(r["time_sec"]) >= 2.:
            grouped[r["condition"],r["zone"]].append(r)
    result=[]
    for (condition,zone),group in grouped.items():
        available=[r for r in group if r["points"] > 0]
        result.append(dict(condition=condition,zone=zone,window="after_2s",frames=len(group),
            frames_with_support=len(available),
            z_median_over_frames_m=float(np.median([r["z_median_m"] for r in available])) if available else None,
            smallest_point_z_m=min(r["z_min_m"] for r in available) if available else None,
            largest_point_z_m=max(r["z_max_m"] for r in available) if available else None,
            nominal_inside_envelope_frames=sum(r["nominal_inside_point_envelope"] for r in available),
            median_nearest_support_gap_m=float(np.median([r["nearest_support_gap_m"] for r in available])) if available else None,
            worst_nearest_support_gap_m=max(r["nearest_support_gap_m"] for r in available) if available else None,
            total_valid_support_points=sum(r["points"] for r in available)))
        result[-1]["support_points_ge_reported_z"]=sum(r.get("support_points_ge_reported_z",0) for r in available)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root",type=Path,required=True)
    args=parser.parse_args()
    comparison=PARENT/"frozen_comparison"
    prov=json.loads((comparison/"provenance.json").read_text())
    settings=BoxCandidateSettings(**prov["settings"])
    if sha256(REPO/"src/offline_box_contact_candidates.py") != prov["implementation_sha256"]["offline_box_contact_candidates.py"]:
        raise ValueError("frozen candidate code changed")
    saved=defaultdict(list)
    for row in read(comparison/"frame_results.csv"):
        if row["variant"]=="seeded_s130_bottom":
            saved[row["session"]].append(row)
    src={s["session"]:s for s in prov["sources"]}
    reviews={(r["condition"],int(r["frame"])):r for r in read(PARENT/"review_frame_manifest.csv")}
    manual={r["condition"]:int(r["frame"]) for r in read(PARENT/"manual_lower_edge.csv")}
    rows,representatives,audits,edge_events,pixel_evidence=[],[],[],[],[]
    edge_example=None
    inputs={str(p.relative_to(REPO)):sha256(p) for p in (
        comparison/"provenance.json",comparison/"frame_results.csv",PARENT/"manual_lower_edge.csv",
        PARENT/"review_frame_manifest.csv",PARENT/"reference_conditions.json")}
    cv2.setNumThreads(1)
    for condition,nominal in CONDITIONS.items():
        found=list((args.session_root/condition).rglob("metadata.json"))
        if len(found)!=1:
            raise ValueError("exactly one session required")
        session=found[0].parent
        print("Checking bottom support:",condition,flush=True)
        p=json.loads(found[0].read_text())["parameters"]
        if p != src[session.name]["parameters"]:
            raise ValueError("metadata not frozen")
        if float(p.get("blue_ground_contact_z_offset_m",0.)) != 0.:
            raise ValueError("this diagnostic compares raw Z to reported Z and requires recorded zero Z offset")
        original=json.dumps(p,sort_keys=True)
        q=dict(p,blue_ground_contact_hsv_s_min=max(settings.body_s_min,p.get("blue_ground_contact_hsv_s_min",70)))
        reference=saved[session.name]
        live=read(session/"detections.csv")
        if [int(r["frame"]) for r in reference]!=list(range(1,len(live)+1)):
            raise ValueError("frame sequence mismatch")
        if [float(r["time_sec"]) for r in reference]!=[float(r["time_sec"]) for r in live]:
            raise ValueError("frame time mismatch")
        for name in ("metadata.json","detections.csv","raw.avi"):
            inputs[str(session/name)]=sha256(session/name)
        cap=cv2.VideoCapture(str(session/"raw.avi"))
        detected=total_valid=0
        max_error=0.
        try:
            for record in reference:
                ok,frame=cap.read()
                if not ok or frame.shape!=(720,1280,3):
                    raise ValueError("raw geometry/frame mismatch")
                number=int(record["frame"])
                component=select_component(seeded_components(frame,q,settings),frame.shape,q)
                points,zones=bottom_columns(component,settings.bottom_central_fraction)
                projected=project_columns(points,zones,q,frame.shape)
                if (projected is not None) != (record["detected"]=="1"):
                    raise ValueError("detection mismatch")
                if projected is None:
                    continue
                if nominal is None:
                    raise ValueError("unexpected no-box detection")
                pixels,ground,zones=projected
                detected+=1
                total_valid+=len(pixels)
                computed=dict(raw_contact_x_m=float(np.median(ground[:,0])),raw_contact_z_m=float(np.median(ground[:,1])),
                              contact_pixel_x=float(np.median(pixels[:,0])),contact_pixel_y=float(np.median(pixels[:,1])))
                error=max(abs(value-float(record[k])) for k,value in computed.items())
                max_error=max(max_error,error)
                if error > 1e-9:
                    raise ValueError("support median not equal to frozen bottom estimator")
                rows.extend(zone_rows(condition,session.name,number,record["time_sec"],pixels,ground,zones,nominal))
                if condition=="z1p10" and float(record["time_sec"])>=2. and edge_example is None and np.any(ground[:,1]>=nominal):
                    edge_example=dict(condition=condition,session=session.name,frame=number,time_sec=record["time_sec"],
                        selection="first_after_2s_with_any_frozen_bottom_support_Z_ge_reported_Z_not_blind_review",
                        decoded_bgr_pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest())
                    for pixel,world,zone in zip(pixels,ground,zones):
                        edge_events.append(dict(**edge_example,pixel_x=pixel[0],pixel_y=pixel[1],
                            zone=("left","centre","right")[zone],x_m=world[0],z_m=world[1]))
                    # Inspect unchanged raw HSV and mask membership, not an edited camera image.
                    hsv=blue_preprocessed_hsv(frame,q)
                    strict=blue_hsv_mask(frame,q)
                    weak=blue_hsv_mask(frame,dict(q,blue_ground_contact_hsv_v_min=settings.weak_v_min))
                    extreme=int(np.argmax(ground[:,1]))
                    col=int(pixels[extreme,0])
                    ox,oy=component["origin"]
                    for y in range(int(pixels[:,1].min())-2,int(pixels[:,1].max())+4):
                        local_x,local_y=col-ox,y-oy
                        member=(0 <= local_y < component["mask"].shape[0]
                                and 0 <= local_x < component["mask"].shape[1]
                                and component["mask"][local_y,local_x] != 0)
                        pixel_evidence.append(dict(condition=condition,frame=number,pixel_x=col,pixel_y=y,
                            hsv_h=int(hsv[y,col,0]),hsv_s=int(hsv[y,col,1]),hsv_v=int(hsv[y,col,2]),
                            configured_body_s_min=q["blue_ground_contact_hsv_s_min"],
                            strict_mask_before_open=int(strict[y,col]!=0),weak_mask_before_open=int(weak[y,col]!=0),
                            selected_component_after_open=int(member)))
                if number==manual[condition]:
                    digest=hashlib.sha256(frame.tobytes()).hexdigest()
                    if digest!=reviews[condition,number]["decoded_bgr_pixels_sha256"]:
                        raise ValueError("representative raw pixels changed")
                    for pixel,world,zone in zip(pixels,ground,zones):
                        inverse=nominal_pixel_y(pixel[0],nominal,q)
                        representatives.append(dict(condition=condition,frame=number,pixel_x=pixel[0],pixel_y=pixel[1],
                            zone=("left","centre","right")[zone],x_m=world[0],z_m=world[1],
                            model_pixel_y_for_reported_z=inverse,
                            actual_y_minus_model_y_px=pixel[1]-inverse if inverse is not None else None,
                            decoded_bgr_pixels_sha256=digest))
            if cap.read()[0]:
                raise ValueError("video longer than CSV")
        finally:
            cap.release()
        if json.dumps(p,sort_keys=True)!=original:
            raise ValueError("parameters mutated")
        if detected!=(0 if nominal is None else len(reference)):
            raise ValueError("unexpected missing support")
        audits.append(dict(condition=condition,frames=len(reference),detected=detected,
            total_valid_support_points=total_valid,maximum_exact_replay_difference=max_error))
    summary=summarize(rows)
    write_csv(HERE/"frame_zone_statistics.csv",rows)
    write_csv(HERE/"support_summary.csv",summary)
    write_csv(HERE/"representative_column_points.csv",representatives)
    write_csv(HERE/"replay_audit.csv",audits)
    write_csv(HERE/"edge_event_column_points.csv",edge_events)
    write_csv(HERE/"edge_event_pixel_evidence.csv",pixel_evidence)
    fig,axes=plt.subplots(1,3,figsize=(13,4.2),sharey=True)
    for ax,condition in zip(axes,("z0p90","z1p10","z1p30")):
        points=[r for r in representatives if r["condition"]==condition]
        ax.plot([r["pixel_x"] for r in points],[r["z_m"] for r in points],".-",label="Frozen bottom-column projection")
        ax.axhline(CONDITIONS[condition],color="red",linestyle="--",label="Reported Z")
        ax.set(title=condition,xlabel="Raw image column x (px)")
        ax.grid(alpha=.3)
    axes[0].set_ylabel("Projected Z (m)")
    axes[0].legend(fontsize=7)
    fig.suptitle("Same frozen geometry: widthwise bottom support at preselected representative frames",fontsize=10)
    fig.tight_layout();fig.savefig(HERE/"bottom_support_profiles.png",dpi=150);plt.close(fig)
    code=(Path(__file__),REPO/"src/ground_contact.py",REPO/"src/offline_box_contact_candidates.py",
          PARENT/"diagnose_distance_geometry.py",PARENT/"analyze_distance_reference.py")
    (HERE/"verification.json").write_text(json.dumps(dict(
        decision="PASS_EXACT_FROZEN_SUPPORT_REPLAY_NOT_GROUND_TRUTH_CALIBRATION",
        reference_conditions=REFERENCE,windows=["all_frames_saved","after_2s_summary"],
        audit=audits,frame_zone_rows=len(rows),representative_points=len(representatives),edge_example=edge_example,
        spatial_selection="central_80_percent_then_fixed_spatial_thirds",
        labels_used_to_select_pixels=False,physical_contacts_independently_labelled=False,
        coefficient_fitting=False,runtime_changed=False,ros_or_hardware_output=False,
        inputs_sha256=inputs,implementation_sha256={str(p.relative_to(REPO)):sha256(p) for p in code},
        limits=["Only frozen S130 colour-mask bottom samples; not all possible physical lower-edge points",
                "Manual estimates are nonblind and no independent floor-contact labels are available",
                "Origin and no height/tilt changes confirmed; absolute pose and placement uncertainty unrecorded",
                "One recording per distance; cannot isolate a unique physical cause or establish a calibration curve"]),indent=2)+"\n")
    print(json.dumps(dict(audit=audits,summary=summary),indent=2))


if __name__=="__main__":
    main()
