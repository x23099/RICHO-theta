#!/usr/bin/env python3
"""Replay the combined area, NIS, and confirmation gate by distance mode."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from compare_observation_gates import (
    SUMMARY_FIELDS,
    load_observations,
    replay_variant,
    summarize,
)


MODES = (
    "forward_z",
    "calibrated_ground_distance",
    "raw_ground_distance",
)

OUTPUT_FIELDS = [
    "dataset_role",
    "source",
    "normalization_mode",
    "threshold",
    *[field for field in SUMMARY_FIELDS if field != "variant"],
    "decision",
]


def decide(summary):
    outlier_rate = summary["outlier_rejection_rate"]
    outlier_ok = math.isnan(outlier_rate) or outlier_rate >= 0.95
    return "PASS" if all(
        [
            summary["stable_inlier_acceptance_rate"] >= 0.98,
            outlier_ok,
            summary["max_abs_vz_mps"] <= 0.30,
            summary["events_track_expired"] == summary["occlusion_events"],
            summary["events_reacquired"] == summary["occlusion_events"],
        ]
    ) else "FAIL"


def evaluate_inputs(inputs, config, thresholds):
    output_rows = []
    for role, path in inputs:
        for session, rows in sorted(load_observations(path).items()):
            for mode in MODES:
                for threshold in thresholds:
                    variant = f"{mode}_{threshold:g}"
                    details = replay_variant(
                        rows,
                        config,
                        variant,
                        {
                            "min_normalized_area": threshold,
                            "max_nis": 9.210,
                            "confirmation_frames": 2,
                            "area_normalization_mode": mode,
                        },
                    )
                    summary = summarize(details)
                    output_rows.append(
                        {
                            "dataset_role": role,
                            "source": str(path),
                            "normalization_mode": mode,
                            "threshold": threshold,
                            **{
                                field: value
                                for field, value in summary.items()
                                if field != "variant"
                            },
                            "decision": decide(summary),
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
        description="Replay combined gates with alternative area distance modes"
    )
    parser.add_argument(
        "--development-input", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--diagnostic-input", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("bird_eye_config.json"),
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

    with args.config.open() as config_file:
        config = json.load(config_file)
    thresholds = args.threshold or [1800.0, 2000.0, 2503.678448310634]
    rows = evaluate_inputs(inputs, config, thresholds)

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
            print(
                f"mode={mode}, threshold={threshold:.1f}, "
                f"pass={sum(row['decision'] == 'PASS' for row in selected)}/"
                f"{len(selected)}"
            )
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
