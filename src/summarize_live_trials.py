#!/usr/bin/env python3
"""Summarize timestamped field-trial recordings produced by bird_eye.py."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


SUMMARY_FIELDS = [
    "experiment_label",
    "session_dir",
    "frames",
    "duration_sec",
    "effective_fps",
    "detection_rate",
    "measurement_acceptance_rate",
    "track_rate",
    "odom_available_rate",
    "moving_frames",
    "direction_correct_rate",
    "relative_speed_mae_mps",
    "ttc_active_rate",
    "ttc_active_rate_while_approaching",
    "minimum_ttc_sec",
    "ttc_vs_odom_mae_sec",
    "path_corridor_rate",
    "warning_or_critical_rate",
    "warning_hold_rate",
    "unknown_rate",
    "critical_rate",
    "warning_or_critical_frames",
    "critical_frames",
]


def _number(row, key):
    value = row.get(key, "")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _flag(row, key):
    value = str(row.get(key, "")).strip().lower()
    return value in {"1", "true", "yes"}


def _rate(numerator, denominator):
    return numerator / denominator if denominator else math.nan


def _mean(values):
    return sum(values) / len(values) if values else math.nan


def load_session(session_dir):
    session_dir = Path(session_dir)
    with (session_dir / "detections.csv").open(newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    metadata_path = session_dir / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        with metadata_path.open() as metadata_file:
            metadata = json.load(metadata_file)
    return metadata, rows


def summarize_session(session_dir, moving_threshold_mps=0.03):
    metadata, rows = load_session(session_dir)
    timestamps = [
        value
        for row in rows
        if (value := _number(row, "monotonic_time_sec")) is not None
    ]
    if len(timestamps) < 2:
        timestamps = [
            value
            for row in rows
            if (value := _number(row, "time_sec")) is not None
        ]
    duration_sec = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0.0
    detected = [row for row in rows if _flag(row, "detected")]
    tracked = [row for row in rows if _flag(row, "track_available")]
    accepted = [row for row in detected if _flag(row, "measurement_accepted")]
    odom_rows = [row for row in rows if _flag(row, "odom_available")]
    moving = [
        row
        for row in odom_rows
        if abs(_number(row, "odom_linear_mps") or 0.0) > moving_threshold_mps
    ]
    approaching = []
    direction_correct = []
    speed_errors = []
    ttc_errors = []
    for row in moving:
        smoothed_vz = _number(row, "smoothed_vz_mps")
        odom_speed = _number(row, "odom_linear_mps")
        filtered_z = _number(row, "filtered_z_m")
        ttc_sec = _number(row, "ttc_sec")
        if smoothed_vz is None or odom_speed is None:
            continue
        direction_correct.append(smoothed_vz * odom_speed < 0.0)
        speed_errors.append(abs(-smoothed_vz - odom_speed))
        if smoothed_vz < -moving_threshold_mps:
            approaching.append(row)
        if (
            ttc_sec is not None
            and filtered_z is not None
            and odom_speed > moving_threshold_mps
        ):
            ttc_errors.append(abs(ttc_sec - filtered_z / odom_speed))

    ttc_values = [
        value
        for row in rows
        if (value := _number(row, "ttc_sec")) is not None
    ]
    path_rows = [
        row for row in tracked if row.get("path_in_collision_corridor", "") != ""
    ]
    risk_levels = [row.get("collision_risk_level", "") for row in rows]
    warning_levels = {"WARNING", "WARNING_HOLD", "CRITICAL"}
    return {
        "experiment_label": metadata.get("experiment_label", Path(session_dir).name),
        "session_dir": str(Path(session_dir).resolve()),
        "frames": len(rows),
        "duration_sec": duration_sec,
        "effective_fps": (len(timestamps) - 1) / duration_sec
        if duration_sec > 0.0
        else math.nan,
        "detection_rate": _rate(len(detected), len(rows)),
        "measurement_acceptance_rate": _rate(len(accepted), len(detected)),
        "track_rate": _rate(len(tracked), len(rows)),
        "odom_available_rate": _rate(len(odom_rows), len(rows)),
        "moving_frames": len(moving),
        "direction_correct_rate": _mean(direction_correct),
        "relative_speed_mae_mps": _mean(speed_errors),
        "ttc_active_rate": _rate(len(ttc_values), len(rows)),
        "ttc_active_rate_while_approaching": _rate(
            sum(_number(row, "ttc_sec") is not None for row in approaching),
            len(approaching),
        ),
        "minimum_ttc_sec": min(ttc_values) if ttc_values else math.nan,
        "ttc_vs_odom_mae_sec": _mean(ttc_errors),
        "path_corridor_rate": _rate(
            sum(_flag(row, "path_in_collision_corridor") for row in path_rows),
            len(path_rows),
        ),
        "warning_or_critical_rate": _rate(
            sum(value in warning_levels for value in risk_levels),
            len(rows),
        ),
        "warning_hold_rate": _rate(
            sum(value == "WARNING_HOLD" for value in risk_levels), len(rows)
        ),
        "unknown_rate": _rate(
            sum(value == "UNKNOWN" for value in risk_levels), len(rows)
        ),
        "critical_rate": _rate(
            sum(value == "CRITICAL" for value in risk_levels), len(rows)
        ),
        "warning_or_critical_frames": sum(
            value in warning_levels for value in risk_levels
        ),
        "critical_frames": sum(value == "CRITICAL" for value in risk_levels),
    }


def find_session_dirs(inputs):
    found = []
    for input_path in inputs:
        input_path = Path(input_path)
        if (input_path / "detections.csv").exists():
            found.append(input_path)
        elif input_path.is_dir():
            found.extend(path.parent for path in input_path.rglob("detections.csv"))
    return sorted(set(found))


def main():
    parser = argparse.ArgumentParser(
        description="Summarize live bird_eye.py field-trial recordings"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("live_trial_summary.csv")
    )
    parser.add_argument("--moving-threshold-mps", type=float, default=0.03)
    args = parser.parse_args()

    sessions = find_session_dirs(args.input)
    if not sessions:
        parser.error("no recording directory containing detections.csv was found")
    summaries = [
        summarize_session(session, args.moving_threshold_mps)
        for session in sessions
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=SUMMARY_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(summaries)
    print(f"Sessions: {len(summaries)}")
    print(f"Summary saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
