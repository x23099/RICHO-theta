#!/usr/bin/env python3
"""Compare an OFFLINE evidence gate with recorded collision/virtual FFB states.

No ROS initialization, publisher, device access or production config writes.
Live tracks/path geometry are retained; this is not a raw-video pipeline replay.
"""
import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from collision_ffb_publisher import CollisionFfbCadenceController
from collision_risk import CollisionRiskHysteresis, classify_candidate_risk
from diagnose_lateral_gate_asymmetry import load_sessions
from offline_velocity_confidence import ConfidenceSettings, OfflineVelocityConfidence
from virtual_ffb import VirtualFfbPolicy


def number(row, key):
    try:
        value = float(row.get(key, ""))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def flag(row, key):
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def evaluate_rows(session, metadata, rows, *, settings=None, candidate=True):
    p = metadata.get("parameters", {})
    confidence = OfflineVelocityConfidence(settings)
    state_filter = CollisionRiskHysteresis(
        warning_ttc_sec=p.get("blue_collision_warning_ttc_sec", 4.6),
        warning_exit_ttc_sec=p.get("blue_collision_warning_exit_ttc_sec", 5.6),
        warning_confirm_frames=p.get("blue_collision_warning_confirm_frames", 3),
        warning_clear_frames=p.get("blue_collision_warning_clear_frames", 3),
        warning_hold_sec=p.get("blue_collision_warning_hold_sec", .8))
    policy = VirtualFfbPolicy(p.get("collision_ffb_warning_magnitude", .25),
                             p.get("collision_ffb_critical_magnitude", .4),
                             p.get("collision_ffb_unknown_magnitude", .15))
    current_time = [0.0]
    cadence = CollisionFfbCadenceController(
        cadence=p.get("collision_ffb_cadence", "triple"),
        duration_sec=p.get("collision_ffb_cadence_duration_sec", .5),
        rate_hz=p.get("collision_ffb_cadence_rate_hz", 30),
        unknown_pulse_duration_sec=p.get("collision_ffb_unknown_pulse_duration_sec", .1),
        unknown_rearm_valid_sec=p.get("collision_ffb_unknown_rearm_valid_sec", .5),
        monotonic_clock=lambda: current_time[0])
    details = []
    for row in rows:
        now = number(row, "monotonic_time_sec")
        if now is None:
            now = number(row, "time_sec")
        if now is None:
            raise ValueError(f"missing finite time in {session}")
        current_time[0] = now
        valid = (flag(row, "track_available") and not flag(row, "track_predicted")
                 and flag(row, "measurement_accepted") and flag(row, "calibration_valid"))
        raw_level = classify_candidate_risk(flag(row, "path_in_collision_corridor"), number(row, "ttc_sec"),
                                            p.get("blue_collision_warning_ttc_sec", 4.6),
                                            p.get("blue_collision_critical_ttc_sec", 2.0))
        visual = number(row, "visual_smoothed_vz_mps")
        if visual is None:
            visual = number(row, "relative_vz_mps")
        evidence = confidence.update(timestamp=now, raw_z_m=number(row, "z_m"), visual_vz_mps=visual,
                                     measurement_valid=valid, track_available=flag(row, "track_available"),
                                     initialized=row.get("rejection_reason") == "initialized",
                                     critical_requested=raw_level == "CRITICAL")
        source = row.get("ttc_velocity_source", "")
        # Only elevated alerts derived from visual velocity require new evidence.
        # ODOM-derived alerts and non-alert PATH/CLEAR are not changed by this prototype.
        visual_selected = source in {"conservative_visual", "visual", "visual_fallback"}
        withheld = bool(candidate and valid and visual_selected
                        and raw_level in {"WARNING", "CRITICAL"} and not evidence["trusted"])
        effective_raw = "UNKNOWN" if withheld else raw_level
        effective_valid = valid and not withheld
        odom = number(row, "odom_linear_mps") if flag(row, "odom_available") else None
        linear = number(row, "prediction_linear_mps")
        if linear is None:
            linear = odom if odom is not None else (number(row, "cmd_linear_mps") or 0.0)
        state = state_filter.update(raw_level=effective_raw, timestamp_sec=now,
                                    measurement_valid=effective_valid,
                                    moving_forward=linear > p.get("blue_collision_forward_motion_threshold_mps", .03),
                                    in_collision_corridor=flag(row, "path_in_collision_corridor"),
                                    ttc_sec=None if withheld else number(row, "ttc_sec"))
        command = cadence.command(state["risk_level"], policy, measurement_valid=effective_valid)
        details.append({"session": session, "variant": "confidence_candidate" if candidate else "baseline",
                        "frame": row.get("frame", len(details) + 1), "time_sec": row.get("time_sec", now),
                        "recorded_risk": row.get("collision_risk_level", ""), "risk": state["risk_level"],
                        "raw_risk": raw_level, "confidence_trusted": int(evidence["trusted"]),
                        "confidence_reason": evidence["reason"], "samples": evidence["samples"],
                        "history_span_sec": evidence["span_sec"], "robust_vz_mps": evidence["robust_vz_mps"],
                        "median_residual_m": evidence["median_residual_m"], "latest_residual_m": evidence["latest_residual_m"],
                        "visual_vz_mps": visual, "ttc_sec": number(row, "ttc_sec"), "alert_withheld": int(withheld),
                        "virtual_active": int(command.active), "virtual_reason": command.reason,
                        "virtual_requested_magnitude": command.normalized_magnitude})
    counts = Counter(r["risk"] for r in details)
    active_groups = sum(r["virtual_active"] and (i == 0 or not details[i - 1]["virtual_active"]) for i, r in enumerate(details))
    return {"session": session, "variant": "confidence_candidate" if candidate else "baseline", "frames": len(details),
            "warning_frames": counts["WARNING"], "hold_frames": counts["WARNING_HOLD"], "critical_frames": counts["CRITICAL"],
            "unknown_frames": counts["UNKNOWN"], "withheld_frames": sum(r["alert_withheld"] for r in details),
            "virtual_active_frames": sum(r["virtual_active"] for r in details), "virtual_active_groups": active_groups,
            "recorded_risk_compared_frames": sum(bool(r["recorded_risk"]) for r in details),
            "recorded_risk_mismatches": sum(bool(r["recorded_risk"]) and r["risk"] != r["recorded_risk"] for r in details),
            "first_warning_sec": next((r["time_sec"] for r in details if r["risk"] == "WARNING"), ""),
            "first_critical_sec": next((r["time_sec"] for r in details if r["risk"] == "CRITICAL"), "")}, details


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--disable-fast-critical-evidence", action="store_true")
    args = parser.parse_args()
    settings = ConfidenceSettings(fast_critical_evidence=not args.disable_fast_critical_evidence)
    results, details = [], []
    for label, source, metadata, rows in load_sessions(args.input):
        for candidate in (False, True):
            summary, frames = evaluate_rows(label, metadata, rows, settings=settings, candidate=candidate)
            summary["source"] = source
            results.append(summary)
            details.extend(frames)
            print(f"{label} {summary['variant']}: WARNING={summary['warning_frames']}, CRITICAL={summary['critical_frames']}, "
                  f"UNKNOWN={summary['unknown_frames']}, virtual groups={summary['virtual_active_groups']}", flush=True)
    if not results:
        parser.error("no recording CSV sessions found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "summary.csv", results)
    write_csv(args.output_dir / "frame_results.csv", details)
    code = [Path(__file__), Path(__file__).with_name("offline_velocity_confidence.py")]
    (args.output_dir / "provenance.json").write_text(json.dumps({
        "scope": "OFFLINE_ONLY_NOT_APPROVED_FOR_HARDWARE", "settings": asdict(settings),
        "inputs": [str(p.resolve()) for p in args.input],
        "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code},
        "limits": ["recorded tracks/path flags and recorded TTC retained", "no distance correction or full raw pipeline replay",
                   "virtual demand is not a hardware status", "thresholds exploratory; independent holdout required"]}, indent=2) + "\n")


if __name__ == "__main__":
    main()
