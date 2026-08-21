#!/usr/bin/env python3
"""Compare observation-gate thresholds across live and occlusion recordings."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from compare_observation_gates import load_observations, replay_variant, summarize
from diagnose_lateral_gate_asymmetry import load_sessions


OUTPUT_FIELDS = [
    "normalized_area_threshold",
    "live_sessions",
    "live_min_area_acceptance_rate",
    "occlusion_sessions",
    "stable_inlier_min_acceptance_rate",
    "outlier_min_rejection_rate",
    "max_abs_vz_mps",
    "occlusion_events",
    "events_track_expired",
    "events_reacquired",
    "decision",
]


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def live_area_acceptance_rates(sessions, threshold):
    """Return per-session area-gate rates for sessions containing detections."""

    rates = []
    for label, _source, _metadata, rows in sessions:
        values = [
            value
            for row in rows
            if str(row.get("detected", "")).strip().lower()
            in {"1", "true", "yes"}
            and (value := _finite_number(row.get("normalized_area"))) is not None
        ]
        if values:
            rates.append((label, sum(value >= threshold for value in values) / len(values)))
    return rates


def threshold_decision(row):
    outlier_rate = row["outlier_min_rejection_rate"]
    outlier_ok = math.isnan(outlier_rate) or outlier_rate >= 0.95
    passed = all(
        [
            row["live_min_area_acceptance_rate"] >= 0.98,
            row["stable_inlier_min_acceptance_rate"] >= 0.98,
            outlier_ok,
            row["max_abs_vz_mps"] <= 0.30,
            row["events_track_expired"] == row["occlusion_events"],
            row["events_reacquired"] == row["occlusion_events"],
        ]
    )
    return "PASS" if passed else "FAIL"


def evaluate_thresholds(live_sessions, occlusion_sessions, config, thresholds):
    output_rows = []
    for threshold in thresholds:
        live_rates = live_area_acceptance_rates(live_sessions, threshold)
        if not live_rates:
            raise ValueError("No live session contains a finite normalized_area")

        summaries = [
            summarize(
                replay_variant(
                    rows,
                    config,
                    "threshold_robustness",
                    {
                        "min_normalized_area": threshold,
                        "max_nis": 9.210,
                        "confirmation_frames": 2,
                    },
                )
            )
            for rows in occlusion_sessions.values()
        ]
        if not summaries:
            raise ValueError("No labelled occlusion session was loaded")

        outlier_rates = [
            row["outlier_rejection_rate"]
            for row in summaries
            if math.isfinite(row["outlier_rejection_rate"])
        ]
        result = {
            "normalized_area_threshold": threshold,
            "live_sessions": len(live_rates),
            "live_min_area_acceptance_rate": min(rate for _label, rate in live_rates),
            "occlusion_sessions": len(summaries),
            "stable_inlier_min_acceptance_rate": min(
                row["stable_inlier_acceptance_rate"] for row in summaries
            ),
            "outlier_min_rejection_rate": min(outlier_rates, default=math.nan),
            "max_abs_vz_mps": max(row["max_abs_vz_mps"] for row in summaries),
            "occlusion_events": sum(row["occlusion_events"] for row in summaries),
            "events_track_expired": sum(
                row["events_track_expired"] for row in summaries
            ),
            "events_reacquired": sum(row["events_reacquired"] for row in summaries),
        }
        result["decision"] = threshold_decision(result)
        output_rows.append(result)
    return output_rows


def main():
    parser = argparse.ArgumentParser(
        description="Sweep normalized-area thresholds over live and occlusion data"
    )
    parser.add_argument("--live-input", type=Path, action="append", required=True)
    parser.add_argument("--occlusion-input", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("bird_eye_config.json"),
    )
    parser.add_argument("--threshold", type=float, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.config.open() as config_file:
        config = json.load(config_file)
    thresholds = args.threshold or [
        1800.0,
        2000.0,
        2100.0,
        2200.0,
        2300.0,
        float(config["blue_observation_normalized_area_min"]),
    ]
    rows = evaluate_thresholds(
        load_sessions(args.live_input),
        load_observations(args.occlusion_input),
        config,
        thresholds,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    for row in rows:
        print(
            f"threshold={row['normalized_area_threshold']:.1f}, "
            f"live_min={row['live_min_area_acceptance_rate']:.1%}, "
            f"occlusion_min={row['stable_inlier_min_acceptance_rate']:.1%}, "
            f"outlier_reject={row['outlier_min_rejection_rate']:.1%}, "
            f"decision={row['decision']}"
        )
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
