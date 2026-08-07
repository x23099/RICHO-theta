#!/usr/bin/env python3
"""Headless evaluation of ground-contact localization on recorded sessions."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np

from ground_contact import detect_blue_ground_contact


POSITION_PATTERN = re.compile(
    r"(?:cal_|holdout_)?x(?P<sign>[mp])(?P<x>\d+(?:\.\d+)?)_z(?P<z>\d+(?:\.\d+)?)(?:_\d+)?$"
)


def parse_expected_position(name: str):
    match = POSITION_PATTERN.search(name)
    if match is None:
        return None
    sign = -1.0 if match.group("sign") == "m" else 1.0
    return sign * float(match.group("x")), float(match.group("z"))


def evaluate_session(
    session_dir: Path,
    frame_step: int,
    warmup_frames: int,
    min_area_px: float,
    contact_fraction: float,
):
    expected = parse_expected_position(session_dir.name)
    if expected is None:
        return None
    with (session_dir / "metadata.json").open() as metadata_file:
        parameters = json.load(metadata_file)["parameters"]

    capture = cv2.VideoCapture(str(session_dir / "raw.avi"))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open {session_dir / 'raw.avi'}")
    detections = []
    frame_index = 0
    sampled = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index >= warmup_frames and frame_index % frame_step == 0:
            sampled += 1
            detection, _ = detect_blue_ground_contact(
                frame,
                parameters,
                min_area_px=min_area_px,
                contact_fraction=contact_fraction,
            )
            if detection is not None:
                detections.append((detection["x_m"], detection["z_m"]))
        frame_index += 1
    capture.release()

    if detections:
        values = np.asarray(detections, dtype=np.float64)
        raw_x, raw_z = np.median(values, axis=0)
        std_x, std_z = np.std(values, axis=0)
    else:
        raw_x = raw_z = std_x = std_z = math.nan
    return {
        "session": session_dir.name,
        "expected_x_m": expected[0],
        "expected_z_m": expected[1],
        "raw_x_m": float(raw_x),
        "raw_z_m": float(raw_z),
        "std_x_m": float(std_x),
        "std_z_m": float(std_z),
        "detected_samples": len(detections),
        "sampled_frames": sampled,
        "detection_rate": len(detections) / sampled if sampled else 0.0,
    }


def collect_sessions(roots, args):
    results = []
    for root in roots:
        for session_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            row = evaluate_session(
                session_dir,
                max(1, args.frame_step),
                max(0, args.warmup_frames),
                args.min_area_px,
                args.contact_fraction,
            )
            if row is not None:
                results.append(row)
    return results


def fit_lateral_calibration(rows):
    valid = [
        row for row in rows
        if math.isfinite(row["raw_x_m"]) and math.isfinite(row["raw_z_m"])
    ]
    if len(valid) < 3:
        raise RuntimeError("At least three detected calibration sessions are required")
    measured = np.asarray([[row["raw_x_m"], 1.0] for row in valid])
    expected_x = np.asarray([row["expected_x_m"] for row in valid])
    return np.linalg.lstsq(measured, expected_x, rcond=None)[0]


def apply_ground_contact_model(rows, lateral_coefficients):
    evaluated = []
    for source in rows:
        row = dict(source)
        if math.isfinite(row["raw_x_m"]) and math.isfinite(row["raw_z_m"]):
            predicted = np.array(
                [
                    row["raw_x_m"] * lateral_coefficients[0]
                    + lateral_coefficients[1],
                    # The ray/floor intersection is already metric. Fitting a
                    # second empirical z transform reintroduced the vertical-
                    # surface bias that this estimator is designed to remove.
                    row["raw_z_m"],
                ]
            )
            error_x = float(predicted[0] - row["expected_x_m"])
            error_z = float(predicted[1] - row["expected_z_m"])
            row.update(
                estimated_x_m=float(predicted[0]),
                estimated_z_m=float(predicted[1]),
                error_x_m=error_x,
                error_z_m=error_z,
                position_error_m=math.hypot(error_x, error_z),
            )
        else:
            row.update(
                estimated_x_m=math.nan,
                estimated_z_m=math.nan,
                error_x_m=math.nan,
                error_z_m=math.nan,
                position_error_m=math.nan,
            )
        evaluated.append(row)
    return evaluated


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate raw-fisheye ground-contact localization without GUI/camera"
    )
    parser.add_argument(
        "--calibration", type=Path, action="append", required=True,
        help="Directory containing calibration session folders; repeatable",
    )
    parser.add_argument(
        "--holdout", type=Path, action="append", required=True,
        help="Directory containing holdout session folders; repeatable",
    )
    parser.add_argument("--frame-step", type=int, default=5)
    parser.add_argument("--warmup-frames", type=int, default=30)
    parser.add_argument("--min-area-px", type=float, default=300.0)
    parser.add_argument("--contact-fraction", type=float, default=0.08)
    parser.add_argument(
        "--output", type=Path,
        default=Path("ground_contact_evaluation.csv"),
    )
    parser.add_argument(
        "--model-output", type=Path,
        default=Path("ground_contact_model.json"),
    )
    args = parser.parse_args()

    calibration = collect_sessions(args.calibration, args)
    holdout = collect_sessions(args.holdout, args)
    lateral_coefficients = fit_lateral_calibration(calibration)
    evaluated = apply_ground_contact_model(holdout, lateral_coefficients)
    if not evaluated:
        raise SystemExit("No labelled holdout sessions were found")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(evaluated[0]))
        writer.writeheader()
        writer.writerows(evaluated)
    model = {
        "type": "ground_contact_lateral_affine",
        "x_scale": float(lateral_coefficients[0]),
        "x_offset_m": float(lateral_coefficients[1]),
        "z_scale": 1.0,
        "z_offset_m": 0.0,
        "contact_fraction": args.contact_fraction,
        "min_area_px": args.min_area_px,
        "warmup_frames": args.warmup_frames,
        "frame_step": args.frame_step,
    }
    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    with args.model_output.open("w") as model_file:
        json.dump(model, model_file, indent=2)
        model_file.write("\n")

    errors = [
        row["position_error_m"] for row in evaluated
        if math.isfinite(row["position_error_m"])
    ]
    for row in evaluated:
        print(
            f'{row["session"]}: detected={row["detection_rate"]:.0%}, '
            f'raw=({row["raw_x_m"]:+.3f}, {row["raw_z_m"]:.3f}) m, '
            f'est=({row["estimated_x_m"]:+.3f}, {row["estimated_z_m"]:.3f}) m, '
            f'error={row["position_error_m"]:.3f} m'
        )
    if not errors:
        raise SystemExit("No holdout detections")
    mean_error = float(np.mean(errors))
    max_error = float(np.max(errors))
    if mean_error <= 0.05 and max_error <= 0.08:
        decision = "PASS"
    elif mean_error <= 0.06 and max_error <= 0.10:
        decision = "CONDITIONAL_PASS"
    else:
        decision = "FAIL"
    print(f"Mean/max position error: {mean_error:.3f}/{max_error:.3f} m")
    print(f"Decision: {decision}")
    print(f"CSV saved: {args.output.resolve()}")
    print(f"Model saved: {args.model_output.resolve()}")


if __name__ == "__main__":
    main()
