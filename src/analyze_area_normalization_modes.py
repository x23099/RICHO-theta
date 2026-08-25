#!/usr/bin/env python3
"""Screen contour-area normalization coordinates on recorded observations.

This is an exploratory, offline comparison.  A session's robust reference
position stands in for the track prediction so that a corrupted observation
cannot increase its own normalized-area score.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


MODES = (
    "forward_z",
    "calibrated_ground_distance",
    "raw_ground_distance",
)

OUTPUT_FIELDS = [
    "dataset_role",
    "source",
    "session",
    "normalization_mode",
    "threshold",
    "reference_x_m",
    "reference_z_m",
    "reference_ground_distance_m",
    "reference_raw_ground_distance_m",
    "detected_observations",
    "stable_inlier_observations",
    "stable_inlier_accepted",
    "stable_inlier_acceptance_rate",
    "outlier_observations",
    "outlier_rejected",
    "outlier_rejection_rate",
    "median_normalized_area",
    "stable_acceptance_decision",
]


def _optional_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _flag(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_sessions(path: Path):
    sessions = {}
    with path.open(newline="") as input_file:
        for row in csv.DictReader(input_file):
            row["detected"] = _flag(row.get("detected"))
            for field in (
                "x_m",
                "z_m",
                "raw_distance_m",
                "area_px",
            ):
                row[field] = _optional_float(row.get(field))
            sessions.setdefault(row["session"], []).append(row)
    return sessions


def _reference_rows(rows):
    detected = [
        row
        for row in rows
        if row["detected"]
        and all(
            row[field] is not None
            for field in ("x_m", "z_m", "raw_distance_m", "area_px")
        )
    ]
    visible = [row for row in detected if row.get("phase_label") == "visible"]
    reference = visible or detected
    if not reference:
        session = rows[0].get("session", "unknown") if rows else "unknown"
        raise ValueError(f"No complete detected observation in session {session}")
    return detected, reference


def reference_position(rows):
    """Return robust calibrated and raw ground-plane reference distances."""

    _detected, reference = _reference_rows(rows)
    reference_x = statistics.median(row["x_m"] for row in reference)
    reference_z = statistics.median(row["z_m"] for row in reference)
    reference_raw_distance = statistics.median(
        row["raw_distance_m"] for row in reference
    )
    return {
        "x_m": reference_x,
        "z_m": reference_z,
        "ground_distance_m": math.hypot(reference_x, reference_z),
        "raw_ground_distance_m": reference_raw_distance,
    }


def normalization_distance(reference, mode):
    if mode == "forward_z":
        return reference["z_m"]
    if mode == "calibrated_ground_distance":
        return reference["ground_distance_m"]
    if mode == "raw_ground_distance":
        return reference["raw_ground_distance_m"]
    raise ValueError(f"Unsupported normalization mode: {mode}")


def normalized_area(area_px, reference, mode):
    distance = normalization_distance(reference, mode)
    return float(area_px) * max(float(distance), 0.2) ** 2


def summarize_session(rows, mode, threshold):
    detected, _reference = _reference_rows(rows)
    reference = reference_position(rows)
    reference_x = reference["x_m"]
    reference_z = reference["z_m"]

    for row in detected:
        row["position_inlier"] = math.hypot(
            row["x_m"] - reference_x,
            row["z_m"] - reference_z,
        ) <= 0.15
        row["score"] = normalized_area(row["area_px"], reference, mode)

    has_phase_labels = any(row.get("phase_label") for row in rows)
    stable = [
        row
        for row in detected
        if row["position_inlier"]
        and (not has_phase_labels or row.get("phase_label") == "visible")
    ]
    outliers = [row for row in detected if not row["position_inlier"]]
    stable_accepted = sum(row["score"] >= threshold for row in stable)
    outlier_rejected = sum(row["score"] < threshold for row in outliers)

    def rate(numerator, denominator):
        return numerator / denominator if denominator else math.nan

    stable_rate = rate(stable_accepted, len(stable))
    outlier_rate = rate(outlier_rejected, len(outliers))
    return {
        "reference_x_m": reference_x,
        "reference_z_m": reference_z,
        "reference_ground_distance_m": reference["ground_distance_m"],
        "reference_raw_ground_distance_m": reference[
            "raw_ground_distance_m"
        ],
        "detected_observations": len(detected),
        "stable_inlier_observations": len(stable),
        "stable_inlier_accepted": stable_accepted,
        "stable_inlier_acceptance_rate": stable_rate,
        "outlier_observations": len(outliers),
        "outlier_rejected": outlier_rejected,
        "outlier_rejection_rate": outlier_rate,
        "median_normalized_area": statistics.median(
            row["score"] for row in detected
        ),
        # This tool selects a range-normalization coordinate only.  Position
        # outliers remain the responsibility of the combined NIS gate and are
        # reported above without being folded into this screening decision.
        "stable_acceptance_decision": (
            "PASS" if stable_rate >= 0.98 else "FAIL"
        ),
    }


def evaluate_inputs(inputs, thresholds):
    output_rows = []
    for role, path in inputs:
        for session, rows in sorted(load_sessions(path).items()):
            for mode in MODES:
                for threshold in thresholds:
                    summary = summarize_session(rows, mode, threshold)
                    output_rows.append(
                        {
                            "dataset_role": role,
                            "source": str(path),
                            "session": session,
                            "normalization_mode": mode,
                            "threshold": threshold,
                            **summary,
                        }
                    )
    return output_rows


def _role_inputs(args):
    return [
        *(("development", path) for path in args.development_input),
        *(("diagnostic", path) for path in args.diagnostic_input),
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Compare range coordinates used to normalize contour area"
    )
    parser.add_argument(
        "--development-input", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--diagnostic-input", type=Path, action="append", default=[]
    )
    parser.add_argument("--threshold", type=float, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = _role_inputs(args)
    if not inputs:
        parser.error("at least one development or diagnostic input is required")
    missing = [path for _role, path in inputs if not path.is_file()]
    if missing:
        parser.error(f"input does not exist: {missing[0]}")

    thresholds = args.threshold or [1800.0, 2000.0, 2503.678448310634]
    rows = evaluate_inputs(inputs, thresholds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    for mode in MODES:
        for threshold in thresholds:
            selected = [
                row
                for row in rows
                if row["normalization_mode"] == mode
                and row["threshold"] == threshold
            ]
            min_acceptance = min(
                row["stable_inlier_acceptance_rate"] for row in selected
            )
            print(
                f"mode={mode}, threshold={threshold:.1f}, "
                f"sessions={len(selected)}, min_stable_accept={min_acceptance:.1%}, "
                f"pass={sum(row['stable_acceptance_decision'] == 'PASS' for row in selected)}/"
                f"{len(selected)}"
            )
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
