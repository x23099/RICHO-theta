#!/usr/bin/env python3
"""Replay recorded collision risks through the live ROS FFB publisher."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import tarfile
import time
from pathlib import Path

import rclpy
from oit_interfaces.msg import CollisionFfbStatus
from rclpy.node import Node

from collision_ffb_publisher import (
    CollisionFfbPublisherBridge,
    collision_command_qos,
)


REQUIRED_FIELDS = {"frame", "time_sec", "collision_risk_level"}


def select_detection_member(
    members: list[str],
    session: str | None,
) -> str:
    """Select exactly one detections.csv member from an archive."""
    candidates = [name for name in members if name.endswith("/detections.csv")]
    if session:
        candidates = [
            name
            for name in candidates
            if name.rsplit("/", maxsplit=1)[0] == session
            or session in name.rsplit("/", maxsplit=1)[0]
        ]
    if not candidates:
        raise ValueError("no matching detections.csv found in archive")
    if len(candidates) > 1:
        available = ", ".join(
            name.rsplit("/", maxsplit=1)[0] for name in candidates
        )
        raise ValueError(
            "multiple sessions found; specify --session. "
            f"Candidates: {available}"
        )
    return candidates[0]


def read_detection_rows(
    input_path: Path,
    session: str | None = None,
) -> tuple[str, list[dict]]:
    """Read one recorded detections table from CSV or tar.xz."""
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise ValueError(f"input does not exist: {input_path}")
    if input_path.name.endswith(".tar.xz"):
        with tarfile.open(input_path, mode="r:xz") as archive:
            member_name = select_detection_member(
                archive.getnames(),
                session,
            )
            extracted = archive.extractfile(member_name)
            if extracted is None:
                raise ValueError(f"cannot read archive member: {member_name}")
            text = io.TextIOWrapper(extracted, encoding="utf-8", newline="")
            rows = list(csv.DictReader(text))
            session_name = member_name.rsplit("/", maxsplit=1)[0]
    else:
        with input_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        session_name = session or input_path.parent.name
    if not rows:
        raise ValueError("detections table contains no rows")
    missing = REQUIRED_FIELDS - set(rows[0])
    if missing:
        raise ValueError(
            "detections table is missing fields: " + ", ".join(sorted(missing))
        )
    return session_name, rows


class ReplayStatusCollector(Node):
    """Collect adapter statuses while recorded risks are replayed."""

    def __init__(self, status_topic: str):
        """Create one status subscription."""
        super().__init__("recorded_collision_ffb_replay")
        self.started_monotonic_sec = time.monotonic()
        self.rows: list[dict] = []
        self.subscription = self.create_subscription(
            CollisionFfbStatus,
            status_topic,
            self._on_status,
            collision_command_qos(),
        )

    def _on_status(self, message: CollisionFfbStatus) -> None:
        received = time.monotonic()
        self.rows.append({
            "receive_monotonic_sec": received,
            "elapsed_sec": received - self.started_monotonic_sec,
            "stamp_sec": (
                float(message.header.stamp.sec)
                + float(message.header.stamp.nanosec) / 1e9
            ),
            "has_sequence": 1 if message.has_sequence else 0,
            "sequence": int(message.sequence),
            "source": str(message.source),
            "output_mode": str(message.output_mode),
            "action": str(message.action),
            "command_active": 1 if message.command_active else 0,
            "output_active": 1 if message.output_active else 0,
            "requested_magnitude": float(message.requested_magnitude),
            "applied_magnitude": float(message.applied_magnitude),
            "pattern": int(message.pattern),
            "reason": str(message.reason),
            "fault": 1 if message.fault else 0,
        })


def spin_until(node: Node, deadline: float) -> None:
    """Service status callbacks until one monotonic deadline."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        rclpy.spin_once(node, timeout_sec=min(0.01, remaining))


def replay_rows(
    rows: list[dict],
    *,
    rate_hz: float,
    command_topic: str,
    status_topic: str,
    source: str,
    discovery_sec: float,
    settle_sec: float,
) -> tuple[list[dict], list[dict]]:
    """Publish recorded risk states at a fixed rate and collect statuses."""
    if not math.isfinite(rate_hz) or not 1.0 <= rate_hz <= 60.0:
        raise ValueError("rate_hz must be finite and within 1..60")
    rclpy.init(args=None)
    collector = ReplayStatusCollector(status_topic)
    bridge = CollisionFfbPublisherBridge(topic=command_topic, source=source)
    command_rows = []
    interval_sec = 1.0 / rate_hz
    try:
        spin_until(collector, time.monotonic() + discovery_sec)
        if bridge.node.count_subscribers(command_topic) < 1:
            raise RuntimeError(
                f"no adapter subscriber discovered on {command_topic}"
            )
        if collector.count_publishers(status_topic) < 1:
            raise RuntimeError(
                f"no adapter status publisher discovered on {status_topic}"
            )
        for row in rows:
            sent = time.monotonic()
            record = bridge.publish_risk(row["collision_risk_level"])
            record.update({
                "source_frame": int(row["frame"]),
                "source_time_sec": float(row["time_sec"]),
                "send_monotonic_sec": sent,
                "elapsed_sec": sent - collector.started_monotonic_sec,
            })
            command_rows.append(record)
            spin_until(collector, time.monotonic() + interval_sec)
    finally:
        bridge.close()
        final_record = dict(bridge.last_record)
        final_record.update({
            "source_frame": "",
            "source_time_sec": "",
            "send_monotonic_sec": time.monotonic(),
            "elapsed_sec": (
                time.monotonic() - collector.started_monotonic_sec
            ),
        })
        command_rows.append(final_record)
        spin_until(collector, time.monotonic() + settle_sec)
        status_rows = list(collector.rows)
        collector.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return command_rows, status_rows


def summarize_replay(
    command_rows: list[dict],
    status_rows: list[dict],
    *,
    expected_mode: str,
) -> dict:
    """Evaluate replay transport without claiming physical perception."""
    published = [
        row
        for row in command_rows
        if int(row["collision_ffb_publish_success"]) == 1
    ]
    active_commands = [
        row for row in command_rows if int(row["collision_ffb_active"]) == 1
    ]
    active_statuses = [
        row for row in status_rows if int(row["output_active"]) == 1
    ]
    fault_count = sum(int(row["fault"]) for row in status_rows)
    observed_modes = sorted({row["output_mode"] for row in status_rows})
    max_applied = max(
        (float(row["applied_magnitude"]) for row in status_rows),
        default=0.0,
    )
    final_inactive = bool(status_rows) and (
        int(status_rows[-1]["output_active"]) == 0
    )
    checks = {
        "all_commands_published": len(published) == len(command_rows),
        "status_received": bool(status_rows),
        "expected_mode_only": observed_modes == [expected_mode],
        "no_fault": fault_count == 0,
        "active_path_observed": not active_commands or bool(active_statuses),
        "adapter_cap_respected": max_applied <= 0.05 + 1e-6,
        "final_inactive": final_inactive,
    }
    return {
        "decision": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "command_count": len(command_rows),
        "active_command_count": len(active_commands),
        "status_count": len(status_rows),
        "active_status_count": len(active_statuses),
        "fault_count": fault_count,
        "observed_output_modes": observed_modes,
        "max_applied_magnitude": max_applied,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write one list of flat rows to CSV."""
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_results(
    output_dir: Path,
    *,
    input_path: Path,
    session: str,
    rate_hz: float,
    command_rows: list[dict],
    status_rows: list[dict],
    summary: dict,
) -> None:
    """Write replay provenance, logs, and automatic judgment."""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "replayed_commands.csv", command_rows)
    write_csv(output_dir / "adapter_status.csv", status_rows)
    payload = {
        "input": str(input_path.resolve()),
        "session": session,
        "rate_hz": rate_hz,
        "summary": summary,
    }
    (output_dir / "replay_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["checks"].items()
    )
    report = f"""# Recorded collision FFB dry-run replay

- 自動判定: **{summary['decision']}**
- input: `{input_path.resolve()}`
- session: `{session}`
- replay rate: `{rate_hz:.1f} Hz`

| 項目 | 値 |
|---|---:|
| command数 | {summary['command_count']} |
| active command数 | {summary['active_command_count']} |
| status数 | {summary['status_count']} |
| active status数 | {summary['active_status_count']} |
| fault数 | {summary['fault_count']} |
| 最大適用強度 | {summary['max_applied_magnitude']:.3f} |

## チェック

{checks}

本結果は、録画済みriskから`CollisionFfbPublisherBridge`、ROS topic、dry-run adapter、
status記録までを対象とする。映像認識の再計算とG923物理出力は行っていない。
"""
    (output_dir / "replay_report.md").write_text(report, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Build the replay command-line parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--session")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rate", type=float, default=30.0)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--command-topic", default="/collision/ffb_command")
    parser.add_argument("--status-topic", default="/collision/ffb_status")
    parser.add_argument("--source", default="bird_eye")
    parser.add_argument("--expect-output-mode", default="dry_run")
    parser.add_argument("--discovery-sec", type=float, default=1.0)
    parser.add_argument("--settle-sec", type=float, default=0.2)
    return parser


def main(args=None) -> int:
    """Replay one session and return 0 only for an automatic PASS."""
    parsed = build_parser().parse_args(args)
    try:
        session, rows = read_detection_rows(parsed.input, parsed.session)
        if parsed.max_frames is not None:
            if parsed.max_frames <= 0:
                raise ValueError("max_frames must be positive")
            rows = rows[:parsed.max_frames]
        command_rows, status_rows = replay_rows(
            rows,
            rate_hz=parsed.rate,
            command_topic=parsed.command_topic,
            status_topic=parsed.status_topic,
            source=parsed.source,
            discovery_sec=parsed.discovery_sec,
            settle_sec=parsed.settle_sec,
        )
        summary = summarize_replay(
            command_rows,
            status_rows,
            expected_mode=parsed.expect_output_mode,
        )
        write_results(
            parsed.output_dir,
            input_path=parsed.input,
            session=session,
            rate_hz=parsed.rate,
            command_rows=command_rows,
            status_rows=status_rows,
            summary=summary,
        )
    except (RuntimeError, ValueError, tarfile.TarError) as error:
        print(f"[ERROR] {error}")
        return 2
    print(f"Decision: {summary['decision']}")
    print(f"Report: {(parsed.output_dir / 'replay_report.md').resolve()}")
    return 0 if summary["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
