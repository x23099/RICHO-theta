#!/usr/bin/env python3
"""Evaluate TTC activation on recorded approach, retreat, and static sessions."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from compare_observation_gates import load_observations, replay_variant
from cross_validate_observation_gates import fit_normalized_area_threshold
from obstacle_tracking import CausalTtcEstimator


SUMMARY_FIELDS = [
    "session",
    "expected_motion",
    "smoothing_window_sec",
    "normalized_area_threshold",
    "frames",
    "movement_frames",
    "measurement_acceptance_rate",
    "z_slope_mps",
    "median_smoothed_vz_mps",
    "direction_correct_rate",
    "deadband_direction_rate",
    "ttc_active_rate",
    "false_ttc_rate",
    "ttc_activation_delay_sec",
    "median_ttc_sec",
    "minimum_ttc_sec",
    "decision",
]

DETAIL_FIELDS = [
    "session",
    "smoothing_window_sec",
    "frame",
    "time_sec",
    "measurement_accepted",
    "rejection_reason",
    "track_available",
    "filtered_z_m",
    "relative_vz_mps",
    "smoothed_vz_mps",
    "ttc_sec",
    "in_movement_interval",
]


def expected_motion(session):
    if session.startswith("approach"):
        return "approach"
    if session.startswith("retreat"):
        return "retreat"
    if session.startswith("static"):
        return "static"
    return "excluded"


def add_causal_velocity_and_ttc(details, window_sec, deadband_mps):
    estimator = CausalTtcEstimator(
        window_sec=window_sec,
        deadband_mps=deadband_mps,
    )
    enriched = []
    for row in details:
        current = dict(row)
        timestamp = float(row["time_sec"])
        if row["track_available"] and row["relative_vz_mps"] != "":
            estimate = estimator.update(
                {
                    "z_m": float(row["filtered_z_m"]),
                    "vz_mps": float(row["relative_vz_mps"]),
                },
                timestamp=timestamp,
            )
        else:
            estimate = estimator.update(None, timestamp=timestamp)
        current["smoothed_vz_mps"] = (
            estimate["smoothed_vz_mps"]
            if estimate["smoothed_vz_mps"] is not None
            else math.nan
        )
        current["ttc_sec"] = (
            estimate["ttc_sec"] if estimate["ttc_sec"] is not None else math.nan
        )
        enriched.append(current)
    return enriched


def movement_interval(rows, motion):
    valid = [
        row
        for row in rows
        if row["track_available"] and row["filtered_z_m"] != ""
    ]
    if not valid or motion == "static":
        return {row["frame"] for row in valid}
    endpoint_count = min(30, max(3, len(valid) // 5))
    start_z = float(
        np.median([float(row["filtered_z_m"]) for row in valid[:endpoint_count]])
    )
    end_z = float(
        np.median([float(row["filtered_z_m"]) for row in valid[-endpoint_count:]])
    )
    displacement = end_z - start_z
    if abs(displacement) < 0.10:
        return {row["frame"] for row in valid}
    selected = set()
    for row in valid:
        progress = (float(row["filtered_z_m"]) - start_z) / displacement
        if 0.10 <= progress <= 0.90:
            selected.add(row["frame"])
    return selected


def summarize_session(rows, motion, window_sec, threshold, deadband_mps):
    movement_frames = movement_interval(rows, motion)
    movement = [
        row
        for row in rows
        if row["frame"] in movement_frames
        and math.isfinite(row["smoothed_vz_mps"])
    ]
    detected = [row for row in rows if row["detected"]]
    accepted = sum(row["measurement_accepted"] for row in detected)
    if len(movement) >= 2:
        times = np.asarray([float(row["time_sec"]) for row in movement])
        positions = np.asarray([float(row["filtered_z_m"]) for row in movement])
        slope = float(np.polyfit(times, positions, 1)[0])
    else:
        slope = math.nan
    velocities = np.asarray([row["smoothed_vz_mps"] for row in movement])
    if motion == "approach":
        direction_correct = velocities < 0.0
        deadband_direction = velocities < -deadband_mps
    elif motion == "retreat":
        direction_correct = velocities > 0.0
        deadband_direction = velocities > deadband_mps
    else:
        direction_correct = np.abs(velocities) <= deadband_mps
        deadband_direction = direction_correct
    ttc_rows = [row for row in movement if math.isfinite(row["ttc_sec"])]
    ttc_values = [row["ttc_sec"] for row in ttc_rows]
    ttc_active_rate = len(ttc_rows) / len(movement) if movement else math.nan
    false_ttc_rate = (
        ttc_active_rate if motion in {"retreat", "static"} else 0.0
    )
    activation_delay = math.nan
    if motion == "approach" and movement and ttc_rows:
        activation_delay = max(
            0.0,
            float(ttc_rows[0]["time_sec"]) - float(movement[0]["time_sec"]),
        )
    direction_rate = float(np.mean(direction_correct)) if len(velocities) else math.nan
    deadband_rate = float(np.mean(deadband_direction)) if len(velocities) else math.nan
    if motion == "approach":
        passed = (
            direction_rate >= 0.95
            and ttc_active_rate >= 0.80
            and activation_delay <= 0.50
        )
    elif motion == "retreat":
        passed = direction_rate >= 0.95 and false_ttc_rate <= 0.01
    else:
        passed = deadband_rate >= 0.95 and false_ttc_rate <= 0.01
    return {
        "session": rows[0]["session"],
        "expected_motion": motion,
        "smoothing_window_sec": window_sec,
        "normalized_area_threshold": threshold,
        "frames": len(rows),
        "movement_frames": len(movement),
        "measurement_acceptance_rate": accepted / len(detected) if detected else math.nan,
        "z_slope_mps": slope,
        "median_smoothed_vz_mps": float(np.median(velocities)) if len(velocities) else math.nan,
        "direction_correct_rate": direction_rate,
        "deadband_direction_rate": deadband_rate,
        "ttc_active_rate": ttc_active_rate,
        "false_ttc_rate": false_ttc_rate,
        "ttc_activation_delay_sec": activation_delay,
        "median_ttc_sec": float(np.median(ttc_values)) if ttc_values else math.nan,
        "minimum_ttc_sec": min(ttc_values) if ttc_values else math.nan,
        "decision": "PASS" if passed else "FAIL",
    }, movement_frames


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate offline TTC behavior after observation gating"
    )
    parser.add_argument("--motion-input", type=Path, required=True)
    parser.add_argument("--gate-training-input", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("bird_eye_config.json"),
    )
    parser.add_argument(
        "--smoothing-window-sec", type=float, action="append"
    )
    parser.add_argument("--deadband-mps", type=float, default=0.05)
    parser.add_argument(
        "--output", type=Path, default=Path("ttc_replay_summary.csv")
    )
    parser.add_argument(
        "--details-output", type=Path, default=Path("ttc_replay_details.csv")
    )
    args = parser.parse_args()

    with args.config.open() as config_file:
        config = json.load(config_file)
    gate_training = load_observations(args.gate_training_input)
    threshold = fit_normalized_area_threshold(gate_training)
    settings = {
        "min_normalized_area": threshold,
        "max_nis": 9.210,
        "confirmation_frames": 2,
    }
    sessions = load_observations(args.motion_input)
    windows = args.smoothing_window_sec or [0.2, 0.3, 0.5]
    summaries = []
    output_details = []
    for session, source_rows in sorted(sessions.items()):
        motion = expected_motion(session)
        if motion == "excluded":
            continue
        replay_rows = [dict(row, phase_label="visible") for row in source_rows]
        tracked = replay_variant(
            replay_rows,
            config,
            "trained_range_nis99_confirm2",
            settings,
        )
        for window_sec in windows:
            enriched = add_causal_velocity_and_ttc(
                tracked, max(0.01, window_sec), args.deadband_mps
            )
            summary, motion_frames = summarize_session(
                enriched,
                motion,
                window_sec,
                threshold,
                args.deadband_mps,
            )
            summaries.append(summary)
            for row in enriched:
                output_details.append(
                    {
                        "session": session,
                        "smoothing_window_sec": window_sec,
                        "frame": row["frame"],
                        "time_sec": row["time_sec"],
                        "measurement_accepted": row["measurement_accepted"],
                        "rejection_reason": row["rejection_reason"],
                        "track_available": row["track_available"],
                        "filtered_z_m": row["filtered_z_m"],
                        "relative_vz_mps": row["relative_vz_mps"],
                        "smoothed_vz_mps": (
                            row["smoothed_vz_mps"]
                            if math.isfinite(row["smoothed_vz_mps"])
                            else ""
                        ),
                        "ttc_sec": (
                            row["ttc_sec"] if math.isfinite(row["ttc_sec"]) else ""
                        ),
                        "in_movement_interval": int(row["frame"] in motion_frames),
                    }
                )
            print(
                f'{session:12s} window={window_sec:.1f}s '
                f'slope={summary["z_slope_mps"]:+.3f} '
                f'vz={summary["median_smoothed_vz_mps"]:+.3f} '
                f'direction={summary["direction_correct_rate"]:.1%} '
                f'TTC active/false={summary["ttc_active_rate"]:.1%}/'
                f'{summary["false_ttc_rate"]:.1%} '
                f'{summary["decision"]}'
            )

    for path, fields, rows in (
        (args.output, SUMMARY_FIELDS, summaries),
        (args.details_output, DETAIL_FIELDS, output_details),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as output_file:
            writer = csv.DictWriter(
                output_file, fieldnames=fields, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
    print(f"Summary saved: {args.output.resolve()}")
    print(f"Details saved: {args.details_output.resolve()}")


if __name__ == "__main__":
    main()
