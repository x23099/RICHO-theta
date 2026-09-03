#!/usr/bin/env python3
"""Diagnose longitudinal range scale against integrated wheel odometry."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path

from diagnose_lateral_gate_asymmetry import load_sessions
from evaluate_dynamic_ttc_conditions import expected_motion, nominal_speed_mps


FIELDS = [
    "session",
    "experiment_label",
    "expected_motion",
    "nominal_speed_mps",
    "motion_frames",
    "motion_duration_sec",
    "odom_path_m",
    "raw_z_change_m",
    "raw_z_scale_vs_odom",
    "raw_z_scale_r2",
    "filtered_z_change_m",
    "filtered_z_scale_vs_odom",
    "filtered_z_scale_r2",
    "median_speed_scale_vs_odom",
    "raw_z_correction_multiplier",
]


def _number(row: dict, key: str):
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _flag(row: dict, key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def _timestamp(row: dict):
    value = _number(row, "monotonic_time_sec")
    return value if value is not None else _number(row, "time_sec")


def _linear_scale(xs: list[float], zs: list[float]):
    """Return the positive scale in z = intercept - scale * odom_path."""

    if len(xs) < 3 or len(xs) != len(zs):
        return math.nan, math.nan
    mean_x = statistics.fmean(xs)
    mean_z = statistics.fmean(zs)
    sum_xx = sum((x - mean_x) ** 2 for x in xs)
    if sum_xx <= 1e-12:
        return math.nan, math.nan
    slope = sum((x - mean_x) * (z - mean_z) for x, z in zip(xs, zs)) / sum_xx
    intercept = mean_z - slope * mean_x
    residual = sum((z - (intercept + slope * x)) ** 2 for x, z in zip(xs, zs))
    total = sum((z - mean_z) ** 2 for z in zs)
    r2 = 1.0 - residual / total if total > 1e-12 else math.nan
    return -slope, r2


def diagnose_session(
    label: str,
    session_name: str,
    rows: list[dict],
    motion_threshold_mps: float,
):
    motion = expected_motion(label)
    nominal_speed = nominal_speed_mps(label)
    if motion == "excluded" or nominal_speed is None:
        return None
    direction = 1.0 if motion == "approach" else -1.0
    motion_rows = []
    for row in rows:
        timestamp = _timestamp(row)
        odom_speed = _number(row, "odom_linear_mps")
        if (
            timestamp is None
            or odom_speed is None
            or not _flag(row, "odom_available")
            or direction * odom_speed <= motion_threshold_mps
        ):
            continue
        motion_rows.append((timestamp, odom_speed, row))
    if len(motion_rows) < 3:
        return None

    cumulative_path = [0.0]
    for previous, current in zip(motion_rows, motion_rows[1:]):
        dt = current[0] - previous[0]
        if dt <= 0.0:
            cumulative_path.append(cumulative_path[-1])
            continue
        cumulative_path.append(
            cumulative_path[-1] + 0.5 * (previous[1] + current[1]) * dt
        )

    raw_xs, raw_zs = [], []
    filtered_xs, filtered_zs = [], []
    speed_scales = []
    for path, (_, odom_speed, row) in zip(cumulative_path, motion_rows):
        if not _flag(row, "track_available") or not _flag(
            row, "calibration_valid"
        ):
            continue
        raw_z = _number(row, "raw_z_m")
        if raw_z is not None and _flag(row, "detected"):
            raw_xs.append(path)
            raw_zs.append(raw_z)
        filtered_z = _number(row, "filtered_z_m")
        if filtered_z is not None:
            filtered_xs.append(path)
            filtered_zs.append(filtered_z)
        smoothed_vz = _number(row, "smoothed_vz_mps")
        if smoothed_vz is not None and abs(odom_speed) > 1e-12:
            speed_scales.append(-smoothed_vz / odom_speed)

    raw_scale, raw_r2 = _linear_scale(raw_xs, raw_zs)
    filtered_scale, filtered_r2 = _linear_scale(filtered_xs, filtered_zs)
    raw_change = abs(raw_zs[-1] - raw_zs[0]) if len(raw_zs) >= 2 else math.nan
    filtered_change = (
        abs(filtered_zs[-1] - filtered_zs[0])
        if len(filtered_zs) >= 2
        else math.nan
    )
    odom_path = abs(cumulative_path[-1] - cumulative_path[0])
    return {
        "session": session_name,
        "experiment_label": label,
        "expected_motion": motion,
        "nominal_speed_mps": nominal_speed,
        "motion_frames": len(motion_rows),
        "motion_duration_sec": motion_rows[-1][0] - motion_rows[0][0],
        "odom_path_m": odom_path,
        "raw_z_change_m": raw_change,
        "raw_z_scale_vs_odom": raw_scale,
        "raw_z_scale_r2": raw_r2,
        "filtered_z_change_m": filtered_change,
        "filtered_z_scale_vs_odom": filtered_scale,
        "filtered_z_scale_r2": filtered_r2,
        "median_speed_scale_vs_odom": (
            statistics.median(speed_scales) if speed_scales else math.nan
        ),
        "raw_z_correction_multiplier": (
            1.0 / raw_scale
            if math.isfinite(raw_scale) and raw_scale > 1e-12
            else math.nan
        ),
    }


def diagnose_inputs(inputs: list[Path], motion_threshold_mps: float):
    results = []
    for label, source, _metadata, rows in load_sessions(inputs):
        session_name = source.rsplit("::", 1)[-1] if "::" in source else Path(source).name
        result = diagnose_session(
            label, session_name, rows, motion_threshold_mps
        )
        if result is not None:
            results.append(result)
    return results


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _format(value, digits=3):
    return f"{value:.{digits}f}" if math.isfinite(float(value)) else "―"


def write_report(path: Path, inputs: list[Path], rows: list[dict]) -> None:
    raw_scales = [
        float(row["raw_z_scale_vs_odom"])
        for row in rows
        if math.isfinite(float(row["raw_z_scale_vs_odom"]))
    ]
    raw_r2 = [
        float(row["raw_z_scale_r2"])
        for row in rows
        if math.isfinite(float(row["raw_z_scale_r2"]))
    ]
    filtered_scales = [
        float(row["filtered_z_scale_vs_odom"])
        for row in rows
        if math.isfinite(float(row["filtered_z_scale_vs_odom"]))
    ]
    speed_scales = [
        float(row["median_speed_scale_vs_odom"])
        for row in rows
        if math.isfinite(float(row["median_speed_scale_vs_odom"]))
    ]
    median_raw = statistics.median(raw_scales) if raw_scales else math.nan
    correction = 1.0 / median_raw if math.isfinite(median_raw) else math.nan
    lines = [
        "# 前後距離スケール診断",
        "",
        "## 入力",
        "",
        *[f"- `{item}`" for item in inputs],
        "",
        "## 集計",
        "",
        "| 指標 | 結果 |",
        "|---|---:|",
        f"| 動的試行 | {len(rows)} |",
        f"| raw zスケール中央値 | {_format(median_raw)} |",
        f"| raw zスケール範囲 | {_format(min(raw_scales))}～{_format(max(raw_scales))} |"
        if raw_scales
        else "| raw zスケール範囲 | ― |",
        f"| raw回帰R2範囲 | {_format(min(raw_r2), 4)}～{_format(max(raw_r2), 4)} |"
        if raw_r2
        else "| raw回帰R2範囲 | ― |",
        f"| filtered zスケール中央値 | {_format(statistics.median(filtered_scales))} |"
        if filtered_scales
        else "| filtered zスケール中央値 | ― |",
        f"| 速度スケール中央値 | {_format(statistics.median(speed_scales))} |"
        if speed_scales
        else "| 速度スケール中央値 | ― |",
        f"| 診断上の距離補正倍率 | {_format(correction)} |",
        "",
        "## 試行別結果",
        "",
        "| ラベル | ODOM移動 | raw z変化 | raw倍率 | R2 | filtered倍率 | 速度倍率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['experiment_label']} | {_format(row['odom_path_m'], 4)} m | "
            f"{_format(row['raw_z_change_m'], 4)} m | "
            f"{_format(row['raw_z_scale_vs_odom'])} | "
            f"{_format(row['raw_z_scale_r2'], 4)} | "
            f"{_format(row['filtered_z_scale_vs_odom'])} | "
            f"{_format(row['median_speed_scale_vs_odom'])} |"
        )
    lines.extend(
        [
            "",
            "## 解釈",
            "",
            "`raw倍率`は、ODOM積算移動量1 mに対して画像のraw zが何m変化したかを、",
            "走行区間の線形回帰で求めた値である。理想値は1.0である。",
            "`filtered倍率`がraw倍率に近ければ、主因はKalmanフィルタではなく入力距離のスケールにある。",
            "",
            "`診断上の距離補正倍率`はraw倍率中央値の逆数であり、直ちに本番設定へ適用する値ではない。",
            "既知距離の静的校正点と別の独立走行で確認してから採用を判断する。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare recorded longitudinal range changes with wheel odometry"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--motion-threshold-mps", type=float, default=0.03)
    args = parser.parse_args(argv)
    if not math.isfinite(args.motion_threshold_mps) or args.motion_threshold_mps < 0:
        parser.error("--motion-threshold-mps must be a finite nonnegative number")
    if args.output.exists() or args.report.exists():
        parser.error("output already exists")
    rows = diagnose_inputs(args.input, args.motion_threshold_mps)
    if not rows:
        raise SystemExit("No supported dynamic sessions were found")
    write_csv(args.output, rows)
    write_report(args.report, args.input, rows)
    print(f"Sessions: {len(rows)}")
    print(f"CSV saved: {args.output.resolve()}")
    print(f"Report saved: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
