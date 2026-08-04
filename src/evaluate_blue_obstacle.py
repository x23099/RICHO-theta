#!/usr/bin/env python3
"""Evaluate blue-obstacle BEV coordinates against named recording positions."""

import argparse
import csv
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np

from bird_eye import detect_blue_obstacle, make_floor_projection_map


POSITION_PATTERN = re.compile(
    r"^x(?P<x>-?\d+(?:\.\d+)?)m_z(?P<z>\d+(?:\.\d+)?)m$"
)


def parse_expected_position(name):
    match = POSITION_PATTERN.match(name)
    if match is None:
        return None
    return float(match.group("x")), float(match.group("z"))


def evaluate_session(session_dir, camera_height, frame_step):
    expected = parse_expected_position(session_dir.name)
    if expected is None:
        return None

    with (session_dir / "metadata.json").open() as metadata_file:
        parameters = json.load(metadata_file)["parameters"]
    parameters["camera_height"] = camera_height

    capture = cv2.VideoCapture(str(session_dir / "raw.avi"))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open {session_dir / 'raw.avi'}")

    ok, first_frame = capture.read()
    if not ok:
        capture.release()
        raise RuntimeError(f"Cannot read {session_dir / 'raw.avi'}")
    in_h, in_w = first_frame.shape[:2]
    map_x, map_y = make_floor_projection_map(
        in_w, in_h, 500, 600,
        parameters["camera_height"], parameters["scale"],
        parameters["pitch_deg"], parameters["roll_deg"], parameters["yaw_deg"],
        parameters["radius_scale"],
        parameters["front_cx_offset"], parameters["front_cy_offset"],
        parameters["back_cx_offset"], parameters["back_cy_offset"],
        parameters.get("bowl_curve", 0.0), "left",
        parameters["car_offset_x"], parameters["car_offset_z"],
        parameters.get("forward_stretch", 0.0),
        parameters.get("backward_stretch", 0.0),
    )

    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    detections = []
    frame_index = 0
    total_sampled = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index % frame_step == 0:
            total_sampled += 1
            bev = cv2.remap(
                frame, map_x, map_y, cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0)
            )
            detection, _ = detect_blue_obstacle(
                bev, float(parameters["scale"]),
                float(parameters.get("blue_min_area", 250))
            )
            if detection is not None:
                detections.append((detection["x_m"], detection["z_m"]))
        frame_index += 1
    capture.release()

    if detections:
        values = np.asarray(detections)
        estimated_x = float(np.median(values[:, 0]))
        estimated_z = float(np.median(values[:, 1]))
        std_x = float(np.std(values[:, 0]))
        std_z = float(np.std(values[:, 1]))
    else:
        estimated_x = estimated_z = std_x = std_z = math.nan

    expected_x, expected_z = expected
    error_x = estimated_x - expected_x
    error_z = estimated_z - expected_z
    position_error = math.hypot(error_x, error_z)
    return {
        "session": session_dir.name,
        "expected_x_m": expected_x,
        "expected_z_m": expected_z,
        "estimated_x_m": estimated_x,
        "estimated_z_m": estimated_z,
        "error_x_m": error_x,
        "error_z_m": error_z,
        "position_error_m": position_error,
        "std_x_m": std_x,
        "std_z_m": std_z,
        "detected_samples": len(detections),
        "total_samples": total_sampled,
        "detection_rate": len(detections) / total_sampled if total_sampled else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("recordings", type=Path, help="Directory containing session folders")
    parser.add_argument("--camera-height", type=float, default=0.58)
    parser.add_argument("--frame-step", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("blue_obstacle_evaluation.csv"))
    args = parser.parse_args()

    results = []
    for session_dir in sorted(path for path in args.recordings.iterdir() if path.is_dir()):
        result = evaluate_session(session_dir, args.camera_height, max(1, args.frame_step))
        if result is not None:
            results.append(result)

    if not results:
        raise SystemExit("No session directories matched xXm_zZm naming")

    fieldnames = list(results[0].keys())
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    for row in results:
        print(
            f'{row["session"]}: detected={row["detection_rate"]:.0%}, '
            f'est=({row["estimated_x_m"]:+.3f}, {row["estimated_z_m"]:.3f}) m, '
            f'error={row["position_error_m"]:.3f} m'
        )
    mean_error = float(np.mean([row["position_error_m"] for row in results]))
    print(f"Mean position error: {mean_error:.3f} m")
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
