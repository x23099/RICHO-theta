#!/usr/bin/env python3
"""Re-diagnose lateral calibration across independently recorded datasets.

Recording archives are read directly without extracting videos.  Trusted
datasets participate in cross-dataset model checks; nominal-only datasets are
reported but never used to fit or select calibration coefficients.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

import numpy as np

from diagnose_lateral_gate_asymmetry import load_sessions
from evaluate_recorded_position_trials import parse_expected_position


POINT_FIELDS = (
    "dataset",
    "role",
    "session",
    "source",
    "samples",
    "expected_x_m",
    "expected_z_m",
    "median_raw_x_m",
    "median_raw_z_m",
    "median_current_x_m",
    "median_current_z_m",
    "current_error_x_m",
    "current_abs_error_x_m",
    "raw_coordinate_source",
)
MODEL_FIELDS = (
    "model",
    "family",
    "training_dataset",
    "evaluation_dataset",
    "evaluation_role",
    "independent_evaluation",
    "coefficient_raw_x",
    "intercept_m",
    "coefficient_raw_z",
    "coefficient_abs_raw_x",
    "points",
    "mean_abs_error_x_m",
    "max_abs_error_x_m",
    "bias_x_m",
    "rmse_x_m",
)
MODEL_FAMILIES = ("affine", "depth_affine", "asymmetric_affine")
P_DECIMAL_POSITION_PATTERN = re.compile(
    r"(?:^|_)x(?P<sign>[mp])(?P<x>\d+(?:p\d+)?)_z(?P<z>\d+(?:p\d+)?)(?:_|$)"
)
CENTER_POSITION_PATTERN = re.compile(
    r"(?:^|_)center_z(?P<z>\d+(?:p\d+)?)(?:_|$)"
)


def _number(row, key):
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _flag(row, key):
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes"}


def parse_dataset_spec(value: str):
    name, separator, path_text = value.partition("=")
    if not separator or not name.strip() or not path_text.strip():
        raise argparse.ArgumentTypeError("dataset must be written as NAME=PATH")
    return name.strip(), Path(path_text).expanduser()


def parse_position_label(label):
    expected = parse_expected_position(label)
    if expected is not None:
        return expected
    match = P_DECIMAL_POSITION_PATTERN.search(label)
    if match is not None:
        sign = -1.0 if match.group("sign") == "m" else 1.0
        return (
            sign * float(match.group("x").replace("p", ".")),
            float(match.group("z").replace("p", ".")),
        )
    match = CENTER_POSITION_PATTERN.search(label)
    if match is not None:
        return 0.0, float(match.group("z").replace("p", "."))
    return None


def _median(values):
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.median(finite) if finite else math.nan


def _point(
    *, dataset, role, session, source, samples, expected, raw_x, raw_z,
    current_x, current_z, raw_source,
):
    error = current_x - expected[0]
    return {
        "dataset": dataset,
        "role": role,
        "session": session,
        "source": source,
        "samples": samples,
        "expected_x_m": expected[0],
        "expected_z_m": expected[1],
        "median_raw_x_m": raw_x,
        "median_raw_z_m": raw_z,
        "median_current_x_m": current_x,
        "median_current_z_m": current_z,
        "current_error_x_m": error,
        "current_abs_error_x_m": abs(error),
        "raw_coordinate_source": raw_source,
    }


def load_archive_points(path, dataset, role, x_scale, x_offset):
    points = []
    for label, source, _metadata, rows in load_sessions([path]):
        expected = parse_position_label(label)
        if expected is None:
            continue
        detected = [row for row in rows if _flag(row, "detected")]
        raw_x = _median(_number(row, "raw_x_m") for row in detected)
        raw_z = _median(_number(row, "raw_z_m") for row in detected)
        current_x = _median(_number(row, "x_m") for row in detected)
        current_z = _median(_number(row, "z_m") for row in detected)
        if not all(math.isfinite(value) for value in (raw_x, raw_z)):
            if not math.isfinite(current_x) or abs(x_scale) <= 1e-12:
                continue
            raw_x = (current_x - x_offset) / x_scale
            raw_z = current_z
            raw_source = "inverted_current"
        else:
            raw_source = "recorded"
        if not math.isfinite(current_x):
            current_x = raw_x * x_scale + x_offset
        if not math.isfinite(current_z):
            current_z = raw_z
        points.append(
            _point(
                dataset=dataset,
                role=role,
                session=label,
                source=source,
                samples=len(detected),
                expected=expected,
                raw_x=raw_x,
                raw_z=raw_z,
                current_x=current_x,
                current_z=current_z,
                raw_source=raw_source,
            )
        )
    return points


def load_csv_points(path, dataset, role, x_scale, x_offset):
    points = []
    with path.open(newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    for row in rows:
        label = row.get("session", "")
        expected_x = _number(row, "expected_x_m")
        expected_z = _number(row, "expected_z_m")
        expected = (
            (expected_x, expected_z)
            if expected_x is not None and expected_z is not None
            else parse_position_label(label)
        )
        if expected is None:
            continue
        raw_x = _number(row, "raw_x_m")
        raw_z = _number(row, "raw_z_m")
        current_x = _number(row, "estimated_x_m")
        if current_x is None:
            current_x = _number(row, "median_x_m")
        current_z = _number(row, "estimated_z_m")
        if current_z is None:
            current_z = _number(row, "median_z_m")
        raw_source = "recorded"
        if raw_x is None:
            if current_x is None or abs(x_scale) <= 1e-12:
                continue
            raw_x = (current_x - x_offset) / x_scale
            raw_source = "inverted_current"
        if raw_z is None:
            raw_z = current_z
        if raw_z is None:
            continue
        if current_x is None:
            current_x = raw_x * x_scale + x_offset
        if current_z is None:
            current_z = raw_z
        samples = _number(row, "detected_samples")
        if samples is None:
            samples = _number(row, "frames") or 1
        points.append(
            _point(
                dataset=dataset,
                role=role,
                session=label,
                source=str(path.resolve()),
                samples=int(samples),
                expected=expected,
                raw_x=raw_x,
                raw_z=raw_z,
                current_x=current_x,
                current_z=current_z,
                raw_source=raw_source,
            )
        )
    return points


def load_dataset(path, dataset, role, x_scale, x_offset):
    if not path.exists():
        raise FileNotFoundError(f"Input does not exist: {path}")
    if path.is_file() and path.suffix.lower() == ".csv":
        return load_csv_points(path, dataset, role, x_scale, x_offset)
    return load_archive_points(path, dataset, role, x_scale, x_offset)


def design_matrix(points, family):
    raw_x = np.asarray([point["median_raw_x_m"] for point in points])
    raw_z = np.asarray([point["median_raw_z_m"] for point in points])
    if family == "affine":
        return np.column_stack((raw_x, np.ones(len(points))))
    if family == "depth_affine":
        return np.column_stack((raw_x, np.ones(len(points)), raw_z))
    if family == "asymmetric_affine":
        return np.column_stack((raw_x, np.ones(len(points)), np.abs(raw_x)))
    raise ValueError(f"Unknown model family: {family}")


def fit_model(points, family):
    matrix = design_matrix(points, family)
    if len(points) < matrix.shape[1] or np.linalg.matrix_rank(matrix) < matrix.shape[1]:
        raise ValueError(f"insufficient independent points for {family}")
    expected = np.asarray([point["expected_x_m"] for point in points])
    return np.linalg.lstsq(matrix, expected, rcond=None)[0]


def _coefficient_fields(family, coefficients):
    result = {
        "coefficient_raw_x": coefficients[0],
        "intercept_m": coefficients[1],
        "coefficient_raw_z": 0.0,
        "coefficient_abs_raw_x": 0.0,
    }
    if family == "depth_affine":
        result["coefficient_raw_z"] = coefficients[2]
    elif family == "asymmetric_affine":
        result["coefficient_abs_raw_x"] = coefficients[2]
    return result


def evaluate_model(
    points, family, coefficients, model, training_dataset, evaluation_dataset,
):
    expected = np.asarray([point["expected_x_m"] for point in points])
    errors = design_matrix(points, family) @ coefficients - expected
    result = {
        "model": model,
        "family": family,
        "training_dataset": training_dataset,
        "evaluation_dataset": evaluation_dataset,
        "evaluation_role": points[0]["role"],
        "independent_evaluation": (
            training_dataset != evaluation_dataset
            and training_dataset != "pooled_trusted"
        ),
        "points": len(points),
        "mean_abs_error_x_m": float(np.mean(np.abs(errors))),
        "max_abs_error_x_m": float(np.max(np.abs(errors))),
        "bias_x_m": float(np.mean(errors)),
        "rmse_x_m": float(np.sqrt(np.mean(errors ** 2))),
    }
    result.update(_coefficient_fields(family, coefficients))
    return result


def build_model_results(points, current_scale, current_offset):
    grouped = {}
    for point in points:
        grouped.setdefault(point["dataset"], []).append(point)
    trusted = {
        name: rows for name, rows in grouped.items() if rows[0]["role"] == "trusted"
    }
    results = []
    current = np.asarray((current_scale, current_offset))
    for name, rows in grouped.items():
        results.append(
            evaluate_model(rows, "affine", current, "current", "original_10", name)
        )
    for training_name, training_rows in trusted.items():
        for family in MODEL_FAMILIES:
            try:
                coefficients = fit_model(training_rows, family)
            except ValueError:
                continue
            for evaluation_name, evaluation_rows in trusted.items():
                results.append(
                    evaluate_model(
                        evaluation_rows,
                        family,
                        coefficients,
                        f"{family}_fit_{training_name}",
                        training_name,
                        evaluation_name,
                    )
                )
    pooled = [point for rows in trusted.values() for point in rows]
    for family in MODEL_FAMILIES:
        try:
            coefficients = fit_model(pooled, family)
        except ValueError:
            continue
        for evaluation_name, evaluation_rows in trusted.items():
            results.append(
                evaluate_model(
                    evaluation_rows,
                    family,
                    coefficients,
                    f"{family}_fit_pooled",
                    "pooled_trusted",
                    evaluation_name,
                )
            )
    return results


def selection_decision(model_rows):
    current = {
        row["evaluation_dataset"]: row
        for row in model_rows
        if row["model"] == "current" and row["evaluation_role"] == "trusted"
    }
    family_passes = {}
    for family in MODEL_FAMILIES:
        folds = [
            row
            for row in model_rows
            if row["family"] == family
            and row["evaluation_role"] == "trusted"
            and row["training_dataset"] not in {"original_10", "pooled_trusted"}
            and row["independent_evaluation"]
        ]
        family_passes[family] = bool(folds) and all(
            row["mean_abs_error_x_m"] < current[row["evaluation_dataset"]]["mean_abs_error_x_m"]
            and row["max_abs_error_x_m"] < current[row["evaluation_dataset"]]["max_abs_error_x_m"]
            for row in folds
        )
    selected = [family for family, passed in family_passes.items() if passed]
    return {
        "decision": "RECALIBRATION_CANDIDATE" if selected else "KEEP_CURRENT",
        "cross_dataset_improving_families": selected,
        "family_passes": family_passes,
    }


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Cross-dataset diagnosis of lateral x calibration"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--trusted", type=parse_dataset_spec, action="append", required=True,
        metavar="NAME=PATH",
    )
    parser.add_argument(
        "--nominal", type=parse_dataset_spec, action="append", default=[],
        metavar="NAME=PATH",
        help="Labelled but not physically measured; excluded from fitting/selection",
    )
    parser.add_argument("--points-output", type=Path, required=True)
    parser.add_argument("--models-output", type=Path, required=True)
    parser.add_argument("--decision-output", type=Path, required=True)
    args = parser.parse_args()

    with args.config.open() as config_file:
        config = json.load(config_file)
    x_scale = float(config["blue_ground_contact_x_scale"])
    x_offset = float(config.get("blue_ground_contact_x_offset_m", 0.0))

    points = []
    seen_names = set()
    for role, specs in (("trusted", args.trusted), ("nominal_only", args.nominal)):
        for name, path in specs:
            if name in seen_names:
                parser.error(f"duplicate dataset name: {name}")
            seen_names.add(name)
            loaded = load_dataset(path, name, role, x_scale, x_offset)
            if not loaded:
                parser.error(f"no labelled position point found in {path}")
            points.extend(loaded)
    trusted_names = {point["dataset"] for point in points if point["role"] == "trusted"}
    if len(trusted_names) < 2:
        parser.error("at least two trusted datasets are required for cross-dataset checks")

    model_rows = build_model_results(points, x_scale, x_offset)
    decision = selection_decision(model_rows)
    decision.update(
        current_x_scale=x_scale,
        current_x_offset_m=x_offset,
        trusted_datasets=sorted(trusted_names),
        nominal_only_datasets=sorted(
            {point["dataset"] for point in points if point["role"] == "nominal_only"}
        ),
        selection_rule=(
            "A family must reduce both mean and maximum absolute x error versus "
            "the current model in every cross-dataset fold."
        ),
    )

    write_csv(args.points_output, POINT_FIELDS, points)
    write_csv(args.models_output, MODEL_FIELDS, model_rows)
    args.decision_output.parent.mkdir(parents=True, exist_ok=True)
    with args.decision_output.open("w") as output_file:
        json.dump(decision, output_file, indent=2, ensure_ascii=False)
        output_file.write("\n")

    print(f"Points: {len(points)} in {len(seen_names)} datasets")
    for row in model_rows:
        if row["model"] == "current":
            print(
                f"Current / {row['evaluation_dataset']}: "
                f"MAE={row['mean_abs_error_x_m'] * 100:.2f} cm, "
                f"max={row['max_abs_error_x_m'] * 100:.2f} cm, "
                f"bias={row['bias_x_m'] * 100:+.2f} cm"
            )
    print(f"Decision: {decision['decision']}")
    print(f"Points saved: {args.points_output.resolve()}")
    print(f"Model checks saved: {args.models_output.resolve()}")
    print(f"Decision saved: {args.decision_output.resolve()}")


if __name__ == "__main__":
    main()
