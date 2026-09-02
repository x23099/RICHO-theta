#!/usr/bin/env python3
"""Replay recorded observations across Kalman and TTC parameter candidates."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path

from diagnose_lateral_gate_asymmetry import load_sessions
from evaluate_dynamic_ttc_conditions import nominal_speed_mps
from obstacle_tracking import BlueObstacleTracker, CausalTtcEstimator


DETAIL_FIELDS = [
    "process_accel_std_mps2",
    "ttc_deadband_mps",
    "experiment_label",
    "source",
    "motion",
    "nominal_speed_mps",
    "frames",
    "track_frames",
    "motion_frames",
    "stable_response_delay_sec",
    "steady_speed_mae_mps",
    "ttc_active_rate",
    "false_ttc_rate",
]

SUMMARY_FIELDS = [
    "process_accel_std_mps2",
    "ttc_deadband_mps",
    "sessions",
    "approach_sessions",
    "retreat_sessions",
    "static_sessions",
    "max_approach_v0p10_response_delay_sec",
    "max_approach_v0p20_response_delay_sec",
    "max_approach_speed_mae_mps",
    "max_retreat_false_ttc_rate",
    "max_static_false_ttc_rate",
]


def _number(row, key):
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _flag(row, key):
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def _timestamp(row):
    value = _number(row, "monotonic_time_sec")
    return value if value is not None else _number(row, "time_sec")


def classify_motion(label, rows, motion_threshold_mps):
    if label.startswith("approach_"):
        return "approach"
    if label.startswith("retreat_"):
        return "retreat"
    odom = [
        abs(value)
        for row in rows
        if (value := _number(row, "odom_linear_mps")) is not None
    ]
    return "static" if not odom or max(odom) <= motion_threshold_mps else "excluded"


def _first_stable_index(values, predicate, stable_frames):
    consecutive = 0
    for index, value in enumerate(values):
        consecutive = consecutive + 1 if predicate(value) else 0
        if consecutive >= stable_frames:
            return index - stable_frames + 1
    return None


def replay_candidate(
    rows,
    process_accel_std_mps2,
    ttc_deadband_mps,
    velocity_window_sec=0.3,
    measurement_std_m=0.03,
    max_missing_sec=0.25,
    max_dt_sec=0.2,
):
    """Replay only baseline-accepted measurements to isolate tracker tuning."""

    tracker = BlueObstacleTracker(
        process_accel_std_mps2=process_accel_std_mps2,
        measurement_std_m=measurement_std_m,
        max_missing_sec=max_missing_sec,
        max_dt_sec=max_dt_sec,
    )
    estimator = CausalTtcEstimator(
        window_sec=velocity_window_sec,
        deadband_mps=ttc_deadband_mps,
    )
    replayed = []
    last_timestamp = None
    for row in rows:
        timestamp = _timestamp(row)
        if timestamp is None:
            continue
        if last_timestamp is not None and timestamp <= last_timestamp:
            raise ValueError("recording timestamps must be strictly increasing")
        last_timestamp = timestamp
        x_m = _number(row, "x_m")
        z_m = _number(row, "z_m")
        measurement = (
            (x_m, z_m)
            if _flag(row, "measurement_accepted")
            and x_m is not None
            and z_m is not None
            else None
        )
        track = tracker.update(measurement, timestamp=timestamp)
        estimate = estimator.update(track, timestamp=timestamp)
        replayed.append(
            {
                "timestamp": timestamp,
                "odom_linear_mps": _number(row, "odom_linear_mps"),
                "track_available": track is not None,
                "filtered_z_m": track["z_m"] if track is not None else None,
                "relative_vz_mps": track["vz_mps"] if track is not None else None,
                "smoothed_vz_mps": estimate["smoothed_vz_mps"],
                "ttc_sec": estimate["ttc_sec"],
            }
        )
    return replayed


def summarize_session(
    label,
    source,
    rows,
    replayed,
    process_accel_std_mps2,
    ttc_deadband_mps,
    motion_threshold_mps=0.05,
    stable_frames=5,
):
    motion = classify_motion(label, rows, motion_threshold_mps)
    if motion == "approach":
        motion_predicate = (
            lambda row: (row["odom_linear_mps"] or 0.0) > motion_threshold_mps
        )
        moving = [
            row
            for row in replayed
            if motion_predicate(row)
        ]
        expected_direction = lambda value: value is not None and value < -ttc_deadband_mps
    elif motion == "retreat":
        motion_predicate = (
            lambda row: (row["odom_linear_mps"] or 0.0) < -motion_threshold_mps
        )
        moving = [
            row
            for row in replayed
            if motion_predicate(row)
        ]
        expected_direction = lambda value: value is not None and value > ttc_deadband_mps
    else:
        motion_predicate = lambda row: False
        moving = []
        expected_direction = lambda value: False

    motion_start_index = next(
        (index for index, row in enumerate(replayed) if motion_predicate(row)), None
    )
    response_rows = (
        replayed[motion_start_index:] if motion_start_index is not None else []
    )
    response_index = _first_stable_index(
        response_rows,
        lambda row: motion_predicate(row)
        and expected_direction(row["smoothed_vz_mps"]),
        stable_frames,
    )
    response_delay = math.nan
    steady_rows = []
    if motion_start_index is not None and response_index is not None:
        response_row = response_rows[response_index]
        response_delay = max(
            0.0,
            response_row["timestamp"] - replayed[motion_start_index]["timestamp"],
        )
        steady_rows = [
            row for row in moving if row["timestamp"] >= response_row["timestamp"]
        ]
    speed_errors = [
        abs(row["smoothed_vz_mps"] + row["odom_linear_mps"])
        for row in steady_rows
        if row["smoothed_vz_mps"] is not None
        and row["odom_linear_mps"] is not None
    ]
    tracked = [row for row in replayed if row["track_available"]]
    ttc_active_rate = (
        sum(row["ttc_sec"] is not None for row in moving) / len(moving)
        if moving
        else math.nan
    )
    false_ttc_rate = (
        sum(row["ttc_sec"] is not None for row in tracked) / len(tracked)
        if motion == "static" and tracked
        else (
            sum(row["ttc_sec"] is not None for row in moving) / len(moving)
            if motion == "retreat" and moving
            else 0.0 if motion in {"retreat", "static"} else math.nan
        )
    )
    return {
        "process_accel_std_mps2": process_accel_std_mps2,
        "ttc_deadband_mps": ttc_deadband_mps,
        "experiment_label": label,
        "source": source,
        "motion": motion,
        "nominal_speed_mps": nominal_speed_mps(label) or "",
        "frames": len(replayed),
        "track_frames": len(tracked),
        "motion_frames": len(moving),
        "stable_response_delay_sec": response_delay,
        "steady_speed_mae_mps": (
            statistics.mean(speed_errors) if speed_errors else math.nan
        ),
        "ttc_active_rate": ttc_active_rate,
        "false_ttc_rate": false_ttc_rate,
    }


def _finite_max(values):
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return max(finite) if finite else math.nan


def summarize_candidates(details):
    groups = {}
    for row in details:
        key = (row["process_accel_std_mps2"], row["ttc_deadband_mps"])
        groups.setdefault(key, []).append(row)
    summaries = []
    for (accel, deadband), rows in sorted(groups.items()):
        usable = [row for row in rows if row["motion"] != "excluded"]
        approach = [row for row in usable if row["motion"] == "approach"]
        retreat = [row for row in usable if row["motion"] == "retreat"]
        static = [row for row in usable if row["motion"] == "static"]

        def approach_at(speed):
            return [
                row
                for row in approach
                if row["nominal_speed_mps"] != ""
                and math.isclose(float(row["nominal_speed_mps"]), speed, abs_tol=1e-6)
            ]

        summaries.append(
            {
                "process_accel_std_mps2": accel,
                "ttc_deadband_mps": deadband,
                "sessions": len(usable),
                "approach_sessions": len(approach),
                "retreat_sessions": len(retreat),
                "static_sessions": len(static),
                "max_approach_v0p10_response_delay_sec": _finite_max(
                    row["stable_response_delay_sec"] for row in approach_at(0.10)
                ),
                "max_approach_v0p20_response_delay_sec": _finite_max(
                    row["stable_response_delay_sec"] for row in approach_at(0.20)
                ),
                "max_approach_speed_mae_mps": _finite_max(
                    row["steady_speed_mae_mps"] for row in approach
                ),
                "max_retreat_false_ttc_rate": _finite_max(
                    row["false_ttc_rate"] for row in retreat
                ),
                "max_static_false_ttc_rate": _finite_max(
                    row["false_ttc_rate"] for row in static
                ),
            }
        )
    return summaries


def _parse_candidates(value, option):
    try:
        candidates = [float(item) for item in value.split(",")]
    except ValueError as error:
        raise ValueError(f"{option} must be comma-separated numbers") from error
    if not candidates or any(not math.isfinite(item) or item <= 0.0 for item in candidates):
        raise ValueError(f"{option} candidates must be finite and positive")
    return sorted(set(candidates))


def _write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _format(value):
    return "―" if not math.isfinite(float(value)) else f"{float(value):.3f}"


def write_report(path, summaries, inputs):
    lines = [
        "# Kalman速度応答・TTCデッドバンド感度評価",
        "",
        "録画時に採用された観測を固定し、KalmanとTTC推定だけを候補ごとに再実行した。",
        "これにより検出・観測ゲートの変化と速度応答の変化を分離している。",
        "",
        "## 入力",
        "",
        *[f"- `{Path(item).resolve()}`" for item in inputs],
        "",
        "## 候補比較（各指標は試行中の最大値）",
        "",
        "| accel std | deadband | 0.10接近遅延 | 0.20接近遅延 | 接近速度MAE | 後退誤TTC率 | 静止誤TTC率 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {a:g} | {d:g} | {r10} | {r20} | {mae} | {ret} | {sta} |".format(
                a=row["process_accel_std_mps2"],
                d=row["ttc_deadband_mps"],
                r10=_format(row["max_approach_v0p10_response_delay_sec"]),
                r20=_format(row["max_approach_v0p20_response_delay_sec"]),
                mae=_format(row["max_approach_speed_mae_mps"]),
                ret=_format(row["max_retreat_false_ttc_rate"]),
                sta=_format(row["max_static_false_ttc_rate"]),
            )
        )
    lines.extend(
        [
            "",
            "現行値は`accel std=1.5 m/s²`、`deadband=0.05 m/s`。",
            "候補決定では応答遅延だけでなく、後退・静止の誤TTC率と速度MAEを同時に確認する。",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def run_analysis(args):
    accel_candidates = _parse_candidates(args.process_accel_std, "--process-accel-std")
    deadband_candidates = _parse_candidates(args.ttc_deadband, "--ttc-deadband")
    sessions = load_sessions(args.input)
    details = []
    for accel in accel_candidates:
        for deadband in deadband_candidates:
            for session_name, source, metadata, rows in sessions:
                label = metadata.get("experiment_label", session_name)
                replayed = replay_candidate(
                    rows,
                    accel,
                    deadband,
                    velocity_window_sec=args.velocity_window_sec,
                )
                details.append(
                    summarize_session(
                        label,
                        source,
                        rows,
                        replayed,
                        accel,
                        deadband,
                        motion_threshold_mps=args.motion_threshold_mps,
                        stable_frames=args.stable_frames,
                    )
                )
    summaries = summarize_candidates(details)
    output_dir = args.output_dir.resolve()
    paths = {
        "details": output_dir / "ttc_kalman_sensitivity_details.csv",
        "summary": output_dir / "ttc_kalman_sensitivity_summary.csv",
        "report": output_dir / "ttc_kalman_sensitivity_report.md",
    }
    existing = [path for path in paths.values() if path.exists()]
    if existing and not args.overwrite:
        rendered = ", ".join(str(path) for path in existing)
        raise ValueError(f"output already exists; use --overwrite: {rendered}")
    _write_csv(paths["details"], DETAIL_FIELDS, details)
    _write_csv(paths["summary"], SUMMARY_FIELDS, summaries)
    write_report(paths["report"], summaries, args.input)
    return summaries


def build_parser():
    parser = argparse.ArgumentParser(
        description="Compare Kalman acceleration noise and TTC deadband on recordings"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--process-accel-std", default="0.75,1.5,3.0,6.0")
    parser.add_argument("--ttc-deadband", default="0.03,0.05,0.07")
    parser.add_argument("--velocity-window-sec", type=float, default=0.3)
    parser.add_argument("--motion-threshold-mps", type=float, default=0.05)
    parser.add_argument("--stable-frames", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.velocity_window_sec <= 0.0:
        parser.error("--velocity-window-sec must be positive")
    if args.motion_threshold_mps < 0.0:
        parser.error("--motion-threshold-mps must not be negative")
    if args.stable_frames < 1:
        parser.error("--stable-frames must be at least one")
    try:
        summaries = run_analysis(args)
    except (FileNotFoundError, OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Candidates: {len(summaries)}")
    print(f"Report: {(args.output_dir / 'ttc_kalman_sensitivity_report.md').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
