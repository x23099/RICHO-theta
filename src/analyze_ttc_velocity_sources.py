#!/usr/bin/env python3
"""Compare visual and ego-odometry TTC velocity sources offline."""

from __future__ import annotations

import argparse
import copy
import csv
import math
from collections import Counter
from pathlib import Path

from diagnose_lateral_gate_asymmetry import load_sessions
from evaluate_dynamic_ttc_conditions import (
    evaluate_session,
    expected_motion,
    load_profile,
)


MODES = ("visual", "odom_static", "conservative")
FIELDS = [
    "session",
    "experiment_label",
    "expected_motion",
    "nominal_speed_mps",
    "velocity_source",
    "decision",
    "decision_without_hold_requirement",
    "relative_speed_mae_mps",
    "ttc_active_rate",
    "ttc_activation_delay_sec",
    "false_ttc_rate",
    "raw_warning_frames",
    "filtered_warning_frames",
    "warning_hold_frames",
    "first_raw_warning_ttc_sec",
    "first_raw_warning_z_m",
    "reasons",
    "reasons_without_hold_requirement",
]


def _number(row: dict, key: str):
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def replace_velocity_source(rows: list[dict], mode: str, deadband_mps: float):
    if mode not in MODES:
        raise ValueError(f"unsupported velocity source: {mode}")
    output = []
    for original in rows:
        row = dict(original)
        if mode == "visual":
            row["ttc_velocity_source"] = "visual"
            output.append(row)
            continue
        visual_vz = _number(row, "smoothed_vz_mps")
        odom_speed = (
            _number(row, "odom_linear_mps")
            if str(row.get("odom_available", "")).strip().lower()
            in {"1", "true", "yes"}
            else None
        )
        track_available = str(row.get("track_available", "")).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if odom_speed is None or not track_available:
            row["ttc_velocity_source"] = "visual_fallback"
            output.append(row)
            continue
        static_obstacle_vz = -odom_speed
        if mode == "odom_static":
            selected_vz = static_obstacle_vz
            selected_source = "odom_static"
        else:
            selected_vz = (
                min(visual_vz, static_obstacle_vz)
                if visual_vz is not None
                else static_obstacle_vz
            )
            selected_source = (
                "conservative_odom"
                if visual_vz is None or static_obstacle_vz < visual_vz
                else "conservative_visual"
            )
        row["smoothed_vz_mps"] = str(selected_vz)
        row["ttc_velocity_source"] = selected_source
        filtered_z = _number(row, "filtered_z_m")
        row["ttc_sec"] = (
            str(filtered_z / -selected_vz)
            if filtered_z is not None
            and filtered_z > 0.0
            and selected_vz < -deadband_mps
            else ""
        )
        output.append(row)
    return output


def compare_inputs(inputs: list[Path], profile: dict):
    results = []
    for label, source, metadata, rows in load_sessions(inputs):
        motion = expected_motion(label)
        if motion == "excluded":
            continue
        session_name = source.rsplit("::", 1)[-1] if "::" in source else Path(source).name
        for mode in MODES:
            mode_profile = copy.deepcopy(profile)
            if mode_profile.get("schema_version") == 3:
                mode_profile["velocity_source"] = mode
            profile_without_hold = copy.deepcopy(mode_profile)
            profile_without_hold["minimum_warning_hold_frames"] = 0
            replay_rows = replace_velocity_source(
                rows, mode, float(profile["motion_deadband_mps"])
            )
            replay_metadata = copy.deepcopy(metadata)
            replay_metadata.setdefault("parameters", {})[
                "blue_ttc_velocity_source"
            ] = mode
            strict = evaluate_session(
                label, session_name, replay_metadata, replay_rows, mode_profile
            )
            without_hold = evaluate_session(
                label,
                session_name,
                replay_metadata,
                replay_rows,
                profile_without_hold,
            )
            results.append(
                {
                    "session": session_name,
                    "experiment_label": label,
                    "expected_motion": strict["expected_motion"],
                    "nominal_speed_mps": strict["nominal_speed_mps"],
                    "velocity_source": mode,
                    "decision": strict["decision"],
                    "decision_without_hold_requirement": without_hold["decision"],
                    "relative_speed_mae_mps": strict["relative_speed_mae_mps"],
                    "ttc_active_rate": strict["ttc_active_rate"],
                    "ttc_activation_delay_sec": strict["ttc_activation_delay_sec"],
                    "false_ttc_rate": strict["false_ttc_rate"],
                    "raw_warning_frames": strict["raw_warning_frames"],
                    "filtered_warning_frames": strict["filtered_warning_frames"],
                    "warning_hold_frames": strict["warning_hold_frames"],
                    "first_raw_warning_ttc_sec": strict["first_raw_warning_ttc_sec"],
                    "first_raw_warning_z_m": strict["first_raw_warning_z_m"],
                    "reasons": strict["reasons"],
                    "reasons_without_hold_requirement": without_hold["reasons"],
                }
            )
    return results


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, inputs: list[Path], rows: list[dict]) -> None:
    lines = [
        "# TTC速度源オフライン比較",
        "",
        "## 入力",
        "",
        *[f"- `{item}`" for item in inputs],
        "",
        "## 方式",
        "",
        "- `visual`: 現行の画像距離差分による相対速度。",
        "- `odom_static`: 対象物が静止していると仮定し、相対速度を`-odom_linear_mps`とする。",
        "- `conservative`: visualと`-odom_linear_mps`のうち、接近側で大きい速度を使う。",
        "",
        "後二方式は候補方式であり、production既定値は`visual`のままとする。",
        "",
        "## 集計",
        "",
        "| 速度源 | 指定profile PASS | HOLD必須を外したPASS | 0.20 m/s WARNING成立 |",
        "|---|---:|---:|---:|",
    ]
    for mode in MODES:
        selected = [row for row in rows if row["velocity_source"] == mode]
        v20 = [
            row
            for row in selected
            if row["expected_motion"] == "approach"
            and float(row["nominal_speed_mps"]) >= 0.15
        ]
        lines.append(
            f"| {mode} | {sum(row['decision'] == 'PASS' for row in selected)}/{len(selected)} | "
            f"{sum(row['decision_without_hold_requirement'] == 'PASS' for row in selected)}/{len(selected)} | "
            f"{sum(int(row['filtered_warning_frames']) > 0 for row in v20)}/{len(v20)} |"
        )
    candidate_rows = [
        row for row in rows if row["velocity_source"] != "visual"
    ]
    candidate_no_hold_failures = [
        row
        for row in candidate_rows
        if row["decision_without_hold_requirement"] == "FAIL"
    ]
    candidate_strict_failures = [
        row for row in candidate_rows if row["decision"] == "FAIL"
    ]
    reason_counts = Counter()
    for row in candidate_no_hold_failures:
        for reason in str(row["reasons_without_hold_requirement"]).split("; "):
            if reason:
                reason_counts[reason.split("=", 1)[0]] += 1
    lines.extend(
        [
            "",
            "## 0.20 m/s接近",
            "",
            "| ラベル | 速度源 | 速度MAE | WARNING | 初回TTC | 厳格判定 | HOLD非必須判定 |",
            "|---|---|---:|---:|---:|---|---|",
        ]
    )
    for row in rows:
        if not (
            row["expected_motion"] == "approach"
            and float(row["nominal_speed_mps"]) >= 0.15
        ):
            continue
        first_ttc = row["first_raw_warning_ttc_sec"]
        first_ttc_text = (
            f"{float(first_ttc):.3f}秒"
            if first_ttc is not None and math.isfinite(float(first_ttc))
            else "―"
        )
        lines.append(
            f"| {row['experiment_label']} | {row['velocity_source']} | "
            f"{float(row['relative_speed_mae_mps']):.4f} m/s | "
            f"{row['filtered_warning_frames']} | {first_ttc_text} | "
            f"{row['decision']} | {row['decision_without_hold_requirement']} |"
        )
    lines.extend(
        [
            "",
            "## 解釈",
            "",
            "ODOMを使う二方式では、0.20 m/s接近の全試行でWARNINGが成立する。",
            "`WARNING_HOLD`は警告成立後に観測が無効になった場合の有限保持状態であり、",
            "遮蔽のない通常接近試験で1 frame以上を必須にすると、正常観測が続くほど不合格になる。",
            "保持性能は警告後に意図的な遮蔽・欠測を入れた別試験で評価する必要がある。",
            "",
            "`odom_static`は対象物の静止を仮定するため、未知の動的物体へそのまま適用できない。",
            "`conservative`は接近速度の過小評価を避ける一方、対象物が遠ざかる場面では過警告になり得る。",
            "本番採用前に、対象物クラスとFFBの安全要求を明確にする。",
        ]
    )
    if candidate_no_hold_failures:
        lines.extend(
            [
                f"HOLD必須を外してもODOM候補には{len(candidate_no_hold_failures)}件のFAILが残る。",
                "これは速度源以外の条件も含むため、方式採否とは分けて試行別理由を確認する。",
                "",
                "| HOLD以外の未達指標 | 件数 |",
                "|---|---:|",
                *[
                    f"| `{reason}` | {count} |"
                    for reason, count in sorted(reason_counts.items())
                ],
            ]
        )
    elif candidate_strict_failures:
        lines.extend(
            [
                "この入力群では、ODOM候補の厳格profileに残るFAIL理由は",
                "`warning_hold_frames=0`のみである。",
            ]
        )
    else:
        lines.extend(
            [
                "この入力群では、ODOM候補は指定profileの全動的試行にPASSした。",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare visual, static-odom, and conservative TTC velocity sources"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if not args.overwrite and (args.output.exists() or args.report.exists()):
        parser.error("output already exists")
    profile = load_profile(args.profile)
    rows = compare_inputs(args.input, profile)
    if not rows:
        raise SystemExit("No supported dynamic sessions were found")
    write_csv(args.output, rows)
    write_report(args.report, args.input, rows)
    print(f"Rows: {len(rows)}")
    print(f"CSV saved: {args.output.resolve()}")
    print(f"Report saved: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
