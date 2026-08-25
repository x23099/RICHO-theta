#!/usr/bin/env python3
"""Preflight checks for a blue-target field experiment."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ros_odometry import RosOdometryBridge
from camera_capture_properties import exposure_summary, read_capture_properties


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("bird_eye_config.json")


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str

    @property
    def failed(self):
        return self.status == "FAIL"


def validate_experiment_config(config):
    required_values = {
        "blue_position_method": "ground_contact",
        "blue_tracking_enabled": 1,
        "blue_observation_gate_enabled": 1,
        "blue_ttc_enabled": 1,
        "blue_collision_candidate_enabled": 1,
    }
    errors = []
    for key, expected in required_values.items():
        if config.get(key) != expected:
            errors.append(f"{key} must be {expected!r}, got {config.get(key)!r}")
    positive_keys = (
        "camera_height",
        "scale",
        "car_width",
        "blue_ground_contact_min_area",
        "blue_observation_normalized_area_min",
        "blue_observation_nis_max",
        "blue_ttc_velocity_window_sec",
        "blue_collision_warning_ttc_sec",
        "blue_collision_critical_ttc_sec",
        "blue_collision_warning_exit_ttc_sec",
        "blue_collision_warning_hold_sec",
        "blue_collision_forward_motion_threshold_mps",
    )
    for key in positive_keys:
        try:
            value = float(config[key])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{key} must be a finite positive number")
            continue
        if not math.isfinite(value) or value <= 0.0:
            errors.append(f"{key} must be a finite positive number")
    warning_ttc = config.get("blue_collision_warning_ttc_sec")
    critical_ttc = config.get("blue_collision_critical_ttc_sec")
    warning_exit_ttc = config.get("blue_collision_warning_exit_ttc_sec")
    if (
        isinstance(warning_ttc, (int, float))
        and isinstance(critical_ttc, (int, float))
        and critical_ttc > warning_ttc
    ):
        errors.append("critical TTC must not exceed warning TTC")
    if (
        isinstance(warning_ttc, (int, float))
        and isinstance(warning_exit_ttc, (int, float))
        and warning_exit_ttc <= warning_ttc
    ):
        errors.append("warning exit TTC must exceed warning TTC")
    for key in (
        "blue_collision_warning_confirm_frames",
        "blue_collision_warning_clear_frames",
    ):
        value = config.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"{key} must be a positive integer")
    area_distance_mode = config.get(
        "blue_observation_area_distance_mode", "forward_z"
    )
    if area_distance_mode not in {
        "forward_z",
        "calibrated_ground_distance",
        "raw_ground_distance",
    }:
        errors.append(
            "blue_observation_area_distance_mode must be forward_z, "
            "calibrated_ground_distance, or raw_ground_distance"
        )
    hsv_v_min = config.get("blue_ground_contact_hsv_v_min", 30)
    if (
        not isinstance(hsv_v_min, int)
        or isinstance(hsv_v_min, bool)
        or not 0 <= hsv_v_min <= 255
    ):
        errors.append("blue_ground_contact_hsv_v_min must be an integer from 0 to 255")
    illumination_mode = config.get(
        "blue_ground_contact_illumination_mode", "none"
    )
    if illumination_mode not in {
        "none",
        "clahe_value",
        "gray_world",
        "gray_world_clahe",
        "shades_of_gray",
        "shades_of_gray_clahe",
    }:
        errors.append("unsupported blue_ground_contact_illumination_mode")
    return errors


def check_dependencies(require_ros):
    modules = ["numpy", "cv2", "PySide6"]
    if require_ros:
        modules.extend(["rclpy", "nav_msgs.msg"])
    missing = []
    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except ImportError as error:
            missing.append(f"{module_name}: {error}")
    if missing:
        return CheckResult("Python dependencies", "FAIL", "; ".join(missing))
    return CheckResult(
        "Python dependencies", "PASS", ", ".join(modules)
    )


def check_config(config_path):
    try:
        with Path(config_path).open() as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        return CheckResult("Experiment config", "FAIL", str(error))
    errors = validate_experiment_config(config)
    if errors:
        return CheckResult("Experiment config", "FAIL", "; ".join(errors))
    return CheckResult(
        "Experiment config",
        "PASS",
        f"{Path(config_path).resolve()} (blue baseline)",
    )


def check_record_storage(record_dir, minimum_free_gb):
    record_dir = Path(record_dir)
    try:
        record_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=record_dir, prefix=".preflight_"):
            pass
        free_bytes = shutil.disk_usage(record_dir).free
    except OSError as error:
        return CheckResult("Recording storage", "FAIL", str(error))
    free_gb = free_bytes / (1024 ** 3)
    status = "PASS" if free_gb >= minimum_free_gb else "FAIL"
    return CheckResult(
        "Recording storage",
        status,
        f"{record_dir.resolve()}: {free_gb:.1f} GiB free "
        f"(required {minimum_free_gb:.1f} GiB)",
    )


def check_git_state(require_clean):
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPOSITORY_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status_output = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        return CheckResult("Git provenance", "FAIL", str(error))
    if status_output:
        status = "FAIL" if require_clean else "WARN"
        return CheckResult(
            "Git provenance", status, f"commit {commit}; working tree has changes"
        )
    return CheckResult("Git provenance", "PASS", f"clean commit {commit}")


def check_unit_tests():
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(REPOSITORY_DIR / "src"), existing_pythonpath) if value
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
        ],
        cwd=REPOSITORY_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip().splitlines()
    detail = output[-1] if output else "no test output"
    return CheckResult(
        "Unit tests", "PASS" if result.returncode == 0 else "FAIL", detail
    )


def check_camera(device, width, height, frame_count, requested_fps=30.0):
    import cv2

    capture_device = int(device) if str(device).isdigit() else str(device)
    backend = cv2.CAP_V4L2 if isinstance(capture_device, int) else cv2.CAP_ANY
    capture = cv2.VideoCapture(capture_device, backend)
    try:
        if not capture.isOpened():
            return CheckResult("Camera", "FAIL", f"cannot open {device}")
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, requested_fps)
        for _ in range(5):
            capture.read()
        valid = 0
        shape = None
        started = time.monotonic()
        for _ in range(max(1, frame_count)):
            ok, frame = capture.read()
            if ok and frame is not None:
                valid += 1
                shape = frame.shape
        elapsed = max(1e-6, time.monotonic() - started)
        capture_properties = read_capture_properties(capture)
    finally:
        capture.release()
    if valid < max(1, frame_count):
        return CheckResult(
            "Camera", "FAIL", f"read {valid}/{max(1, frame_count)} valid frames"
        )
    read_rate = valid / elapsed
    reported_fps = capture_properties.get("fps", math.nan)
    rate_status = (
        "PASS"
        if not math.isfinite(reported_fps) or read_rate >= 0.8 * reported_fps
        else "WARN"
    )
    return CheckResult(
        "Camera",
        rate_status,
        f"{valid} frames, shape={shape}, read rate={read_rate:.1f} fps, "
        f"requested={requested_fps:.1f} fps, "
        f"reported={reported_fps:.1f} fps; "
        f"{exposure_summary(capture_properties)}",
    )


def check_odometry(topic, timeout_sec):
    try:
        bridge = RosOdometryBridge(topic)
    except Exception as error:
        return CheckResult("ROS odometry", "FAIL", str(error))
    try:
        deadline = time.monotonic() + timeout_sec
        sample = None
        while time.monotonic() < deadline and sample is None:
            bridge.spin_once()
            sample = bridge.sample()
            if sample is None:
                time.sleep(0.02)
    except Exception as error:
        return CheckResult("ROS odometry", "FAIL", str(error))
    finally:
        bridge.close()
    if sample is None:
        return CheckResult(
            "ROS odometry", "FAIL", f"no {topic} message in {timeout_sec:.1f}s"
        )
    return CheckResult(
        "ROS odometry",
        "PASS",
        f"{topic}: linear.x={sample['linear_mps']:+.4f} m/s, "
        f"angular.z={sample['angular_radps']:+.4f} rad/s",
    )


def print_results(results):
    for result in results:
        print(f"[{result.status:4s}] {result.name}: {result.detail}")
    failures = [result for result in results if result.failed]
    print("Decision:", "PASS" if not failures else "FAIL")
    return not failures


def main():
    parser = argparse.ArgumentParser(
        description="Preflight the blue-target field experiment environment"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--record-dir", type=Path, required=True)
    parser.add_argument("--minimum-free-gb", type=float, default=20.0)
    parser.add_argument("--camera-device", default="")
    parser.add_argument("--camera-width", type=int, default=1280)
    parser.add_argument("--camera-height", type=int, default=720)
    parser.add_argument("--camera-fps", type=float, default=30.0)
    parser.add_argument("--camera-frames", type=int, default=30)
    parser.add_argument("--odom-topic", default="")
    parser.add_argument("--odom-timeout-sec", type=float, default=3.0)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--require-clean-git", action="store_true")
    args = parser.parse_args()

    results = [
        check_dependencies(require_ros=bool(args.odom_topic)),
        check_config(args.config),
        check_record_storage(args.record_dir, max(0.0, args.minimum_free_gb)),
        check_git_state(args.require_clean_git),
    ]
    if not args.skip_tests:
        results.append(check_unit_tests())
    else:
        results.append(CheckResult("Unit tests", "WARN", "skipped"))
    if args.camera_device:
        results.append(
            check_camera(
                args.camera_device,
                args.camera_width,
                args.camera_height,
                args.camera_frames,
                args.camera_fps,
            )
        )
    else:
        results.append(CheckResult("Camera", "WARN", "not requested"))
    if args.odom_topic:
        results.append(check_odometry(args.odom_topic, args.odom_timeout_sec))
    else:
        results.append(CheckResult("ROS odometry", "WARN", "not requested"))

    raise SystemExit(0 if print_results(results) else 1)


if __name__ == "__main__":
    main()
