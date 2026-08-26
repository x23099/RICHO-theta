#!/usr/bin/env python3
"""Diagnose frame-interval behavior in live recording CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from frame_timing import PROCESSING_TIMING_FIELDS


OUTPUT_FIELDS = [
    "experiment_label",
    "session_dir",
    "frames",
    "requested_fps",
    "effective_fps",
    "fps_within_one_percent",
    "dt_median_ms",
    "dt_p90_ms",
    "dt_p95_ms",
    "dt_p99_ms",
    "dt_max_ms",
    "dt_over_40ms_rate",
    "dt_over_50ms_rate",
    "first_half_fps",
    "last_half_fps",
    "raw_kib_per_frame",
    "bev_kib_per_frame",
    "detection_kib_per_frame",
    "odom_poll_median_ms",
    "capture_read_median_ms",
    "bev_preprocess_median_ms",
    "blue_pipeline_median_ms",
    "ai_perception_median_ms",
    "overlay_render_median_ms",
    "display_median_ms",
    "video_write_median_ms",
    "processing_total_median_ms",
    "processing_over_budget_rate",
]


TIMING_SUMMARY_FIELDS = {
    "processing_odom_poll_ms": "odom_poll_median_ms",
    "processing_capture_read_ms": "capture_read_median_ms",
    "processing_bev_preprocess_ms": "bev_preprocess_median_ms",
    "processing_blue_pipeline_ms": "blue_pipeline_median_ms",
    "processing_ai_perception_ms": "ai_perception_median_ms",
    "processing_overlay_render_ms": "overlay_render_median_ms",
    "processing_display_ms": "display_median_ms",
    "processing_video_write_ms": "video_write_median_ms",
    "processing_total_before_csv_ms": "processing_total_median_ms",
}
assert set(TIMING_SUMMARY_FIELDS) == set(PROCESSING_TIMING_FIELDS)


def _timestamps(rows):
    for field in ("monotonic_time_sec", "time_sec"):
        try:
            values = np.asarray([float(row[field]) for row in rows], dtype=float)
        except (KeyError, TypeError, ValueError):
            continue
        if len(values) >= 2 and np.all(np.isfinite(values)):
            return values
    raise ValueError("Recording has fewer than two valid timestamps")


def summarize_rows(label, source, metadata, rows, video_sizes=None):
    times = _timestamps(rows)
    deltas = np.diff(times)
    if np.any(deltas <= 0.0):
        raise ValueError(f"Non-increasing timestamp in {source}")
    requested = float(metadata.get("requested_camera_fps", 30.0))
    effective = (len(times) - 1) / (times[-1] - times[0])
    midpoint = max(1, len(deltas) // 2)
    first = 1.0 / float(np.mean(deltas[:midpoint]))
    last = 1.0 / float(np.mean(deltas[midpoint:]))
    quantiles = np.quantile(deltas, [0.5, 0.9, 0.95, 0.99, 1.0]) * 1000.0
    sizes = video_sizes or {}

    def kib_per_frame(name):
        return sizes.get(name, math.nan) / len(rows) / 1024.0

    timing_summary = {}
    for source_field, output_field in TIMING_SUMMARY_FIELDS.items():
        values = []
        for row in rows:
            try:
                value = float(row.get(source_field, ""))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
        timing_summary[output_field] = (
            float(np.median(values)) if values else math.nan
        )
    total_values = []
    for row in rows:
        try:
            value = float(row.get("processing_total_before_csv_ms", ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            total_values.append(value)
    over_budget_rate = (
        float(np.mean(np.asarray(total_values) > 1000.0 / requested))
        if total_values and requested > 0.0
        else math.nan
    )

    return {
        "experiment_label": metadata.get("experiment_label", label),
        "session_dir": source,
        "frames": len(rows),
        "requested_fps": requested,
        "effective_fps": effective,
        "fps_within_one_percent": int(abs(effective - requested) <= requested * 0.01),
        "dt_median_ms": quantiles[0],
        "dt_p90_ms": quantiles[1],
        "dt_p95_ms": quantiles[2],
        "dt_p99_ms": quantiles[3],
        "dt_max_ms": quantiles[4],
        "dt_over_40ms_rate": float(np.mean(deltas > 0.040)),
        "dt_over_50ms_rate": float(np.mean(deltas > 0.050)),
        "first_half_fps": first,
        "last_half_fps": last,
        "raw_kib_per_frame": kib_per_frame("raw"),
        "bev_kib_per_frame": kib_per_frame("bev"),
        "detection_kib_per_frame": kib_per_frame("detection"),
        **timing_summary,
        "processing_over_budget_rate": over_budget_rate,
    }


def find_sessions(inputs):
    sessions = set()
    for source in inputs:
        source = Path(source)
        if (source / "detections.csv").is_file():
            sessions.add(source.resolve())
        elif source.is_dir():
            sessions.update(path.parent.resolve() for path in source.rglob("detections.csv"))
        else:
            raise ValueError(f"Input is not a recording directory: {source}")
    return sorted(sessions, key=str)


def summarize_session(session_dir):
    with (session_dir / "detections.csv").open(newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    metadata = {}
    if (session_dir / "metadata.json").is_file():
        with (session_dir / "metadata.json").open() as metadata_file:
            metadata = json.load(metadata_file)
    video_sizes = {
        name: (session_dir / f"{name}.avi").stat().st_size
        for name in ("raw", "bev", "detection")
        if (session_dir / f"{name}.avi").is_file()
    }
    return summarize_rows(session_dir.name, str(session_dir), metadata, rows, video_sizes)


def main():
    parser = argparse.ArgumentParser(description="Summarize recording frame intervals")
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = [summarize_session(path) for path in find_sessions(args.input)]
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    if not rows:
        parser.error("no recording sessions were found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Timing diagnosis saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
