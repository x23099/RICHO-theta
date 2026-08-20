#!/usr/bin/env python3
"""Evaluate live-trial summary rows against explicit completeness requirements."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import math
import sys
from pathlib import Path


REQUIREMENT_FIELDS = [
    "rule_id",
    "experiment_label_glob",
    "min_trials",
    "min_detection_rate",
    "max_detection_rate",
    "min_measurement_acceptance_rate",
    "min_track_rate",
    "max_track_rate",
    "max_warning_or_critical_rate",
    "max_unknown_rate",
    "min_direction_correct_rate",
    "max_relative_speed_mae_mps",
    "min_ttc_active_rate_while_approaching",
    "max_ttc_active_rate",
    "min_warning_or_critical_frames",
    "max_warning_or_critical_frames",
    "min_filtered_warning_frames",
    "max_filtered_warning_frames",
    "min_warning_hold_frames",
    "max_raw_warning_frames",
    "max_warning_entry_delay_sec",
    "max_path_while_forward_after_warning_frames",
    "max_unknown_frames",
    "min_odom_available_rate",
    "max_position_error_m",
    "max_mean_position_error_m",
    "expected_final_state",
]
RESULT_FIELDS = [
    "rule_id",
    "experiment_label_glob",
    "matched_trials",
    "matched_labels",
    "result",
    "reasons",
]
NUMERIC_REQUIREMENTS = [
    ("min_detection_rate", "detection_rate", "min", 0.0, 1.0),
    ("max_detection_rate", "detection_rate", "max", 0.0, 1.0),
    (
        "min_measurement_acceptance_rate",
        "measurement_acceptance_rate",
        "min",
        0.0,
        1.0,
    ),
    ("min_track_rate", "track_rate", "min", 0.0, 1.0),
    ("max_track_rate", "track_rate", "max", 0.0, 1.0),
    (
        "max_warning_or_critical_rate",
        "warning_or_critical_rate",
        "max",
        0.0,
        1.0,
    ),
    ("max_unknown_rate", "unknown_rate", "max", 0.0, 1.0),
    (
        "min_direction_correct_rate",
        "direction_correct_rate",
        "min",
        0.0,
        1.0,
    ),
    (
        "max_relative_speed_mae_mps",
        "relative_speed_mae_mps",
        "max",
        0.0,
        None,
    ),
    (
        "min_ttc_active_rate_while_approaching",
        "ttc_active_rate_while_approaching",
        "min",
        0.0,
        1.0,
    ),
    ("max_ttc_active_rate", "ttc_active_rate", "max", 0.0, 1.0),
    (
        "min_warning_or_critical_frames",
        "warning_or_critical_frames",
        "min",
        0.0,
        None,
    ),
    (
        "max_warning_or_critical_frames",
        "warning_or_critical_frames",
        "max",
        0.0,
        None,
    ),
    (
        "min_filtered_warning_frames",
        "filtered_warning_frames",
        "min",
        0.0,
        None,
    ),
    (
        "max_filtered_warning_frames",
        "filtered_warning_frames",
        "max",
        0.0,
        None,
    ),
    (
        "min_warning_hold_frames",
        "warning_hold_frames",
        "min",
        0.0,
        None,
    ),
    ("max_raw_warning_frames", "raw_warning_frames", "max", 0.0, None),
    (
        "max_warning_entry_delay_sec",
        "maximum_warning_entry_delay_sec",
        "max",
        0.0,
        None,
    ),
    (
        "max_path_while_forward_after_warning_frames",
        "path_while_forward_after_warning_frames",
        "max",
        0.0,
        None,
    ),
    ("max_unknown_frames", "unknown_frames", "max", 0.0, None),
    ("min_odom_available_rate", "odom_available_rate", "min", 0.0, 1.0),
    ("max_position_error_m", "position_error_m", "max", 0.0, None),
]
AGGREGATE_REQUIREMENTS = [
    (
        "max_mean_position_error_m",
        "position_error_m",
        "max",
        0.0,
        None,
    ),
]


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_csv(path, expected_fields=None):
    with Path(path).open(newline="") as input_file:
        reader = csv.DictReader(input_file)
        if expected_fields is not None and reader.fieldnames != expected_fields:
            raise ValueError(
                f"Unexpected columns in {path}: {reader.fieldnames}; "
                f"expected {expected_fields}"
            )
        return list(reader)


def load_requirements(path):
    with Path(path).open(newline="") as input_file:
        reader = csv.DictReader(input_file)
        fieldnames = reader.fieldnames or []
        required = {"rule_id", "experiment_label_glob", "min_trials"}
        missing = sorted(required - set(fieldnames))
        unknown = sorted(set(fieldnames) - set(REQUIREMENT_FIELDS))
        if missing or unknown:
            raise ValueError(
                f"Invalid requirement columns in {path}: "
                f"missing={missing}, unknown={unknown}"
            )
        rows = []
        for source_row in reader:
            row = dict.fromkeys(REQUIREMENT_FIELDS, "")
            row.update(source_row)
            rows.append(row)
        return rows


def _validate_numeric_requirement(rule, key, minimum, maximum):
    value = str(rule.get(key, "")).strip()
    if not value:
        return None
    number = _finite_number(value)
    if number is None or (minimum is not None and number < minimum) or (
        maximum is not None and number > maximum
    ):
        interval = f"[{minimum if minimum is not None else '-inf'}, "
        interval += f"{maximum if maximum is not None else 'inf'}]"
        raise ValueError(f"{rule['rule_id']}: {key} must be in {interval}")
    return number


def evaluate_requirements(
    summary_rows,
    requirement_rows,
    label_column="experiment_label",
):
    results = []
    for rule in requirement_rows:
        rule_id = rule["rule_id"].strip()
        pattern = rule["experiment_label_glob"].strip()
        if not rule_id or not pattern:
            raise ValueError("rule_id and experiment_label_glob are required")
        try:
            min_trials = int(rule["min_trials"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{rule_id}: min_trials must be an integer") from error
        if min_trials < 1:
            raise ValueError(f"{rule_id}: min_trials must be at least 1")

        constraints = [
            (
                requirement_key,
                metric_key,
                comparison,
                _validate_numeric_requirement(
                    rule, requirement_key, minimum, maximum
                ),
            )
            for (
                requirement_key,
                metric_key,
                comparison,
                minimum,
                maximum,
            ) in NUMERIC_REQUIREMENTS
        ]
        aggregate_constraints = [
            (
                requirement_key,
                metric_key,
                comparison,
                _validate_numeric_requirement(
                    rule, requirement_key, minimum, maximum
                ),
            )
            for (
                requirement_key,
                metric_key,
                comparison,
                minimum,
                maximum,
            ) in AGGREGATE_REQUIREMENTS
        ]
        expected_final_state = rule.get("expected_final_state", "").strip()
        matches = [
            row
            for row in summary_rows
            if fnmatch.fnmatchcase(row.get(label_column, ""), pattern)
        ]
        reasons = []
        if len(matches) < min_trials:
            reasons.append(f"matched_trials={len(matches)} < min_trials={min_trials}")

        for row in matches:
            label = row.get(label_column, "")
            for requirement_key, metric_key, comparison, limit in constraints:
                if limit is None:
                    continue
                measured = _finite_number(row.get(metric_key, ""))
                if measured is None:
                    reasons.append(f"{label}: {metric_key} is unavailable")
                elif comparison == "min" and measured < limit:
                    reasons.append(
                        f"{label}: {metric_key}={measured:.6f} < "
                        f"{requirement_key}={limit:.6f}"
                    )
                elif comparison == "max" and measured > limit:
                    reasons.append(
                        f"{label}: {metric_key}={measured:.6f} > "
                        f"{requirement_key}={limit:.6f}"
                    )
            if expected_final_state and row.get("final_state", "") != expected_final_state:
                reasons.append(
                    f"{label}: final_state={row.get('final_state', '')!r} != "
                    f"expected_final_state={expected_final_state!r}"
                )

        for requirement_key, metric_key, comparison, limit in aggregate_constraints:
            if limit is None:
                continue
            values = [_finite_number(row.get(metric_key, "")) for row in matches]
            if not values or any(value is None for value in values):
                reasons.append(f"matched trials: {metric_key} is unavailable")
                continue
            aggregate = sum(values) / len(values)
            if comparison == "max" and aggregate > limit:
                reasons.append(
                    f"matched trials: mean({metric_key})={aggregate:.6f} > "
                    f"{requirement_key}={limit:.6f}"
                )

        results.append(
            {
                "rule_id": rule_id,
                "experiment_label_glob": pattern,
                "matched_trials": len(matches),
                "matched_labels": ";".join(
                    row.get(label_column, "") for row in matches
                ),
                "result": "FAIL" if reasons else "PASS",
                "reasons": "; ".join(reasons),
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate summarized live trials against CSV requirements"
    )
    parser.add_argument("--summary", type=Path, action="append", required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label-column", default="experiment_label")
    args = parser.parse_args()

    summary_rows = [
        row
        for summary_path in args.summary
        for row in load_csv(summary_path)
    ]
    requirement_rows = load_requirements(args.requirements)
    results = evaluate_requirements(
        summary_rows,
        requirement_rows,
        label_column=args.label_column,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=RESULT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(results)

    failed = [row for row in results if row["result"] == "FAIL"]
    print(f"Rules: {len(results)}")
    print(f"PASS: {len(results) - len(failed)}")
    print(f"FAIL: {len(failed)}")
    for row in failed:
        print(f"[FAIL] {row['rule_id']}: {row['reasons']}")
    print(f"Results saved: {args.output.resolve()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
