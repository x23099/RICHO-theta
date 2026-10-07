"""Offline static-reference assessment; no fitting, ROS or hardware access."""
import argparse
import ast
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
from analyze_field_recording import summarize_session_integrity
from evaluate_velocity_confidence_replay import flag, number
from evaluate_raw_velocity_confidence_replay import sha256

CONDITIONS = {"no_box": None, "z0p90": .90, "z1p10": 1.10, "z1p30": 1.30}
VARIANTS = ("live", "baseline", "seeded_s130_nearest", "seeded_s130_bottom")
REFERENCE = json.loads((HERE / "reference_conditions.json").read_text())


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def describe(values, expected=None):
    a = np.asarray(values, dtype=float)
    if len(a) == 0:
        return dict(n=0)
    assert np.all(np.isfinite(a))
    result = dict(n=len(a), median_m=float(np.median(a)), min_m=float(a.min()), max_m=float(a.max()),
                  p05_m=float(np.percentile(a, 5)), p95_m=float(np.percentile(a, 95)),
                  iqr_m=float(np.percentile(a, 75) - np.percentile(a, 25)), std_m=float(a.std()))
    if expected is not None:
        result.update(bias_m=float(np.median(a) - expected), mae_m=float(np.mean(np.abs(a - expected))),
                      p95_abs_error_m=float(np.percentile(np.abs(a - expected), 95)))
    return result


def summarize(condition, variant, window, rows):
    expected = CONDITIONS[condition]
    detected = [r for r in rows if flag(r, "detected")]
    accepted = [r for r in rows if flag(r, "measurement_accepted")]
    tracks = [r for r in rows if flag(r, "track_available")]
    result = dict(condition=condition, variant=variant, window=window,
                  expected_z_m=expected, reference_quality=REFERENCE["reference_quality"] if expected is not None else "no_distance_reference",
                  frames=len(rows), detected=len(detected), accepted=len(accepted),
                  calibration_valid=sum(flag(r, "calibration_valid") for r in rows),
                  track_available=len(tracks), track_predicted=sum(flag(r, "track_predicted") for r in rows),
                  detected_fraction=len(detected)/len(rows), accepted_fraction=len(accepted)/len(rows))
    for prefix, group, key, target in (
        ("detected_z", detected, "z_m", expected), ("accepted_z", accepted, "z_m", expected),
        ("filtered_z", tracks, "filtered_z_m", expected),
        ("detected_x", detected, "x_m", 0. if expected is not None else None),
        ("raw_z", detected, "raw_z_m" if variant == "live" else "raw_contact_z_m", expected)):
        vals = [number(r, key) for r in group]
        assert all(v is not None for v in vals), (condition, variant, key)
        result.update({prefix+"_"+k: v for k,v in describe(vals, target).items()})
    result["rejections"] = json.dumps(Counter(r["rejection_reason"] for r in rows), sort_keys=True)
    risk_key = "collision_risk_level" if variant == "live" else "risk"
    result["risk_counts"] = json.dumps(Counter(r[risk_key] for r in rows), sort_keys=True)
    active_key = "collision_ffb_active" if variant == "live" else "virtual_active"
    result["active_updates"] = sum(flag(r, active_key) for r in rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--comparison-dir", type=Path, default=HERE/"frozen_comparison")
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    reviews = read(out/"manual_review.csv")
    frozen = read(args.comparison_dir/"frame_results.csv")
    provenance = json.loads((args.comparison_dir/"provenance.json").read_text())
    assert provenance["frozen_candidate_check"]["settings_match"]
    assert provenance["frozen_candidate_check"]["candidate_implementation_matches"]
    configured = json.loads((REPO/"src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json").read_text())
    groups, summaries, audits, manifest, source_hashes, review_join = {}, [], [], [], {}, []
    cv2.setNumThreads(1)
    for condition, expected in CONDITIONS.items():
        matches = list((args.session_root/condition).rglob("metadata.json"))
        assert len(matches) == 1
        session = matches[0].parent
        meta = json.loads(matches[0].read_text())
        source_hashes[condition] = {name: sha256(session/name) for name in ("metadata.json","detections.csv","raw.avi")}
        assert not {k:(v,meta["parameters"].get(k)) for k,v in configured.items() if v != meta["parameters"].get(k)}
        live = read(session/"detections.csv")
        integrity = summarize_session_integrity(session, "provided_archive::"+session.name)
        assert integrity["decision"] == "PASS", integrity
        reviewed = {int(r["frame"]):r for r in reviews if r["condition"] == condition}
        counts = {}
        for name in ("raw.avi", "bev.avi", "detection.avi"):
            cap, n = cv2.VideoCapture(str(session/name)), 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                if name == "raw.avi":
                    assert frame.shape == (720,1280,3)
                    if n in reviewed:
                        manifest.append(dict(condition=condition, session=session.name, frame=n,
                                             time_sec=live[n-1]["time_sec"],label=reviewed[n]["label"],
                                             decoded_bgr_pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest()))
            cap.release()
            counts[name] = n
        assert set(counts.values()) == {len(live)}
        times = np.asarray([float(r["time_sec"]) for r in live])
        dts = np.diff(times)*1000
        processing = [number(r,"processing_total_before_csv_ms") for r in live]
        audit = dict(condition=condition, session=session.name, **{k:v for k,v in integrity.items() if k!="session"},
                     duration_sec=float(times[-1]), elapsed_fps=float((len(live)-1)/(times[-1]-times[0])),
                     frame_interval_median_ms=float(np.median(dts)), frame_interval_p95_ms=float(np.percentile(dts,95)),
                     frame_interval_max_ms=float(dts.max()), processing_median_ms=float(np.median(processing)),
                     processing_p95_ms=float(np.percentile(processing,95)),processing_max_ms=max(processing),
                     sequential_video_frame_counts=json.dumps(counts),
                     odom_missing=sum(not flag(r,"odom_available") for r in live),
                     odom_nonzero=sum(number(r,"odom_linear_mps") not in (0.,None) or number(r,"odom_angular_radps") not in (0.,None) for r in live),
                     command_nonzero=sum(number(r,"cmd_linear_mps") not in (0.,None) or number(r,"cmd_angular_radps") not in (0.,None) for r in live),
                     publisher_failures=sum(not flag(r,"collision_ffb_publish_success") for r in live))
        audits.append(audit)
        for variant in VARIANTS:
            rows = live if variant=="live" else [r for r in frozen if r["session"]==session.name and r["variant"]==variant]
            assert [int(r["frame"]) for r in rows] == list(range(1,len(live)+1))
            assert [float(r["time_sec"]) for r in rows] == list(times)
            assert all(not flag(r,"measurement_accepted") or flag(r,"detected") for r in rows)
            groups[condition,variant] = rows
            for window, selected in (("all",rows),("after_2s",[r for r in rows if float(r["time_sec"])>=2.])):
                assert selected
                summaries.append(summarize(condition,variant,window,selected))
            review_join.extend(dict(condition=condition,variant=variant,frame=n,label=reviewed[n]["label"],
                                    detected=rows[n-1]["detected"],measurement_accepted=rows[n-1]["measurement_accepted"],
                                    z_m=rows[n-1]["z_m"]) for n in reviewed)
    assert len(manifest) == len(reviews) == 12
    assert len(frozen) == 3*sum(r["csv_frames"] for r in audits)
    assert all(r["odom_missing"] == r["odom_nonzero"] == r["command_nonzero"] == r["publisher_failures"] == 0 for r in audits)
    assert all(r["active_updates"] == 0 for r in summaries)
    assert all(json.loads(r["risk_counts"]).keys() == {"CLEAR"} for r in summaries)
    checked_images = 0
    for condition,prefix in (("no_box","distance_reference_no_box"),("z1p10","distance_reference_z1p10")):
        for image in read(out.parent/"report_assets"/f"{prefix}_export_manifest.csv"):
            pixels = cv2.imread(str(out.parent/"report_assets"/Path(image["raw_png"]).name))
            assert pixels.shape == (720,1280,3)
            reference = next(r for r in manifest if r["condition"] == condition and r["frame"] == int(image["frame_one_based"]))
            assert hashlib.sha256(pixels.tobytes()).hexdigest() == reference["decoded_bgr_pixels_sha256"] == image["decoded_bgr_pixels_sha256"]
            checked_images += 1
    write_csv(out/"integrity.csv",audits)
    write_csv(out/"distance_summary.csv",summaries)
    write_csv(out/"review_frame_manifest.csv",manifest)
    write_csv(out/"review_detection_join.csv",review_join)
    timeline = [dict(condition=c,variant=v,frame=r["frame"],time_sec=r["time_sec"],
                     detected=r["detected"],measurement_accepted=r["measurement_accepted"],
                     z_m=r["z_m"],filtered_z_m=r["filtered_z_m"]) for (c,v),rows in groups.items() for r in rows]
    write_csv(out/"distance_timeline.csv",timeline)
    fig,axes=plt.subplots(3,1,figsize=(12,9),sharex=True)
    colors=dict(zip(VARIANTS,("black","tab:blue","tab:orange","tab:green")))
    for ax,(condition,expected) in zip(axes,[(k,v) for k,v in CONDITIONS.items() if v is not None]):
        for variant in VARIANTS:
            rows=groups[condition,variant]
            ax.plot([float(r["time_sec"]) for r in rows],
                    [number(r,"z_m") if flag(r,"detected") else np.nan for r in rows],
                    color=colors[variant],label=variant,linewidth=1,alpha=.8)
        ax.axhline(expected,color="red",linestyle="--",label="nominal reference")
        ax.set_ylabel("detected Z [m]")
        ax.set_title(f"{condition}: nominal Z={expected:.2f} m, all detections incl. rejected")
        ax.grid(alpha=.3)
    axes[0].legend(loc="upper left",fontsize=8,ncol=3)
    axes[-1].set_xlabel("time after recording start [s]")
    fig.tight_layout();fig.savefig(out/"static_distance_timeline.png",dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8))
    for variant in VARIANTS:
        data=[r for r in summaries if r["variant"]==variant and r["window"]=="after_2s" and r["expected_z_m"] is not None]
        x=[r["expected_z_m"] for r in data];y=[r["detected_z_median_m"] for r in data]
        axes[0].errorbar(x,y,yerr=[[r["detected_z_median_m"]-r["detected_z_p05_m"] for r in data],
                                  [r["detected_z_p95_m"]-r["detected_z_median_m"] for r in data]],
                         color=colors[variant],marker="o",label=variant,capsize=4)
        axes[1].plot(x,[100*r["detected_z_bias_m"] for r in data],marker="o",color=colors[variant],label=variant)
    axes[0].plot([.85,1.35],[.85,1.35],"r--",label="identity")
    axes[0].set_ylabel("estimated Z median [m], bars P5-P95")
    axes[1].axhline(0,color="red",linestyle="--")
    axes[1].set_ylabel("median signed error vs nominal [cm]")
    for ax in axes:
        ax.set_xlabel("nominal Z reference [m]");ax.set_xticks([.9,1.1,1.3]);ax.grid(alpha=.3)
    axes[0].legend(fontsize=8)
    fig.suptitle("Static references after 2 s; origin confirmed, pose unchanged; placement uncertainty unknown")
    fig.tight_layout();fig.savefig(out/"static_distance_bias.png",dpi=150);plt.close(fig)
    ast.parse(Path(__file__).read_text())
    (out/"assessment.json").write_text(json.dumps(dict(
        scope="OFFLINE_ONLY_NO_FITTING_NO_RUNTIME_OR_HARDWARE_APPROVAL",
        reference_quality=REFERENCE["reference_quality"],
        reference_conditions=REFERENCE,
        reference_conditions_sha256=sha256(HERE / "reference_conditions.json"),
        sessions=audits,source_sha256=source_hashes,reviewed_frames=len(reviews),
        candidate_frozen=provenance["frozen_candidate_check"],frozen_rows=len(frozen),
        analysis_script_sha256=sha256(Path(__file__)),
        limits=["User confirms camera-under/Kobuki-centre origin and no height/tilt changes; endpoint detail, absolute pose and placement uncertainty unrecorded",
                "One session per distance; temporally correlated frames are not independent trials",
                "Only 3 raw frames per session visually reviewed; not all-frame visual labels",
                "Live pipeline already warm at recording start; offline replay starts tracker from scratch",
                "Distance statistics include rejected detections; accepted and predicted track counts separate",
                "No bag supplied: publish_success does not prove downstream delivery or physical vibration",
                "No coefficients fitted or config/safety gates changed"]),indent=2)+"\n")
    (out/"verification.json").write_text(json.dumps(dict(
        integrity_and_sequential_decode="PASS_ALL_FOUR_SESSIONS_ALL_THREE_VIDEOS",
        total_frames=sum(r["csv_frames"] for r in audits), frozen_rows=len(frozen),
        reviewed_raw_frames=len(manifest), representative_png_pixels_match_raw=checked_images,
        parameter_differences={}, candidate_frozen=provenance["frozen_candidate_check"],
        contiguous_frames_and_matching_times=True, zero_motion_and_no_alerts=True,
        distance_statistics_keep_rejected_detections=True, coefficient_fitting=False,
        runtime_configuration_changed=False, downstream_delivery_or_hardware_evaluated=False,
        reference_conditions=REFERENCE, reference_conditions_sha256=sha256(HERE / "reference_conditions.json")),indent=2)+"\n")
    print("PASS: integrity, sequential decode, timestamps, frozen candidate and review joins")
    for row in summaries:
        if row["window"]=="after_2s":
            print(row["condition"],row["variant"],row["frames"],row["detected"],row["accepted"],
                  row.get("detected_z_median_m"),row.get("detected_z_bias_m"),row.get("detected_z_iqr_m"))


if __name__ == "__main__":
    main()
