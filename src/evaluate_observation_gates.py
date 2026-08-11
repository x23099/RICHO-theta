#!/usr/bin/env python3
"""Recompute ground-contact observations from recorded raw video.

This module is intentionally independent from Qt and YOLO.  Recording metadata
provides the camera geometry that was active during capture, while the current
configuration provides the ground-contact detector and lateral calibration.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Iterable, Mapping

import cv2

from ground_contact import detect_blue_ground_contact
from obstacle_tracking import BlueObstacleTracker


OUTPUT_FIELDS = [
    "session",
    "session_path",
    "frame",
    "time_sec",
    "occlusion_event",
    "phase_label",
    "detected",
    "source_pixel_x",
    "source_pixel_y",
    "raw_x_m",
    "raw_z_m",
    "raw_distance_m",
    "x_m",
    "z_m",
    "distance_m",
    "area_px",
    "contact_samples",
    "bbox_width_px",
    "bbox_height_px",
    "bbox_aspect_ratio",
    "bbox_fill_ratio",
    "contour_solidity",
    "measurement_available",
    "measurement_accepted",
    "rejection_reason",
    "predicted_x_m",
    "predicted_z_m",
    "innovation_x_m",
    "innovation_z_m",
    "innovation_cov_xx",
    "innovation_cov_xz",
    "innovation_cov_zz",
    "nis",
    "track_available",
    "track_predicted",
    "filtered_x_m",
    "filtered_z_m",
    "filtered_distance_m",
    "relative_vx_mps",
    "relative_vz_mps",
    "missing_age_sec",
]


def find_session_directories(inputs: Iterable[Path]) -> list[Path]:
    """Return recording directories containing both raw video and metadata."""

    sessions: set[Path] = set()
    for source in inputs:
        source = source.resolve()
        if not source.exists():
            raise FileNotFoundError(f"Input does not exist: {source}")
        if source.is_file():
            raise ValueError(f"Input must be a recording directory: {source}")
        if (source / "raw.avi").is_file() and (source / "metadata.json").is_file():
            sessions.add(source)
            continue
        for video_path in source.rglob("raw.avi"):
            session_dir = video_path.parent
            if (session_dir / "metadata.json").is_file():
                sessions.add(session_dir.resolve())
    return sorted(sessions, key=str)


def load_detector_parameters(
    session_dir: Path,
    current_config: Mapping[str, object],
) -> dict:
    """Combine capture-time camera geometry with current detector settings."""

    with (session_dir / "metadata.json").open() as metadata_file:
        parameters = dict(json.load(metadata_file)["parameters"])
    for key, value in current_config.items():
        if key.startswith("blue_ground_contact_"):
            parameters[key] = value
    return parameters


def load_phase_labels(label_path: Path) -> dict[str, list[dict]]:
    """Load and validate non-overlapping inclusive frame intervals."""

    labels: dict[str, list[dict]] = {}
    with label_path.open(newline="") as label_file:
        for row in csv.DictReader(label_file):
            interval = dict(row)
            interval["start_frame"] = int(row["start_frame"])
            interval["end_frame"] = int(row["end_frame"])
            if interval["end_frame"] < interval["start_frame"]:
                raise ValueError(f"Invalid label interval: {row}")
            labels.setdefault(row["session"], []).append(interval)
    for session, intervals in labels.items():
        intervals.sort(key=lambda item: item["start_frame"])
        previous_end = -1
        for interval in intervals:
            if interval["start_frame"] <= previous_end:
                raise ValueError(f"Overlapping label intervals for {session}")
            previous_end = interval["end_frame"]
    return labels


def phase_for_frame(intervals: Iterable[dict], frame_index: int) -> tuple[str, str]:
    for interval in intervals:
        if interval["start_frame"] <= frame_index <= interval["end_frame"]:
            return interval.get("event", ""), interval["phase"]
    return "", ""


def contour_shape_features(contour) -> dict[str, float]:
    """Return scale-independent contour quality features."""

    x, y, width, height = cv2.boundingRect(contour)
    del x, y
    area = float(cv2.contourArea(contour))
    bounding_area = float(width * height)
    hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
    return {
        "bbox_width_px": int(width),
        "bbox_height_px": int(height),
        "bbox_aspect_ratio": width / height if height else math.nan,
        "bbox_fill_ratio": area / bounding_area if bounding_area else math.nan,
        "contour_solidity": area / hull_area if hull_area else math.nan,
    }


def recompute_session(
    session_dir: Path,
    current_config: Mapping[str, object],
    frame_step: int = 1,
    phase_intervals: Iterable[dict] = (),
    source_label: str | None = None,
) -> tuple[list[dict], dict]:
    """Recompute observations for one session and return rows and a summary."""

    frame_step = max(1, int(frame_step))
    parameters = load_detector_parameters(session_dir, current_config)
    min_area_px = float(parameters.get("blue_ground_contact_min_area", 300.0))
    contact_fraction = float(
        parameters.get("blue_ground_contact_fraction", 0.08)
    )
    x_scale = float(parameters.get("blue_ground_contact_x_scale", 1.0))
    x_offset_m = float(
        parameters.get("blue_ground_contact_x_offset_m", 0.0)
    )
    z_offset_m = float(
        parameters.get("blue_ground_contact_z_offset_m", 0.0)
    )
    tracker = BlueObstacleTracker(
        process_accel_std_mps2=float(
            current_config.get("blue_tracking_process_accel_std_mps2", 1.5)
        ),
        measurement_std_m=float(
            current_config.get("blue_tracking_measurement_std_m", 0.03)
        ),
        max_missing_sec=float(
            current_config.get("blue_tracking_max_missing_sec", 0.25)
        ),
        max_dt_sec=float(
            current_config.get("blue_tracking_max_dt_sec", 0.2)
        ),
    )

    video_path = session_dir / "raw.avi"
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps < 1.0 or fps > 120.0:
        fps = 30.0

    rows = []
    frame_index = 0
    processed_frames = 0
    detected_frames = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % frame_step != 0:
                frame_index += 1
                continue

            detection, _ = detect_blue_ground_contact(
                frame,
                parameters,
                min_area_px=min_area_px,
                contact_fraction=contact_fraction,
            )
            row = {
                "session": session_dir.name,
                "session_path": (
                    f"{source_label}::{session_dir.name}"
                    if source_label
                    else str(session_dir)
                ),
                "frame": frame_index,
                "time_sec": frame_index / fps,
                "occlusion_event": "",
                "phase_label": "",
                "detected": int(detection is not None),
                "source_pixel_x": "",
                "source_pixel_y": "",
                "raw_x_m": "",
                "raw_z_m": "",
                "raw_distance_m": "",
                "x_m": "",
                "z_m": "",
                "distance_m": "",
                "area_px": "",
                "contact_samples": "",
                "bbox_width_px": "",
                "bbox_height_px": "",
                "bbox_aspect_ratio": "",
                "bbox_fill_ratio": "",
                "contour_solidity": "",
            }
            event, phase = phase_for_frame(phase_intervals, frame_index)
            row["occlusion_event"] = event
            row["phase_label"] = phase
            measurement = None
            if detection is not None:
                raw_x_m = float(detection["x_m"])
                raw_z_m = float(detection["z_m"])
                x_m = raw_x_m * x_scale + x_offset_m
                z_m = raw_z_m + z_offset_m
                row.update(
                    source_pixel_x=float(detection["pixel_x"]),
                    source_pixel_y=float(detection["pixel_y"]),
                    raw_x_m=raw_x_m,
                    raw_z_m=raw_z_m,
                    raw_distance_m=math.hypot(raw_x_m, raw_z_m),
                    x_m=x_m,
                    z_m=z_m,
                    distance_m=math.hypot(x_m, z_m),
                    area_px=float(detection["area_px"]),
                    contact_samples=int(detection["contact_samples"]),
                )
                row.update(contour_shape_features(detection["contour"]))
                measurement = (x_m, z_m)
                detected_frames += 1
            track, diagnostics = tracker.update_with_diagnostics(
                measurement,
                timestamp=frame_index / fps,
            )
            row.update(diagnostics)
            row.update(
                track_available=int(track is not None),
                track_predicted=(int(track["predicted"]) if track else ""),
                filtered_x_m=(track["x_m"] if track else ""),
                filtered_z_m=(track["z_m"] if track else ""),
                filtered_distance_m=(track["distance_m"] if track else ""),
                relative_vx_mps=(track["vx_mps"] if track else ""),
                relative_vz_mps=(track["vz_mps"] if track else ""),
                missing_age_sec=(track["missing_age_sec"] if track else ""),
            )
            rows.append(row)
            processed_frames += 1
            frame_index += 1
    finally:
        capture.release()

    summary = {
        "session": session_dir.name,
        "session_path": str(session_dir),
        "video_frames": frame_index,
        "processed_frames": processed_frames,
        "detected_frames": detected_frames,
        "detection_rate": (
            detected_frames / processed_frames if processed_frames else 0.0
        ),
        "fps": fps,
    }
    return rows, summary


def write_csv(rows: Iterable[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute ground-contact observations from recorded raw.avi files"
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        required=True,
        help="Recording session or a root containing sessions; repeatable",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("bird_eye_config.json"),
    )
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument(
        "--source-label",
        help="Stable source identifier stored instead of the extracted directory path",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        help="Optional CSV containing session/event/phase/start_frame/end_frame",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("observation_replay.csv"),
    )
    args = parser.parse_args()

    with args.config.open() as config_file:
        current_config = json.load(config_file)
    phase_labels = load_phase_labels(args.labels) if args.labels else {}
    sessions = find_session_directories(args.input)
    if not sessions:
        raise SystemExit("No recording sessions with raw.avi and metadata.json found")

    all_rows = []
    summaries = []
    for session_dir in sessions:
        rows, summary = recompute_session(
            session_dir,
            current_config,
            frame_step=args.frame_step,
            phase_intervals=phase_labels.get(session_dir.name, ()),
            source_label=args.source_label,
        )
        all_rows.extend(rows)
        summaries.append(summary)
        print(
            f'{summary["session"]}: '
            f'{summary["detected_frames"]}/{summary["processed_frames"]} '
            f'detected ({summary["detection_rate"]:.1%}), '
            f'video_frames={summary["video_frames"]}, '
            f'fps={summary["fps"]:.2f}'
        )

    write_csv(all_rows, args.output)
    print(f"Sessions: {len(summaries)}")
    print(f"Rows: {len(all_rows)}")
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
