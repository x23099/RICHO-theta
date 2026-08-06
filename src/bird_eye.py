#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import math
import json
import argparse
import time
import csv

# Compatibility patch for PyTorch/torchvision Self type in Python 3.10
try:
    import typing
    if not hasattr(typing, "Self"):
        try:
            from typing_extensions import Self
            typing.Self = Self
        except ImportError:
            pass
except Exception:
    pass
import cv2
import numpy as np

from PySide6.QtCore import Qt, QTimer, QPoint, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QSlider, QGridLayout, QVBoxLayout,
    QHBoxLayout, QPushButton, QGroupBox, QFormLayout, QFileDialog, QCheckBox,
    QDoubleSpinBox, QSpinBox, QComboBox
)

try:
    import torch
    HAS_TORCH = True
except Exception as e:
    torch = None
    HAS_TORCH = False
    print(f"[WARN] Failed to import PyTorch; AI perception disabled: {e}")

# Fix for PyTorch 2.6+ weights_only=True default load restriction for Ultralytics models
try:
    if not HAS_TORCH:
        raise ImportError("PyTorch is not installed")
    import ultralytics.nn.tasks
    import ultralytics.nn.modules
    torch.serialization.add_safe_globals([
        ultralytics.nn.tasks.DetectionModel,
        ultralytics.nn.modules.Conv,
        ultralytics.nn.modules.C2f,
        ultralytics.nn.modules.SPPF,
        ultralytics.nn.modules.Detect,
        ultralytics.nn.modules.Bottleneck
    ])
except Exception:
    pass

try:
    if not HAS_TORCH:
        raise ImportError("PyTorch is not installed")
    from ultralytics import YOLO
    HAS_ULTRALYTICS = True
except Exception as e:
    HAS_ULTRALYTICS = False
    print(f"[WARN] Failed to import ultralytics/YOLO: {e}")

# Configuration file name
DEFAULT_CONFIG_FILE = "bird_eye_config.json"

# Vehicle geometry is kept separate from camera/BEV calibration.  Only the
# Kobuki dimensions are known here.  AI-FORMULA dimensions must be measured on
# the actual vehicle instead of being inferred from the thesis photographs.
VEHICLE_PROFILES = {
    "kobuki": {
        "label": "Kobuki (354 mm circular)",
        "camera_height": 0.58,
        "width": 0.354,
        "length": 0.354,
        "footprint_shape": "circle",
    },
    "aiformula": {
        "label": "AI-FORMULA (use measured dimensions)",
        "footprint_shape": "rectangle",
    },
    "custom": {
        "label": "Custom vehicle",
    },
}

class MockCapture:
    """
    Simulates a 360 dual-fisheye camera feed with a grid pattern
    and a 3D orbiting object to verify calibration math.
    """
    def __init__(self, width, height, radius_scale=0.96):
        self.width = width
        self.height = height
        self.radius_scale = radius_scale
        self.frame_count = 0

    def isOpened(self):
        return True

    def read(self):
        self.frame_count += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (15, 15, 15)  # Dark background

        # Circle centers
        left_cx = int(self.width * 0.25)
        right_cx = int(self.width * 0.75)
        cy = int(self.height * 0.5)
        radius = int(min(self.width / 4.0, self.height / 2.0) * self.radius_scale)

        # Draw fisheye circles
        cv2.circle(frame, (left_cx, cy), radius, (30, 45, 60), -1)
        cv2.circle(frame, (right_cx, cy), radius, (45, 30, 60), -1)
        
        cv2.circle(frame, (left_cx, cy), radius, (200, 200, 200), 2)
        cv2.circle(frame, (right_cx, cy), radius, (200, 200, 200), 2)

        # Draw reference radial lines on the fisheye circles
        for angle in range(0, 360, 30):
            rad = math.radians(angle)
            lx = int(left_cx + radius * math.cos(rad))
            ly = int(cy + radius * math.sin(rad))
            rx = int(right_cx + radius * math.cos(rad))
            ry = int(cy + radius * math.sin(rad))
            cv2.line(frame, (left_cx, cy), (lx, ly), (80, 100, 120), 1)
            cv2.line(frame, (right_cx, cy), (rx, ry), (120, 80, 120), 1)

        # 3D Orbiting Dot Simulation
        # Simulate a point orbiting the robot in 3D world:
        # X = R * cos(t), Z = R * sin(t), Y = -H (ground level)
        t = self.frame_count * 0.05
        orbit_r = 1.0  # 1 meter radius
        cam_h = 0.58   # Camera height (default)
        
        p_x = orbit_r * math.cos(t)
        p_z = orbit_r * math.sin(t)
        p_y = -cam_h

        # Project 3D point (p_x, p_y, p_z) to fisheye circles (No camera tilt for mock input generation)
        norm = math.sqrt(p_x*p_x + p_y*p_y + p_z*p_z)
        if norm > 1e-6:
            ux = p_x / norm
            uy = p_y / norm
            uz = p_z / norm

            # Front vs Rear lens mapping
            if uz >= 0:
                # Front lens (left circle)
                lx, ly, lz = ux, uy, uz
                cx = left_cx
            else:
                # Rear lens (right circle)
                lx, ly, lz = -ux, uy, -uz
                cx = right_cx

            theta_l = math.acos(lz)
            if theta_l <= math.pi / 2.0:
                r_l = radius * theta_l / (math.pi / 2.0)
                sin_theta = math.sin(theta_l)
                if sin_theta > 1e-6:
                    dx = r_l * (lx / sin_theta)
                    dy = -r_l * (ly / sin_theta)
                    px = int(cx + dx)
                    py = int(cy + dy)
                    cv2.circle(frame, (px, py), 12, (0, 255, 0), -1)
                    cv2.putText(frame, "P", (px - 5, py + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

        # Add texts
        cv2.putText(frame, "MOCK FRONT LENS (LEFT)", (left_cx - 100, cy - radius - 15), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "MOCK REAR LENS (RIGHT)", (right_cx - 100, cy - radius - 15), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1, cv2.LINE_AA)

        return True, frame

    def get(self, prop_id):
        if prop_id == cv2.CAP_PROP_FPS:
            return 24.0
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        return 0.0

    def release(self):
        pass


def make_floor_projection_map(
    in_w, in_h,
    out_w, out_h,
    camera_height,
    scale,
    pitch_deg,
    roll_deg,
    yaw_deg,
    radius_scale,
    front_cx_offset,
    front_cy_offset,
    back_cx_offset,
    back_cy_offset,
    bowl_curve=0.0,
    front_lens="left",
    camera_offset_x=0.0,
    camera_offset_z=0.0,
    forward_stretch=0.0,
    backward_stretch=0.0
):
    """
    Computes maps for cv2.remap that project a dual-fisheye image onto a horizontal floor plane.
    """
    # 1. Lens coordinates base
    radius = min(in_w / 4.0, in_h / 2.0) * radius_scale
    cy_base = in_h / 2.0
    
    if front_lens == "left":
        front_cx_base = in_w * 0.3125
        back_cx_base = in_w * 0.6875
    else:
        front_cx_base = in_w * 0.6875
        back_cx_base = in_w * 0.3125

    front_cx = front_cx_base + front_cx_offset
    front_cy = cy_base + front_cy_offset
    back_cx = back_cx_base + back_cx_offset
    back_cy = cy_base + back_cy_offset

    # 2. Setup ground grid in meters
    # Target center is (out_w/2, out_h/2).
    # X_w represents right-left axis, Z_w represents forward-backward axis.
    xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))
    X_w_cam = (xs - out_w / 2.0) * scale - camera_offset_x
    Z_w_cam = (out_h / 2.0 - ys) * scale - camera_offset_z
    
    # Non-linear forward stretching for front area (Z_w_cam > 0)
    if forward_stretch > 0.0:
        forward_mask = Z_w_cam > 0.0
        factor = 1.0 + forward_stretch * Z_w_cam
        X_w_cam = np.where(forward_mask, X_w_cam * factor, X_w_cam)
        Z_w_cam = np.where(forward_mask, Z_w_cam * factor, Z_w_cam)
        
    # Non-linear backward stretching for rear area (Z_w_cam < 0)
    if backward_stretch > 0.0:
        backward_mask = Z_w_cam < 0.0
        factor = 1.0 + backward_stretch * (-Z_w_cam)
        X_w_cam = np.where(backward_mask, X_w_cam * factor, X_w_cam)
        Z_w_cam = np.where(backward_mask, Z_w_cam * factor, Z_w_cam)
    
    if bowl_curve > 0.0:
        # X方向（左右）に 1.6 倍の重み、Z方向（前後）に 0.6 倍の重みをかけて d を計算
        # これにより、横方向は素早く立ち上がってお椀壁になり引き伸ばしが緩和され、
        # 正面方向は平らな地面が広く保たれるため直線歪みが小さくなります
        d = np.sqrt(1.6 * X_w_cam * X_w_cam + 0.6 * Z_w_cam * Z_w_cam)
        Y_w = -camera_height * np.exp(-bowl_curve * d)
    else:
        Y_w = -np.ones_like(X_w_cam) * camera_height

    X_w = X_w_cam
    Z_w = Z_w_cam

    # 3. Apply Camera Rotation relative to Vehicle: R = Rz(roll) * Rx(pitch) * Ry(yaw)
    yaw = np.deg2rad(yaw_deg)
    pitch = np.deg2rad(pitch_deg)
    roll = np.deg2rad(roll_deg)

    # Step A: Yaw (around Y-axis)
    x1 = X_w * np.cos(yaw) + Z_w * np.sin(yaw)
    y1 = Y_w
    z1 = -X_w * np.sin(yaw) + Z_w * np.cos(yaw)

    # Step B: Pitch (around X-axis)
    x2 = x1
    y2 = y1 * np.cos(pitch) - z1 * np.sin(pitch)
    z2 = y1 * np.sin(pitch) + z1 * np.cos(pitch)

    # Step C: Roll (around Z-axis)
    x_c = x2 * np.cos(roll) - y2 * np.sin(roll)
    y_c = x2 * np.sin(roll) + y2 * np.cos(roll)
    z_c = z2

    # 4. Normalize to get unit vectors
    norm = np.sqrt(x_c * x_c + y_c * y_c + z_c * z_c)
    norm = np.where(norm < 1e-6, 1.0, norm)
    x_u = x_c / norm
    y_u = y_c / norm
    z_u = z_c / norm

    # 5. Determine front/back lens based on z_u (look-forward axis)
    use_front = z_u >= 0.0
    cx = np.where(use_front, front_cx, back_cx)
    cy = np.where(use_front, front_cy, back_cy)

    # Convert direction vector to lens local frame
    lens_x = np.where(use_front, x_u, -x_u)
    lens_y = y_u
    lens_z = np.clip(np.where(use_front, z_u, -z_u), -1.0, 1.0)

    # Radial angle theta
    lens_theta = np.arccos(lens_z)
    sin_lens_theta = np.sin(lens_theta)

    # Equidistant fisheye mapping
    r = radius * lens_theta / (np.pi / 2.0)

    map_dx = np.zeros_like(lens_theta)
    map_dy = np.zeros_like(lens_theta)

    valid = sin_lens_theta > 1e-6
    map_dx[valid] = r[valid] * (lens_x[valid] / sin_lens_theta[valid])
    map_dy[valid] = -r[valid] * (lens_y[valid] / sin_lens_theta[valid])

    map_x = cx + map_dx
    map_y = cy + map_dy

    # Hide out of lens hemisphere (theta > 90 deg)
    invalid = lens_theta > (np.pi / 2.0)
    map_x[invalid] = -1
    map_y[invalid] = -1

    return map_x.astype(np.float32), map_y.astype(np.float32)


def calibrate_obstacle_coordinates(
    raw_x_m, raw_z_m, x_scale=1.0, z_scale=1.0, z_offset_m=0.0
):
    """Apply vehicle-centered calibration to a raw BEV ground position."""
    return (
        float(raw_x_m) * float(x_scale),
        float(raw_z_m) * float(z_scale) + float(z_offset_m),
    )


def classify_obstacle_region(
    raw_x_m, raw_z_m, input_x_max_m, input_z_min_m, input_z_max_m
):
    """Classify why a raw position is inside or outside calibration data."""
    if raw_z_m < input_z_min_m:
        return "NEAR"
    if raw_z_m > input_z_max_m:
        return "FAR"
    if abs(raw_x_m) > input_x_max_m:
        return "SIDE"
    return "CAL"


def combine_obstacle_regions(range_region, lateral_region):
    """Combine independent distance and lateral states without hiding either."""
    if lateral_region == "SIDE" and range_region != "CAL":
        return f"{range_region}+SIDE"
    if lateral_region == "SIDE":
        return "SIDE"
    return range_region


class ObstacleRegionHysteresis:
    """Stabilize calibration-region labels around their thresholds."""

    def __init__(
        self,
        input_x_max_m,
        input_z_min_m,
        input_z_max_m,
        margin_m=0.03,
        confirm_frames=3,
    ):
        self.input_x_max_m = float(input_x_max_m)
        self.input_z_min_m = float(input_z_min_m)
        self.input_z_max_m = float(input_z_max_m)
        self.margin_m = max(0.0, float(margin_m))
        self.confirm_frames = max(1, int(confirm_frames))
        self.reset()

    def reset(self):
        self.stable_region = None
        self.pending_region = None
        self.pending_count = 0

    def _candidate_region(self, raw_x_m, raw_z_m):
        margin = self.margin_m

        # An active OUT state uses a tighter return threshold. This creates a
        # dead band, so small measurement noise cannot toggle the label.
        if (
            self.stable_region == "NEAR"
            and raw_z_m < self.input_z_min_m + margin
        ):
            return "NEAR"
        if (
            self.stable_region == "FAR"
            and raw_z_m > self.input_z_max_m - margin
        ):
            return "FAR"

        # CAL requires a wider threshold before changing to an OUT state.
        if raw_z_m < self.input_z_min_m - margin:
            return "NEAR"
        if raw_z_m > self.input_z_max_m + margin:
            return "FAR"

        if (
            self.stable_region == "SIDE"
            and abs(raw_x_m) > self.input_x_max_m - margin
        ):
            return "SIDE"
        if abs(raw_x_m) > self.input_x_max_m + margin:
            return "SIDE"
        return "CAL"

    def update(self, raw_x_m, raw_z_m):
        if self.stable_region is None:
            self.stable_region = classify_obstacle_region(
                float(raw_x_m),
                float(raw_z_m),
                self.input_x_max_m,
                self.input_z_min_m,
                self.input_z_max_m,
            )
            return self.stable_region

        candidate = self._candidate_region(float(raw_x_m), float(raw_z_m))
        if candidate == self.stable_region:
            self.pending_region = None
            self.pending_count = 0
            return self.stable_region

        if candidate != self.pending_region:
            self.pending_region = candidate
            self.pending_count = 1
        else:
            self.pending_count += 1

        if self.pending_count >= self.confirm_frames:
            self.stable_region = candidate
            self.pending_region = None
            self.pending_count = 0
        return self.stable_region


class BlueObstacleTracker:
    """Track one obstacle in vehicle coordinates with a constant-velocity KF."""

    def __init__(
        self,
        process_accel_std_mps2=1.5,
        measurement_std_m=0.03,
        max_missing_sec=0.25,
        max_dt_sec=0.2,
    ):
        self.process_accel_std_mps2 = max(
            1e-6, float(process_accel_std_mps2)
        )
        self.measurement_std_m = max(1e-6, float(measurement_std_m))
        self.max_missing_sec = max(0.0, float(max_missing_sec))
        self.max_dt_sec = max(1e-3, float(max_dt_sec))
        self.filter = cv2.KalmanFilter(4, 2)
        self.filter.measurementMatrix = np.array(
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
            dtype=np.float32,
        )
        measurement_variance = self.measurement_std_m ** 2
        self.filter.measurementNoiseCov = np.eye(2, dtype=np.float32) * (
            measurement_variance
        )
        self.reset()

    def reset(self):
        self.initialized = False
        self.last_update_time = None
        self.last_measurement_time = None
        self.filter.statePre = np.zeros((4, 1), dtype=np.float32)
        self.filter.statePost = np.zeros((4, 1), dtype=np.float32)
        self.filter.errorCovPost = np.diag(
            [
                self.measurement_std_m ** 2,
                self.measurement_std_m ** 2,
                0.25,
                0.25,
            ]
        ).astype(np.float32)

    def _set_motion_model(self, dt):
        dt = max(1e-3, min(float(dt), self.max_dt_sec))
        self.filter.transitionMatrix = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        accel_variance = self.process_accel_std_mps2 ** 2
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        self.filter.processNoiseCov = np.array(
            [
                [dt4 / 4.0, 0.0, dt3 / 2.0, 0.0],
                [0.0, dt4 / 4.0, 0.0, dt3 / 2.0],
                [dt3 / 2.0, 0.0, dt2, 0.0],
                [0.0, dt3 / 2.0, 0.0, dt2],
            ],
            dtype=np.float32,
        ) * accel_variance

    @staticmethod
    def _result(state, predicted, missing_age_sec):
        x_m, z_m, vx_mps, vz_mps = state.reshape(-1)
        return {
            "x_m": float(x_m),
            "z_m": float(z_m),
            "distance_m": math.hypot(float(x_m), float(z_m)),
            "vx_mps": float(vx_mps),
            "vz_mps": float(vz_mps),
            "predicted": bool(predicted),
            "missing_age_sec": float(missing_age_sec),
        }

    def update(self, measurement, timestamp=None):
        """Update with ``(x_m, z_m)`` or predict briefly when it is ``None``."""
        now = time.monotonic() if timestamp is None else float(timestamp)
        if not self.initialized:
            if measurement is None:
                return None
            x_m, z_m = (float(measurement[0]), float(measurement[1]))
            state = np.array([[x_m], [z_m], [0.0], [0.0]], dtype=np.float32)
            self.filter.statePre = state.copy()
            self.filter.statePost = state.copy()
            self.initialized = True
            self.last_update_time = now
            self.last_measurement_time = now
            return self._result(state, False, 0.0)

        dt = max(1e-3, now - self.last_update_time)
        self._set_motion_model(dt)
        predicted_state = self.filter.predict()
        self.last_update_time = now

        if measurement is not None:
            x_m, z_m = (float(measurement[0]), float(measurement[1]))
            corrected_state = self.filter.correct(
                np.array([[x_m], [z_m]], dtype=np.float32)
            )
            self.last_measurement_time = now
            return self._result(corrected_state, False, 0.0)

        missing_age_sec = max(0.0, now - self.last_measurement_time)
        if missing_age_sec > self.max_missing_sec:
            self.reset()
            return None
        return self._result(predicted_state, True, missing_age_sec)


def detect_blue_obstacle(
    bev_img,
    scale,
    min_area=250.0,
    x_scale=1.0,
    z_scale=1.0,
    z_offset_m=0.0,
    valid_input_x_max_m=None,
    valid_input_z_min_m=None,
    valid_input_z_max_m=None,
):
    """Detect the nearest point of the largest blue obstacle in a BEV image."""
    hsv = cv2.cvtColor(bev_img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (90, 70, 30), (140, 255, 255))
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [cnt for cnt in contours if cv2.contourArea(cnt) >= min_area]
    if not contours:
        return None, mask

    contour = max(contours, key=cv2.contourArea)
    points = contour[:, 0, :].astype(np.float32)
    image_center = np.array([bev_img.shape[1] / 2.0, bev_img.shape[0] / 2.0])
    distances = np.linalg.norm(points - image_center, axis=1)
    nearest_count = max(3, int(math.ceil(len(points) * 0.08)))
    nearest_indices = np.argpartition(distances, nearest_count - 1)[:nearest_count]
    contact = np.median(points[nearest_indices], axis=0)
    px, py = float(contact[0]), float(contact[1])

    raw_x_m = (px - image_center[0]) * scale
    raw_z_m = (image_center[1] - py) * scale
    x_m, z_m = calibrate_obstacle_coordinates(
        raw_x_m, raw_z_m, x_scale, z_scale, z_offset_m
    )
    region = "CAL"
    if None not in (
        valid_input_x_max_m, valid_input_z_min_m, valid_input_z_max_m
    ):
        region = classify_obstacle_region(
            raw_x_m,
            raw_z_m,
            float(valid_input_x_max_m),
            float(valid_input_z_min_m),
            float(valid_input_z_max_m),
        )
    result = {
        "pixel_x": px,
        "pixel_y": py,
        "raw_x_m": raw_x_m,
        "raw_z_m": raw_z_m,
        "raw_distance_m": math.hypot(raw_x_m, raw_z_m),
        "x_m": x_m,
        "z_m": z_m,
        "distance_m": math.hypot(x_m, z_m),
        "instant_region": region,
        "region": region,
        "calibration_valid": region == "CAL",
        "area_px": float(cv2.contourArea(contour)),
        "contour": contour,
    }
    return result, mask


class CalibrationWindow(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        
        # Load parameters
        self.config_path = args.config
        self.params = self.load_config()

        # Canvas Size
        self.bev_w = 500
        self.bev_h = 600

        # Prediction path variables (matching zc33s_ui.py)
        self.last_odom_time = 0.0
        self.prediction_odom_timeout = 0.5
        self.prediction_min_speed = 0.01
        self.prediction_angular_deadband = 0.005
        self.odom_linear_x = 0.0
        self.odom_angular_z = 0.0
        self.cmd_linear_x = 0.0
        self.cmd_angular_z = 0.0
        self.yaw_to_handle_ratio = 1.25
        self.handle_limit_deg = 450.0

        # WASD & Gear keyboard state
        self.current_gear = 1
        self.gear_speeds = {
            1: 0.35,
            2: 0.70,
            3: 1.20,
            4: 1.80,
            5: 2.50,
            6: 3.50,
        }
        self.keys_pressed = {
            Qt.Key_W: False,
            Qt.Key_A: False,
            Qt.Key_S: False,
            Qt.Key_D: False,
        }

        # STEP 2: Local Occupancy Grid Map Memory (Accumulated map)
        self.occupancy_map = np.zeros((self.bev_h, self.bev_w), dtype=np.float32)
        self.last_map_update_time = time.time()

        # Camera streams setup
        self.cap = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        
        self.map_x = None
        self.map_y = None
        self.map_dirty = True

        # Experiment recording state. Writers are opened on the first frame so
        # the files always use the camera's actual resolution.
        self.is_recording = False
        self.recording_session_dir = None
        self.recording_writers = {}
        self.recording_frame_count = 0
        self.recording_csv_file = None
        self.recording_csv_writer = None
        self.last_blue_detection = None
        self.last_blue_track = None
        self.blue_obstacle_tracker = self.create_blue_obstacle_tracker()
        (
            self.blue_range_hysteresis,
            self.blue_side_hysteresis,
        ) = self.create_blue_region_hysteresis()

        self.init_ui()
        self.start_capture()

    def load_config(self):
        defaults = {
            "camera_height": 0.58,
            "scale": 0.005,
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
            "yaw_deg": 0.0,
            "radius_scale": 0.96,
            "front_cx_offset": 0.0,
            "front_cy_offset": 0.0,
            "back_cx_offset": 0.0,
            "back_cy_offset": 0.0,
            "car_offset_x": 0.0,
            "car_offset_z": 0.0,
            "vehicle_profile": "kobuki",
            "footprint_shape": "circle",
            "car_width": 0.354,
            "car_length": 0.354,
            "show_circles": 1,
            "bowl_curve": 1.2,
            "forward_stretch": 0.0,
            "backward_stretch": 0.0,
            "white_thresh": 185,
            "sat_thresh": 60,
            "roi_forward": 2.5,
            "roi_side": 1.5,
            "max_area": 5000,
            "detect_blue_obstacle": 1,
            "blue_min_area": 250,
            "blue_calibration_x_scale": 1.0,
            "blue_calibration_z_scale": 1.0,
            "blue_calibration_z_offset_m": 0.0,
            "blue_calibration_input_x_max_m": 0.5,
            "blue_calibration_input_z_min_m": 0.65,
            "blue_calibration_input_z_max_m": 1.2,
            "blue_region_x_max_m": 0.5,
            "blue_region_distance_min_m": 0.75,
            "blue_region_distance_max_m": 1.4,
            "blue_region_hysteresis_margin_m": 0.03,
            "blue_region_confirm_frames": 3,
            "blue_tracking_enabled": 1,
            "blue_tracking_process_accel_std_mps2": 1.5,
            "blue_tracking_measurement_std_m": 0.03,
            "blue_tracking_max_missing_sec": 0.25,
            "blue_tracking_max_dt_sec": 0.2,
            "enable_ai": 0,
            "yolo_model": "yolov8s.pt"
        }
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    saved = json.load(f)
                    defaults.update(saved)
                    print(f"[INFO] Config loaded from {self.config_path}")
            except Exception as e:
                print(f"[WARN] Failed to load config: {e}")
        return defaults

    def save_config(self):
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.params, f, indent=4)
            print(f"[INFO] Config saved to {self.config_path}")
        except Exception as e:
            print(f"[ERROR] Failed to save config: {e}")

    def reset_config(self):
        self.params = {
            "camera_height": 0.58,
            "scale": 0.005,
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
            "yaw_deg": 0.0,
            "radius_scale": 0.96,
            "front_cx_offset": 0.0,
            "front_cy_offset": 0.0,
            "back_cx_offset": 0.0,
            "back_cy_offset": 0.0,
            "car_offset_x": 0.0,
            "car_offset_z": 0.0,
            "vehicle_profile": "kobuki",
            "footprint_shape": "circle",
            "car_width": 0.354,
            "car_length": 0.354,
            "show_circles": 1,
            "bowl_curve": 1.2,
            "forward_stretch": 0.0,
            "backward_stretch": 0.0,
            "white_thresh": 185,
            "sat_thresh": 60,
            "roi_forward": 2.5,
            "roi_side": 1.5,
            "max_area": 5000,
            "detect_blue_obstacle": 1,
            "blue_min_area": 250,
            "blue_calibration_x_scale": 1.0,
            "blue_calibration_z_scale": 1.0,
            "blue_calibration_z_offset_m": 0.0,
            "blue_calibration_input_x_max_m": 0.5,
            "blue_calibration_input_z_min_m": 0.65,
            "blue_calibration_input_z_max_m": 1.2,
            "blue_region_x_max_m": 0.5,
            "blue_region_distance_min_m": 0.75,
            "blue_region_distance_max_m": 1.4,
            "blue_region_hysteresis_margin_m": 0.03,
            "blue_region_confirm_frames": 3,
            "blue_tracking_enabled": 1,
            "blue_tracking_process_accel_std_mps2": 1.5,
            "blue_tracking_measurement_std_m": 0.03,
            "blue_tracking_max_missing_sec": 0.25,
            "blue_tracking_max_dt_sec": 0.2,
            "enable_ai": 0,
            "yolo_model": "yolov8s.pt"
        }
        self.update_sliders()
        self.map_dirty = True
        (
            self.blue_range_hysteresis,
            self.blue_side_hysteresis,
        ) = self.create_blue_region_hysteresis()
        self.blue_obstacle_tracker = self.create_blue_obstacle_tracker()
        self.last_blue_track = None

    def create_blue_obstacle_tracker(self):
        return BlueObstacleTracker(
            self.params.get("blue_tracking_process_accel_std_mps2", 1.5),
            self.params.get("blue_tracking_measurement_std_m", 0.03),
            self.params.get("blue_tracking_max_missing_sec", 0.25),
            self.params.get("blue_tracking_max_dt_sec", 0.2),
        )

    def create_blue_region_hysteresis(self):
        margin = self.params.get("blue_region_hysteresis_margin_m", 0.03)
        confirm_frames = self.params.get("blue_region_confirm_frames", 3)
        range_hysteresis = ObstacleRegionHysteresis(
            float("inf"),
            self.params.get("blue_region_distance_min_m", 0.75),
            self.params.get("blue_region_distance_max_m", 1.4),
            margin,
            confirm_frames,
        )
        side_hysteresis = ObstacleRegionHysteresis(
            self.params.get("blue_region_x_max_m", 0.5),
            float("-inf"),
            float("inf"),
            margin,
            confirm_frames,
        )
        return range_hysteresis, side_hysteresis

    def init_ui(self):
        self.setWindowTitle("360 Camera Bird's Eye View (AVM) Calibration Tool")
        self.setStyleSheet("""
            QWidget {
                background-color: #121214;
                color: #e1e1e6;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                border: 2px solid #282830;
                border-radius: 8px;
                margin-top: 1ex;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                color: #00e5ff;
            }
            QLabel {
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #282830;
                height: 4px;
                background: #1e1e22;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #00e5ff;
                border: 1px solid #00b3cc;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QPushButton {
                background-color: #202024;
                border: 1px solid #323238;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #282830;
                border-color: #00e5ff;
            }
            QPushButton#saveBtn {
                background-color: #004d40;
                border-color: #00e5ff;
            }
            QPushButton#saveBtn:hover {
                background-color: #00796b;
            }
        """)

        main_layout = QHBoxLayout(self)

        # 1. Left Layout - Bird's Eye View Label
        left_layout = QVBoxLayout()
        bev_title = QLabel("BIRD'S EYE VIEW (TOP-DOWN FLOOR PROJECTION)")
        bev_title.setFont(QFont("Arial", 11, QFont.Bold))
        bev_title.setStyleSheet("color: #00e5ff;")
        left_layout.addWidget(bev_title)
        
        self.bev_label = QLabel()
        self.bev_label.setFixedSize(self.bev_w, self.bev_h)
        self.bev_label.setStyleSheet("border: 2px solid #282830; background-color: #050508;")
        left_layout.addWidget(self.bev_label)

        record_layout = QHBoxLayout()
        self.record_btn = QPushButton("Start Recording")
        self.record_btn.clicked.connect(self.toggle_recording)
        self.record_status_label = QLabel("Not recording")
        self.record_status_label.setStyleSheet("color: #9e9e9e;")
        record_layout.addWidget(self.record_btn)
        record_layout.addWidget(self.record_status_label)
        left_layout.addLayout(record_layout)
        main_layout.addLayout(left_layout)

        # 2. Center Layout - Lane Detection & Occupancy Mask
        center_layout = QVBoxLayout()
        lane_mask_title = QLabel("WHITE LANE DETECTION & OCCUPANCY MASK")
        lane_mask_title.setFont(QFont("Arial", 11, QFont.Bold))
        lane_mask_title.setStyleSheet("color: #00e5ff;")
        center_layout.addWidget(lane_mask_title)

        self.lane_mask_label = QLabel()
        self.lane_mask_label.setFixedSize(self.bev_w, self.bev_h)
        self.lane_mask_label.setStyleSheet("border: 2px solid #282830; background-color: #050508;")
        center_layout.addWidget(self.lane_mask_label)

        # Bottom info section
        info_box = QGroupBox("Kobuki Robot Specifications")
        info_layout = QGridLayout()
        info_layout.addWidget(QLabel("Chassis:"), 0, 0)
        info_layout.addWidget(QLabel("Circular (Diameter: 354 mm / 0.354 m)"), 0, 1)
        info_layout.addWidget(QLabel("Default Height:"), 1, 0)
        info_layout.addWidget(QLabel("Camera is mounted at 580 mm (0.58 m) above floor"), 1, 1)
        info_box.setLayout(info_layout)
        center_layout.addWidget(info_box)
        main_layout.addLayout(center_layout)

        # 3. Right Layout - Calibration Sliders & Actions
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(10, 0, 10, 0)
        
        # Helper method to create synced slider + spinbox row
        self.control_widgets = {} # Stores (slider, spinbox, multiplier) for update_sliders
        
        def add_control(group_layout, name, unit, key, min_val, max_val, init_val, decimals, multiplier, callback):
            label = QLabel(f"{name} ({unit}):")
            label.setMinimumWidth(120)
            
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(int(round(min_val * multiplier)))
            slider.setMaximum(int(round(max_val * multiplier)))
            slider.setValue(int(round(init_val * multiplier)))
            
            if decimals == 0:
                spinbox = QSpinBox()
                spinbox.setRange(int(min_val), int(max_val))
                spinbox.setValue(int(init_val))
            else:
                spinbox = QDoubleSpinBox()
                spinbox.setRange(float(min_val), float(max_val))
                spinbox.setDecimals(decimals)
                spinbox.setSingleStep(1.0 / multiplier)
                spinbox.setValue(float(init_val))
                
            spinbox.setFixedWidth(70)
            
            # Sync slider -> spinbox
            def on_slider_val_changed(val):
                real_val = val / float(multiplier)
                if abs(spinbox.value() - real_val) > 1e-6:
                    spinbox.blockSignals(True)
                    spinbox.setValue(real_val)
                    spinbox.blockSignals(False)
                callback()
                
            # Sync spinbox -> slider
            def on_spin_val_changed(val):
                slider_val = int(round(val * multiplier))
                if slider.value() != slider_val:
                    slider.blockSignals(True)
                    slider.setValue(slider_val)
                    slider.blockSignals(False)
                callback()
                
            slider.valueChanged.connect(on_slider_val_changed)
            spinbox.valueChanged.connect(on_spin_val_changed)
            
            row_layout = QHBoxLayout()
            row_layout.addWidget(slider)
            row_layout.addWidget(spinbox)
            group_layout.addRow(label, row_layout)
            
            self.control_widgets[key] = (slider, spinbox, multiplier)
            return slider, spinbox

        # Projection Calibration Group
        proj_group = QGroupBox("1. Floor Projection Math")
        proj_layout = QFormLayout()
        
        self.sl_height, self.sp_height = add_control(
            proj_layout, "Cam Height (H)", "m", "camera_height", 0.20, 2.00, self.params["camera_height"], 2, 100.0, self.on_proj_slider_changed
        )
        self.sl_scale, self.sp_scale = add_control(
            proj_layout, "Scale (mm/px)", "mm", "scale", 0.001, 0.100, self.params["scale"], 3, 1000.0, self.on_proj_slider_changed
        )
        self.sl_pitch, self.sp_pitch = add_control(
            proj_layout, "Pitch (Tilt Forward)", "deg", "pitch_deg", -90.0, 90.0, self.params["pitch_deg"], 0, 1.0, self.on_proj_slider_changed
        )
        self.sl_roll, self.sp_roll = add_control(
            proj_layout, "Roll (Tilt Side)", "deg", "roll_deg", -30.0, 30.0, self.params["roll_deg"], 0, 1.0, self.on_proj_slider_changed
        )
        self.sl_yaw, self.sp_yaw = add_control(
            proj_layout, "Yaw (Rotate)", "deg", "yaw_deg", -180.0, 180.0, self.params["yaw_deg"], 0, 1.0, self.on_proj_slider_changed
        )
        self.sl_bowl, self.sp_bowl = add_control(
            proj_layout, "Bowl Distortion", "", "bowl_curve", 0.00, 50.00, self.params.get("bowl_curve", 0.0), 2, 100.0, self.on_proj_slider_changed
        )
        self.sl_forward_stretch, self.sp_forward_stretch = add_control(
            proj_layout, "Forward Stretch", "", "forward_stretch", 0.00, 3.00, self.params.get("forward_stretch", 0.0), 2, 100.0, self.on_proj_slider_changed
        )
        self.sl_backward_stretch, self.sp_backward_stretch = add_control(
            proj_layout, "Backward Stretch", "", "backward_stretch", 0.00, 3.00, self.params.get("backward_stretch", 0.0), 2, 100.0, self.on_proj_slider_changed
        )
        
        proj_group.setLayout(proj_layout)
        right_layout.addWidget(proj_group)

        # Lens Calibration Group
        lens_group = QGroupBox("2. Fisheye Lens Calibration")
        lens_layout = QFormLayout()
        
        self.sl_rad_scale, self.sp_rad_scale = add_control(
            lens_layout, "Lens Radius Scale", "%", "radius_scale", 0.80, 1.20, self.params["radius_scale"], 2, 100.0, self.on_proj_slider_changed
        )
        self.sl_fcx, self.sp_fcx = add_control(
            lens_layout, "Front Lens CX Off", "px", "front_cx_offset", -100.0, 100.0, self.params["front_cx_offset"], 0, 1.0, self.on_proj_slider_changed
        )
        self.sl_fcy, self.sp_fcy = add_control(
            lens_layout, "Front Lens CY Off", "px", "front_cy_offset", -100.0, 100.0, self.params["front_cy_offset"], 0, 1.0, self.on_proj_slider_changed
        )
        self.sl_bcx, self.sp_bcx = add_control(
            lens_layout, "Back Lens CX Off", "px", "back_cx_offset", -100.0, 100.0, self.params["back_cx_offset"], 0, 1.0, self.on_proj_slider_changed
        )
        self.sl_bcy, self.sp_bcy = add_control(
            lens_layout, "Back Lens CY Off", "px", "back_cy_offset", -100.0, 100.0, self.params["back_cy_offset"], 0, 1.0, self.on_proj_slider_changed
        )

        lens_group.setLayout(lens_layout)
        right_layout.addWidget(lens_group)

        # Vehicle geometry is independent of camera calibration so the same
        # perception pipeline can be moved from Kobuki to AI-FORMULA.
        robot_group = QGroupBox("3. Vehicle Geometry & Camera Offset")
        robot_layout = QFormLayout()

        self.combo_vehicle_profile = QComboBox()
        self.vehicle_profile_keys = list(VEHICLE_PROFILES.keys())
        for key in self.vehicle_profile_keys:
            self.combo_vehicle_profile.addItem(VEHICLE_PROFILES[key]["label"], key)
        current_profile = self.params.get("vehicle_profile", "custom")
        profile_index = self.combo_vehicle_profile.findData(current_profile)
        self.combo_vehicle_profile.setCurrentIndex(max(0, profile_index))
        self.combo_vehicle_profile.currentIndexChanged.connect(self.on_vehicle_profile_changed)
        robot_layout.addRow(QLabel("Vehicle Profile:"), self.combo_vehicle_profile)
        
        self.sl_car_x, self.sp_car_x = add_control(
            robot_layout, "Offset X", "cm", "car_offset_x", -1.00, 1.00, self.params["car_offset_x"], 2, 100.0, self.on_car_slider_changed
        )
        self.sl_car_z, self.sp_car_z = add_control(
            robot_layout, "Offset Z (Fwd/Bwd)", "cm", "car_offset_z", -1.00, 1.00, self.params["car_offset_z"], 2, 100.0, self.on_car_slider_changed
        )
        self.sl_car_width, self.sp_car_width = add_control(
            robot_layout, "Vehicle Width", "cm", "car_width", 0.10, 3.00, self.params["car_width"], 3, 100.0, self.on_car_slider_changed
        )
        self.sl_car_length, self.sp_car_length = add_control(
            robot_layout, "Vehicle Length", "cm", "car_length", 0.10, 3.00, self.params["car_length"], 3, 100.0, self.on_car_slider_changed
        )
        
        robot_group.setLayout(robot_layout)
        right_layout.addWidget(robot_group)

        # Lane Detection Threshold & Mask Group
        lane_group = QGroupBox("4. Lane Detection Parameters")
        lane_layout = QFormLayout()
        
        self.sl_white, self.sp_white = add_control(
            lane_layout, "White Threshold", "", "white_thresh", 100, 255, self.params.get("white_thresh", 185), 0, 1.0, self.on_lane_slider_changed
        )
        self.sl_sat, self.sp_sat = add_control(
            lane_layout, "Sat Threshold", "", "sat_thresh", 10, 255, self.params.get("sat_thresh", 60), 0, 1.0, self.on_lane_slider_changed
        )
        self.sl_roi_fwd, self.sp_roi_fwd = add_control(
            lane_layout, "ROI Forward", "m", "roi_forward", 0.5, 10.0, self.params.get("roi_forward", 2.5), 2, 100.0, self.on_lane_slider_changed
        )
        self.sl_roi_side, self.sp_roi_side = add_control(
            lane_layout, "ROI Side", "m", "roi_side", 0.5, 10.0, self.params.get("roi_side", 1.5), 2, 100.0, self.on_lane_slider_changed
        )
        self.sl_max_area, self.sp_max_area = add_control(
            lane_layout, "Max Area", "px", "max_area", 500, 30000, self.params.get("max_area", 5000), 0, 1.0, self.on_lane_slider_changed
        )
        
        lane_group.setLayout(lane_layout)
        right_layout.addWidget(lane_group)

        # AI Perception Group
        ai_group = QGroupBox("5. AI Perception & 3D Box (YOLOv8)")
        ai_layout = QFormLayout()
        
        self.chk_enable_ai = QCheckBox("Enable YOLOv8 AI Detection")
        self.chk_enable_ai.setChecked(self.params.get("enable_ai", 0) == 1)
        self.chk_enable_ai.stateChanged.connect(self.on_ai_checkbox_changed)
        ai_layout.addRow(self.chk_enable_ai)

        self.combo_yolo_model = QComboBox()
        self.combo_yolo_model.addItems(["yolov8n.pt (Nano - Faster)", "yolov8s.pt (Small - Balanced)", "yolov8m.pt (Medium - Precise)"])
        cur_model = self.params.get("yolo_model", "yolov8s.pt")
        if "yolov8n" in cur_model:
            self.combo_yolo_model.setCurrentIndex(0)
        elif "yolov8m" in cur_model:
            self.combo_yolo_model.setCurrentIndex(2)
        else:
            self.combo_yolo_model.setCurrentIndex(1)
        self.combo_yolo_model.currentIndexChanged.connect(self.on_yolo_model_changed)
        ai_layout.addRow(QLabel("YOLO Model Size:"), self.combo_yolo_model)

        ai_group.setLayout(ai_layout)
        right_layout.addWidget(ai_group)

        # Action layout
        btn_layout = QVBoxLayout()
        
        self.chk_circles = QCheckBox("Show lens calibration circles on raw feed")
        self.chk_circles.setChecked(self.params["show_circles"] == 1)
        self.chk_circles.stateChanged.connect(self.on_checkbox_changed)
        btn_layout.addWidget(self.chk_circles)

        self.chk_blue_obstacle = QCheckBox("Detect blue obstacle")
        self.chk_blue_obstacle.setChecked(
            self.params.get("detect_blue_obstacle", 1) == 1
        )
        self.chk_blue_obstacle.stateChanged.connect(self.on_checkbox_changed)
        btn_layout.addWidget(self.chk_blue_obstacle)
        
        h_btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save Config")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self.save_config)
        
        reset_btn = QPushButton("Reset Defaults")
        reset_btn.clicked.connect(self.reset_config)
        
        h_btn_layout.addWidget(save_btn)
        h_btn_layout.addWidget(reset_btn)
        btn_layout.addLayout(h_btn_layout)

        right_layout.addLayout(btn_layout)
        right_layout.addStretch()
        
        main_layout.addLayout(right_layout)

    def toggle_recording(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        timestamp += f"_{int(time.time() * 1000) % 1000:03d}"
        session_dir = os.path.abspath(os.path.join(self.args.record_dir, timestamp))
        try:
            os.makedirs(session_dir, exist_ok=False)
            metadata = {
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "device": str(self.args.device),
                "requested_camera_width": self.args.cam_width,
                "requested_camera_height": self.args.cam_height,
                "parameters": self.params,
            }
            with open(os.path.join(session_dir, "metadata.json"), "w") as f:
                json.dump(metadata, f, indent=4)
            self.recording_csv_file = open(
                os.path.join(session_dir, "detections.csv"), "w", newline=""
            )
            self.recording_csv_writer = csv.writer(self.recording_csv_file)
            self.recording_csv_writer.writerow([
                "frame", "time_sec", "detected", "pixel_x", "pixel_y",
                "raw_x_m", "raw_z_m", "raw_distance_m",
                "x_m", "z_m", "distance_m", "calibration_valid",
                "region", "instant_region", "area_px",
                "track_available", "track_predicted",
                "filtered_x_m", "filtered_z_m", "filtered_distance_m",
                "relative_vx_mps", "relative_vz_mps", "missing_age_sec"
            ])
        except Exception as e:
            print(f"[ERROR] Failed to prepare recording directory: {e}")
            self.record_status_label.setText("Recording error")
            self.record_status_label.setStyleSheet("color: #ff5252;")
            return

        self.recording_session_dir = session_dir
        self.recording_writers = {}
        self.recording_frame_count = 0
        self.is_recording = True
        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet("background-color: #7f0000; border-color: #ff5252;")
        self.record_status_label.setText("REC 00:00")
        self.record_status_label.setStyleSheet("color: #ff5252; font-weight: bold;")
        print(f"[INFO] Recording started: {session_dir}")

    def _open_recording_writers(self, frame):
        if not self.is_recording or self.recording_writers:
            return True

        raw_h, raw_w = frame.shape[:2]
        fps = float(self.cap.get(cv2.CAP_PROP_FPS)) if self.cap is not None else 0.0
        if not math.isfinite(fps) or fps < 1.0 or fps > 120.0:
            fps = 24.0

        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        specifications = {
            "raw": (raw_w, raw_h),
            "bev": (self.bev_w, self.bev_h),
            "detection": (self.bev_w, self.bev_h),
        }
        writers = {}
        for name, size in specifications.items():
            path = os.path.join(self.recording_session_dir, f"{name}.avi")
            writer = cv2.VideoWriter(path, fourcc, fps, size)
            if not writer.isOpened():
                for opened_writer in writers.values():
                    opened_writer.release()
                print(f"[ERROR] Failed to open video writer: {path}")
                return False
            writers[name] = writer

        self.recording_writers = writers
        print(f"[INFO] Recording video at {fps:.2f} fps, raw={raw_w}x{raw_h}")
        return True

    def record_frames(self, raw_frame, bev_frame, detection_frame):
        if not self.is_recording:
            return
        if not self._open_recording_writers(raw_frame):
            self.stop_recording()
            self.record_status_label.setText("Recording error")
            self.record_status_label.setStyleSheet("color: #ff5252;")
            return

        self.recording_writers["raw"].write(raw_frame)
        self.recording_writers["bev"].write(bev_frame)
        self.recording_writers["detection"].write(detection_frame)
        self.recording_frame_count += 1

        fps = float(self.cap.get(cv2.CAP_PROP_FPS)) if self.cap is not None else 0.0
        if not math.isfinite(fps) or fps < 1.0 or fps > 120.0:
            fps = 24.0
        detection = self.last_blue_detection
        track = self.last_blue_track
        if self.recording_csv_writer is not None:
            if detection is None:
                if track is None:
                    detection_values = [""] * 12
                else:
                    detection_values = [""] * 9 + [
                        track.get("region", ""),
                        track.get("instant_region", ""),
                        "",
                    ]
            else:
                detection_values = [
                    f'{detection["pixel_x"]:.2f}', f'{detection["pixel_y"]:.2f}',
                    f'{detection["raw_x_m"]:.4f}', f'{detection["raw_z_m"]:.4f}',
                    f'{detection["raw_distance_m"]:.4f}',
                    f'{detection["x_m"]:.4f}', f'{detection["z_m"]:.4f}',
                    f'{detection["distance_m"]:.4f}',
                    1 if detection["calibration_valid"] else 0,
                    detection["region"], detection["instant_region"],
                    f'{detection["area_px"]:.1f}'
                ]
            if track is None:
                tracking_values = [0, "", "", "", "", "", "", ""]
            else:
                tracking_values = [
                    1, 1 if track["predicted"] else 0,
                    f'{track["x_m"]:.4f}', f'{track["z_m"]:.4f}',
                    f'{track["distance_m"]:.4f}', f'{track["vx_mps"]:.4f}',
                    f'{track["vz_mps"]:.4f}',
                    f'{track["missing_age_sec"]:.4f}',
                ]
            self.recording_csv_writer.writerow([
                self.recording_frame_count,
                self.recording_frame_count / fps,
                1 if detection is not None else 0,
            ] + detection_values + tracking_values)
        elapsed_seconds = int(self.recording_frame_count / fps)
        self.record_status_label.setText(
            f"REC {elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}"
        )

    def stop_recording(self):
        if not self.is_recording and not self.recording_writers:
            return
        for writer in self.recording_writers.values():
            writer.release()
        if self.recording_csv_file is not None:
            self.recording_csv_file.close()
            self.recording_csv_file = None
            self.recording_csv_writer = None
        saved_dir = self.recording_session_dir
        frame_count = self.recording_frame_count
        self.recording_writers = {}
        self.is_recording = False
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("")
        self.record_status_label.setText(f"Saved {frame_count} frames")
        self.record_status_label.setStyleSheet("color: #69f0ae;")
        print(f"[INFO] Recording stopped: {saved_dir} ({frame_count} frames)")

    def update_sliders(self):
        # Temporarily block signals to avoid triggering multiple updates
        for key, (slider, spinbox, multiplier) in self.control_widgets.items():
            slider.blockSignals(True)
            spinbox.blockSignals(True)
            
            val = float(self.params.get(key, 0.0))
            slider.setValue(int(round(val * multiplier)))
            spinbox.setValue(val)
            
            slider.blockSignals(False)
            spinbox.blockSignals(False)

    def on_proj_slider_changed(self):
        # Update values from controls
        self.params["camera_height"] = self.sp_height.value()
        self.params["scale"] = self.sp_scale.value()
        self.params["pitch_deg"] = self.sp_pitch.value()
        self.params["roll_deg"] = self.sp_roll.value()
        self.params["yaw_deg"] = self.sp_yaw.value()
        self.params["radius_scale"] = self.sp_rad_scale.value()
        self.params["front_cx_offset"] = self.sp_fcx.value()
        self.params["front_cy_offset"] = self.sp_fcy.value()
        self.params["back_cx_offset"] = self.sp_bcx.value()
        self.params["back_cy_offset"] = self.sp_bcy.value()
        self.params["bowl_curve"] = self.sp_bowl.value()
        self.params["forward_stretch"] = self.sp_forward_stretch.value()
        self.params["backward_stretch"] = self.sp_backward_stretch.value()
        
        # Mark remapping matrices as dirty to force rebuild
        self.map_dirty = True

    def on_car_slider_changed(self):
        self.params["car_offset_x"] = self.sp_car_x.value()
        self.params["car_offset_z"] = self.sp_car_z.value()
        self.params["car_width"] = self.sp_car_width.value()
        self.params["car_length"] = self.sp_car_length.value()
        self.map_dirty = True

    def on_vehicle_profile_changed(self, index):
        profile_key = self.combo_vehicle_profile.itemData(index)
        if profile_key not in VEHICLE_PROFILES:
            return

        profile = VEHICLE_PROFILES[profile_key]
        self.params["vehicle_profile"] = profile_key
        self.params["footprint_shape"] = profile.get(
            "footprint_shape", self.params.get("footprint_shape", "rectangle")
        )

        # Apply only dimensions that are verified.  AI-FORMULA deliberately
        # retains the current editable values until the real chassis is measured.
        if "width" in profile:
            self.params["car_width"] = profile["width"]
        if "length" in profile:
            self.params["car_length"] = profile["length"]
        if "camera_height" in profile:
            self.params["camera_height"] = profile["camera_height"]

        self.update_sliders()
        self.map_dirty = True

    def on_lane_slider_changed(self):
        self.params["white_thresh"] = self.sp_white.value()
        self.params["sat_thresh"] = self.sp_sat.value()
        self.params["roi_forward"] = self.sp_roi_fwd.value()
        self.params["roi_side"] = self.sp_roi_side.value()
        self.params["max_area"] = self.sp_max_area.value()

    def on_checkbox_changed(self, state):
        self.params["show_circles"] = 1 if self.chk_circles.isChecked() else 0
        self.params["detect_blue_obstacle"] = (
            1 if self.chk_blue_obstacle.isChecked() else 0
        )
        if not self.chk_blue_obstacle.isChecked():
            self.blue_range_hysteresis.reset()
            self.blue_side_hysteresis.reset()

    def on_ai_checkbox_changed(self, state):
        self.params["enable_ai"] = 1 if self.chk_enable_ai.isChecked() else 0
        if self.params["enable_ai"] == 1 and getattr(self, 'yolo_model_obj', None) is None:
            self.load_yolo_model()

    def on_yolo_model_changed(self, index):
        models = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt"]
        if 0 <= index < len(models):
            self.params["yolo_model"] = models[index]
            if self.params.get("enable_ai", 0) == 1:
                self.load_yolo_model()

    def load_yolo_model(self):
        if not HAS_ULTRALYTICS:
            print("[WARN] Ultralytics package is not installed. AI Perception disabled.")
            return
        model_name = self.params.get("yolo_model", "yolov8s.pt")
        try:
            print(f"[INFO] Loading YOLOv8 model: {model_name}...")
            self.yolo_model_obj = YOLO(model_name)
            print(f"[INFO] YOLOv8 model {model_name} loaded successfully!")
        except Exception as e:
            print(f"[WARN] Initial load failed for {model_name}: {e}. Retrying with patched torch.load...")
            try:
                # Workaround for PyTorch 2.6 default weights_only=True restriction
                orig_load = torch.load
                def patched_load(*args, **kwargs):
                    if 'weights_only' not in kwargs:
                        kwargs['weights_only'] = False
                    return orig_load(*args, **kwargs)
                torch.load = patched_load
                self.yolo_model_obj = YOLO(model_name)
                torch.load = orig_load
                print(f"[INFO] YOLOv8 model {model_name} loaded successfully via fallback!")
            except Exception as e2:
                print(f"[ERROR] Failed to load YOLOv8 model {model_name}: {e2}")
                self.yolo_model_obj = None

    def process_ai_perception(self, img):
        if not HAS_ULTRALYTICS or self.params.get("enable_ai", 0) != 1:
            return
        if getattr(self, 'yolo_model_obj', None) is None:
            self.load_yolo_model()
            if getattr(self, 'yolo_model_obj', None) is None:
                return

        # Perform inference on BEV image or camera frame
        try:
            results = self.yolo_model_obj(img, verbose=False, conf=0.25)
            for r in results:
                boxes = r.boxes
                for box in boxes:
                    # Class name & confidence
                    cls_id = int(box.cls[0])
                    label_name = self.yolo_model_obj.names[cls_id]
                    conf = float(box.conf[0])
                    
                    # 2D Bounding box coordinates
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])
                    
                    # Draw 3D wireframe box
                    self.draw_3d_bounding_box_bev(img, x1, y1, x2, y2, label_name, conf)
        except Exception as e:
            print(f"[WARN] Error during YOLO inference: {e}")

    def draw_3d_bounding_box_bev(self, img, x1, y1, x2, y2, label, conf):
        """
        Draws a Tesla FSD-style 3D Wireframe Bounding Box on BEV image.
        """
        bw = x2 - x1
        bh = y2 - y1
        if bw <= 0 or bh <= 0:
            return

        # 3D Box height offset in pixels (proportional to object 2D height/width)
        box_h_px = int(min(bh * 0.4, 40))
        
        # Bottom rectangle (ground contact)
        b_tl = (x1, y2 - int(bh * 0.3))
        b_tr = (x2, y2 - int(bh * 0.3))
        b_br = (x2, y2)
        b_bl = (x1, y2)

        # Top rectangle (height offset)
        t_tl = (x1, b_tl[1] - box_h_px)
        t_tr = (x2, b_tr[1] - box_h_px)
        t_br = (x2, b_br[1] - box_h_px)
        t_bl = (x1, b_bl[1] - box_h_px)

        # Cyberpunk Cyan/Neon Green colors (BGR)
        box_color = (0, 229, 255) # Cyan
        top_color = (0, 255, 120) # Green

        # Draw Bottom Face
        cv2.line(img, b_tl, b_tr, box_color, 1, cv2.LINE_AA)
        cv2.line(img, b_tr, b_br, box_color, 1, cv2.LINE_AA)
        cv2.line(img, b_br, b_bl, box_color, 1, cv2.LINE_AA)
        cv2.line(img, b_bl, b_tl, box_color, 1, cv2.LINE_AA)

        # Draw Top Face
        cv2.line(img, t_tl, t_tr, top_color, 2, cv2.LINE_AA)
        cv2.line(img, t_tr, t_br, top_color, 2, cv2.LINE_AA)
        cv2.line(img, t_br, t_bl, top_color, 2, cv2.LINE_AA)
        cv2.line(img, t_bl, t_tl, top_color, 2, cv2.LINE_AA)

        # Draw Vertical Pillars (Pillars connecting bottom to top)
        cv2.line(img, b_tl, t_tl, box_color, 1, cv2.LINE_AA)
        cv2.line(img, b_tr, t_tr, box_color, 1, cv2.LINE_AA)
        cv2.line(img, b_br, t_br, box_color, 1, cv2.LINE_AA)
        cv2.line(img, b_bl, t_bl, box_color, 1, cv2.LINE_AA)

        # Label tag (Tesla FSD Style)
        tag_text = f"{label} {conf:.2f}"
        cv2.putText(img, tag_text, (x1, max(15, t_tl[1] - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

    def start_capture(self):
        if self.args.mock_camera:
            print("[INFO] Initializing simulated mock 360 camera...")
            self.cap = MockCapture(self.args.cam_width, self.args.cam_height)
        else:
            device = self.args.device
            print(f"[INFO] Initializing hardware/video capture from: {device}")
            if str(device).isdigit():
                self.cap = cv2.VideoCapture(int(device), cv2.CAP_V4L2)
            else:
                self.cap = cv2.VideoCapture(str(device))
            
            # Request MJPG and set resolution
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.args.cam_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.args.cam_height)
            self.cap.set(cv2.CAP_PROP_FPS, 24)

        if not self.cap.isOpened():
            print(f"[ERROR] Failed to open capture device/file: {self.args.device}")
            sys.exit(1)

        # Trigger timer (24 fps -> ~41 ms interval)
        self.timer.start(41)

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            # Loop for video files
            if not self.args.mock_camera and not str(self.args.device).isdigit():
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                return
            print("[WARN] Failed to read frame")
            return

        in_h, in_w = frame.shape[:2]

        # Recompute projection map if dirty
        if self.map_dirty or self.map_x is None:
            self.map_x, self.map_y = make_floor_projection_map(
                in_w=in_w,
                in_h=in_h,
                out_w=self.bev_w,
                out_h=self.bev_h,
                camera_height=self.params["camera_height"],
                scale=self.params["scale"],
                pitch_deg=self.params["pitch_deg"],
                roll_deg=self.params["roll_deg"],
                yaw_deg=self.params["yaw_deg"],
                radius_scale=self.params["radius_scale"],
                front_cx_offset=self.params["front_cx_offset"],
                front_cy_offset=self.params["front_cy_offset"],
                back_cx_offset=self.params["back_cx_offset"],
                back_cy_offset=self.params["back_cy_offset"],
                bowl_curve=self.params.get("bowl_curve", 0.0),
                camera_offset_x=self.params["car_offset_x"],
                camera_offset_z=self.params["car_offset_z"],
                forward_stretch=self.params.get("forward_stretch", 0.0),
                backward_stretch=self.params.get("backward_stretch", 0.0)
            )
            self.map_dirty = False

        # Process STEP 1: White Lane Detection & Mask Generation
        bev_img = cv2.remap(
            frame,
            self.map_x,
            self.map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0)
        )
        lane_mask_visual = self.process_white_lane_detection(bev_img)

        # Detect the blue evaluation target before drawing vehicle/UI overlays.
        self.last_blue_detection = None
        tracking_enabled = self.params.get("blue_tracking_enabled", 1) == 1
        if self.params.get("detect_blue_obstacle", 1) == 1:
            self.last_blue_detection, _ = detect_blue_obstacle(
                bev_img,
                max(float(self.params["scale"]), 1e-6),
                float(self.params.get("blue_min_area", 250)),
                x_scale=float(self.params.get("blue_calibration_x_scale", 1.0)),
                z_scale=float(self.params.get("blue_calibration_z_scale", 1.0)),
                z_offset_m=float(
                    self.params.get("blue_calibration_z_offset_m", 0.0)
                ),
                valid_input_x_max_m=float(
                    self.params.get("blue_calibration_input_x_max_m", 0.5)
                ),
                valid_input_z_min_m=float(
                    self.params.get("blue_calibration_input_z_min_m", 0.65)
                ),
                valid_input_z_max_m=float(
                    self.params.get("blue_calibration_input_z_max_m", 1.2)
                ),
            )
            measurement = None
            if self.last_blue_detection is not None:
                measurement = (
                    self.last_blue_detection["x_m"],
                    self.last_blue_detection["z_m"],
                )
            if tracking_enabled:
                self.last_blue_track = self.blue_obstacle_tracker.update(measurement)
            elif measurement is not None:
                self.blue_obstacle_tracker.reset()
                self.last_blue_track = {
                    "x_m": measurement[0],
                    "z_m": measurement[1],
                    "distance_m": math.hypot(*measurement),
                    "vx_mps": 0.0,
                    "vz_mps": 0.0,
                    "predicted": False,
                    "missing_age_sec": 0.0,
                }
            else:
                self.blue_obstacle_tracker.reset()
                self.last_blue_track = None

            if self.last_blue_track is not None:
                # Convert the filtered vehicle coordinate back to the BEV only
                # for drawing a marker during a short prediction-only period.
                x_scale = float(
                    self.params.get("blue_calibration_x_scale", 1.0)
                )
                z_scale = float(
                    self.params.get("blue_calibration_z_scale", 1.0)
                )
                z_offset_m = float(
                    self.params.get("blue_calibration_z_offset_m", 0.0)
                )
                bev_scale = max(float(self.params["scale"]), 1e-6)
                if abs(x_scale) > 1e-6 and abs(z_scale) > 1e-6:
                    raw_track_x_m = self.last_blue_track["x_m"] / x_scale
                    raw_track_z_m = (
                        self.last_blue_track["z_m"] - z_offset_m
                    ) / z_scale
                    self.last_blue_track["pixel_x"] = (
                        self.bev_w / 2.0 + raw_track_x_m / bev_scale
                    )
                    self.last_blue_track["pixel_y"] = (
                        self.bev_h / 2.0 - raw_track_z_m / bev_scale
                    )
                instant_range_region = classify_obstacle_region(
                    0.0,
                    self.last_blue_track["distance_m"],
                    float("inf"),
                    float(self.params.get("blue_region_distance_min_m", 0.75)),
                    float(self.params.get("blue_region_distance_max_m", 1.4)),
                )
                instant_side_region = classify_obstacle_region(
                    self.last_blue_track["x_m"],
                    0.0,
                    float(self.params.get("blue_region_x_max_m", 0.5)),
                    float("-inf"),
                    float("inf"),
                )
                stable_range_region = self.blue_range_hysteresis.update(
                    0.0, self.last_blue_track["distance_m"]
                )
                stable_side_region = self.blue_side_hysteresis.update(
                    self.last_blue_track["x_m"], 0.0
                )
                self.last_blue_track["instant_region"] = (
                    combine_obstacle_regions(
                        instant_range_region, instant_side_region
                    )
                )
                self.last_blue_track["region"] = combine_obstacle_regions(
                    stable_range_region, stable_side_region
                )
                if self.last_blue_detection is not None:
                    self.last_blue_detection["instant_region"] = (
                        self.last_blue_track["instant_region"]
                    )
                    self.last_blue_detection["region"] = self.last_blue_track[
                        "region"
                    ]
            else:
                self.blue_range_hysteresis.reset()
                self.blue_side_hysteresis.reset()
        else:
            self.blue_obstacle_tracker.reset()
            self.last_blue_track = None
            self.blue_range_hysteresis.reset()
            self.blue_side_hysteresis.reset()

        # Process AI Perception (YOLOv8 Object Detection & 3D Box Rendering)
        if self.params.get("enable_ai", 0) == 1:
            self.process_ai_perception(bev_img)
            self.process_ai_perception(lane_mask_visual)

        # Draw overlays on BEV
        self.draw_bev_overlays(bev_img)
        self.draw_blue_obstacle_detection(
            bev_img, self.last_blue_detection, self.last_blue_track
        )
        self.draw_blue_obstacle_detection(
            lane_mask_visual, self.last_blue_detection, self.last_blue_track
        )

        # Save the camera input and both processed views for later evaluation.
        self.record_frames(frame, bev_img, lane_mask_visual)

        # Display images to UI
        self.display_image(self.bev_label, bev_img)
        self.display_image(self.lane_mask_label, lane_mask_visual)

    @staticmethod
    def draw_blue_obstacle_detection(img, detection, track=None):
        if detection is None and track is None:
            return
        region_source = track if track is not None else detection
        region = region_source.get("region", "CAL")
        region_colors = {
            "CAL": (0, 165, 255),
            "NEAR": (0, 0, 255),
            "FAR": (255, 255, 0),
            "SIDE": (255, 0, 255),
            "NEAR+SIDE": (128, 0, 255),
            "FAR+SIDE": (255, 128, 255),
        }
        color = region_colors.get(region, (0, 165, 255))
        if detection is not None:
            contour = detection["contour"]
            px = int(round(detection["pixel_x"]))
            py = int(round(detection["pixel_y"]))
            cv2.drawContours(img, [contour], -1, color, 2, cv2.LINE_AA)
            cv2.drawMarker(
                img, (px, py), color, cv2.MARKER_CROSS,
                markerSize=16, thickness=2, line_type=cv2.LINE_AA
            )
        else:
            px = int(round(track.get("pixel_x", img.shape[1] / 2.0)))
            py = int(round(track.get("pixel_y", img.shape[0] / 2.0)))
            if 0 <= px < img.shape[1] and 0 <= py < img.shape[0]:
                cv2.drawMarker(
                    img, (px, py), color, cv2.MARKER_DIAMOND,
                    markerSize=14, thickness=2, line_type=cv2.LINE_AA
                )
        position = track if track is not None else detection
        prediction_label = " PRED" if position.get("predicted", False) else ""
        text = (
            f'BLUE[{region}{prediction_label}] x={position["x_m"]:+.2f}m '
            f'z={position["z_m"]:.2f}m d={position["distance_m"]:.2f}m'
        )
        text_x = max(5, min(img.shape[1] - 300, px - 100))
        text_y = max(45, min(img.shape[0] - 10, py - 12))
        cv2.putText(
            img, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX,
            0.45, color, 2, cv2.LINE_AA
        )
        if track is not None:
            velocity_text = (
                f'REL vx={track["vx_mps"]:+.2f}m/s '
                f'vz={track["vz_mps"]:+.2f}m/s'
            )
            velocity_y = max(18, min(img.shape[0] - 5, text_y + 18))
            cv2.putText(
                img, velocity_text, (text_x, velocity_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, color, 1, cv2.LINE_AA
            )

    def process_white_lane_detection(self, bev_img):
        """
        STEP 1 Prototype: Detects white lane markings (solid, dashed, curves) from BEV image,
        applies sliding window polynomial fitting, and returns a binary/color mask image.
        """
        h, w = bev_img.shape[:2]

        # 1. Convert to HLS color space (L: Lightness, S: Saturation)
        hls = cv2.cvtColor(bev_img, cv2.COLOR_BGR2HLS)
        l_channel = hls[:, :, 1]
        s_channel = hls[:, :, 2]

        # 2. Strict thresholding on Lightness (L >= white_thresh) to ignore grey floor
        white_t = int(self.params.get("white_thresh", 185))
        _, l_mask = cv2.threshold(l_channel, white_t, 255, cv2.THRESH_BINARY)

        # 3. Saturation filter (S < sat_thresh) to exclude colored reflections
        sat_t = int(self.params.get("sat_thresh", 60))
        _, s_mask = cv2.threshold(s_channel, sat_t, 255, cv2.THRESH_BINARY_INV)

        # Combine L and S masks (pure bright white line only)
        binary_mask = cv2.bitwise_and(l_mask, s_mask)

        # Morphological close to bridge dashed lines
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 7))
        binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel)

        # 4. ROI (Region of Interest) Physical Distance Masking
        roi_fwd = float(self.params.get("roi_forward", 2.5))
        roi_side = float(self.params.get("roi_side", 1.5))
        scale = float(self.params.get("scale", 0.005))
        if scale <= 0.0:
            scale = 0.005

        cx_px = w / 2.0 + (self.params.get("car_offset_x", 0.0) / scale)
        cy_px = h / 2.0 - (self.params.get("car_offset_z", 0.0) / scale)

        y_coords, x_coords = np.ogrid[:h, :w]
        dist_x_m = np.abs(x_coords - cx_px) * scale
        dist_z_m = np.abs(cy_px - y_coords) * scale

        roi_mask = (dist_x_m <= roi_side) & (dist_z_m <= roi_fwd)
        binary_mask[~roi_mask] = 0

        # 5. Create visual output image (BGR)
        mask_visual = cv2.cvtColor(binary_mask, cv2.COLOR_GRAY2BGR)

        # Draw ROI boundary box on mask visual (Red line)
        roi_min_x = int(max(0, cx_px - roi_side / scale))
        roi_max_x = int(min(w - 1, cx_px + roi_side / scale))
        roi_min_y = int(max(0, cy_px - roi_fwd / scale))
        roi_max_y = int(min(h - 1, cy_px + roi_fwd / scale))
        cv2.rectangle(mask_visual, (roi_min_x, roi_min_y), (roi_max_x, roi_max_y), (80, 80, 220), 1)

        # 6. Robust Localized Fitting using cv2.fitLine (Prevents wild screen-wide crossing lines)
        contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        max_area = float(self.params.get("max_area", 5000))

        for cnt in contours:
            area = cv2.contourArea(cnt)
            # Ignore small noise dots AND huge background regions (walls/reflections)
            if area < 30 or area > max_area:
                continue

            # Bounding box of the detected tape segment
            x_box, y_box, w_box, h_box = cv2.boundingRect(cnt)
            cv2.rectangle(mask_visual, (x_box, y_box), (x_box + w_box, y_box + h_box), (0, 255, 120), 1)

            # Require minimum height or width to avoid fitting random small spots
            if h_box < 15 and w_box < 15:
                continue

            # Fit straight line direction vector (vx, vy) and point (x0, y0) for THIS contour only
            [vx, vy, x0, y0] = cv2.fitLine(cnt, cv2.DIST_L2, 0, 0.01, 0.01)
            
            vx = float(vx[0])
            vy = float(vy[0])
            x0 = float(x0[0])
            y0 = float(y0[0])

            # Calculate line endpoints restricted strictly to the Y-span of this contour segment
            if abs(vy) > 1e-4:
                y1 = float(y_box)
                y2 = float(y_box + h_box)
                x1 = x0 + (y1 - y0) * (vx / vy)
                x2 = x0 + (y2 - y0) * (vx / vy)

                # Clamp endpoints to image boundaries
                x1 = max(0, min(w - 1, int(x1)))
                x2 = max(0, min(w - 1, int(x2)))
                y1 = int(y1)
                y2 = int(y2)

                # Draw fitted yellow line segment OVER the actual detected tape region only
                cv2.line(mask_visual, (x1, y1), (x2, y2), (0, 229, 255), 3, cv2.LINE_AA)

        # Header info overlay
        cv2.putText(mask_visual, "STEP 1: LOCALIZED CONTOUR FITLINE (STABLE)", (15, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 120), 1, cv2.LINE_AA)

        # STEP 2: Update persistent local occupancy grid map memory with vehicle motion
        accumulated_map_visual = self.update_occupancy_map(binary_mask)

        # Blend accumulated persistent map with current frame's fitted lines
        final_visual = cv2.addWeighted(accumulated_map_visual, 0.65, mask_visual, 0.35, 0)
        cv2.putText(final_visual, "STEP 2: LOCAL OCCUPANCY MAP ACCUMULATION (TESLA STYLE)", (15, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 229, 255), 1, cv2.LINE_AA)

        return final_visual

    def update_occupancy_map(self, binary_mask):
        """
        STEP 2: Accumulates detected white lines into a persistent local occupancy grid map,
        and scrolls/rotates the map matrix according to vehicle odometry (v, w) velocity commands.
        """
        now = time.time()
        dt = now - self.last_map_update_time
        self.last_map_update_time = now

        # Prevent large jump on first frame
        if dt > 0.2:
            dt = 0.04

        h, w = binary_mask.shape[:2]
        center_x = w / 2.0
        center_y = h / 2.0
        scale = float(self.params["scale"])
        if scale <= 0:
            scale = 0.005

        # Robot vehicle velocities (WASD commands or odom)
        v = float(self.cmd_linear_x)
        w_rad = float(self.cmd_angular_z)

        # 1. Calculate map scroll shift & rotation based on vehicle motion over dt
        # Forward displacement in meters
        d_s = v * dt
        # Pixel shift (Forward motion moves background map downwards)
        dy_px = d_s / scale

        # Heading angle rotation in degrees
        d_yaw_deg = math.degrees(w_rad * dt)

        # Rotation center at vehicle position
        rob_offset_x_px = int(self.params["car_offset_x"] / scale)
        rob_offset_z_px = int(self.params["car_offset_z"] / scale)
        rx = center_x + rob_offset_x_px
        ry = center_y - rob_offset_z_px

        # Compute affine transformation matrix for map scrolling & rotation
        # Note: If vehicle turns left (+w), background map rotates right (-d_yaw_deg)
        M = cv2.getRotationMatrix2D((rx, ry), -d_yaw_deg, 1.0)
        M[1, 2] += dy_px  # Scroll map downwards when moving forward

        # Apply warpAffine to scroll existing map memory
        self.occupancy_map = cv2.warpAffine(
            self.occupancy_map, M, (w, h),
            borderMode=cv2.BORDER_CONSTANT, borderValue=0.0
        )

        # 2. Apply decay filter to gradually fade out stale noise (decay factor = 0.985)
        self.occupancy_map *= 0.985

        # 3. Fuse current frame binary mask into accumulated map
        current_mask = (binary_mask.astype(np.float32) / 255.0)
        self.occupancy_map = np.clip(self.occupancy_map + current_mask * 0.45, 0.0, 1.0)

        # 4. Generate color visualization for accumulated map (Glowing Cyan/Blue)
        map_uint8 = (self.occupancy_map * 255).astype(np.uint8)
        accumulated_visual = cv2.cvtColor(map_uint8, cv2.COLOR_GRAY2BGR)
        
        active_mask = map_uint8 > 25
        accumulated_visual[active_mask, 0] = np.clip(map_uint8[active_mask] * 1.0, 0, 255) # B
        accumulated_visual[active_mask, 1] = np.clip(map_uint8[active_mask] * 0.8, 0, 255) # G
        accumulated_visual[active_mask, 2] = np.clip(map_uint8[active_mask] * 0.2, 0, 255) # R

        return accumulated_visual

    def draw_fisheye_calibration_circles(self, frame):
        """
        Draws circles in the raw camera view to align lens radii and centers.
        """
        h, w = frame.shape[:2]
        radius = int(min(w / 4.0, h / 2.0) * self.params["radius_scale"])
        cy_base = h / 2.0
        
        front_cx_base = w * 0.3125
        back_cx_base = w * 0.6875
        
        fcx = int(front_cx_base + self.params["front_cx_offset"])
        fcy = int(cy_base + self.params["front_cy_offset"])
        bcx = int(back_cx_base + self.params["back_cx_offset"])
        bcy = int(cy_base + self.params["back_cy_offset"])

        # Draw Front circle in Cyan
        cv2.circle(frame, (fcx, fcy), radius, (255, 255, 0), 2)
        cv2.circle(frame, (fcx, fcy), 4, (255, 255, 0), -1)
        cv2.putText(frame, "FRONT LENS CALIBRATION", (fcx - 80, fcy - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1, cv2.LINE_AA)

        # Draw Rear circle in Magenta
        cv2.circle(frame, (bcx, bcy), radius, (255, 0, 255), 2)
        cv2.circle(frame, (bcx, bcy), 4, (255, 0, 255), -1)
        cv2.putText(frame, "REAR LENS CALIBRATION", (bcx - 70, bcy - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1, cv2.LINE_AA)

    def draw_bev_overlays(self, bev_img):
        """
        Draws the configured vehicle footprint and corner guide lines.
        """
        h, w = bev_img.shape[:2]
        center_x = w // 2
        center_y = h // 2

        # 1. Draw Diagonal Corner Guide Lines (Standard AVM grid seams)
        scale = max(float(self.params["scale"]), 1e-6)
        half_width_px = max(1, int(float(self.params["car_width"]) / (2.0 * scale)))
        half_length_px = max(1, int(float(self.params["car_length"]) / (2.0 * scale)))
        
        # Bounding box corners relative to the robot center
        corners = [
            (-half_width_px, -half_length_px),
            (half_width_px, -half_length_px),
            (-half_width_px, half_length_px),
            (half_width_px, half_length_px),
        ]

        # Draw diagonal seams extending outwards
        for cx, cy in corners:
            start_x = center_x + cx
            start_y = center_y + cy
            # Calculate unit direction vector pointing away from center
            dx = cx
            dy = cy
            d_norm = math.sqrt(dx*dx + dy*dy)
            if d_norm > 0:
                ux = dx / d_norm
                uy = dy / d_norm
                # Extend line to edge of screen
                end_x = int(start_x + ux * 500)
                end_y = int(start_y + uy * 500)
                cv2.line(bev_img, (start_x, start_y), (end_x, end_y), (100, 100, 100), 1, cv2.LINE_AA)

        # 2. Draw Predicted Trajectory Path (Tesla style translucent blue band)
        self.draw_predicted_path_on_bev(bev_img)

        # 3. Draw the vehicle footprint in the center (overwriting the blind spot)
        # Apply robot center offset
        rob_offset_x_px = int(self.params["car_offset_x"] / self.params["scale"])
        rob_offset_z_px = int(self.params["car_offset_z"] / self.params["scale"])
        
        rx = center_x + rob_offset_x_px
        ry = center_y - rob_offset_z_px  # -Z is forward (up) in pixel coords

        footprint_shape = self.params.get("footprint_shape", "rectangle")
        if footprint_shape == "circle":
            body_radius_px = half_width_px
            cv2.circle(bev_img, (rx, ry), body_radius_px, (45, 45, 48), -1)
            cv2.circle(bev_img, (rx, ry), body_radius_px, (0, 229, 255), 2)
        else:
            cv2.rectangle(
                bev_img,
                (rx - half_width_px, ry - half_length_px),
                (rx + half_width_px, ry + half_length_px),
                (45, 45, 48),
                -1,
            )
            cv2.rectangle(
                bev_img,
                (rx - half_width_px, ry - half_length_px),
                (rx + half_width_px, ry + half_length_px),
                (0, 229, 255),
                2,
            )

        # Draw Wheel cutouts (left/right wheel positions)
        wheel_w = max(2, int(half_width_px * 0.15))
        wheel_h = max(4, int(half_length_px * 0.5))
        # Left wheel
        cv2.rectangle(bev_img, 
                      (rx - half_width_px + 2, ry - wheel_h // 2),
                      (rx - half_width_px + 2 + wheel_w, ry + wheel_h // 2),
                      (20, 20, 20), -1)
        # Right wheel
        cv2.rectangle(bev_img, 
                      (rx + half_width_px - 2 - wheel_w, ry - wheel_h // 2),
                      (rx + half_width_px - 2, ry + wheel_h // 2),
                      (20, 20, 20), -1)

        if footprint_shape == "circle":
            # Forward is top (-Y in screen space, angle range 180 to 360)
            cv2.ellipse(
                bev_img, (rx, ry), (half_width_px, half_length_px),
                0, 200, 340, (80, 80, 85), 4
            )
        else:
            cv2.line(
                bev_img,
                (rx - half_width_px, ry - half_length_px),
                (rx + half_width_px, ry - half_length_px),
                (80, 80, 85),
                4,
                cv2.LINE_AA,
            )

        # Draw Status LEDs (two small green dots at the front left/right nose)
        led_offset = int(half_width_px * 0.5)
        led_y = ry - half_length_px + max(4, int(half_length_px * 0.15))
        cv2.circle(bev_img, (rx - led_offset, led_y), 4, (0, 255, 0), -1)
        cv2.circle(bev_img, (rx + led_offset, led_y), 4, (0, 255, 0), -1)

        # Draw Direction Arrow (triangle pointing forward/up)
        arrow_w = max(2, int(half_width_px * 0.25))
        arrow_h = max(3, int(half_length_px * 0.35))
        arrow_top = ry - half_length_px + 10
        pts = np.array([
            [rx, arrow_top],
            [rx - arrow_w, arrow_top + arrow_h],
            [rx + arrow_w, arrow_top + arrow_h],
        ], np.int32)
        cv2.fillPoly(bev_img, [pts], (0, 229, 255))

        # Text indicating camera center crosshair
        cv2.drawMarker(bev_img, (center_x, center_y), (0, 0, 255), 
                       cv2.MARKER_CROSS, markerSize=12, thickness=1, line_type=cv2.LINE_AA)

        # Draw Gear & Speed status overlay on BEV
        speed_max = self.gear_speeds[self.current_gear]
        gear_info = f"GEAR: {self.current_gear} | MAX V: {speed_max:.2f} m/s [Q:ShiftDown / E:ShiftUp]"
        cv2.putText(bev_img, gear_info, (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 229, 255), 1, cv2.LINE_AA)

    def predict_path_points(self, prediction_time=3.5, dt=0.05):
        """
        Calculates predicted path points identical to zc33s_ui.py logic.
        """
        now = time.time()
        odom_is_recent = (
            self.last_odom_time > 0.0
            and now - self.last_odom_time <= self.prediction_odom_timeout
        )

        if odom_is_recent and abs(self.odom_linear_x) >= self.prediction_min_speed:
            v = float(self.odom_linear_x)
        else:
            v = float(self.cmd_linear_x)

        if abs(self.cmd_angular_z) >= 1e-4:
            w = float(self.cmd_angular_z)
            source = "cmd"
        elif odom_is_recent and abs(self.odom_angular_z) >= self.prediction_angular_deadband:
            w = float(self.odom_angular_z)
            source = "odom"
        else:
            w = float(self.cmd_angular_z)
            source = "cmd"

        v_abs = abs(v)
        if (
            v_abs < self.prediction_min_speed
            and abs(w) < self.prediction_angular_deadband
        ):
            return []

        if source == "cmd":
            abs_cmd_w = abs(w)
            if abs_cmd_w > 1e-4:
                target_yaw_deg = 90.0 * ((abs_cmd_w / 0.8) ** (1.0 / 0.60))
                target_yaw_deg = min(360.0, target_yaw_deg)
                target_yaw_rad = math.radians(target_yaw_deg)
                
                w_base = target_yaw_rad / prediction_time
                v_ref = 0.8
                w = math.copysign(w_base * (v_abs / v_ref), w)
            else:
                w = 0.0

        min_distance = 1.5
        if v_abs > 1e-4:
            required_time = max(prediction_time, min_distance / v_abs)
            required_time = min(15.0, required_time)
        else:
            required_time = prediction_time

        x = 0.0
        y = 0.0
        yaw = 0.0
        points = []

        steps = int(required_time / dt)
        max_yaw_limit = math.radians(100.0)

        for _ in range(steps):
            x += v * math.cos(yaw) * dt
            y += v * math.sin(yaw) * dt
            yaw += w * dt
            points.append((x, y, yaw))
            if abs(yaw) >= max_yaw_limit:
                break

        return points

    def update_keyboard_input(self):
        """
        Updates cmd_linear_x and cmd_angular_z based on W, A, S, D key status and gear.
        Matches zc33s_ui.py keyboard driving logic.
        """
        target_v = 0.0
        target_w = 0.0
        gear_speed = self.gear_speeds[self.current_gear]

        if self.keys_pressed.get(Qt.Key_W, False):
            target_v = gear_speed  # Forward speed (m/s) based on gear
        elif self.keys_pressed.get(Qt.Key_S, False):
            target_v = -gear_speed * 0.7 # Backward speed (m/s)

        if self.keys_pressed.get(Qt.Key_A, False):
            target_w = 0.55  # Turn left (rad/s)
        elif self.keys_pressed.get(Qt.Key_D, False):
            target_w = -0.55 # Turn right (rad/s)

        self.cmd_linear_x = target_v
        self.cmd_angular_z = target_w

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D):
            self.keys_pressed[event.key()] = True
        elif event.key() == Qt.Key_Q:
            # Shift Down
            self.current_gear = max(1, self.current_gear - 1)
            print(f"[INFO] Shift Down -> Gear {self.current_gear} ({self.gear_speeds[self.current_gear]} m/s)")
        elif event.key() == Qt.Key_E:
            # Shift Up
            self.current_gear = min(6, self.current_gear + 1)
            print(f"[INFO] Shift Up -> Gear {self.current_gear} ({self.gear_speeds[self.current_gear]} m/s)")
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D) and not event.isAutoRepeat():
            self.keys_pressed[event.key()] = False
        else:
            super().keyReleaseEvent(event)

    def draw_predicted_path_on_bev(self, bev_img):
        """
        Draws Tesla-style translucent blue path polygon on Bird's Eye View image.
        """
        # Update velocities based on keyboard input
        self.update_keyboard_input()

        points = self.predict_path_points(prediction_time=3.5, dt=0.05)
        if len(points) < 2:
            return

        points = [(0.0, 0.0, 0.0)] + points

        h, w = bev_img.shape[:2]
        center_x = w // 2
        center_y = h // 2

        rob_offset_x_px = int(self.params["car_offset_x"] / self.params["scale"])
        rob_offset_z_px = int(self.params["car_offset_z"] / self.params["scale"])
        rx = center_x + rob_offset_x_px
        ry = center_y - rob_offset_z_px

        scale = float(self.params["scale"])
        if scale <= 0:
            return

        # Width of trajectory line (matching vehicle body width)
        half_width = float(self.params.get("car_width", 0.354)) / 2.0

        left_screen_points = []
        right_screen_points = []

        for x, y, yaw in points:
            # x is forward (longitudinal), y is lateral (positive left)
            x_l = x - half_width * math.sin(yaw)
            y_l = y + half_width * math.cos(yaw)

            x_r = x + half_width * math.sin(yaw)
            y_r = y - half_width * math.cos(yaw)

            # Map to BEV pixels
            # +x (forward) -> -Y on screen
            # +y (left) -> -X on screen
            px_l = int(rx - y_l / scale)
            py_l = int(ry - x_l / scale)

            px_r = int(rx - y_r / scale)
            py_r = int(ry - x_r / scale)

            left_screen_points.append((px_l, py_l))
            right_screen_points.append((px_r, py_r))

        if len(left_screen_points) < 2 or len(right_screen_points) < 2:
            return

        poly_points = left_screen_points + list(reversed(right_screen_points))
        pts = np.array(poly_points, dtype=np.int32).reshape((-1, 1, 2))

        overlay = bev_img.copy()
        # Tesla-style deep solid blue color BGR: (240, 110, 0)
        cv2.fillPoly(overlay, [pts], color=(240, 110, 0))

        # Blend with opacity 0.70
        cv2.addWeighted(overlay, 0.70, bev_img, 0.30, 0, dst=bev_img)

    def display_image(self, label, img):
        h, w, c = img.shape
        bytes_per_line = c * w
        # Convert BGR to RGB
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        q_img = QImage(rgb_img.data, w, h, bytes_per_line, QImage.Format_RGB888)
        
        # Scale to match label size smoothly
        scaled_pixmap = QPixmap.fromImage(q_img).scaled(
            label.width(), label.height(), 
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        label.setPixmap(scaled_pixmap)

    def closeEvent(self, event):
        self.timer.stop()
        self.stop_recording()
        if self.cap is not None:
            self.cap.release()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Kobuki 360-Camera Bird's Eye View Tool")
    parser.add_argument("--device", default="0", help="Camera index or video file path")
    parser.add_argument("--cam-width", type=int, default=1280, help="Camera width resolution")
    parser.add_argument("--cam-height", type=int, default=720, help="Camera height resolution")
    parser.add_argument("--mock-camera", action="store_true", help="Use simulated dual-fisheye frames")
    parser.add_argument("--config", default=DEFAULT_CONFIG_FILE, help="Path to config JSON file")
    parser.add_argument(
        "--record-dir", default="recordings",
        help="Directory where recording session folders are created"
    )
    
    args = parser.parse_args()

    app = QApplication(sys.argv)
    win = CalibrationWindow(args)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
