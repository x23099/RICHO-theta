#!/usr/bin/env python3
"""Run the standard field-recording analysis pipeline with one command."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import cv2

from compare_area_normalization_replays import (
    MODES,
    OUTPUT_FIELDS as GATE_FIELDS,
    decide as decide_gate,
)
from compare_observation_gates import (
    load_observations,
    replay_variant,
    summarize as summarize_gate,
)
from diagnose_lateral_gate_asymmetry import (
    OUTPUT_FIELDS as LATERAL_FIELDS,
    lateral_pair_diagnosis,
    summarize_inputs as summarize_lateral_inputs,
)
from diagnose_recording_timing import (
    OUTPUT_FIELDS as TIMING_FIELDS,
    find_sessions as find_timing_sessions,
    summarize_session as summarize_timing_session,
)
from evaluate_live_trial_requirements import (
    RESULT_FIELDS as REQUIREMENT_RESULT_FIELDS,
    evaluate_requirements,
    load_requirements,
)
from evaluate_dynamic_ttc_conditions import (
    FIELDS as DYNAMIC_TTC_FIELDS,
    evaluate_inputs as evaluate_dynamic_ttc_inputs,
    load_profile as load_dynamic_ttc_profile,
)
from evaluate_observation_gates import (
    find_session_directories,
    load_phase_labels,
    recompute_session,
    write_csv as write_observation_csv,
)
from frame_timing import PROCESSING_TIMING_FIELDS
from inventory_recording_archives import (
    OUTPUT_FIELDS as INVENTORY_FIELDS,
    inspect_archive,
)
from summarize_live_trials import (
    SUMMARY_FIELDS as LIVE_FIELDS,
    summarize_inputs as summarize_live_inputs,
)


DEFAULT_CONFIG = Path(__file__).with_name(
    "bird_eye_config_raw_ground_distance.json"
)
ARTIFACT_NAMES = (
    "archive_inventory.csv",
    "session_integrity.csv",
    "live_summary.csv",
    "processing_timing.csv",
    "lateral_summary.csv",
    "observation_replay.csv",
    "gate_regression.csv",
    "requirements_results.csv",
    "dynamic_ttc_results.csv",
    "analysis_report.md",
)
INTEGRITY_FIELDS = (
    "session",
    "source",
    "required_files_complete",
    "csv_frames",
    "frame_sequence_ok",
    "timestamps_monotonic",
    "time_alias_ok",
    "raw_frames",
    "bev_frames",
    "detection_frames",
    "video_counts_match",
    "processing_timing_status",
    "decision",
    "reasons",
)


def write_rows(path: Path, fields, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def safe_extract_archive(
    archive_path: Path,
    destination: Path,
    max_extracted_bytes: int,
) -> None:
    """Extract only regular files and directories below destination."""

    destination = destination.resolve()
    total_bytes = 0
    with tarfile.open(archive_path, mode="r:xz") as archive:
        for member in archive:
            member_path = PurePosixPath(member.name)
            if (
                member_path.is_absolute()
                or not member_path.parts
                or ".." in member_path.parts
            ):
                raise ValueError(f"unsafe archive path: {member.name!r}")
            if member.issym() or member.islnk():
                raise ValueError(f"archive links are not allowed: {member.name!r}")
            if not (member.isdir() or member.isfile()):
                raise ValueError(
                    f"unsupported archive member type: {member.name!r}"
                )
            target = destination.joinpath(*member_path.parts)
            try:
                target.resolve().relative_to(destination)
            except ValueError as error:
                raise ValueError(f"unsafe archive path: {member.name!r}") from error
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total_bytes += member.size
            if total_bytes > max_extracted_bytes:
                raise ValueError(
                    "archive exceeds extraction limit: "
                    f"{total_bytes} > {max_extracted_bytes} bytes"
                )
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"cannot read archive member: {member.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with stream, target.open("wb") as output_file:
                shutil.copyfileobj(stream, output_file, length=1024 * 1024)


def _video_frame_count(path: Path):
    if not path.is_file():
        return None
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return None
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    finally:
        capture.release()
    return int(round(count)) if math.isfinite(count) and count >= 0 else None


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def summarize_session_integrity(session_dir: Path, source_label: str) -> dict:
    required_paths = [
        session_dir / "metadata.json",
        session_dir / "detections.csv",
        session_dir / "raw.avi",
        session_dir / "bev.avi",
        session_dir / "detection.avi",
    ]
    reasons = []
    required_complete = all(path.is_file() for path in required_paths)
    if not required_complete:
        reasons.append("required files are missing")

    rows = []
    fieldnames = []
    detections_path = session_dir / "detections.csv"
    if detections_path.is_file():
        with detections_path.open(newline="") as input_file:
            reader = csv.DictReader(input_file)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
    csv_frames = len(rows)
    try:
        frames = [int(row["frame"]) for row in rows]
    except (KeyError, TypeError, ValueError):
        frames = []
    frame_sequence_ok = bool(rows) and frames == list(range(1, csv_frames + 1))
    if not frame_sequence_ok:
        reasons.append("frame column is not a 1-based contiguous sequence")

    timestamp_field = (
        "monotonic_time_sec"
        if "monotonic_time_sec" in fieldnames
        else "time_sec"
    )
    try:
        timestamps = [float(row[timestamp_field]) for row in rows]
    except (KeyError, TypeError, ValueError):
        timestamps = []
    timestamps_monotonic = (
        len(timestamps) == csv_frames
        and all(math.isfinite(value) for value in timestamps)
        and all(current > previous for previous, current in zip(timestamps, timestamps[1:]))
    )
    if not timestamps_monotonic:
        reasons.append("timestamps are unavailable or not strictly increasing")

    if {"time_sec", "monotonic_time_sec"} <= set(fieldnames):
        time_alias_ok = all(
            _finite(row["time_sec"])
            and _finite(row["monotonic_time_sec"])
            and float(row["time_sec"]) == float(row["monotonic_time_sec"])
            for row in rows
        )
    else:
        time_alias_ok = None
    if time_alias_ok is False:
        reasons.append("time_sec and monotonic_time_sec differ")

    video_counts = {
        name: _video_frame_count(session_dir / f"{name}.avi")
        for name in ("raw", "bev", "detection")
    }
    video_counts_match = (
        all(value is not None for value in video_counts.values())
        and all(value == csv_frames for value in video_counts.values())
    )
    if not video_counts_match:
        reasons.append("CSV and video frame counts do not match")

    timing_columns = set(PROCESSING_TIMING_FIELDS) & set(fieldnames)
    if not timing_columns:
        timing_status = "NOT_AVAILABLE"
    elif timing_columns != set(PROCESSING_TIMING_FIELDS):
        timing_status = "FAIL"
    else:
        timing_status = "PASS" if all(
            _finite(row[field]) and float(row[field]) >= 0.0
            for row in rows
            for field in PROCESSING_TIMING_FIELDS
        ) else "FAIL"
    if timing_status == "FAIL":
        reasons.append("processing timing columns are partial or invalid")

    decision = "PASS" if not reasons else "FAIL"
    return {
        "session": session_dir.name,
        "source": f"{source_label}::{session_dir.name}",
        "required_files_complete": int(required_complete),
        "csv_frames": csv_frames,
        "frame_sequence_ok": int(frame_sequence_ok),
        "timestamps_monotonic": int(timestamps_monotonic),
        "time_alias_ok": "" if time_alias_ok is None else int(time_alias_ok),
        "raw_frames": "" if video_counts["raw"] is None else video_counts["raw"],
        "bev_frames": "" if video_counts["bev"] is None else video_counts["bev"],
        "detection_frames": (
            "" if video_counts["detection"] is None else video_counts["detection"]
        ),
        "video_counts_match": int(video_counts_match),
        "processing_timing_status": timing_status,
        "decision": decision,
        "reasons": "; ".join(reasons),
    }


def summarize_integrity(root: Path, source_label: str) -> list[dict]:
    return [
        summarize_session_integrity(session, source_label)
        for session in find_session_directories([root])
    ]


def summarize_timing(root: Path, source_label: str) -> list[dict]:
    rows = []
    for session in find_timing_sessions([root]):
        row = summarize_timing_session(session)
        row["session_dir"] = f"{source_label}::{session.name}"
        rows.append(row)
    return rows


def replay_observations(
    root: Path,
    config: dict,
    labels_path: Path | None,
    source_label: str,
    output_path: Path,
) -> list[dict]:
    phase_labels = load_phase_labels(labels_path) if labels_path else {}
    rows = []
    for session in find_session_directories([root]):
        session_rows, _summary = recompute_session(
            session,
            config,
            phase_intervals=phase_labels.get(session.name, ()),
            source_label=source_label,
        )
        rows.extend(session_rows)
    write_observation_csv(rows, output_path)
    return rows


def evaluate_gate_rows(
    observation_path: Path,
    config: dict,
    threshold: float,
) -> tuple[list[dict], list[str]]:
    output_rows = []
    skipped = []
    for session, rows in sorted(load_observations(observation_path).items()):
        if not any(row["detected"] for row in rows):
            skipped.append(session)
            continue
        for mode in MODES:
            variant = f"{mode}_{threshold:g}"
            details = replay_variant(
                rows,
                config,
                variant,
                {
                    "min_normalized_area": threshold,
                    "max_nis": float(config.get("blue_observation_nis_max", 9.21)),
                    "confirmation_frames": int(
                        config.get("blue_observation_confirmation_frames", 2)
                    ),
                    "area_normalization_mode": mode,
                },
            )
            summary = summarize_gate(details)
            output_rows.append(
                {
                    "dataset_role": "diagnostic",
                    "source": str(observation_path),
                    "normalization_mode": mode,
                    "threshold": threshold,
                    **{
                        field: value
                        for field, value in summary.items()
                        if field != "variant"
                    },
                    "decision": decide_gate(summary),
                }
            )
    return output_rows, skipped


def _pct(value) -> str:
    return "―" if not _finite(value) else f"{float(value):.2%}"


def _number(value, digits=3) -> str:
    return "―" if not _finite(value) else f"{float(value):.{digits}f}"


def _markdown(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def is_dynamic_ttc_session(session_name: str) -> bool:
    return str(session_name).startswith(("approach_", "retreat_"))


def automatic_status(
    archive_ok: bool,
    integrity_rows: list[dict],
    timing_rows: list[dict],
    gate_rows: list[dict],
    selected_gate_mode: str,
    requirement_rows: list[dict] | None,
    dynamic_ttc_rows: list[dict] | None = None,
) -> tuple[str, list[str]]:
    reasons = []
    if not archive_ok:
        reasons.append("archive completeness failed")
    if not integrity_rows or any(row["decision"] != "PASS" for row in integrity_rows):
        reasons.append("session integrity failed")
    if not timing_rows or any(not int(row["fps_within_one_percent"]) for row in timing_rows):
        reasons.append("effective FPS is outside ±1%")
    selected_gate_rows = [
        row
        for row in gate_rows
        if row["normalization_mode"] == selected_gate_mode
    ]
    dynamic_sessions = {
        row["session"] for row in (dynamic_ttc_rows or []) if row.get("session")
    }
    dynamic_sessions.update(
        row.get("session")
        for row in selected_gate_rows
        if is_dynamic_ttc_session(row.get("session", ""))
    )
    static_gate_rows = [
        row for row in selected_gate_rows if row.get("session") not in dynamic_sessions
    ]
    if any(row["decision"] != "PASS" for row in static_gate_rows):
        reasons.append(f"{selected_gate_mode} observation gate failed")
    if requirement_rows is not None and any(
        row["result"] != "PASS" for row in requirement_rows
    ):
        reasons.append("one or more predefined requirements failed")
    if dynamic_ttc_rows is not None and (
        not dynamic_ttc_rows
        or any(row["decision"] != "PASS" for row in dynamic_ttc_rows)
    ):
        reasons.append("one or more fixed dynamic TTC conditions failed")
    if reasons:
        return "FAIL", reasons
    if requirement_rows is None:
        return "DIAGNOSTIC", [
            "no predefined requirement CSV was supplied; component metrics only"
        ]
    return "PASS", []


def build_report(
    archive_path: Path,
    config_path: Path,
    inventory: dict,
    integrity_rows: list[dict],
    live_rows: list[dict],
    timing_rows: list[dict],
    lateral_rows: list[dict],
    gate_rows: list[dict],
    skipped_gate_sessions: list[str],
    requirement_rows: list[dict] | None,
    labels_path: Path | None,
    threshold: float,
    selected_gate_mode: str,
    dynamic_ttc_rows: list[dict] | None,
    dynamic_ttc_profile_path: Path | None,
) -> str:
    archive_ok = (
        inventory["tar_xz_status"] == "PASS"
        and int(inventory["recording_sessions"] or 0) > 0
        and inventory["recording_sessions"] == inventory["complete_core_sessions"]
    )
    status, status_reasons = automatic_status(
        archive_ok,
        integrity_rows,
        timing_rows,
        gate_rows,
        selected_gate_mode,
        requirement_rows,
        dynamic_ttc_rows,
    )
    lines = [
        "# 録画一括解析レポート",
        "",
        "## 結論",
        "",
        f"自動判定: **{status}**",
        "",
    ]
    lines.extend(f"- {_markdown(reason)}" for reason in status_reasons)
    artifact_names = [
        name
        for name in ARTIFACT_NAMES
        if name != "analysis_report.md"
        and (name != "requirements_results.csv" or requirement_rows is not None)
        and (name != "dynamic_ttc_results.csv" or dynamic_ttc_rows is not None)
    ]
    if status == "DIAGNOSTIC":
        lines.extend(
            [
                "",
                "`DIAGNOSTIC`は解析失敗ではない。条件別の事前要件CSVがないため、",
                "この録画だけから正式な実験PASSを宣言していないことを表す。",
            ]
        )
    lines.extend(
        [
            "",
            "## 入力と来歴",
            "",
            "| 項目 | 値 |",
            "|---|---|",
            f"| アーカイブ | `{archive_path.resolve()}` |",
            f"| SHA-256 | `{inventory['sha256']}` |",
            f"| サイズ | {int(inventory['size_bytes']):,} bytes |",
            f"| セッション | {inventory['recording_sessions']} |",
            f"| config | `{config_path.resolve()}` |",
            f"| ゲート評価しきい値 | {threshold:g} |",
            f"| 遮蔽ラベル | `{labels_path.resolve()}` |" if labels_path else "| 遮蔽ラベル | なし |",
            "",
            "## セッション完全性",
            "",
            "| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for row in integrity_rows:
        video_counts = f"{row['raw_frames']}/{row['bev_frames']}/{row['detection_frames']}"
        lines.append(
            f"| {_markdown(row['session'])} | {row['csv_frames']} | {video_counts} | "
            f"{'PASS' if row['timestamps_monotonic'] else 'FAIL'} | "
            f"{row['processing_timing_status']} | {row['decision']} |"
        )

    timing_by_source = {row["session_dir"]: row for row in timing_rows}
    lines.extend(
        [
            "",
            "## ライブ結果",
            "",
            "| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in live_rows:
        timing = timing_by_source.get(row["session_dir"], {})
        lines.append(
            f"| {_markdown(row['experiment_label'])} | {row['frames']} | "
            f"{_number(row['effective_fps'])} | {_pct(row['detection_rate'])} | "
            f"{_pct(row['measurement_acceptance_rate'])} | {_pct(row['track_rate'])} | "
            f"{_pct(row['odom_available_rate'])} | "
            f"{_number(timing.get('processing_active_p95_ms'), 2)} ms |"
        )

    diagnosis = lateral_pair_diagnosis(lateral_rows)
    lines.extend(["", "## 左右診断", ""])
    if diagnosis:
        lines.extend(
            [
                f"- 左: `{diagnosis['left_label']}`",
                f"- 右: `{diagnosis['right_label']}`",
                "- 正規化面積の左/右比: "
                f"{diagnosis['normalized_area_ratio_left_to_right']:.3f}",
                f"- z²の左/右比: {diagnosis['z_squared_ratio_left_to_right']:.3f}",
                f"- 生面積の左/右比: {diagnosis['raw_area_ratio_left_to_right']:.3f}",
            ]
        )
    else:
        lines.append("- 左右ペアを自動選択できなかった。")

    selected_gate_rows = [
        row
        for row in gate_rows
        if row["normalization_mode"] == selected_gate_mode
    ]
    lines.extend(
        [
            "",
            f"## {selected_gate_mode}ゲート再生",
            "",
            "| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in selected_gate_rows:
        lines.append(
            f"| {_markdown(row['session'])} | {_pct(row['stable_inlier_acceptance_rate'])} | "
            f"{_number(row['max_abs_vz_mps'], 4)} | "
            f"{row['events_track_expired']}/{row['occlusion_events']} | "
            f"{row['events_reacquired']}/{row['occlusion_events']} | {row['decision']} |"
        )
    if any(
        is_dynamic_ttc_session(row.get("session", ""))
        for row in selected_gate_rows
    ):
        lines.extend(
            [
                "",
                "動的TTC対象sessionのゲート再生は診断値として保存するが、"
                "静的位置外れ値判定を総合判定へは加えない。",
            ]
        )
    if skipped_gate_sessions:
        lines.extend(
            [
                "",
                "検出0のためゲート再生対象外: "
                + ", ".join(f"`{name}`" for name in skipped_gate_sessions),
            ]
        )
    if labels_path is None:
        lines.extend(
            [
                "",
                "遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。",
            ]
        )

    lines.extend(["", "## 事前要件", ""])
    if requirement_rows is None:
        lines.append("- 要件CSV未指定。正式な条件別採否は未評価。")
    else:
        for row in requirement_rows:
            detail = f": {row['reasons']}" if row["reasons"] else ""
            lines.append(f"- {row['rule_id']}: **{row['result']}**{detail}")

    lines.extend(["", "## 固定動的TTC条件", ""])
    if dynamic_ttc_rows is None:
        lines.append("- 動的TTCプロファイル未指定。")
    else:
        lines.extend(
            [
                f"- profile: `{dynamic_ttc_profile_path.resolve()}`",
                "",
                "| ラベル | 精度区間 | 追跡(全体/走行) | 方向(全体/定常) | "
                "方向応答 | 速度MAE | TTC発火 | 警告/保持 | 判定 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in dynamic_ttc_rows:
            lines.append(
                f"| {_markdown(row['experiment_label'])} | "
                f"{row['accuracy_interval_frames']} | "
                f"{_pct(row['track_rate'])}/{_pct(row['motion_track_rate'])} | "
                f"{_pct(row['direction_correct_rate'])}/"
                f"{_pct(row['steady_direction_correct_rate'])} | "
                f"{_number(row['direction_response_delay_sec'], 3)} s | "
                f"{_number(row['relative_speed_mae_mps'], 4)} m/s | "
                f"{_pct(row['ttc_active_rate'])} | "
                f"{row['filtered_warning_frames']}/{row['warning_hold_frames']} | "
                f"{row['decision']} |"
            )
    lines.extend(
        [
            "",
            "## 成果物",
            "",
            *[f"- `{name}`" for name in artifact_names],
            "",
        ]
    )
    return "\n".join(lines)


def ensure_output_paths(output_dir: Path, overwrite: bool) -> dict[str, Path]:
    paths = {name: output_dir / name for name in ARTIFACT_NAMES}
    existing = [path for path in paths.values() if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "analysis output already exists; use --overwrite: " + str(existing[0])
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    return paths


def run_analysis(args: argparse.Namespace) -> str:
    archive_path = args.input.expanduser().resolve()
    config_path = args.config.expanduser().resolve()
    labels_path = args.labels.expanduser().resolve() if args.labels else None
    requirements_path = (
        args.requirements.expanduser().resolve() if args.requirements else None
    )
    dynamic_ttc_profile_path = (
        args.dynamic_ttc_profile.expanduser().resolve()
        if getattr(args, "dynamic_ttc_profile", None)
        else None
    )
    if not archive_path.is_file():
        raise FileNotFoundError(f"archive does not exist: {archive_path}")
    if not config_path.is_file():
        raise FileNotFoundError(f"config does not exist: {config_path}")
    if labels_path and not labels_path.is_file():
        raise FileNotFoundError(f"labels do not exist: {labels_path}")
    if requirements_path and not requirements_path.is_file():
        raise FileNotFoundError(f"requirements do not exist: {requirements_path}")
    if dynamic_ttc_profile_path and not dynamic_ttc_profile_path.is_file():
        raise FileNotFoundError(
            f"dynamic TTC profile does not exist: {dynamic_ttc_profile_path}"
        )

    paths = ensure_output_paths(args.output_dir.resolve(), args.overwrite)
    print("[1/9] Inspecting archive...", flush=True)
    inventory = inspect_archive(archive_path)
    write_rows(paths["archive_inventory.csv"], INVENTORY_FIELDS, [inventory])
    if inventory["tar_xz_status"] != "PASS":
        raise ValueError(f"archive inspection failed: {inventory['error']}")
    if int(inventory["recording_sessions"] or 0) < 1:
        raise ValueError("archive contains no recording session")

    with config_path.open() as config_file:
        config = json.load(config_file)
    selected_gate_mode = config.get(
        "blue_observation_area_distance_mode", "forward_z"
    )
    if selected_gate_mode not in MODES:
        raise ValueError(
            "unsupported blue_observation_area_distance_mode: "
            f"{selected_gate_mode!r}"
        )
    threshold = (
        args.threshold
        if args.threshold is not None
        else float(config["blue_observation_normalized_area_min"])
    )
    source_label = str(archive_path)
    max_bytes = int(args.max_extracted_gb * 1024**3)

    with tempfile.TemporaryDirectory(prefix="field-recording-analysis-") as temporary:
        extracted_root = Path(temporary)
        print("[2/9] Safely extracting archive...", flush=True)
        safe_extract_archive(archive_path, extracted_root, max_bytes)

        print("[3/9] Checking session integrity...", flush=True)
        integrity_rows = summarize_integrity(extracted_root, source_label)
        write_rows(paths["session_integrity.csv"], INTEGRITY_FIELDS, integrity_rows)

        print("[4/9] Summarizing live data and timing...", flush=True)
        live_rows = summarize_live_inputs([archive_path], args.moving_threshold_mps)
        write_rows(paths["live_summary.csv"], LIVE_FIELDS, live_rows)
        timing_rows = summarize_timing(extracted_root, source_label)
        write_rows(paths["processing_timing.csv"], TIMING_FIELDS, timing_rows)

        print("[5/9] Diagnosing lateral behavior...", flush=True)
        lateral_rows = summarize_lateral_inputs([archive_path], threshold)
        write_rows(paths["lateral_summary.csv"], LATERAL_FIELDS, lateral_rows)

        print("[6/9] Recomputing observations from raw video...", flush=True)
        replay_observations(
            extracted_root,
            config,
            labels_path,
            source_label,
            paths["observation_replay.csv"],
        )

    print("[7/9] Replaying observation gates...", flush=True)
    gate_rows, skipped_gate_sessions = evaluate_gate_rows(
        paths["observation_replay.csv"], config, threshold
    )
    write_rows(paths["gate_regression.csv"], GATE_FIELDS, gate_rows)

    requirement_results = None
    if requirements_path:
        requirement_definitions = load_requirements(requirements_path)
        if not requirement_definitions:
            raise ValueError("requirements CSV contains no rules")
        requirement_results = evaluate_requirements(
            live_rows, requirement_definitions
        )
        write_rows(
            paths["requirements_results.csv"],
            REQUIREMENT_RESULT_FIELDS,
            requirement_results,
        )
    elif paths["requirements_results.csv"].exists():
        paths["requirements_results.csv"].unlink()

    print("[8/9] Evaluating fixed dynamic TTC conditions...", flush=True)
    dynamic_ttc_rows = None
    if dynamic_ttc_profile_path:
        dynamic_ttc_rows = evaluate_dynamic_ttc_inputs(
            [archive_path], load_dynamic_ttc_profile(dynamic_ttc_profile_path)
        )
        if not dynamic_ttc_rows:
            raise ValueError(
                "dynamic TTC profile supplied but no supported session was found"
            )
        write_rows(
            paths["dynamic_ttc_results.csv"],
            DYNAMIC_TTC_FIELDS,
            dynamic_ttc_rows,
        )
    elif paths["dynamic_ttc_results.csv"].exists():
        paths["dynamic_ttc_results.csv"].unlink()

    print("[9/9] Writing Markdown report...", flush=True)
    report = build_report(
        archive_path,
        config_path,
        inventory,
        integrity_rows,
        live_rows,
        timing_rows,
        lateral_rows,
        gate_rows,
        skipped_gate_sessions,
        requirement_results,
        labels_path,
        threshold,
        selected_gate_mode,
        dynamic_ttc_rows,
        dynamic_ttc_profile_path,
    )
    paths["analysis_report.md"].write_text(report, encoding="utf-8")
    status_line = next(
        line for line in report.splitlines() if line.startswith("自動判定:")
    )
    print(status_line)
    print(f"Report saved: {paths['analysis_report.md']}")
    return status_line.split("**", 2)[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze one field-recording tar.xz archive end to end"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--dynamic-ttc-profile", type=Path)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--moving-threshold-mps", type=float, default=0.03)
    parser.add_argument("--max-extracted-gb", type=float, default=50.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.threshold is not None and (
        not math.isfinite(args.threshold) or args.threshold <= 0.0
    ):
        parser.error("--threshold must be a finite positive number")
    if not math.isfinite(args.max_extracted_gb) or args.max_extracted_gb <= 0.0:
        parser.error("--max-extracted-gb must be a finite positive number")
    try:
        status = run_analysis(args)
    except (FileNotFoundError, OSError, ValueError, KeyError, tarfile.TarError) as error:
        parser.error(str(error))
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
