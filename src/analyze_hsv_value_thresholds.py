#!/usr/bin/env python3
"""Evaluate blue HSV value thresholds on recorded target and no-target video."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from compare_area_normalization_replays import decide as combined_gate_decision
from compare_observation_gates import replay_variant, summarize
from evaluate_observation_gates import (
    find_session_directories,
    load_phase_labels,
    recompute_session,
)


OUTPUT_FIELDS = [
    "hsv_v_min",
    "session",
    "no_target",
    "frames",
    "detected_frames",
    "detection_rate",
    "median_area_px",
    "median_fill_ratio",
    "median_solidity",
    "measurement_acceptance_rate",
    "track_available_rate",
    "stable_inlier_acceptance_rate",
    "outlier_rejection_rate",
    "max_abs_vz_mps",
    "occlusion_events",
    "events_track_expired",
    "events_reacquired",
    "decision",
]


def _median(rows, field):
    values = [float(row[field]) for row in rows if row.get(field) not in {None, ""}]
    return statistics.median(values) if values else math.nan


def no_target_decision(detection_rate, track_rate):
    return "PASS" if detection_rate == 0.0 and track_rate == 0.0 else "FAIL"


def summarize_threshold(rows, basic_summary, config, no_target):
    detected = [row for row in rows if row["detected"]]
    common = {
        "frames": basic_summary["processed_frames"],
        "detected_frames": len(detected),
        "detection_rate": basic_summary["detection_rate"],
        "median_area_px": _median(detected, "area_px"),
        "median_fill_ratio": _median(detected, "bbox_fill_ratio"),
        "median_solidity": _median(detected, "contour_solidity"),
    }
    if not detected:
        return {
            **common,
            "measurement_acceptance_rate": 0.0,
            "track_available_rate": 0.0,
            "stable_inlier_acceptance_rate": math.nan,
            "outlier_rejection_rate": math.nan,
            "max_abs_vz_mps": math.nan,
            "occlusion_events": 0,
            "events_track_expired": 0,
            "events_reacquired": 0,
            "decision": "PASS" if no_target else "FAIL",
        }

    details = replay_variant(
        rows,
        config,
        "raw_ground_distance_2000",
        {
            "min_normalized_area": 2000.0,
            "max_nis": 9.210,
            "confirmation_frames": 2,
            "area_normalization_mode": "raw_ground_distance",
        },
    )
    summary = summarize(details)
    accepted = sum(row["measurement_accepted"] for row in details)
    tracked = sum(row["track_available"] for row in details)
    measurement_rate = accepted / len(detected)
    track_rate = tracked / len(details)
    decision = (
        no_target_decision(common["detection_rate"], track_rate)
        if no_target
        else combined_gate_decision(summary)
    )
    return {
        **common,
        "measurement_acceptance_rate": measurement_rate,
        "track_available_rate": track_rate,
        "stable_inlier_acceptance_rate": summary[
            "stable_inlier_acceptance_rate"
        ],
        "outlier_rejection_rate": summary["outlier_rejection_rate"],
        "max_abs_vz_mps": summary["max_abs_vz_mps"],
        "occlusion_events": summary["occlusion_events"],
        "events_track_expired": summary["events_track_expired"],
        "events_reacquired": summary["events_reacquired"],
        "decision": decision,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Sweep HSV V lower bounds on recorded blue-target video"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("bird_eye_config.json"),
    )
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--v-min", type=int, action="append")
    parser.add_argument(
        "--no-target-prefix", default="hakonasi",
        help="Session prefix identifying the no-blue-target control",
    )
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.config.open() as config_file:
        base_config = json.load(config_file)
    labels = load_phase_labels(args.labels) if args.labels else {}
    sessions = find_session_directories(args.input)
    if not sessions:
        parser.error("no recording sessions were found")
    thresholds = args.v_min or [10, 20, 25, 30]

    output_rows = []
    for value_min in thresholds:
        config = dict(base_config)
        config["blue_ground_contact_hsv_v_min"] = value_min
        for session_dir in sessions:
            rows, basic = recompute_session(
                session_dir,
                config,
                frame_step=args.frame_step,
                phase_intervals=labels.get(session_dir.name, ()),
                source_label=str(session_dir.parent),
            )
            no_target = session_dir.name.startswith(args.no_target_prefix)
            output_rows.append(
                {
                    "hsv_v_min": value_min,
                    "session": session_dir.name,
                    "no_target": int(no_target),
                    **summarize_threshold(rows, basic, config, no_target),
                }
            )
            print(
                f"V>={value_min:2d} {session_dir.name}: "
                f"detect={basic['detection_rate']:.1%}, "
                f"decision={output_rows[-1]['decision']}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
