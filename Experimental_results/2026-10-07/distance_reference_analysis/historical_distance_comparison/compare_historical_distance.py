"""Historical distance-only replay. No fitting, motion synthesis, ROS or FFB.

The original CSV is legacy BEV output: use only frame/time alignment, never
as raw ground-contact geometry. Truth is joined only after detection.
"""
import argparse
import csv
from dataclasses import asdict
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
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "src"))
from compare_offline_box_contacts import contact_metrics, verify_frozen_candidate
from diagnose_ground_contact_quality import DETECTOR_KEYS
from evaluate_ground_contact import parse_expected_position
from ground_contact import detect_blue_ground_contact
from offline_box_contact_candidates import (BoxCandidateSettings, component_contact,
                                           seeded_components, select_component)

GEOMETRY = ("camera_height", "pitch_deg", "roll_deg", "yaw_deg", "radius_scale",
            "front_cx_offset", "front_cy_offset", "back_cx_offset", "back_cy_offset")
VARIANTS = ("historical_recipe", "baseline", "seeded_s130_nearest", "seeded_s130_bottom")
WINDOWS = ("all", "after_2s", "historical_sampled")
DEFAULTS = dict(blue_ground_contact_min_area=300., blue_ground_contact_fraction=.08,
                blue_ground_contact_max_aspect_ratio=None,
                blue_ground_contact_hsv_h_min=90, blue_ground_contact_hsv_h_max=140,
                blue_ground_contact_hsv_s_min=70, blue_ground_contact_hsv_s_max=255,
                blue_ground_contact_hsv_v_min=30, blue_ground_contact_hsv_v_max=255,
                blue_ground_contact_illumination_mode="none")


def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write(path, rows):
    if not rows:
        raise ValueError("empty output table")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sampled(frame, model):
    index = frame - 1
    return index >= model["warmup_frames"] and index % model["frame_step"] == 0


def validate_reference(name, reference):
    position = parse_expected_position(name)
    if position is None or position != (float(reference["expected_x_m"]), float(reference["expected_z_m"])):
        raise ValueError("session and historical nominal labels differ")


def detector_parameters(recorded, configured):
    overrides = {k: v for k, v in configured.items()
                 if k in DETECTOR_KEYS or k.startswith("blue_ground_contact_hsv_")}
    result = dict(recorded, **overrides)
    if any(result[k] != recorded[k] for k in GEOMETRY):
        raise ValueError("detector overrides changed geometry")
    return result


def calibrated(contact, config):
    if contact is None:
        return dict(detected=0, x_m=None, z_m=None, calibration_valid=0)
    x = contact["x_m"]*config["blue_ground_contact_x_scale"]+config["blue_ground_contact_x_offset_m"]
    z = contact["z_m"]+config["blue_ground_contact_z_offset_m"]
    if not math.isfinite(x) or not math.isfinite(z):
        raise ValueError("nonfinite ground position")
    valid = (abs(x) <= config["blue_calibration_input_x_max_m"] and
             config["blue_calibration_input_z_min_m"] <= z <= config["blue_calibration_input_z_max_m"])
    return dict(detected=1, x_m=x, z_m=z, calibration_valid=int(valid))


def summarize(rows, reference, window):
    detected = [r for r in rows if r["detected"]]
    result = dict(session=reference["session"], variant=rows[0]["variant"], window=window,
                  frames=len(rows), detected=len(detected),
                  calibration_valid=sum(r["calibration_valid"] for r in rows),
                  expected_x_m=float(reference["expected_x_m"]), expected_z_m=float(reference["expected_z_m"]))
    for axis, raw_key in (("x", "raw_contact_x_m"), ("z", "raw_contact_z_m")):
        values = [r[axis+"_m"] for r in detected]
        median = float(np.median(values)) if values else None
        result.update({axis+"_median_m": median,
                       "raw_"+axis+"_median_m": float(np.median([r[raw_key] for r in detected])) if values else None,
                       axis+"_bias_m": median-result["expected_"+axis+"_m"] if values else None,
                       axis+"_iqr_m": float(np.percentile(values,75)-np.percentile(values,25)) if values else None})
    result["position_error_m"] = math.hypot(result["x_bias_m"], result["z_bias_m"]) if detected else None
    return result


def decode_count(path):
    video = cv2.VideoCapture(str(path))
    if not video.isOpened():
        raise ValueError(f"cannot open {path}")
    count = 0
    try:
        while video.read()[0]:
            count += 1
    finally:
        video.release()
    return count


def replay(session, config, model, settings):
    metadata = json.loads((session/"metadata.json").read_text())
    recorded = metadata["parameters"]
    if any(recorded[k] != config[k] for k in GEOMETRY):
        raise ValueError("recorded and current numerical camera geometry differ")
    parameters = detector_parameters(recorded, config)
    motion = read(session/"detections.csv")
    frames = [int(r["frame"]) for r in motion]
    times = [float(r["time_sec"]) for r in motion]
    if frames != list(range(1,len(motion)+1)) or not all(math.isfinite(t) for t in times) or any(
            b <= a for a,b in zip(times,times[1:])):
        raise ValueError("noncontiguous frames or invalid nominal times")
    output = []
    video = cv2.VideoCapture(str(session/"raw.avi"))
    if not video.isOpened():
        raise ValueError("cannot open raw video")
    try:
        for aligned in motion:
            ok, frame = video.read()
            if not ok or frame.shape[:2] != (metadata["requested_camera_height"], metadata["requested_camera_width"]):
                raise ValueError("raw/CSV length or image geometry mismatch")
            contacts = {}
            contacts["historical_recipe"],_ = detect_blue_ground_contact(frame, recorded,
                min_area_px=model["min_area_px"], contact_fraction=model["contact_fraction"])
            contacts["baseline"],_ = detect_blue_ground_contact(frame, parameters,
                min_area_px=parameters["blue_ground_contact_min_area"], contact_fraction=parameters["blue_ground_contact_fraction"])
            strict = dict(parameters, blue_ground_contact_hsv_s_min=max(settings.body_s_min,
                          parameters.get("blue_ground_contact_hsv_s_min",70)))
            component = select_component(seeded_components(frame, strict, settings), frame.shape, strict)
            for name, bottom in (("seeded_s130_nearest",False),("seeded_s130_bottom",True)):
                contacts[name] = component_contact(component,frame.shape,strict,settings,bottom=bottom)
            for name, contact in contacts.items():
                output.append(dict(session=session.name,variant=name,frame=int(aligned["frame"]),
                    time_sec=float(aligned["time_sec"]),**calibrated(contact,config),**contact_metrics(contact)))
        if video.read()[0]:
            raise ValueError("raw video longer than CSV")
    finally:
        video.release()
    counts = dict(csv=len(motion),raw=len(output)//len(VARIANTS))
    for filename in ("bev.avi", "detection.avi"):
        counts[filename] = decode_count(session/filename)
    if len(set(counts.values())) != 1:
        raise ValueError("decoded video counts differ")
    audit = []
    for variant,p in (("historical_recipe",recorded),("baseline",parameters),("seeded_s130",strict)):
        for key in sorted(set(DEFAULTS)|set(GEOMETRY)|DETECTOR_KEYS):
            audit.append(dict(session=session.name,variant=variant,key=key,
                effective_value=p.get(key,DEFAULTS.get(key)),source="recorded_or_override" if key in p else "default_or_inactive"))
    return output, counts, audit


def reproduce(rows, references):
    checks = []
    for ref in references:
        r = next(r for r in rows if r["session"]==ref["session"] and
                 r["variant"]=="historical_recipe" and r["window"]=="historical_sampled")
        for actual, expected in (("raw_x_median_m","raw_x_m"),("raw_z_median_m","raw_z_m"),
                ("x_median_m","estimated_x_m"),("z_median_m","estimated_z_m"),
                ("detected","detected_samples"),("frames","sampled_frames")):
            delta = abs(float(r[actual])-float(ref[expected])) if r[actual] is not None else math.inf
            checks.append(dict(session=ref["session"],field=actual,current=r[actual],historical=ref[expected],
                               absolute_difference=delta,match=int(delta <= 1e-9)))
    return checks


def aggregate(rows):
    output=[]
    for window in WINDOWS:
        for variant in VARIANTS:
            group=[r for r in rows if r["window"]==window and r["variant"]==variant]
            valid=[r for r in group if r["position_error_m"] is not None]
            result=dict(window=window,variant=variant,sessions=len(group),sessions_detected=len(valid),
                        frames=sum(r["frames"] for r in group),detected=sum(r["detected"] for r in group))
            for axis in ("x","z"):
                errors=[abs(r[axis+"_bias_m"]) for r in valid]
                result[axis+"_session_median_mae_m"]=float(np.mean(errors)) if errors else None
                result[axis+"_session_median_max_abs_error_m"]=max(errors) if errors else None
            result["mean_session_position_error_m"]=float(np.mean([r["position_error_m"] for r in valid])) if valid else None
            output.append(result)
    return output


def plot(rows):
    selected = [r for r in rows if r["window"]=="after_2s"]
    sessions = sorted(set(r["session"] for r in selected))
    fig, axes = plt.subplots(2,1,figsize=(10,7),sharex=True)
    for ax,axis in zip(axes,("z","x")):
        for i,variant in enumerate(VARIANTS):
            values = [next(r[axis+"_bias_m"]*100 for r in selected if r["session"]==s and r["variant"]==variant)
                      for s in sessions]
            ax.bar(np.arange(len(sessions))+(i-1.5)*.2,values,.2,label=variant)
        ax.axhline(0,color="black",linewidth=.8)
        ax.set_ylabel(axis.upper()+" signed error (cm)")
        ax.grid(axis="y",alpha=.25)
    axes[0].legend(fontsize=8,ncol=2)
    axes[-1].set_xticks(range(len(sessions)),[s.replace("holdout_","") for s in sessions])
    fig.suptitle("Historical nominal references / after 2 nominal seconds / no refit")
    fig.tight_layout()
    fig.savefig(HERE/"historical_distance_bias.png",dpi=160)
    plt.close(fig)


def plot_timeline(rows, refs):
    fig,axes=plt.subplots(2,2,figsize=(12,7))
    for ax,ref in zip(axes.flat,refs):
        for variant in VARIANTS[1:]:
            group=[r for r in rows if r["session"]==ref["session"] and r["variant"]==variant and r["detected"]]
            ax.plot([r["time_sec"] for r in group],[r["z_m"] for r in group],label=variant,linewidth=.8)
        ax.axhline(float(ref["expected_z_m"]),color="black",linestyle="--",label="historical nominal Z")
        ax.axvline(2,color="grey",linestyle=":")
        ax.set_title(ref["session"].replace("holdout_",""))
        ax.set_xlabel("Nominal video time (s), not measured capture time")
        ax.set_ylabel("Recomputed Z (m)")
        ax.grid(alpha=.2)
    axes.flat[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(HERE/"historical_distance_timeline.png",dpi=160)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root",type=Path,required=True)
    parser.add_argument("--source-archive",type=Path,required=True)
    args=parser.parse_args()
    cv2.setNumThreads(1)
    cfgpath=REPO/"src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json"
    config=json.loads(cfgpath.read_text())
    refpath=REPO/"Experimental_results/2026-08-07/2026-08-07_ground_contact_final_evaluation.csv"
    modelpath=refpath.with_name("2026-08-07_ground_contact_model.json")
    refs=read(refpath)
    model=json.loads(modelpath.read_text())
    if (config["blue_ground_contact_x_scale"],config["blue_ground_contact_x_offset_m"],
        config["blue_ground_contact_z_offset_m"]) != (model["x_scale"],model["x_offset_m"],model["z_offset_m"]) or model["z_scale"] != 1:
        raise ValueError("current and historical ground-contact calibration differ")
    frozen=REPO/"Experimental_results/2026-10-06/box_contact_candidates/provenance.json"
    settings=BoxCandidateSettings()
    freeze_check=verify_frozen_candidate(frozen,settings)
    freeze=json.loads(frozen.read_text())
    overrides={k:v for k,v in config.items() if k in DETECTOR_KEYS or k.startswith("blue_ground_contact_hsv_")}
    if overrides != freeze["detector_overrides"]:
        raise ValueError("detector overrides differ from frozen comparison")
    for name in ("ground_contact.py","offline_box_contact_candidates.py"):
        if sha(REPO/"src"/name) != freeze["implementation_sha256"][name]:
            raise ValueError("frozen geometry/segmentation implementation changed")
    if len(refs)!=4 or len({r["session"] for r in refs})!=4:
        raise ValueError("four unique historical references required")
    allrows, summaries, audits, sources = [], [], [], []
    for ref in refs:
        validate_reference(ref["session"],ref)
        session=args.session_root/ref["session"]
        output,counts,audit=replay(session,config,model,settings)
        allrows.extend(output)
        audits.extend(audit)
        for variant in VARIANTS:
            rows=[r for r in output if r["variant"]==variant]
            for window in WINDOWS:
                selected=[r for r in rows if window=="all" or
                    (window=="after_2s" and r["time_sec"] >= 2.) or
                    (window=="historical_sampled" and sampled(r["frame"],model))]
                summaries.append(summarize(selected,ref,window))
        sources.append(dict(session=session.name,counts=counts,sha256={
            name:sha(session/name) for name in ("raw.avi","bev.avi","detection.avi","detections.csv","metadata.json")}))
        print(f"{session.name}: decoded {counts}",flush=True)
    checks=reproduce(summaries,refs)
    write(HERE/"frame_results.csv",allrows)
    write(HERE/"summary.csv",summaries)
    write(HERE/"aggregate.csv",aggregate(summaries))
    write(HERE/"parameter_audit.csv",audits)
    write(HERE/"historical_reproduction.csv",checks)
    plot(summaries)
    plot_timeline(allrows,refs)
    provenance=dict(scope="DISTANCE_ONLY_NO_ROS_OR_HARDWARE",source_archive=str(args.source_archive.resolve()),
        source_archive_sha256=sha(args.source_archive),sessions=sources,settings=asdict(settings),freeze=freeze_check,
        inputs_sha256={str(p.relative_to(REPO)):sha(p) for p in (cfgpath,refpath,modelpath,frozen,HERE/"manual_review.csv")},
        implementation_sha256={str(p.relative_to(REPO)):sha(p) for p in (Path(__file__),REPO/"src/ground_contact.py",
            REPO/"src/offline_box_contact_candidates.py",REPO/"src/compare_offline_box_contacts.py")},
        coefficient_fitting=False,all_detected_included_even_outside_range=True,
        geometry="recorded parameters retained; numerical equality with current config verified, not physical pose equivalence",
        time_provenance="legacy frame-index/30 nominal timestamps; actual capture/processing rate unknown",
        motion_tracking_ttc_network_physical_ffb="NOT_EVALUATED; no odometry or command speeds fabricated",
        independent_blind_validation=False,reference_uncertainty="not recorded; legacy nominal labels only",
        historical_reproduction_all_match=all(r["match"] for r in checks))
    (HERE/"verification.json").write_text(json.dumps(provenance,indent=2)+"\n")
    if not provenance["historical_reproduction_all_match"]:
        raise ValueError("historical reproduction mismatch; inspect table before interpretation")
    print("PASS: 24 historical reproduction checks; 4,200 distance-only frame results",flush=True)


if __name__=="__main__":
    main()
