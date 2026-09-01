#!/usr/bin/env python3
"""Replay collision-warning hysteresis from recorded live-trial CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from collision_risk import CollisionRiskHysteresis, classify_candidate_risk
from diagnose_lateral_gate_asymmetry import load_sessions as load_recording_sessions


FIELDS = [
    "session",
    "frames",
    "raw_warning_frames",
    "confirmable_warning_frames",
    "longest_raw_warning_run_frames",
    "longest_confirmable_warning_run_frames",
    "raw_warning_track_unavailable_frames",
    "raw_warning_track_predicted_frames",
    "raw_warning_measurement_rejected_frames",
    "raw_warning_calibration_invalid_frames",
    "raw_warning_not_forward_frames",
    "minimum_ttc_threshold_for_confirmation_sec",
    "filtered_warning_frames",
    "warning_hold_frames",
    "unknown_frames",
    "raw_critical_frames",
    "filtered_critical_frames",
    "first_raw_warning_sec",
    "first_raw_warning_ttc_sec",
    "first_raw_warning_z_m",
    "first_filtered_warning_sec",
    "first_filtered_warning_ttc_sec",
    "first_filtered_warning_z_m",
    "maximum_warning_entry_delay_sec",
    "path_while_forward_after_warning_frames",
    "final_state",
]


def _number(row, key):
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _flag(row, key):
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def _parameters(metadata, overrides=None):
    parameters = metadata.get("parameters", {})
    result = dict(parameters)
    if overrides:
        result.update(overrides)
    return result


def replay_session(session_dir, overrides=None):
    session_dir = Path(session_dir)
    with (session_dir / "metadata.json").open() as metadata_file:
        metadata = json.load(metadata_file)
    with (session_dir / "detections.csv").open(newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    return replay_rows(session_dir.name, metadata, rows, overrides)


def replay_rows(session, metadata, rows, overrides=None):
    parameters = _parameters(metadata, overrides)
    state_filter = CollisionRiskHysteresis(
        warning_ttc_sec=parameters.get(
            "blue_collision_warning_ttc_sec", 4.0
        ),
        warning_exit_ttc_sec=parameters.get(
            "blue_collision_warning_exit_ttc_sec", 5.0
        ),
        warning_confirm_frames=parameters.get(
            "blue_collision_warning_confirm_frames", 3
        ),
        warning_clear_frames=parameters.get(
            "blue_collision_warning_clear_frames", 3
        ),
        warning_hold_sec=parameters.get(
            "blue_collision_warning_hold_sec", 0.8
        ),
    )
    motion_threshold = float(
        parameters.get("blue_collision_forward_motion_threshold_mps", 0.03)
    )
    output_levels = []
    raw_levels = []
    timestamps = []
    moving_forward_flags = []
    confirmable_warning_flags = []
    raw_warning_invalid_counts = {
        "raw_warning_track_unavailable_frames": 0,
        "raw_warning_track_predicted_frames": 0,
        "raw_warning_measurement_rejected_frames": 0,
        "raw_warning_calibration_invalid_frames": 0,
        "raw_warning_not_forward_frames": 0,
    }
    confirmable_ttc_run = []
    minimum_ttc_threshold_for_confirmation = math.inf
    first_raw_warning_sec = None
    first_raw_warning_ttc_sec = None
    first_raw_warning_z_m = None
    first_filtered_warning_sec = None
    first_filtered_warning_ttc_sec = None
    first_filtered_warning_z_m = None
    warning_entry_delays = []
    pending_raw_warning_sec = None
    warning_seen = False
    path_while_forward_after_warning = 0
    for row in rows:
        timestamp = _number(row, "monotonic_time_sec")
        if timestamp is None:
            timestamp = _number(row, "time_sec")
        if timestamp is None:
            continue
        ttc_sec = _number(row, "ttc_sec")
        in_corridor = _flag(row, "path_in_collision_corridor")
        raw_level = classify_candidate_risk(
            in_corridor,
            ttc_sec,
            warning_ttc_sec=parameters.get(
                "blue_collision_warning_ttc_sec", 4.0
            ),
            critical_ttc_sec=parameters.get(
                "blue_collision_critical_ttc_sec", 2.0
            ),
        )
        odom_linear = _number(row, "odom_linear_mps")
        cmd_linear = _number(row, "cmd_linear_mps") or 0.0
        linear_mps = odom_linear if odom_linear is not None else cmd_linear
        moving_forward = linear_mps > motion_threshold
        measurement_valid = (
            _flag(row, "track_available")
            and not _flag(row, "track_predicted")
            and _flag(row, "measurement_accepted")
            and _flag(row, "calibration_valid")
        )
        state = state_filter.update(
            raw_level=raw_level,
            timestamp_sec=timestamp,
            measurement_valid=measurement_valid,
            moving_forward=moving_forward,
            in_collision_corridor=in_corridor,
            ttc_sec=ttc_sec,
        )
        output_level = state["risk_level"]
        confirmable_warning = (
            raw_level in {"WARNING", "CRITICAL"}
            and measurement_valid
            and moving_forward
        )
        confirmation_base = (
            measurement_valid
            and moving_forward
            and in_corridor
            and ttc_sec is not None
        )
        if confirmation_base:
            confirmable_ttc_run.append(ttc_sec)
            confirm_frames = state_filter.warning_confirm_frames
            if len(confirmable_ttc_run) >= confirm_frames:
                required_threshold = max(confirmable_ttc_run[-confirm_frames:])
                minimum_ttc_threshold_for_confirmation = min(
                    minimum_ttc_threshold_for_confirmation,
                    required_threshold,
                )
        else:
            confirmable_ttc_run.clear()
        if raw_level in {"WARNING", "CRITICAL"}:
            raw_warning_invalid_counts["raw_warning_track_unavailable_frames"] += (
                not _flag(row, "track_available")
            )
            raw_warning_invalid_counts["raw_warning_track_predicted_frames"] += (
                _flag(row, "track_predicted")
            )
            raw_warning_invalid_counts["raw_warning_measurement_rejected_frames"] += (
                not _flag(row, "measurement_accepted")
            )
            raw_warning_invalid_counts["raw_warning_calibration_invalid_frames"] += (
                not _flag(row, "calibration_valid")
            )
            raw_warning_invalid_counts["raw_warning_not_forward_frames"] += (
                not moving_forward
            )
        if raw_level in {"WARNING", "CRITICAL"}:
            if first_raw_warning_sec is None:
                first_raw_warning_sec = timestamp
                first_raw_warning_ttc_sec = ttc_sec
                first_raw_warning_z_m = _number(row, "filtered_z_m")
            if pending_raw_warning_sec is None:
                pending_raw_warning_sec = timestamp
        else:
            pending_raw_warning_sec = None
        if output_level in {"WARNING", "CRITICAL"}:
            if first_filtered_warning_sec is None:
                first_filtered_warning_sec = timestamp
                first_filtered_warning_ttc_sec = ttc_sec
                first_filtered_warning_z_m = _number(row, "filtered_z_m")
            if pending_raw_warning_sec is not None:
                warning_entry_delays.append(timestamp - pending_raw_warning_sec)
                pending_raw_warning_sec = None
            warning_seen = True
        elif warning_seen and output_level == "PATH" and moving_forward:
            path_while_forward_after_warning += 1
        raw_levels.append(raw_level)
        output_levels.append(output_level)
        timestamps.append(timestamp)
        moving_forward_flags.append(moving_forward)
        confirmable_warning_flags.append(confirmable_warning)

    def longest_true_run(flags):
        longest = 0
        current = 0
        for flag in flags:
            current = current + 1 if flag else 0
            longest = max(longest, current)
        return longest

    raw_warning_flags = [
        value in {"WARNING", "CRITICAL"} for value in raw_levels
    ]

    return {
        "session": session,
        "frames": len(output_levels),
        "raw_warning_frames": sum(raw_warning_flags),
        "confirmable_warning_frames": sum(confirmable_warning_flags),
        "longest_raw_warning_run_frames": longest_true_run(raw_warning_flags),
        "longest_confirmable_warning_run_frames": longest_true_run(
            confirmable_warning_flags
        ),
        **raw_warning_invalid_counts,
        "minimum_ttc_threshold_for_confirmation_sec": (
            minimum_ttc_threshold_for_confirmation
            if math.isfinite(minimum_ttc_threshold_for_confirmation)
            else math.nan
        ),
        "filtered_warning_frames": sum(
            value in {"WARNING", "WARNING_HOLD", "CRITICAL"}
            for value in output_levels
        ),
        "warning_hold_frames": sum(
            value == "WARNING_HOLD" for value in output_levels
        ),
        "unknown_frames": sum(value == "UNKNOWN" for value in output_levels),
        "raw_critical_frames": sum(value == "CRITICAL" for value in raw_levels),
        "filtered_critical_frames": sum(
            value == "CRITICAL" for value in output_levels
        ),
        "first_raw_warning_sec": first_raw_warning_sec,
        "first_raw_warning_ttc_sec": first_raw_warning_ttc_sec,
        "first_raw_warning_z_m": first_raw_warning_z_m,
        "first_filtered_warning_sec": first_filtered_warning_sec,
        "first_filtered_warning_ttc_sec": first_filtered_warning_ttc_sec,
        "first_filtered_warning_z_m": first_filtered_warning_z_m,
        "maximum_warning_entry_delay_sec": (
            max(warning_entry_delays) if warning_entry_delays else math.nan
        ),
        "path_while_forward_after_warning_frames": (
            path_while_forward_after_warning
        ),
        "final_state": output_levels[-1] if output_levels else "",
    }


def find_sessions(inputs):
    sessions = []
    for input_path in inputs:
        input_path = Path(input_path)
        if (input_path / "detections.csv").exists():
            sessions.append(input_path)
        elif input_path.is_dir():
            sessions.extend(
                path.parent for path in input_path.rglob("detections.csv")
            )
    return sorted(set(sessions))


def main():
    parser = argparse.ArgumentParser(
        description="Replay finite collision-warning hysteresis"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        sessions = load_recording_sessions(args.input)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    if not sessions:
        parser.error("no recording session containing detections.csv was found")
    overrides = {
        "blue_collision_warning_exit_ttc_sec": 5.0,
        "blue_collision_warning_confirm_frames": 3,
        "blue_collision_warning_clear_frames": 3,
        "blue_collision_warning_hold_sec": 0.8,
        "blue_collision_forward_motion_threshold_mps": 0.03,
    }
    results = [
        replay_rows(label, metadata, rows, overrides)
        for label, _source, metadata, rows in sessions
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)
    for row in results:
        print(
            f'{row["session"]}: raw_warning={row["raw_warning_frames"]}, '
            f'filtered_warning={row["filtered_warning_frames"]}, '
            f'hold={row["warning_hold_frames"]}, '
            f'unknown={row["unknown_frames"]}, '
            f'post_warning_path_while_forward='
            f'{row["path_while_forward_after_warning_frames"]}'
        )
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
