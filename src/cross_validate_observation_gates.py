#!/usr/bin/env python3
"""Leave-one-distance-out validation for the observation quality gate."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from compare_observation_gates import (
    load_observations,
    reference_position,
    replay_variant,
    summarize,
)


OUTPUT_FIELDS = [
    "holdout_session",
    "training_sessions",
    "normalized_area_threshold",
    "stable_inlier_acceptance_rate",
    "outlier_rejection_rate",
    "max_abs_vz_mps",
    "events_track_expired",
    "events_reacquired",
    "mean_reacquisition_delay_frames",
    "max_reacquisition_delay_frames",
    "decision",
]


def session_normalized_area_percentile(rows, percentile=1.0):
    reference_x, reference_z = reference_position(rows)
    values = []
    for row in rows:
        if not row["detected"] or row["phase_label"] != "visible":
            continue
        if math.hypot(
            row["x_m"] - reference_x,
            row["z_m"] - reference_z,
        ) > 0.15:
            continue
        values.append(row["area_px"] * reference_z ** 2)
    if not values:
        raise ValueError(f'No stable inliers for {rows[0]["session"]}')
    return float(np.percentile(values, percentile))


def fit_normalized_area_threshold(training_sessions, safety_factor=0.75):
    """Fit a conservative lower bound from each training session's 1st percentile."""

    per_session_limits = [
        session_normalized_area_percentile(rows)
        for rows in training_sessions.values()
    ]
    return float(safety_factor) * min(per_session_limits)


def decide(summary):
    outlier_ok = (
        math.isnan(summary["outlier_rejection_rate"])
        or summary["outlier_rejection_rate"] >= 0.95
    )
    passed = all(
        [
            summary["stable_inlier_acceptance_rate"] >= 0.98,
            outlier_ok,
            summary["max_abs_vz_mps"] <= 0.30,
            summary["events_track_expired"] == summary["occlusion_events"],
            summary["events_reacquired"] == summary["occlusion_events"],
        ]
    )
    return "PASS" if passed else "FAIL"


def main():
    parser = argparse.ArgumentParser(
        description="Leave one recorded distance out when fitting the gate"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("bird_eye_config.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("gate_leave_one_distance_out.csv")
    )
    args = parser.parse_args()

    with args.config.open() as config_file:
        config = json.load(config_file)
    sessions = load_observations(args.input)
    if len(sessions) < 3:
        raise SystemExit("At least three labelled distance sessions are required")

    output_rows = []
    for holdout_session, holdout_rows in sorted(sessions.items()):
        training = {
            session: rows
            for session, rows in sessions.items()
            if session != holdout_session
        }
        threshold = fit_normalized_area_threshold(training)
        settings = {
            "min_normalized_area": threshold,
            "max_nis": 9.210,
            "confirmation_frames": 2,
        }
        summary = summarize(
            replay_variant(
                holdout_rows,
                config,
                "trained_range_nis99_confirm2",
                settings,
            )
        )
        row = {
            "holdout_session": holdout_session,
            "training_sessions": ";".join(sorted(training)),
            "normalized_area_threshold": threshold,
            "stable_inlier_acceptance_rate": summary[
                "stable_inlier_acceptance_rate"
            ],
            "outlier_rejection_rate": summary["outlier_rejection_rate"],
            "max_abs_vz_mps": summary["max_abs_vz_mps"],
            "events_track_expired": summary["events_track_expired"],
            "events_reacquired": summary["events_reacquired"],
            "mean_reacquisition_delay_frames": summary[
                "mean_reacquisition_delay_frames"
            ],
            "max_reacquisition_delay_frames": summary[
                "max_reacquisition_delay_frames"
            ],
            "decision": decide(summary),
        }
        output_rows.append(row)
        print(
            f'{holdout_session}: threshold={threshold:.1f}, '
            f'accept={row["stable_inlier_acceptance_rate"]:.1%}, '
            f'outlier_reject={row["outlier_rejection_rate"]:.1%}, '
            f'max|vz|={row["max_abs_vz_mps"]:.3f}, '
            f'decision={row["decision"]}'
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(output_rows)
    overall = "PASS" if all(row["decision"] == "PASS" for row in output_rows) else "FAIL"
    print(f"Overall leave-one-distance-out decision: {overall}")
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
