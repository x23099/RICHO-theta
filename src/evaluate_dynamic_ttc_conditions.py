#!/usr/bin/env python3
"""Evaluate dynamic TTC recordings using one versioned condition profile."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path

from diagnose_lateral_gate_asymmetry import load_sessions
from evaluate_collision_hysteresis_replay import replay_rows


DEFAULT_PROFILE = Path(__file__).with_name("dynamic_ttc_evaluation_profile.json")
NOMINAL_SPEED_PATTERN = re.compile(r"(?:^|_)v(\d+)p(\d+)(?:_|$)")
FIELDS = [
    "session",
    "experiment_label",
    "expected_motion",
    "nominal_speed_mps",
    "frames",
    "motion_frames",
    "accuracy_interval_frames",
    "detection_rate",
    "track_rate",
    "odom_available_rate",
    "odom_speed_p90_mps",
    "nominal_speed_error_mps",
    "nominal_speed_error_limit_mps",
    "abs_odom_angular_p95_radps",
    "median_abs_odom_speed_mps",
    "speed_mae_limit_mps",
    "direction_correct_rate",
    "relative_speed_mae_mps",
    "ttc_expected_frames",
    "ttc_active_rate",
    "ttc_activation_delay_sec",
    "false_ttc_rate",
    "raw_warning_frames",
    "filtered_warning_frames",
    "warning_hold_frames",
    "unknown_frames",
    "first_raw_warning_ttc_sec",
    "first_raw_warning_z_m",
    "maximum_warning_entry_delay_sec",
    "path_while_forward_after_warning_frames",
    "critical_frames",
    "final_state",
    "decision",
    "reasons",
]
REQUIRED_PROFILE_FIELDS = {
    "schema_version",
    "motion_deadband_mps",
    "calibration_z_min_m",
    "calibration_z_max_m",
    "minimum_accuracy_interval_frames",
    "minimum_detection_rate",
    "minimum_track_rate",
    "minimum_odom_available_rate",
    "nominal_speed_absolute_tolerance_mps",
    "nominal_speed_relative_tolerance",
    "maximum_abs_odom_angular_p95_radps",
    "minimum_direction_correct_rate",
    "speed_mae_absolute_limit_mps",
    "speed_mae_relative_limit",
    "minimum_ttc_active_rate",
    "maximum_ttc_activation_delay_sec",
    "maximum_false_ttc_rate",
    "warning_required_nominal_speed_mps",
    "warning_ttc_sec",
    "critical_ttc_sec",
    "warning_exit_ttc_sec",
    "warning_confirm_frames",
    "warning_clear_frames",
    "warning_hold_sec",
    "forward_motion_threshold_mps",
    "minimum_warning_onset_ttc_sec",
    "maximum_warning_entry_delay_sec",
    "minimum_filtered_warning_frames",
    "minimum_warning_hold_frames",
    "maximum_post_warning_path_while_forward_frames",
    "maximum_critical_frames",
    "expected_final_state",
}


def _number(row, key):
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _flag(row, key):
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def _rate(count, total):
    return count / total if total else math.nan


def _timestamp(row):
    value = _number(row, "monotonic_time_sec")
    return value if value is not None else _number(row, "time_sec")


def _nearest_rank(values, proportion):
    if not values:
        return math.nan
    ordered = sorted(values)
    index = max(0, math.ceil(float(proportion) * len(ordered)) - 1)
    return ordered[index]


def expected_motion(label: str) -> str:
    if label.startswith("approach_"):
        return "approach"
    if label.startswith("retreat_"):
        return "retreat"
    return "excluded"


def nominal_speed_mps(label: str):
    match = NOMINAL_SPEED_PATTERN.search(label)
    if match is None:
        return None
    return float(f"{match.group(1)}.{match.group(2)}")


def load_profile(path: Path) -> dict:
    with Path(path).open() as input_file:
        profile = json.load(input_file)
    missing = sorted(REQUIRED_PROFILE_FIELDS - set(profile))
    unknown = sorted(set(profile) - REQUIRED_PROFILE_FIELDS)
    if missing or unknown:
        raise ValueError(
            f"invalid dynamic TTC profile: missing={missing}, unknown={unknown}"
        )
    if profile["schema_version"] != 1:
        raise ValueError("unsupported dynamic TTC profile schema_version")
    numeric_fields = REQUIRED_PROFILE_FIELDS - {
        "schema_version",
        "expected_final_state",
    }
    try:
        numeric_values = {field: float(profile[field]) for field in numeric_fields}
    except (TypeError, ValueError) as error:
        raise ValueError("dynamic TTC profile values must be numeric") from error
    if any(not math.isfinite(value) for value in numeric_values.values()):
        raise ValueError("dynamic TTC profile values must be finite")
    if any(value < 0.0 for value in numeric_values.values()):
        raise ValueError("dynamic TTC profile values must be nonnegative")
    if not (
        0.0 < float(profile["calibration_z_min_m"])
        < float(profile["calibration_z_max_m"])
    ):
        raise ValueError("calibration z range is invalid")
    rate_fields = (
        "minimum_detection_rate",
        "minimum_track_rate",
        "minimum_odom_available_rate",
        "minimum_direction_correct_rate",
        "speed_mae_relative_limit",
        "minimum_ttc_active_rate",
        "maximum_false_ttc_rate",
        "nominal_speed_relative_tolerance",
    )
    if any(not 0.0 <= numeric_values[field] <= 1.0 for field in rate_fields):
        raise ValueError("dynamic TTC profile rates must be in [0, 1]")
    if not (
        0.0
        < numeric_values["critical_ttc_sec"]
        < numeric_values["minimum_warning_onset_ttc_sec"]
        <= numeric_values["warning_ttc_sec"]
        < numeric_values["warning_exit_ttc_sec"]
    ):
        raise ValueError("dynamic TTC warning thresholds are inconsistent")
    integer_fields = (
        "minimum_accuracy_interval_frames",
        "warning_confirm_frames",
        "warning_clear_frames",
        "minimum_filtered_warning_frames",
        "minimum_warning_hold_frames",
        "maximum_post_warning_path_while_forward_frames",
        "maximum_critical_frames",
    )
    if any(not numeric_values[field].is_integer() for field in integer_fields):
        raise ValueError("dynamic TTC profile frame counts must be integers")
    if int(profile["minimum_accuracy_interval_frames"]) < 1:
        raise ValueError("minimum_accuracy_interval_frames must be positive")
    if int(profile["warning_confirm_frames"]) < 1 or int(
        profile["warning_clear_frames"]
    ) < 1:
        raise ValueError("warning confirmation frame counts must be positive")
    if numeric_values["forward_motion_threshold_mps"] > numeric_values[
        "motion_deadband_mps"
    ]:
        raise ValueError("forward motion threshold must not exceed motion deadband")
    if profile["expected_final_state"] not in {
        "CLEAR",
        "PATH",
        "WARNING",
        "WARNING_HOLD",
        "UNKNOWN",
        "CRITICAL",
    }:
        raise ValueError("expected_final_state is invalid")
    return profile


def _hysteresis_overrides(profile: dict) -> dict:
    return {
        "blue_collision_warning_ttc_sec": profile["warning_ttc_sec"],
        "blue_collision_critical_ttc_sec": profile["critical_ttc_sec"],
        "blue_collision_warning_exit_ttc_sec": profile["warning_exit_ttc_sec"],
        "blue_collision_warning_confirm_frames": profile[
            "warning_confirm_frames"
        ],
        "blue_collision_warning_clear_frames": profile["warning_clear_frames"],
        "blue_collision_warning_hold_sec": profile["warning_hold_sec"],
        "blue_collision_forward_motion_threshold_mps": profile[
            "forward_motion_threshold_mps"
        ],
    }


def evaluate_session(
    label: str,
    session_name: str,
    metadata: dict,
    rows: list[dict],
    profile: dict,
) -> dict:
    motion = expected_motion(label)
    nominal_speed = nominal_speed_mps(label)
    if motion == "excluded" or nominal_speed is None:
        raise ValueError(f"unsupported dynamic experiment label: {label!r}")

    deadband = float(profile["motion_deadband_mps"])
    z_min = float(profile["calibration_z_min_m"])
    z_max = float(profile["calibration_z_max_m"])
    warning_required = (
        motion == "approach"
        and nominal_speed >= float(profile["warning_required_nominal_speed_mps"])
    )
    hysteresis = replay_rows(
        label, metadata, rows, _hysteresis_overrides(profile)
    )
    odom_rows = [row for row in rows if _flag(row, "odom_available")]
    if motion == "approach":
        motion_rows = [
            row
            for row in odom_rows
            if (_number(row, "odom_linear_mps") or 0.0) > deadband
        ]
    else:
        motion_rows = [
            row
            for row in odom_rows
            if (_number(row, "odom_linear_mps") or 0.0) < -deadband
        ]
    accuracy_rows = [
        row
        for row in motion_rows
        if _flag(row, "track_available")
        and _flag(row, "calibration_valid")
        and (z := _number(row, "filtered_z_m")) is not None
        and z_min <= z <= z_max
        and _number(row, "smoothed_vz_mps") is not None
    ]
    first_warning_time = hysteresis["first_raw_warning_sec"]
    if warning_required and first_warning_time is not None:
        def before_first_warning(row):
            timestamp = _timestamp(row)
            return timestamp is not None and timestamp <= first_warning_time

        accuracy_rows = [
            row for row in accuracy_rows if before_first_warning(row)
        ]

    direction_flags = []
    speed_errors = []
    odom_speeds = []
    for row in accuracy_rows:
        odom_speed = _number(row, "odom_linear_mps")
        smoothed_vz = _number(row, "smoothed_vz_mps")
        direction_flags.append(smoothed_vz * odom_speed < 0.0)
        speed_errors.append(abs(-smoothed_vz - odom_speed))
        odom_speeds.append(abs(odom_speed))
    odom_angular_speeds = [
        abs(value)
        for row in motion_rows
        if (value := _number(row, "odom_angular_radps")) is not None
    ]

    median_odom_speed = statistics.median(odom_speeds) if odom_speeds else math.nan
    odom_speed_p90 = _nearest_rank(
        [abs(_number(row, "odom_linear_mps")) for row in motion_rows], 0.90
    )
    nominal_speed_error = abs(odom_speed_p90 - nominal_speed)
    nominal_speed_error_limit = max(
        float(profile["nominal_speed_absolute_tolerance_mps"]),
        float(profile["nominal_speed_relative_tolerance"]) * nominal_speed,
    )
    abs_odom_angular_p95 = _nearest_rank(odom_angular_speeds, 0.95)
    speed_mae_limit = (
        max(
            float(profile["speed_mae_absolute_limit_mps"]),
            float(profile["speed_mae_relative_limit"]) * median_odom_speed,
        )
        if math.isfinite(median_odom_speed)
        else math.nan
    )
    direction_rate = _rate(sum(direction_flags), len(direction_flags))
    speed_mae = (
        sum(speed_errors) / len(speed_errors) if speed_errors else math.nan
    )

    if motion == "approach":
        ttc_expected_rows = [
            row
            for row in accuracy_rows
            if (_number(row, "smoothed_vz_mps") or 0.0) < -deadband
        ]
        ttc_active_rate = _rate(
            sum(_number(row, "ttc_sec") is not None for row in ttc_expected_rows),
            len(ttc_expected_rows),
        )
        first_motion_time = _timestamp(accuracy_rows[0]) if accuracy_rows else None
        active_rows = [
            row for row in accuracy_rows if _number(row, "ttc_sec") is not None
        ]
        first_ttc_time = _timestamp(active_rows[0]) if active_rows else None
        activation_delay = (
            max(0.0, first_ttc_time - first_motion_time)
            if first_motion_time is not None and first_ttc_time is not None
            else math.nan
        )
        false_ttc_rate = 0.0
    else:
        ttc_expected_rows = []
        ttc_active_rate = math.nan
        activation_delay = math.nan
        false_ttc_rate = _rate(
            sum(_number(row, "ttc_sec") is not None for row in accuracy_rows),
            len(accuracy_rows),
        )
    critical_frames = hysteresis["filtered_critical_frames"]
    detection_rate = _rate(sum(_flag(row, "detected") for row in rows), len(rows))
    track_rate = _rate(
        sum(_flag(row, "track_available") for row in rows), len(rows)
    )
    odom_rate = _rate(len(odom_rows), len(rows))

    reasons = []

    def require_min(name, value, minimum):
        if not math.isfinite(value) or value < float(minimum):
            reasons.append(f"{name}={value} < {minimum}")

    def require_max(name, value, maximum):
        if not math.isfinite(value) or value > float(maximum):
            reasons.append(f"{name}={value} > {maximum}")

    require_min("detection_rate", detection_rate, profile["minimum_detection_rate"])
    require_min("track_rate", track_rate, profile["minimum_track_rate"])
    require_min(
        "odom_available_rate", odom_rate, profile["minimum_odom_available_rate"]
    )
    require_max(
        "nominal_speed_error_mps",
        nominal_speed_error,
        nominal_speed_error_limit,
    )
    require_max(
        "abs_odom_angular_p95_radps",
        abs_odom_angular_p95,
        profile["maximum_abs_odom_angular_p95_radps"],
    )
    require_min(
        "accuracy_interval_frames",
        float(len(accuracy_rows)),
        profile["minimum_accuracy_interval_frames"],
    )
    require_min(
        "direction_correct_rate",
        direction_rate,
        profile["minimum_direction_correct_rate"],
    )
    require_max("relative_speed_mae_mps", speed_mae, speed_mae_limit)

    if motion == "approach":
        require_min(
            "ttc_active_rate", ttc_active_rate, profile["minimum_ttc_active_rate"]
        )
        require_max(
            "ttc_activation_delay_sec",
            activation_delay,
            profile["maximum_ttc_activation_delay_sec"],
        )
    else:
        require_max(
            "false_ttc_rate", false_ttc_rate, profile["maximum_false_ttc_rate"]
        )

    if warning_required:
        require_min(
            "filtered_warning_frames",
            float(hysteresis["filtered_warning_frames"]),
            profile["minimum_filtered_warning_frames"],
        )
        require_min(
            "warning_hold_frames",
            float(hysteresis["warning_hold_frames"]),
            profile["minimum_warning_hold_frames"],
        )
        require_min(
            "first_raw_warning_ttc_sec",
            hysteresis["first_raw_warning_ttc_sec"] or math.nan,
            profile["minimum_warning_onset_ttc_sec"],
        )
        require_max(
            "first_raw_warning_ttc_sec",
            hysteresis["first_raw_warning_ttc_sec"] or math.nan,
            profile["warning_ttc_sec"],
        )
        require_min(
            "first_raw_warning_z_m",
            hysteresis["first_raw_warning_z_m"] or math.nan,
            profile["calibration_z_min_m"],
        )
        require_max(
            "maximum_warning_entry_delay_sec",
            hysteresis["maximum_warning_entry_delay_sec"],
            profile["maximum_warning_entry_delay_sec"],
        )
        require_max(
            "path_while_forward_after_warning_frames",
            float(hysteresis["path_while_forward_after_warning_frames"]),
            profile["maximum_post_warning_path_while_forward_frames"],
        )
    else:
        require_max("raw_warning_frames", float(hysteresis["raw_warning_frames"]), 0)
        require_max(
            "filtered_warning_frames",
            float(hysteresis["filtered_warning_frames"]),
            0,
        )
    require_max(
        "critical_frames", float(critical_frames), profile["maximum_critical_frames"]
    )
    if hysteresis["final_state"] != profile["expected_final_state"]:
        reasons.append(
            f"final_state={hysteresis['final_state']!r} != "
            f"{profile['expected_final_state']!r}"
        )

    return {
        "session": session_name,
        "experiment_label": label,
        "expected_motion": motion,
        "nominal_speed_mps": nominal_speed,
        "frames": len(rows),
        "motion_frames": len(motion_rows),
        "accuracy_interval_frames": len(accuracy_rows),
        "detection_rate": detection_rate,
        "track_rate": track_rate,
        "odom_available_rate": odom_rate,
        "odom_speed_p90_mps": odom_speed_p90,
        "nominal_speed_error_mps": nominal_speed_error,
        "nominal_speed_error_limit_mps": nominal_speed_error_limit,
        "abs_odom_angular_p95_radps": abs_odom_angular_p95,
        "median_abs_odom_speed_mps": median_odom_speed,
        "speed_mae_limit_mps": speed_mae_limit,
        "direction_correct_rate": direction_rate,
        "relative_speed_mae_mps": speed_mae,
        "ttc_expected_frames": len(ttc_expected_rows),
        "ttc_active_rate": ttc_active_rate,
        "ttc_activation_delay_sec": activation_delay,
        "false_ttc_rate": false_ttc_rate,
        "raw_warning_frames": hysteresis["raw_warning_frames"],
        "filtered_warning_frames": hysteresis["filtered_warning_frames"],
        "warning_hold_frames": hysteresis["warning_hold_frames"],
        "unknown_frames": hysteresis["unknown_frames"],
        "first_raw_warning_ttc_sec": hysteresis["first_raw_warning_ttc_sec"],
        "first_raw_warning_z_m": hysteresis["first_raw_warning_z_m"],
        "maximum_warning_entry_delay_sec": hysteresis[
            "maximum_warning_entry_delay_sec"
        ],
        "path_while_forward_after_warning_frames": hysteresis[
            "path_while_forward_after_warning_frames"
        ],
        "critical_frames": critical_frames,
        "final_state": hysteresis["final_state"],
        "decision": "FAIL" if reasons else "PASS",
        "reasons": "; ".join(reasons),
    }


def evaluate_inputs(inputs: list[Path], profile: dict) -> list[dict]:
    results = []
    for label, source, metadata, rows in load_sessions(inputs):
        motion = expected_motion(label)
        if motion == "excluded":
            continue
        session_name = (
            source.rsplit("::", 1)[-1]
            if "::" in source
            else Path(source).name
        )
        results.append(
            evaluate_session(label, session_name, metadata, rows, profile)
        )
    return results


def write_results(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate dynamic TTC trials with a fixed versioned profile"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        profile = load_profile(args.profile)
        results = evaluate_inputs(args.input, profile)
    except (FileNotFoundError, OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    if not results:
        parser.error("no supported approach or retreat session was found")
    write_results(args.output, results)
    failed = [row for row in results if row["decision"] == "FAIL"]
    for row in results:
        print(
            f"{row['experiment_label']}: {row['decision']} "
            f"direction={row['direction_correct_rate']:.2%}, "
            f"speed_MAE={row['relative_speed_mae_mps']:.4f}, "
            f"TTC_active={row['ttc_active_rate']}"
        )
        if row["reasons"]:
            print(f"  {row['reasons']}")
    print(f"PASS: {len(results) - len(failed)}/{len(results)}")
    print(f"Results saved: {args.output.resolve()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
