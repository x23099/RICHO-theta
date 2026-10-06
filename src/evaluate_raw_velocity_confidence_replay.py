#!/usr/bin/env python3
"""Offline blue-target video -> gate -> tracking -> TTC -> risk/virtual demand.

No GUI, ROS initialization, hardware access, or production configuration edits.
Logged per-frame times and motion are external inputs, not simulated ROS timing.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import cv2

from collision_risk import assess_path_collision, predict_unicycle_path
from evaluate_observation_gates import find_session_directories
from evaluate_velocity_confidence_replay import evaluate_rows, flag, number, write_csv
from ground_contact import area_normalization_distance, detect_blue_ground_contact
from obstacle_tracking import BlueObstacleTracker, CausalTtcEstimator, ObstacleObservationGate


def validate_rows(rows):
    if not rows:
        raise ValueError("empty detections.csv")
    last_time = None
    for index, row in enumerate(rows, 1):
        if int(row["frame"]) != index:
            raise ValueError("requires consecutive one-based frame IDs matching raw.avi")
        now = number(row, "monotonic_time_sec")
        if now is None:
            now = number(row, "time_sec")
        if now is None or (last_time is not None and now <= last_time):
            raise ValueError("requires finite strictly increasing recorded frame times")
        if flag(row, "odom_available") and any(number(row, k) is None for k in ("odom_linear_mps", "odom_angular_radps")):
            raise ValueError("available odometry requires finite linear/angular values")
        if any(number(row, k) is None for k in ("cmd_linear_mps", "cmd_angular_radps")):
            raise ValueError("requires finite per-frame command motion")
        last_time = now


def predicted_motion(row):
    """Reproduce bird_eye.py prediction selection; not a motion controller."""
    recent = flag(row, "odom_available")
    ov = number(row, "odom_linear_mps") if recent else None
    ow = number(row, "odom_angular_radps") if recent else None
    cv = number(row, "cmd_linear_mps") or 0.0
    cw = number(row, "cmd_angular_radps") or 0.0
    v = ov if ov is not None and abs(ov) >= .01 else cv
    linear_source = "odom" if ov is not None and abs(ov) >= .01 else "cmd"
    if abs(cw) >= 1e-4:
        w, angular_source = cw, "cmd"
    elif ow is not None and abs(ow) >= .005:
        w, angular_source = ow, "odom"
    else:
        w, angular_source = cw, "cmd"
    if abs(v) < .01 and abs(w) < .005:
        return 0.0, 0.0, "none", []
    if angular_source == "cmd":
        yaw = math.radians(min(360, 90 * (abs(w) / .8) ** (1 / .60)))
        w = math.copysign((yaw / 3.5) * (abs(v) / .8), w) if abs(w) > 1e-4 else 0.0
    source = "odom" if linear_source == angular_source == "odom" else f"{linear_source}+{angular_source}"
    return v, w, source, predict_unicycle_path(v, w)


class OfflineBluePipeline:
    def __init__(self, parameters):
        self.p = dict(parameters)
        p = self.p
        if p.get("blue_position_method", "ground_contact") != "ground_contact":
            raise ValueError("only ground_contact recordings are supported")
        for key in ("detect_blue_obstacle", "blue_tracking_enabled", "blue_collision_candidate_enabled"):
            if p.get(key, 1) != 1:
                raise ValueError(f"requires {key}=1; disabled pipelines not reconstructed")
        self.tracker = BlueObstacleTracker(
            p.get("blue_tracking_process_accel_std_mps2", 1.5),
            p.get("blue_tracking_measurement_std_m", .03),
            p.get("blue_tracking_max_missing_sec", .25), p.get("blue_tracking_max_dt_sec", .2))
        self.gate = ObstacleObservationGate(
            enabled=p.get("blue_observation_gate_enabled", 1) == 1,
            min_normalized_area=p.get("blue_observation_normalized_area_min", 2503.678448310634),
            max_nis=p.get("blue_observation_nis_max", 9.210),
            confirmation_frames=p.get("blue_observation_confirmation_frames", 2),
            confirmation_distance_m=p.get("blue_observation_confirmation_distance_m", .15))
        self.ttc = CausalTtcEstimator(
            enabled=p.get("blue_ttc_enabled", 1) == 1,
            window_sec=p.get("blue_ttc_velocity_window_sec", .3),
            deadband_mps=p.get("blue_ttc_deadband_mps", .05),
            velocity_source=p.get("blue_ttc_velocity_source", "visual"))

    def calibrate_contact(self, contact):
        if contact is None:
            return None
        p = self.p
        x = contact["x_m"] * p.get("blue_ground_contact_x_scale", 1) + p.get("blue_ground_contact_x_offset_m", 0)
        z = contact["z_m"] + p.get("blue_ground_contact_z_offset_m", 0)
        valid = (abs(x) <= p.get("blue_calibration_input_x_max_m", .5)
                 and p.get("blue_calibration_input_z_min_m", .65) <= z <= p.get("blue_calibration_input_z_max_m", 1.35))
        return {"x_m": x, "z_m": z, "area_px": contact["area_px"], "calibration_valid": valid,
                "raw_distance_m": math.hypot(contact["x_m"], contact["z_m"])}

    def update_observation(self, observation, motion):
        p = self.p
        now = number(motion, "monotonic_time_sec")
        if now is None:
            now = number(motion, "time_sec")
        if now is None:
            raise ValueError("missing finite frame time")
        raw = (observation["x_m"], observation["z_m"]) if observation else None
        projected = self.tracker.projected_position(timestamp=now)
        norm = area_normalization_distance(p.get("blue_observation_area_distance_mode", "forward_z"),
                                          projected, observation["raw_distance_m"] if observation else None, p)
        measurement, gate_diag = self.gate.filter_measurement(
            raw, area_px=observation["area_px"] if observation else None,
            predicted_z_m=projected[1] if projected else (raw[1] if raw else None),
            normalization_distance_m=norm, tracker_initialized=self.tracker.initialized,
            measurement_valid=bool(observation and observation["calibration_valid"]), invalid_reason="calibration_range_gate")
        track, diagnostics = self.tracker.update_with_diagnostics(
            measurement, timestamp=now, max_nis=self.gate.max_nis if self.gate.enabled else None)
        if raw is not None and measurement is None:
            diagnostics.update(measurement_available=True, measurement_accepted=False,
                               rejection_reason=gate_diag["gate_rejection_reason"])
        odom = number(motion, "odom_linear_mps") if flag(motion, "odom_available") else None
        estimate = self.ttc.update(track, timestamp=now, ego_linear_mps=odom)
        v, w, source, path = predicted_motion(motion)
        collision = assess_path_collision(
            path, track["z_m"], -track["x_m"], p.get("car_width", .354),
            safety_margin_m=p.get("blue_collision_safety_margin_m", .1), path_speed_mps=v,
            ttc_sec=estimate["ttc_sec"], warning_ttc_sec=p.get("blue_collision_warning_ttc_sec", 4),
            critical_ttc_sec=p.get("blue_collision_critical_ttc_sec", 2)) if track else {}
        row = {"frame": motion["frame"], "time_sec": motion["time_sec"], "monotonic_time_sec": now,
               "detected": int(observation is not None), "x_m": raw[0] if raw else "", "z_m": raw[1] if raw else "",
               "area_px": observation["area_px"] if observation else "",
               "calibration_valid": int(bool(observation and observation["calibration_valid"])),
               "measurement_accepted": int(diagnostics["measurement_accepted"]), "rejection_reason": diagnostics["rejection_reason"],
               "normalized_area": gate_diag["normalized_area"], "observation_nis": diagnostics["nis"],
               "track_available": int(track is not None), "track_predicted": int(track["predicted"]) if track else 0,
               "filtered_x_m": track["x_m"] if track else "", "filtered_z_m": track["z_m"] if track else "",
               "relative_vz_mps": track["vz_mps"] if track else "",
               "odom_available": int(flag(motion, "odom_available")), "odom_linear_mps": odom if odom is not None else "",
               "odom_angular_radps": number(motion, "odom_angular_radps") if flag(motion, "odom_available") else "",
               "cmd_linear_mps": number(motion, "cmd_linear_mps"), "cmd_angular_radps": number(motion, "cmd_angular_radps"),
               # Distinguish recorded commands from the selected prediction motion.
               "prediction_linear_mps": v, "prediction_angular_radps": w,
               "prediction_motion_source": source, "path_in_collision_corridor": int(collision.get("in_collision_corridor", False)),
               "collision_risk_level": motion.get("collision_risk_level", "")}
        row.update({k: value if value is not None else "" for k, value in estimate.items()})
        # Keep ODOM for audit; the state evaluator uses prediction_linear_mps.
        return row


def live_observation(row):
    if not flag(row, "detected"):
        return None
    values = {k: number(row, k) for k in ("x_m", "z_m", "area_px", "raw_distance_m")}
    if any(value is None for value in values.values()):
        raise ValueError("incomplete recorded observation")
    return dict(values, calibration_valid=flag(row, "calibration_valid"))


def replay_session(session_dir):
    metadata = json.loads((session_dir / "metadata.json").read_text())
    with (session_dir / "detections.csv").open(newline="") as stream:
        live = list(csv.DictReader(stream))
    validate_rows(live)
    control = OfflineBluePipeline(metadata["parameters"])
    video_pipeline = OfflineBluePipeline(metadata["parameters"])
    video = cv2.VideoCapture(str(session_dir / "raw.avi"))
    if not video.isOpened():
        raise ValueError(f"cannot open raw.avi: {session_dir}")
    control_rows, raw_rows = [], []
    try:
        for motion in live:
            ok, frame = video.read()
            if not ok:
                raise ValueError("video shorter than detections.csv; cannot align frame motion")
            expected = (metadata.get("requested_camera_height"), metadata.get("requested_camera_width"))
            if all(expected) and frame.shape[:2] != expected:
                raise ValueError("recorded frame dimensions differ from metadata geometry")
            p = video_pipeline.p
            contact, _ = detect_blue_ground_contact(frame, p, min_area_px=p.get("blue_ground_contact_min_area", 300),
                                                     contact_fraction=p.get("blue_ground_contact_fraction", .08))
            raw_rows.append(video_pipeline.update_observation(video_pipeline.calibrate_contact(contact), motion))
            control_rows.append(control.update_observation(live_observation(motion), motion))
        if video.read()[0]:
            raise ValueError("video longer than detections.csv; cannot align frame motion")
    finally:
        video.release()
    return metadata, live, control_rows, raw_rows


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True, help="extracted session/root directory")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sessions = set()
    for source in args.input:
        found = find_session_directories([source])
        if not found:
            parser.error(f"no raw.avi + metadata.json sessions in requested input: {source}")
        sessions.update(found)
    sessions = sorted(sessions)
    if len({p.name for p in sessions}) != len(sessions):
        parser.error("duplicate session names; use separate output directories")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries, details, comparisons, provenance = [], [], [], []
    for session in sessions:
        print(f"Recomputing {session.name} ...", flush=True)
        metadata, live, control, raw = replay_session(session)
        session_output = args.output_dir / session.name
        session_output.mkdir(exist_ok=True)
        write_csv(session_output / "recomputed_inputs.csv", raw)
        write_csv(session_output / "logged_measurement_rebuild_inputs.csv", control)
        rebuilt = {}
        for name, source, candidate in [("logged_measurement_rebuild", control, False),
                                        ("raw_video_baseline", raw, False), ("raw_video_candidate", raw, True)]:
            summary, frames = evaluate_rows(session.name, metadata, source, candidate=candidate)
            summary.update(variant=name, detected_frames=sum(flag(r, "detected") for r in source),
                           accepted_frames=sum(flag(r, "measurement_accepted") for r in source))
            for row in frames:
                row["variant"] = name
            summaries.append(summary)
            details.extend(frames)
            rebuilt[name] = frames
            print(f"  {name}: warning={summary['warning_frames']} critical={summary['critical_frames']} "
                  f"unknown={summary['unknown_frames']} groups={summary['virtual_active_groups']}", flush=True)
        for index, (original, c, r) in enumerate(zip(live, control, raw)):
            comparisons.append({"session": session.name, "frame": original["frame"], "time_sec": original["time_sec"],
                                "live_detected": int(flag(original, "detected")), "video_detected": r["detected"],
                                "live_z_m": original.get("z_m", ""), "video_z_m": r["z_m"],
                                "live_accepted": int(flag(original, "measurement_accepted")),
                                "control_accepted": c["measurement_accepted"], "video_accepted": r["measurement_accepted"],
                                "live_risk": original.get("collision_risk_level", ""),
                                **{k: frames[index]["risk"] for k, frames in rebuilt.items()}})
        provenance.append({"session": session.name, "path": str(session),
                           "sha256": {name: sha256(session / name) for name in ("raw.avi", "detections.csv", "metadata.json")}})
    write_csv(args.output_dir / "summary.csv", summaries)
    write_csv(args.output_dir / "frame_results.csv", details)
    write_csv(args.output_dir / "live_video_comparison.csv", comparisons)
    code = [Path(__file__), Path(__file__).with_name("evaluate_velocity_confidence_replay.py"),
            Path(__file__).with_name("offline_velocity_confidence.py"), Path(__file__).with_name("ground_contact.py"),
            Path(__file__).with_name("obstacle_tracking.py"), Path(__file__).with_name("collision_risk.py"),
            Path(__file__).with_name("collision_ffb_publisher.py"), Path(__file__).with_name("virtual_ffb.py")]
    (args.output_dir / "provenance.json").write_text(json.dumps({
        "scope": "OFFLINE_ONLY_NO_PHYSICAL_OUTPUT", "sessions": provenance,
        "implementation_sha256": {p.name: sha256(p) for p in code},
        "limits": ["recorded frame times and ODOM/CMD retained, not ROS bag timing replay",
                   "MJPG pixels differ from live capture", "no GUI, YOLO, relay, adapter or hardware replay",
                   "metadata parameters frozen; no runtime config change"]}, indent=2) + "\n")


if __name__ == "__main__":
    main()
