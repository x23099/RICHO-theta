#!/usr/bin/env python3
"""Compare false blue candidates with stable target contours."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np


OUTPUT_FIELDS = [
    "class",
    "sources",
    "sessions",
    "observations",
    "max_aspect_ratio",
    "candidate_accepted",
    "candidate_acceptance_rate",
    "area_min_px",
    "area_median_px",
    "area_max_px",
    "aspect_min",
    "aspect_p01",
    "aspect_p05",
    "aspect_median",
    "aspect_p95",
    "aspect_p99",
    "aspect_max",
    "fill_median",
    "solidity_median",
    "source_pixel_x_median",
    "source_pixel_y_median",
    "raw_distance_median_m",
]


def _number(row, field):
    try:
        value = float(row.get(field, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def load_detected(paths):
    rows = []
    for path in paths:
        with Path(path).open(newline="") as input_file:
            rows.extend(
                row
                for row in csv.DictReader(input_file)
                if row.get("detected", "").strip().lower()
                in {"1", "true", "yes"}
            )
    return rows


def stable_target_rows(rows, position_tolerance_m=0.15):
    """Keep position-consistent visible/reappearing target observations."""

    sessions = defaultdict(list)
    for row in rows:
        sessions[row.get("session", "")].append(row)

    stable = []
    for session_rows in sessions.values():
        visible = [
            row for row in session_rows if row.get("phase_label", "") == "visible"
        ]
        reference_rows = visible or session_rows
        positions = [
            (_number(row, "x_m"), _number(row, "z_m"))
            for row in reference_rows
        ]
        positions = [(x, z) for x, z in positions if x is not None and z is not None]
        if not positions:
            continue
        reference = np.median(np.asarray(positions), axis=0)
        has_phase_labels = any(row.get("phase_label", "") for row in session_rows)
        for row in session_rows:
            phase = row.get("phase_label", "")
            if has_phase_labels and phase not in {"visible", "reappearing"}:
                continue
            x_m = _number(row, "x_m")
            z_m = _number(row, "z_m")
            if x_m is None or z_m is None:
                continue
            if math.hypot(x_m - reference[0], z_m - reference[1]) <= position_tolerance_m:
                stable.append(row)
    return stable


def _values(rows, field):
    return [value for row in rows if (value := _number(row, field)) is not None]


def summarize(class_name, sources, rows, max_aspect_ratio):
    aspects = np.asarray(_values(rows, "bbox_aspect_ratio"), dtype=float)
    if not len(aspects):
        raise ValueError(f"No contour aspect ratios for {class_name}")
    areas = np.asarray(_values(rows, "area_px"), dtype=float)

    def median(field):
        values = _values(rows, field)
        return float(np.median(values)) if values else math.nan

    quantiles = np.quantile(aspects, [0.0, 0.01, 0.05, 0.5, 0.95, 0.99, 1.0])
    accepted = int(np.count_nonzero(aspects <= max_aspect_ratio))
    return {
        "class": class_name,
        "sources": ";".join(str(Path(source)) for source in sources),
        "sessions": len({row.get("session", "") for row in rows}),
        "observations": len(rows),
        "max_aspect_ratio": max_aspect_ratio,
        "candidate_accepted": accepted,
        "candidate_acceptance_rate": accepted / len(aspects),
        "area_min_px": float(np.min(areas)),
        "area_median_px": float(np.median(areas)),
        "area_max_px": float(np.max(areas)),
        "aspect_min": quantiles[0],
        "aspect_p01": quantiles[1],
        "aspect_p05": quantiles[2],
        "aspect_median": quantiles[3],
        "aspect_p95": quantiles[4],
        "aspect_p99": quantiles[5],
        "aspect_max": quantiles[6],
        "fill_median": median("bbox_fill_ratio"),
        "solidity_median": median("contour_solidity"),
        "source_pixel_x_median": median("source_pixel_x"),
        "source_pixel_y_median": median("source_pixel_y"),
        "raw_distance_median_m": median("raw_distance_m"),
    }


def compare(no_target_inputs, target_inputs, max_aspect_ratio=1.5, position_tolerance_m=0.15):
    no_target = load_detected(no_target_inputs)
    target = stable_target_rows(
        load_detected(target_inputs), position_tolerance_m=position_tolerance_m
    )
    return [
        summarize("no_target_false_candidate", no_target_inputs, no_target, max_aspect_ratio),
        summarize("stable_blue_target", target_inputs, target, max_aspect_ratio),
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Compare no-target false contours with stable blue targets"
    )
    parser.add_argument("--no-target-input", type=Path, action="append", required=True)
    parser.add_argument("--target-input", type=Path, action="append", required=True)
    parser.add_argument("--max-aspect-ratio", type=float, default=1.5)
    parser.add_argument("--position-tolerance-m", type=float, default=0.15)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = compare(
        args.no_target_input,
        args.target_input,
        max_aspect_ratio=args.max_aspect_ratio,
        position_tolerance_m=args.position_tolerance_m,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Shape comparison saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
