#!/usr/bin/env python3
"""Replay recorded observations through candidate quality gates."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from obstacle_tracking import BlueObstacleTracker, ObstacleObservationGate


VARIANTS = {
    "baseline": {},
    "fixed_area_2000": {"min_area_px": 2000.0},
    "range_normalized_area": {"min_normalized_area": 3000.0},
    "shape": {"min_fill_ratio": 0.60, "min_solidity": 0.70},
    "nis_95": {"max_nis": 5.991},
    "range_nis99_confirm2": {
        "min_normalized_area": 3000.0,
        "max_nis": 9.210,
        "confirmation_frames": 2,
    },
    "hybrid_confirm3": {
        "min_normalized_area": 3000.0,
        "min_fill_ratio": 0.60,
        "min_solidity": 0.70,
        "max_nis": 5.991,
        "confirmation_frames": 3,
    },
}

DETAIL_FIELDS = [
    "variant",
    "session",
    "frame",
    "time_sec",
    "occlusion_event",
    "phase_label",
    "detected",
    "position_inlier",
    "measurement_accepted",
    "rejection_reason",
    "nis",
    "track_available",
    "track_predicted",
    "filtered_x_m",
    "filtered_z_m",
    "relative_vx_mps",
    "relative_vz_mps",
]

SUMMARY_FIELDS = [
    "variant",
    "session",
    "detected_observations",
    "stable_inlier_observations",
    "stable_inlier_accepted",
    "stable_inlier_acceptance_rate",
    "outlier_observations",
    "outlier_rejected",
    "outlier_rejection_rate",
    "partial_observations",
    "partial_rejected",
    "partial_rejection_rate",
    "accepted_outliers",
    "max_abs_vz_mps",
    "p99_abs_vz_mps",
    "occlusion_events",
    "events_track_expired",
    "events_reacquired",
    "mean_reacquisition_delay_frames",
    "max_reacquisition_delay_frames",
]


def optional_float(value):
    return float(value) if value not in {None, ""} else None


def load_observations(path: Path) -> dict[str, list[dict]]:
    sessions: dict[str, list[dict]] = defaultdict(list)
    with path.open(newline="") as input_file:
        for row in csv.DictReader(input_file):
            row["frame"] = int(row["frame"])
            row["time_sec"] = float(row["time_sec"])
            row["detected"] = row["detected"] == "1"
            for field in (
                "x_m",
                "z_m",
                "area_px",
                "bbox_fill_ratio",
                "contour_solidity",
            ):
                row[field] = optional_float(row[field])
            sessions[row["session"]].append(row)
    for rows in sessions.values():
        rows.sort(key=lambda row: row["frame"])
    return dict(sessions)


def reference_position(rows: list[dict]) -> tuple[float, float]:
    visible = [
        (row["x_m"], row["z_m"])
        for row in rows
        if row["phase_label"] == "visible" and row["detected"]
    ]
    if not visible:
        raise ValueError(f'No visible observations for {rows[0]["session"]}')
    return tuple(np.median(np.asarray(visible), axis=0))


def external_rejection_reason(row, settings, predicted_z_m):
    gate = ObstacleObservationGate(**settings)
    measurement = (
        (row.get("x_m", 0.0), row.get("z_m", predicted_z_m))
        if row["detected"]
        else None
    )
    _, diagnostics = gate.filter_measurement(
        measurement,
        area_px=row.get("area_px"),
        predicted_z_m=predicted_z_m,
        tracker_initialized=True,
        fill_ratio=row.get("bbox_fill_ratio"),
        solidity=row.get("contour_solidity"),
    )
    return diagnostics["gate_rejection_reason"]


def replay_variant(rows, config, variant, settings):
    tracker = BlueObstacleTracker(
        process_accel_std_mps2=config["blue_tracking_process_accel_std_mps2"],
        measurement_std_m=config["blue_tracking_measurement_std_m"],
        max_missing_sec=config["blue_tracking_max_missing_sec"],
        max_dt_sec=config["blue_tracking_max_dt_sec"],
    )
    gate = ObstacleObservationGate(**settings)
    reference_x, reference_z = reference_position(rows)
    details = []

    for row in rows:
        timestamp = row["time_sec"]
        projected_position = tracker.projected_position(timestamp=timestamp)
        predicted_z_m = (
            projected_position[1]
            if projected_position is not None
            else (row["z_m"] if row["z_m"] is not None else reference_z)
        )
        raw_measurement = (
            (row["x_m"], row["z_m"]) if row["detected"] else None
        )
        measurement, gate_diagnostics = gate.filter_measurement(
            raw_measurement,
            area_px=row["area_px"],
            predicted_z_m=predicted_z_m,
            tracker_initialized=tracker.initialized,
            fill_ratio=row["bbox_fill_ratio"],
            solidity=row["contour_solidity"],
        )

        track, diagnostics = tracker.update_with_diagnostics(
            measurement,
            timestamp=timestamp,
            max_nis=gate.max_nis if gate.enabled else None,
        )
        if raw_measurement is not None and measurement is None:
            diagnostics["measurement_available"] = True
            diagnostics["measurement_accepted"] = False
            diagnostics["rejection_reason"] = gate_diagnostics[
                "gate_rejection_reason"
            ]

        position_inlier = False
        if row["detected"]:
            position_inlier = math.hypot(
                row["x_m"] - reference_x,
                row["z_m"] - reference_z,
            ) <= 0.15
        details.append(
            {
                "variant": variant,
                "session": row["session"],
                "frame": row["frame"],
                "time_sec": timestamp,
                "occlusion_event": row["occlusion_event"],
                "phase_label": row["phase_label"],
                "detected": int(row["detected"]),
                "position_inlier": int(position_inlier),
                "measurement_accepted": int(
                    diagnostics["measurement_accepted"]
                ),
                "rejection_reason": diagnostics["rejection_reason"],
                "nis": diagnostics["nis"],
                "track_available": int(track is not None),
                "track_predicted": int(track["predicted"]) if track else "",
                "filtered_x_m": track["x_m"] if track else "",
                "filtered_z_m": track["z_m"] if track else "",
                "relative_vx_mps": track["vx_mps"] if track else "",
                "relative_vz_mps": track["vz_mps"] if track else "",
            }
        )
    return details


def summarize(details):
    detected = [row for row in details if row["detected"]]
    stable_inliers = [
        row
        for row in detected
        if row["phase_label"] == "visible" and row["position_inlier"]
    ]
    outliers = [row for row in detected if not row["position_inlier"]]
    partial = [
        row for row in detected if row["phase_label"] == "partial_occlusion"
    ]
    velocities = [
        abs(float(row["relative_vz_mps"]))
        for row in details
        if row["relative_vz_mps"] != ""
    ]
    event_ids = sorted(
        {
            row["occlusion_event"]
            for row in details
            if row["occlusion_event"] not in {"", "0"}
        },
        key=lambda event_id: min(
            row["frame"]
            for row in details
            if row["occlusion_event"] == event_id
        ),
    )
    expired = 0
    reacquired = 0
    reacquisition_delays = []
    for event_index, event_id in enumerate(event_ids):
        full = [
            row
            for row in details
            if row["occlusion_event"] == event_id
            and row["phase_label"] == "fully_occluded"
        ]
        full_end = max(row["frame"] for row in full)
        if event_index + 1 < len(event_ids):
            next_event_id = event_ids[event_index + 1]
            post_end = min(
                row["frame"]
                for row in details
                if row["occlusion_event"] == next_event_id
            ) - 1
        else:
            post_end = details[-1]["frame"]
        post_occlusion = [
            row
            for row in details
            if full_end < row["frame"] <= post_end
        ]
        if any(not row["track_available"] for row in full):
            expired += 1
        accepted_frames = [
            row["frame"]
            for row in post_occlusion
            if row["measurement_accepted"] and row["position_inlier"]
        ]
        if accepted_frames:
            reacquired += 1
            reacquisition_delays.append(min(accepted_frames) - full_end)

    def rate(numerator, denominator):
        return numerator / denominator if denominator else math.nan

    stable_accepted = sum(row["measurement_accepted"] for row in stable_inliers)
    outlier_rejected = sum(not row["measurement_accepted"] for row in outliers)
    partial_rejected = sum(not row["measurement_accepted"] for row in partial)
    return {
        "variant": details[0]["variant"],
        "session": details[0]["session"],
        "detected_observations": len(detected),
        "stable_inlier_observations": len(stable_inliers),
        "stable_inlier_accepted": stable_accepted,
        "stable_inlier_acceptance_rate": rate(stable_accepted, len(stable_inliers)),
        "outlier_observations": len(outliers),
        "outlier_rejected": outlier_rejected,
        "outlier_rejection_rate": rate(outlier_rejected, len(outliers)),
        "partial_observations": len(partial),
        "partial_rejected": partial_rejected,
        "partial_rejection_rate": rate(partial_rejected, len(partial)),
        "accepted_outliers": len(outliers) - outlier_rejected,
        "max_abs_vz_mps": max(velocities, default=math.nan),
        "p99_abs_vz_mps": (
            float(np.percentile(velocities, 99)) if velocities else math.nan
        ),
        "occlusion_events": len(event_ids),
        "events_track_expired": expired,
        "events_reacquired": reacquired,
        "mean_reacquisition_delay_frames": (
            float(np.mean(reacquisition_delays))
            if reacquisition_delays
            else math.nan
        ),
        "max_reacquisition_delay_frames": (
            max(reacquisition_delays) if reacquisition_delays else math.nan
        ),
    }


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=fieldnames, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Compare observation gates using labelled replay data"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("bird_eye_config.json"),
    )
    parser.add_argument(
        "--summary-output", type=Path, default=Path("gate_comparison.csv")
    )
    parser.add_argument(
        "--details-output", type=Path, default=Path("gate_comparison_details.csv")
    )
    args = parser.parse_args()

    with args.config.open() as config_file:
        config = json.load(config_file)
    sessions = load_observations(args.input)
    all_details = []
    summaries = []
    for variant, settings in VARIANTS.items():
        for session, rows in sorted(sessions.items()):
            details = replay_variant(rows, config, variant, settings)
            all_details.extend(details)
            summaries.append(summarize(details))
    write_csv(args.summary_output, SUMMARY_FIELDS, summaries)
    write_csv(args.details_output, DETAIL_FIELDS, all_details)
    for row in summaries:
        print(
            f'{row["variant"]:22s} {row["session"]:13s} '
            f'inlier_accept={row["stable_inlier_acceptance_rate"]:.1%} '
            f'outlier_reject={row["outlier_rejection_rate"]:.1%} '
            f'max|vz|={row["max_abs_vz_mps"]:.3f} '
            f'expire/reacquire={row["events_track_expired"]}/'
            f'{row["events_reacquired"]}'
        )
    print(f"Summary saved: {args.summary_output.resolve()}")
    print(f"Details saved: {args.details_output.resolve()}")


if __name__ == "__main__":
    main()
