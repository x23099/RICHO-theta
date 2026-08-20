#!/usr/bin/env python3
"""Summarize lateral observation-gate behavior from live recording CSVs.

Inputs may be unpacked recording directories or tar archives.  Archives are
read directly and are never extracted, which makes this suitable for remote,
read-only diagnosis of field recordings.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import tarfile
from pathlib import Path, PurePosixPath


OUTPUT_FIELDS = [
    "experiment_label",
    "source",
    "frames",
    "detected_frames",
    "measurement_accepted_frames",
    "normalized_area_rejection_frames",
    "measurement_acceptance_rate",
    "median_x_m",
    "median_z_m",
    "median_area_px",
    "median_normalized_area",
    "normalized_area_threshold",
    "median_normalized_area_to_threshold",
]


def _number(row, key):
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _flag(row, key):
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def _median(rows, key):
    values = [value for row in rows if (value := _number(row, key)) is not None]
    return statistics.median(values) if values else math.nan


def _threshold(metadata, fallback):
    parameters = metadata.get("parameters", {})
    try:
        value = float(parameters["blue_observation_normalized_area_min"])
    except (KeyError, TypeError, ValueError):
        value = fallback
    return value if value is not None and math.isfinite(value) else math.nan


def _summarize(label, source, metadata, rows, fallback_threshold):
    detected = [row for row in rows if _flag(row, "detected")]
    accepted = [row for row in detected if _flag(row, "measurement_accepted")]
    normalized_rejections = [
        row
        for row in detected
        if row.get("rejection_reason", "") == "normalized_area_gate"
    ]
    threshold = _threshold(metadata, fallback_threshold)
    median_normalized_area = _median(detected, "normalized_area")
    return {
        "experiment_label": metadata.get("experiment_label", label),
        "source": source,
        "frames": len(rows),
        "detected_frames": len(detected),
        "measurement_accepted_frames": len(accepted),
        "normalized_area_rejection_frames": len(normalized_rejections),
        "measurement_acceptance_rate": (
            len(accepted) / len(detected) if detected else math.nan
        ),
        "median_x_m": _median(detected, "x_m"),
        "median_z_m": _median(detected, "z_m"),
        "median_area_px": _median(detected, "area_px"),
        "median_normalized_area": median_normalized_area,
        "normalized_area_threshold": threshold,
        "median_normalized_area_to_threshold": (
            median_normalized_area / threshold
            if math.isfinite(median_normalized_area)
            and math.isfinite(threshold)
            and threshold > 0.0
            else math.nan
        ),
    }


def _load_directory_sessions(source):
    source = source.resolve()
    if (source / "detections.csv").is_file():
        session_dirs = [source]
    else:
        session_dirs = sorted(
            {path.parent for path in source.rglob("detections.csv")}, key=str
        )
    sessions = []
    for session_dir in session_dirs:
        with (session_dir / "detections.csv").open(newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        metadata_path = session_dir / "metadata.json"
        metadata = {}
        if metadata_path.is_file():
            with metadata_path.open() as metadata_file:
                metadata = json.load(metadata_file)
        sessions.append(
            (session_dir.name, str(session_dir), metadata, rows)
        )
    return sessions


def _load_archive_sessions(source):
    collected = {}
    with tarfile.open(source, mode="r:*") as archive:
        # Iterate once: seeking repeatedly in a compressed 360-degree-camera
        # archive would decompress the large video members more than once.
        for member in archive:
            member_path = PurePosixPath(member.name)
            if not member.isfile() or member_path.name not in {
                "detections.csv",
                "metadata.json",
            }:
                continue
            stream = archive.extractfile(member)
            if stream is None:
                continue
            session = collected.setdefault(member_path.parent, {})
            with io.TextIOWrapper(stream, encoding="utf-8", newline="") as file:
                if member_path.name == "detections.csv":
                    session["rows"] = list(csv.DictReader(file))
                else:
                    session["metadata"] = json.load(file)
    sessions = []
    for session_path, values in sorted(collected.items(), key=lambda item: str(item[0])):
        if "rows" not in values:
            continue
        sessions.append(
            (
                session_path.name,
                f"{source.resolve()}::{session_path}",
                values.get("metadata", {}),
                values["rows"],
            )
        )
    return sessions


def load_sessions(inputs):
    sessions = []
    for source in inputs:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"Input does not exist: {source}")
        if source.is_dir():
            sessions.extend(_load_directory_sessions(source))
        elif tarfile.is_tarfile(source):
            sessions.extend(_load_archive_sessions(source))
        else:
            raise ValueError(f"Input is not a recording directory or tar archive: {source}")
    return sessions


def summarize_inputs(inputs, fallback_threshold=None):
    return [
        _summarize(label, source, metadata, rows, fallback_threshold)
        for label, source, metadata, rows in load_sessions(inputs)
    ]


def lateral_pair_diagnosis(summaries):
    usable = [
        row
        for row in summaries
        if row["detected_frames"] > 0 and math.isfinite(row["median_x_m"])
    ]
    left = max(
        (row for row in usable if row["median_x_m"] < 0.0),
        default=None,
        key=lambda row: abs(row["median_x_m"]),
    )
    right = max(
        (row for row in usable if row["median_x_m"] > 0.0),
        default=None,
        key=lambda row: abs(row["median_x_m"]),
    )
    if left is None or right is None:
        return None
    left_norm = left["median_normalized_area"]
    right_norm = right["median_normalized_area"]
    left_z = left["median_z_m"]
    right_z = right["median_z_m"]
    left_area = left["median_area_px"]
    right_area = right["median_area_px"]
    if not all(
        math.isfinite(value) and value > 0.0
        for value in (left_norm, right_norm, left_z, right_z, left_area, right_area)
    ):
        return None
    return {
        "left_label": left["experiment_label"],
        "right_label": right["experiment_label"],
        "normalized_area_ratio_left_to_right": left_norm / right_norm,
        "z_squared_ratio_left_to_right": (left_z / right_z) ** 2,
        "raw_area_ratio_left_to_right": left_area / right_area,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose left/right normalized-area gate asymmetry"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=float)
    args = parser.parse_args()

    summaries = summarize_inputs(args.input, args.threshold)
    if not summaries:
        parser.error("no recording session containing detections.csv was found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(summaries)

    print(f"Sessions: {len(summaries)}")
    diagnosis = lateral_pair_diagnosis(summaries)
    if diagnosis is not None:
        print(
            "Left/right ratios: "
            f"normalized_area={diagnosis['normalized_area_ratio_left_to_right']:.3f}, "
            f"z^2={diagnosis['z_squared_ratio_left_to_right']:.3f}, "
            f"raw_area={diagnosis['raw_area_ratio_left_to_right']:.3f}"
        )
    print(f"Summary saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
