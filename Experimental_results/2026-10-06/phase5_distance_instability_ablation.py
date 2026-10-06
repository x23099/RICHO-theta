#!/usr/bin/env python3
"""録画のみで輪郭感度・TTC速度源・再初期化の影響を切り分ける。ROS送信なし。"""
import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from evaluate_observation_gates import recompute_session
from evaluate_collision_hysteresis_replay import replay_rows_with_states
from obstacle_tracking import BlueObstacleTracker, CausalTtcEstimator


def num(row, key):
    try:
        value = float(row[key])
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, KeyError):
        return None


def flag(row, key):
    return str(row.get(key, "")).lower() in {"1", "true", "yes"}


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def maximum(values):
    values = [v for v in values if v is not None]
    return max(values) if values else None


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def live_phases(session, rows):
    moving = [num(r, "time_sec") for r in rows if (num(r, "odom_linear_mps") or 0) > .03]
    start, stop = min(moving), max(moving)
    phases = []
    for phase, selected in (
        ("before_motion", [r for r in rows if num(r, "time_sec") < start]),
        ("moving", [r for r in rows if start <= num(r, "time_sec") <= stop]),
        ("after_stop_plus_0p5", [r for r in rows if num(r, "time_sec") > stop + .5]),
    ):
        detected = [r for r in selected if flag(r, "detected")]
        zs = [num(r, "raw_z_m") for r in detected]
        zs = [z for z in zs if z is not None]
        accepted = [r for r in selected if flag(r, "measurement_accepted")]
        residuals = []
        for a, b in zip(selected, selected[1:]):
            za, zb = num(a, "raw_z_m"), num(b, "raw_z_m")
            if za is None or zb is None:
                continue
            dt = num(b, "time_sec") - num(a, "time_sec")
            travel = .5 * ((num(a, "odom_linear_mps") or 0) + (num(b, "odom_linear_mps") or 0)) * dt
            residuals.append(abs(zb - za + travel))
        phases.append({
            "session": session, "phase": phase, "frames": len(selected),
            "live_detected": len(detected), "live_detection_rate": len(detected) / len(selected),
            "live_accepted": len(accepted), "live_acceptance_all_frames": len(accepted) / len(selected),
            "raw_z_median_m": median(zs), "raw_z_std_m": statistics.pstdev(zs) if zs else None,
            "raw_z_min_m": min(zs) if zs else None, "raw_z_max_m": maximum(zs),
            "max_adjacent_raw_motion_residual_m": maximum(residuals),
            "residual_over_0p03m_count": sum(v > .03 for v in residuals),
            "residual_pair_count": len(residuals),
            "initialization_count": sum(r["rejection_reason"] == "initialized" for r in selected),
            "nis_rejection_count": sum(r["rejection_reason"] in {"nis_gate", "nis_gate_track_expired"} for r in selected),
        })
    return phases


def ttc_ablation(session, metadata, rows, mode):
    p = metadata["parameters"]
    estimator = CausalTtcEstimator(
        window_sec=p["blue_ttc_velocity_window_sec"], deadband_mps=p["blue_ttc_deadband_mps"],
        velocity_source="conservative" if mode == "coldstart_odom_0p3" else mode,
    )
    replay = []
    track_since = None
    for original in rows:
        row = dict(original)
        now = num(row, "monotonic_time_sec")
        if now is None:
            now = num(row, "time_sec")
        track = None
        if flag(row, "track_available"):
            track = {"z_m": num(row, "filtered_z_m"), "vz_mps": num(row, "relative_vz_mps")}
            if track_since is None:
                track_since = now
        else:
            track_since = None
        ego = num(row, "odom_linear_mps") if flag(row, "odom_available") else None
        estimate = estimator.update(track, timestamp=now, ego_linear_mps=ego)
        if mode == "coldstart_odom_0p3" and track is not None and ego is not None and now - track_since < .3:
            # 原因切り分け用。動く障害物を見逃す可能性があり、本番候補として採用しない。
            vz = -ego
            estimate.update(smoothed_vz_mps=vz, ttc_velocity_source="diagnostic_coldstart_odom",
                            ttc_sec=track["z_m"] / -vz if vz < -p["blue_ttc_deadband_mps"] else None)
        row.update({k: "" if v is None else v for k, v in estimate.items()})
        replay.append(row)
    summary, replay = replay_rows_with_states(session, metadata, replay)
    finite = [num(r, "ttc_sec") for r in replay]
    finite = [v for v in finite if v is not None]
    baseline_mismatches = sum(r["collision_risk_level"] != original["collision_risk_level"] for r, original in zip(replay, rows))
    details = [{"session": session, "mode": mode, "frame": r["frame"], "time_sec": r["time_sec"],
                "ttc_sec": r["ttc_sec"], "smoothed_vz_mps": r["smoothed_vz_mps"],
                "velocity_source": r["ttc_velocity_source"], "risk_level": r["collision_risk_level"]}
               for r in replay]
    return {"session": session, "mode": mode, "min_ttc_sec": min(finite) if finite else None,
            "raw_critical_frames": summary["raw_critical_frames"],
            "filtered_critical_frames": summary["filtered_critical_frames"],
            "filtered_warning_including_hold_critical_frames": summary["filtered_warning_frames"],
            "unknown_frames": summary["unknown_frames"], "risk_difference_vs_live_frames": baseline_mismatches}, details


def prior_ablation(session, metadata, rows):
    initialized = [i for i, r in enumerate(rows) if r["rejection_reason"] == "initialized"]
    if len(initialized) < 2:
        return []
    start = initialized[1]
    selected = rows[start:start + 14]
    p = metadata["parameters"]
    output = []
    for sigma in [.5, .2, .1]:
        tracker = BlueObstacleTracker(p["blue_tracking_process_accel_std_mps2"], p["blue_tracking_measurement_std_m"],
                                      p["blue_tracking_max_missing_sec"], p["blue_tracking_max_dt_sec"])
        ttc = CausalTtcEstimator(p["blue_ttc_velocity_window_sec"], p["blue_ttc_deadband_mps"], velocity_source="conservative")
        for index, r in enumerate(selected):
            measurement = (num(r, "x_m"), num(r, "z_m")) if flag(r, "detected") and flag(r, "calibration_valid") else None
            now = num(r, "monotonic_time_sec")
            track, diagnostics = tracker.update_with_diagnostics(measurement, timestamp=now, max_nis=p["blue_observation_nis_max"])
            if index == 0:
                covariance = tracker.filter.errorCovPost.copy()
                covariance[2, 2] = covariance[3, 3] = sigma ** 2
                tracker.filter.errorCovPost = covariance
            estimate = ttc.update(track, timestamp=now, ego_linear_mps=num(r, "odom_linear_mps"))
            output.append({"session": session, "diagnostic_initial_velocity_sigma_mps": sigma,
                           "frame": r["frame"], "time_sec": r["time_sec"], "raw_z_m": r["raw_z_m"],
                           "live_vz_mps": r["relative_vz_mps"], "replayed_vz_mps": track["vz_mps"] if track else "",
                           "measurement_accepted": int(diagnostics["measurement_accepted"]),
                           "nis": diagnostics["nis"], "ttc_sec": estimate["ttc_sec"],
                           "odom_linear_mps": r["odom_linear_mps"]})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--no-target", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.input and args.no_target is None:
        parser.error("--inputまたは--no-targetが必要です")
    cv2.setNumThreads(1)
    args.output.mkdir(parents=True, exist_ok=True)
    phases, ttcs, ttc_details, priors, sweeps, detector_details = [], [], [], [], [], []
    baseline_checks = []
    variants = [
        ("baseline_v30_aspect1p5", {}),
        ("v20_aspect1p5", {"blue_ground_contact_hsv_v_min": 20}),
        ("v25_aspect1p5", {"blue_ground_contact_hsv_v_min": 25}),
        ("v35_aspect1p5", {"blue_ground_contact_hsv_v_min": 35}),
        ("v30_aspect_unrestricted_diagnostic", {"blue_ground_contact_max_aspect_ratio": 1000}),
        ("v30_contact_fraction0p02", {"blue_ground_contact_fraction": .02}),
        ("v30_contact_fraction0p16", {"blue_ground_contact_fraction": .16}),
    ]
    inputs = args.input + ([args.no_target] if args.no_target else [])
    for session_dir in inputs:
        metadata = json.loads((session_dir / "metadata.json").read_text())
        p = metadata["parameters"]
        rows = list(csv.DictReader((session_dir / "detections.csv").open(newline="")))
        no_target = session_dir == args.no_target
        if not no_target:
            phases.extend(live_phases(session_dir.name, rows))
            for mode in ["conservative", "visual", "odom_static", "coldstart_odom_0p3"]:
                summary, details = ttc_ablation(session_dir.name, metadata, rows, mode)
                ttcs.append(summary)
                ttc_details.extend(details)
                if mode == "conservative":
                    baseline_checks.append({"session": session_dir.name, "risk_mismatches": summary["risk_difference_vs_live_frames"]})
            priors.extend(prior_ablation(session_dir.name, metadata, rows))
        for variant, overrides in variants:
            config = dict(p)
            # 古いcontrolのmetadataに未記録の検出設定も、今回のbaselineで比較する。
            config.setdefault("blue_ground_contact_hsv_v_min", 30)
            config.setdefault("blue_ground_contact_illumination_mode", "none")
            config.setdefault("blue_ground_contact_max_aspect_ratio", 1.5)
            config.update(overrides)
            observations, basic = recompute_session(session_dir, config)
            if len(observations) != len(rows):
                raise ValueError(f"動画とCSVのframe数が不一致: {session_dir}")
            zs, residuals, contact_ys, calibration = [], [], [], 0
            previous = None
            for obs in observations:
                n = obs["frame"]
                live = rows[n]
                valid = bool(obs["detected"] and abs(obs["x_m"]) <= p["blue_calibration_input_x_max_m"]
                             and p["blue_calibration_input_z_min_m"] <= obs["z_m"] <= p["blue_calibration_input_z_max_m"])
                calibration += valid
                if obs["detected"]:
                    zs.append(obs["z_m"])
                    contact_ys.append(obs["source_pixel_y"])
                    if previous and previous["frame"] == n - 1:
                        dt = num(live, "time_sec") - num(rows[n - 1], "time_sec")
                        travel = .5 * ((num(live, "odom_linear_mps") or 0) + (num(rows[n - 1], "odom_linear_mps") or 0)) * dt
                        residuals.append(abs(obs["z_m"] - previous["z_m"] + travel))
                    previous = obs
                else:
                    previous = None
                detector_details.append({"session": session_dir.name, "no_target": int(no_target), "variant": variant,
                                         "frame": n + 1, "time_sec": live["time_sec"], "live_detected": live["detected"],
                                         "avi_detected": obs["detected"], "avi_z_m": obs["z_m"], "avi_calibration_valid": int(valid),
                                         "avi_source_pixel_y": obs["source_pixel_y"], "avi_area_px": obs["area_px"],
                                         "avi_bbox_aspect_ratio": obs["bbox_aspect_ratio"], "avi_fill_ratio": obs["bbox_fill_ratio"]})
            sweeps.append({"session": session_dir.name, "no_target": int(no_target), "variant": variant,
                           "frames": len(observations), "avi_detected": basic["detected_frames"], "avi_detection_rate": basic["detection_rate"],
                           "avi_calibration_valid": calibration, "avi_calibration_valid_rate": calibration / len(observations),
                           "avi_z_median_m": median(zs), "avi_z_min_m": min(zs) if zs else None, "avi_z_max_m": maximum(zs),
                           "avi_contact_y_std_px": statistics.pstdev(contact_ys) if contact_ys else None,
                           "adjacent_motion_residual_over_0p03m": sum(v > .03 for v in residuals),
                           "adjacent_detected_pair_count": len(residuals), "max_adjacent_motion_residual_m": maximum(residuals),
                           "avi_live_detection_mismatch_frames": sum(bool(o["detected"]) != flag(live, "detected") for o, live in zip(observations, rows))})
            print(f"{session_dir.name} {variant}: detect={basic['detection_rate']:.1%}, CAL={calibration}/{len(observations)}", flush=True)
    for filename, results in [("live_phases.csv", phases), ("ttc_velocity_ablation.csv", ttcs),
                              ("ttc_velocity_ablation_frames.csv", ttc_details), ("reinitialization_prior_ablation.csv", priors),
                              ("detector_sensitivity.csv", sweeps), ("detector_sensitivity_frames.csv", detector_details)]:
        if results:
            write_csv(args.output / filename, results)
    (args.output / "provenance.json").write_text(json.dumps({
        "inputs": [str(p) for p in inputs], "baseline_checks": baseline_checks,
        "scope": "offline diagnosis only; no ROS publishing, hardware access or production config changes",
        "limits": ["AVI is MJPG-reencoded; not pixel-identical to live capture", "no new-floor ground-truth labels",
                   "TTC counterfactual retains live tracks and path flags", "prior ablation isolates 14 frames; not full pipeline regression"],
    }, ensure_ascii=False, indent=2) + "\n")
    print("Live conservative replay checks:", baseline_checks, flush=True)


if __name__ == "__main__":
    main()
