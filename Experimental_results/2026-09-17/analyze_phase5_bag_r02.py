#!/usr/bin/env python3
"""Decode the 2026-09-17 Phase 5 rosbag without a built oit_interfaces package."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sqlite3
import struct
import tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo


class CDR:
    def __init__(self, data: bytes) -> None:
        if len(data) < 4 or data[:2] != b"\x00\x01":
            raise ValueError("Expected little-endian CDR encapsulation")
        self.data = data
        self.pos = 0  # Relative to the four-byte CDR encapsulation header.

    def unpack(self, fmt: str, alignment: int):
        self.pos = (self.pos + alignment - 1) // alignment * alignment
        result = struct.unpack_from("<" + fmt, self.data, 4 + self.pos)[0]
        self.pos += struct.calcsize(fmt)
        return result

    def text(self) -> str:
        length = self.unpack("I", 4)
        if length < 1:
            raise ValueError("Invalid CDR string length")
        start = 4 + self.pos
        end = start + length
        if self.data[end - 1] != 0:
            raise ValueError("CDR string not NUL terminated")
        self.pos += length
        return self.data[start : end - 1].decode("utf-8")

    def header(self) -> dict:
        seconds = self.unpack("i", 4)
        nanoseconds = self.unpack("I", 4)
        return {"stamp_ns": seconds * 1_000_000_000 + nanoseconds, "frame_id": self.text()}


def decode_command(data: bytes) -> dict:
    reader = CDR(data)
    result = reader.header()
    result.update(
        sequence=reader.unpack("Q", 8),
        source=reader.text(),
        risk_level=reader.unpack("B", 1),
        pattern=reader.unpack("B", 1),
        active=bool(reader.unpack("B", 1)),
        normalized_magnitude=reader.unpack("f", 4),
        reason=reader.text(),
    )
    aligned = (reader.pos + 7) // 8 * 8
    if len(data) >= 4 + aligned + 16:
        result["receiver_session_id"] = reader.unpack("Q", 8)
        result["receiver_token"] = reader.unpack("Q", 8)
    else:
        result["receiver_session_id"] = 0
        result["receiver_token"] = 0
    return result


def decode_challenge(data: bytes) -> dict:
    reader = CDR(data)
    return {
        "session_id": reader.unpack("Q", 8),
        "token": reader.unpack("Q", 8),
    }


def decode_status(data: bytes) -> dict:
    reader = CDR(data)
    result = reader.header()
    result.update(
        has_sequence=bool(reader.unpack("B", 1)),
        sequence=reader.unpack("Q", 8),
        source=reader.text(),
        output_mode=reader.text(),
        action=reader.text(),
        command_active=bool(reader.unpack("B", 1)),
        output_active=bool(reader.unpack("B", 1)),
        requested_magnitude=reader.unpack("f", 4),
        applied_magnitude=reader.unpack("f", 4),
        pattern=reader.unpack("B", 1),
        reason=reader.text(),
        fault=bool(reader.unpack("B", 1)),
    )
    return result


def decode_odom(data: bytes) -> dict:
    reader = CDR(data)
    result = reader.header()
    result["child_frame_id"] = reader.text()
    for _ in range(7 + 36):  # Pose position, quaternion, and covariance.
        reader.unpack("d", 8)
    result["linear_x"] = reader.unpack("d", 8)
    for _ in range(2):
        reader.unpack("d", 8)
    for _ in range(2):
        reader.unpack("d", 8)
    result["angular_z"] = reader.unpack("d", 8)
    return result


def clock(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, ZoneInfo("Asia/Tokyo")).isoformat(timespec="milliseconds")


def span(rows: list[dict], key: str = "bag_ns") -> list[str] | None:
    return [clock(rows[0][key]), clock(rows[-1][key])] if rows else None


def camera_rows(path: Path) -> tuple[str, list[dict]]:
    with tarfile.open(path, "r:xz") as archive:
        members = [member for member in archive if member.name.endswith("/detections.csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one detections.csv, got {len(members)}")
        stream = archive.extractfile(members[0])
        if stream is None:
            raise ValueError("Cannot read detections.csv")
        with stream, io.TextIOWrapper(stream, encoding="utf-8", newline="") as text_stream:
            return members[0].name.split("/")[0], list(csv.DictReader(text_stream))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-archive", type=Path, required=True)
    parser.add_argument("--bag-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact-prefix", default="phase5_live_dryrun_r02")
    args = parser.parse_args()
    if not args.artifact_prefix or not all(
        character.isalnum() or character in "_-" for character in args.artifact_prefix
    ):
        parser.error("--artifact-prefix must contain only letters, digits, _ or -")

    connection = sqlite3.connect(f"file:{args.bag_db}?mode=ro", uri=True)
    topic_names = dict(connection.execute("SELECT id, name FROM topics"))
    decoders = {
        "/collision/ffb_command": decode_command,
        "/collision/ffb_status": decode_status,
        "/collision/ffb_challenge": decode_challenge,
        "/phase5/mock_odom": decode_odom,
    }
    events: dict[str, list[dict]] = {topic: [] for topic in decoders}
    for topic_id, bag_ns, data in connection.execute(
        "SELECT topic_id, timestamp, data FROM messages ORDER BY timestamp"
    ):
        topic = topic_names[topic_id]
        decoded = decoders[topic](data)
        decoded["bag_ns"] = bag_ns
        events[topic].append(decoded)
    connection.close()

    commands = events["/collision/ffb_command"]
    statuses = events["/collision/ffb_status"]
    challenges = events["/collision/ffb_challenge"]
    odom = events["/phase5/mock_odom"]
    camera_session, camera = camera_rows(args.camera_archive)
    camera_active = [row for row in camera if row["collision_ffb_active"] == "1"]
    camera_warning = [row for row in camera if row["collision_risk_level"] == "WARNING"]
    camera_motion = [
        row for row in camera
        if row["odom_available"] == "1" and float(row["odom_linear_mps"] or 0) > 0.1
    ]
    active_commands = [row for row in commands if row["active"]]
    active_statuses = [row for row in statuses if row["command_active"]]
    fault_statuses = [row for row in statuses if row["fault"]]
    positive_odom = [row for row in odom if row["linear_x"] > 0.1]
    camera_active_sequences = {int(row["collision_ffb_sequence"]) for row in camera_active}
    bag_active_sequences = {row["sequence"] for row in active_commands}
    status_active_sequences = {row["sequence"] for row in active_statuses}
    matching_statuses = [row for row in statuses if row["sequence"] in bag_active_sequences]
    active_command_by_sequence = {row["sequence"]: row for row in active_commands}
    matching_status_delays_ms = [
        (row["bag_ns"] - active_command_by_sequence[row["sequence"]]["bag_ns"]) / 1e6
        for row in matching_statuses
    ]
    fault_ages = [
        float(row["reason"].split(":age=", 1)[1]) * 1000
        for row in fault_statuses if ":age=" in row["reason"]
    ]
    active_header_minus_bag_ms = [
        (row["stamp_ns"] - row["bag_ns"]) / 1e6 for row in active_commands
    ]
    issued_challenges = {
        (row["session_id"], row["token"]): row["bag_ns"]
        for row in challenges
    }
    active_challenge_delays_ms = [
        (row["bag_ns"] - issued_challenges[
            (row["receiver_session_id"], row["receiver_token"])
        ]) / 1e6
        for row in active_commands
        if (row["receiver_session_id"], row["receiver_token"])
        in issued_challenges
    ]

    summary = {
        "camera_session": camera_session,
        "camera_frames": len(camera),
        "camera_detected_frames": sum(row["detected"] == "1" for row in camera),
        "camera_odom_available_frames": sum(row["odom_available"] == "1" for row in camera),
        "camera_motion_frames": len(camera_motion),
        "camera_motion_elapsed_sec": (
            [float(camera_motion[0]["time_sec"]), float(camera_motion[-1]["time_sec"])]
            if camera_motion else None
        ),
        "camera_warning_frames": len(camera_warning),
        "camera_warning_elapsed_sec": (
            [float(camera_warning[0]["time_sec"]), float(camera_warning[-1]["time_sec"])]
            if camera_warning else None
        ),
        "camera_active_frames": len(camera_active),
        "camera_min_finite_ttc_sec": min(
            (
                float(row["ttc_sec"]) for row in camera
                if row["ttc_sec"] and math.isfinite(float(row["ttc_sec"]))
            ),
            default=None,
        ),
        "camera_active_requested_magnitudes": sorted({
            float(row["collision_ffb_requested_magnitude"]) for row in camera_active
        }),
        "camera_active_elapsed_sec": (
            [float(camera_active[0]["time_sec"]), float(camera_active[-1]["time_sec"])]
            if camera_active else None
        ),
        "camera_active_sequences": sorted(camera_active_sequences),
        "camera_ffb_publish_failures": sum(
            row["collision_ffb_publish_success"] == "0" for row in camera
        ),
        "bag_counts": {name: len(rows) for name, rows in events.items()},
        "bag_spans": {name: span(rows) for name, rows in events.items()},
        "bag_odom_speed_counts": dict(sorted(Counter(round(row["linear_x"], 3) for row in odom).items())),
        "bag_positive_odom_count": len(positive_odom),
        "bag_positive_odom_span": span(positive_odom),
        "bag_active_command_count": len(active_commands),
        "bag_active_command_span": span(active_commands),
        "bag_active_command_sequences": sorted(bag_active_sequences),
        "bag_active_commands_with_known_challenge": len(active_challenge_delays_ms),
        "bag_active_challenge_roundtrip_ms": {
            "min": min(active_challenge_delays_ms),
            "max": max(active_challenge_delays_ms),
            "median": median(active_challenge_delays_ms),
        } if active_challenge_delays_ms else None,
        "bag_command_risk_counts": dict(Counter(row["risk_level"] for row in commands)),
        "bag_command_reasons": dict(Counter(row["reason"] for row in commands)),
        "bag_status_modes": dict(Counter(row["output_mode"] for row in statuses)),
        "bag_status_actions": dict(Counter(row["action"] for row in statuses)),
        "bag_active_status_count": len(active_statuses),
        "bag_active_status_span": span(active_statuses),
        "bag_statuses_matching_active_sequences": [
            {key: row[key] for key in (
                "sequence", "output_mode", "action", "command_active",
                "output_active", "requested_magnitude", "applied_magnitude",
                "reason", "fault", "bag_ns",
            )} for row in matching_statuses
        ],
        "active_command_to_status_bag_delay_ms": {
            "min": min(matching_status_delays_ms),
            "max": max(matching_status_delays_ms),
            "median": median(matching_status_delays_ms),
        } if matching_status_delays_ms else None,
        "bag_active_output_count": sum(row["output_active"] for row in statuses),
        "bag_fault_count": len(fault_statuses),
        "bag_fault_categories": dict(Counter(row["reason"].split(":age=", 1)[0] for row in fault_statuses)),
        "bag_fault_age_ms": {
            "min": min(fault_ages), "max": max(fault_ages), "mean": mean(fault_ages),
        } if fault_ages else None,
        "bag_status_last": statuses[-1] if statuses else None,
        "active_sequence_intersection_camera_command": sorted(camera_active_sequences & bag_active_sequences),
        "active_sequence_intersection_command_status": sorted(bag_active_sequences & status_active_sequences),
        "command_stamp_minus_bag_ms": {
            "min": min((row["stamp_ns"] - row["bag_ns"]) / 1e6 for row in commands),
            "max": max((row["stamp_ns"] - row["bag_ns"]) / 1e6 for row in commands),
            "mean": sum(
                (row["stamp_ns"] - row["bag_ns"]) / 1e6
                for row in commands
            ) / len(commands),
        } if commands else None,
        "active_command_stamp_minus_bag_ms": {
            "min": min(active_header_minus_bag_ms),
            "max": max(active_header_minus_bag_ms),
            "median": median(active_header_minus_bag_ms),
        } if active_header_minus_bag_ms else None,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f"{args.artifact_prefix}_bag_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / f"{args.artifact_prefix}_events.csv").open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([
            "topic", "bag_time_jst", "header_time_jst", "sequence", "linear_x_mps",
            "risk_level", "active", "output_mode", "action", "output_active",
            "requested_magnitude", "applied_magnitude", "fault", "reason",
            "receiver_session_id", "receiver_token", "challenge_session_id",
            "challenge_token",
        ])
        for topic, rows in events.items():
            for row in rows:
                writer.writerow([
                    topic, clock(row["bag_ns"]),
                    clock(row["stamp_ns"]) if "stamp_ns" in row else "",
                    row.get("sequence", ""), row.get("linear_x", ""),
                    row.get("risk_level", ""), row.get("active", row.get("command_active", "")),
                    row.get("output_mode", ""), row.get("action", ""),
                    row.get("output_active", ""), row.get("requested_magnitude", row.get("normalized_magnitude", "")),
                    row.get("applied_magnitude", ""), row.get("fault", ""), row.get("reason", ""),
                    row.get("receiver_session_id", ""), row.get("receiver_token", ""),
                    row.get("session_id", ""), row.get("token", ""),
                ])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
