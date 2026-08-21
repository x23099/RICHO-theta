#!/usr/bin/env python3
"""Evaluate labelled position trials from recorded detections.csv files."""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from pathlib import Path

from diagnose_lateral_gate_asymmetry import load_sessions


POSITION_PATTERN = re.compile(
    r"(?:^|_)x(?P<x>[+-]?\d+(?:\.\d+)?)m_z(?P<z>\d+(?:\.\d+)?)m(?:_|$)"
)
LEGACY_POSITION_PATTERN = re.compile(
    r"(?:^|_)(?:cal_|holdout_)?x(?P<sign>[mp])(?P<x>\d+(?:\.\d+)?)_z"
    r"(?P<z>\d+(?:\.\d+)?)(?:_|$)"
)
OUTPUT_FIELDS = [
    "session",
    "expected_x_m",
    "expected_z_m",
    "frames",
    "duration_sec",
    "detection_rate",
    "measurement_acceptance_rate",
    "track_rate",
    "odom_available_rate",
    "median_x_m",
    "median_z_m",
    "error_x_m",
    "error_z_m",
    "position_error_m",
    "std_x_m",
    "std_z_m",
]


def parse_expected_position(label):
    match = POSITION_PATTERN.search(label)
    if match is not None:
        return float(match.group("x")), float(match.group("z"))
    match = LEGACY_POSITION_PATTERN.search(label)
    if match is None:
        return None
    sign = -1.0 if match.group("sign") == "m" else 1.0
    return sign * float(match.group("x")), float(match.group("z"))


def _number(row, key):
    try:
        number = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _flag(row, key):
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def _rate(numerator, denominator):
    return numerator / denominator if denominator else math.nan


def evaluate_position_rows(label, rows):
    expected = parse_expected_position(label)
    if expected is None:
        return None
    detected = [row for row in rows if _flag(row, "detected")]
    accepted = [row for row in detected if _flag(row, "measurement_accepted")]
    tracked = [row for row in rows if _flag(row, "track_available")]
    odom = [row for row in rows if _flag(row, "odom_available")]
    positions = [
        (x, z)
        for row in detected
        if (x := _number(row, "x_m")) is not None
        and (z := _number(row, "z_m")) is not None
    ]
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
    duration = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0.0
    if positions:
        x_values = [position[0] for position in positions]
        z_values = [position[1] for position in positions]
        median_x = statistics.median(x_values)
        median_z = statistics.median(z_values)
        std_x = statistics.pstdev(x_values)
        std_z = statistics.pstdev(z_values)
        error_x = median_x - expected[0]
        error_z = median_z - expected[1]
        position_error = math.hypot(error_x, error_z)
    else:
        median_x = median_z = std_x = std_z = math.nan
        error_x = error_z = position_error = math.nan
    return {
        "session": label,
        "expected_x_m": expected[0],
        "expected_z_m": expected[1],
        "frames": len(rows),
        "duration_sec": duration,
        "detection_rate": _rate(len(detected), len(rows)),
        "measurement_acceptance_rate": _rate(len(accepted), len(detected)),
        "track_rate": _rate(len(tracked), len(rows)),
        "odom_available_rate": _rate(len(odom), len(rows)),
        "median_x_m": median_x,
        "median_z_m": median_z,
        "error_x_m": error_x,
        "error_z_m": error_z,
        "position_error_m": position_error,
        "std_x_m": std_x,
        "std_z_m": std_z,
    }


def evaluate_inputs(inputs):
    results = []
    for label, _source, _metadata, rows in load_sessions(inputs):
        result = evaluate_position_rows(label, rows)
        if result is not None:
            results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate labelled position trials in directories or tar archives"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    results = evaluate_inputs(args.input)
    if not results:
        parser.error("no session name contains a supported x/z position label")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(results)

    errors = [row["position_error_m"] for row in results]
    print(f"Trials: {len(results)}")
    print(f"Mean position error: {statistics.mean(errors):.4f} m")
    print(f"Maximum position error: {max(errors):.4f} m")
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
