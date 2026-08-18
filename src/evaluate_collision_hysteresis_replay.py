#!/usr/bin/env python3
"""Replay collision-warning hysteresis from recorded live-trial CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from collision_risk import CollisionRiskHysteresis, classify_candidate_risk


FIELDS = [
    "session",
    "frames",
    "raw_warning_frames",
    "filtered_warning_frames",
    "warning_hold_frames",
    "unknown_frames",
    "first_raw_warning_sec",
    "first_filtered_warning_sec",
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


def _load_parameters(session_dir, overrides=None):
    with (Path(session_dir) / "metadata.json").open() as metadata_file:
        parameters = json.load(metadata_file).get("parameters", {})
    result = dict(parameters)
    if overrides:
        result.update(overrides)
    return result


def replay_session(session_dir, overrides=None):
    session_dir = Path(session_dir)
    parameters = _load_parameters(session_dir, overrides)
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
    with (session_dir / "detections.csv").open(newline="") as input_file:
        rows = list(csv.DictReader(input_file))

    output_levels = []
    raw_levels = []
    timestamps = []
    moving_forward_flags = []
    first_raw_warning_sec = None
    first_filtered_warning_sec = None
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
        if raw_level in {"WARNING", "CRITICAL"}:
            if first_raw_warning_sec is None:
                first_raw_warning_sec = timestamp
            if pending_raw_warning_sec is None:
                pending_raw_warning_sec = timestamp
        else:
            pending_raw_warning_sec = None
        if output_level in {"WARNING", "CRITICAL"}:
            if first_filtered_warning_sec is None:
                first_filtered_warning_sec = timestamp
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

    return {
        "session": session_dir.name,
        "frames": len(output_levels),
        "raw_warning_frames": sum(
            value in {"WARNING", "CRITICAL"} for value in raw_levels
        ),
        "filtered_warning_frames": sum(
            value in {"WARNING", "WARNING_HOLD", "CRITICAL"}
            for value in output_levels
        ),
        "warning_hold_frames": sum(
            value == "WARNING_HOLD" for value in output_levels
        ),
        "unknown_frames": sum(value == "UNKNOWN" for value in output_levels),
        "first_raw_warning_sec": first_raw_warning_sec,
        "first_filtered_warning_sec": first_filtered_warning_sec,
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
    sessions = find_sessions(args.input)
    if not sessions:
        parser.error("no recording directory containing detections.csv was found")
    overrides = {
        "blue_collision_warning_exit_ttc_sec": 5.0,
        "blue_collision_warning_confirm_frames": 3,
        "blue_collision_warning_clear_frames": 3,
        "blue_collision_warning_hold_sec": 0.8,
        "blue_collision_forward_motion_threshold_mps": 0.03,
    }
    results = [replay_session(session, overrides) for session in sessions]
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
