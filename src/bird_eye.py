#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import math
import json
import argparse
import time
import cv2
import numpy as np

from PySide6.QtCore import Qt, QTimer, QPoint, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QSlider, QGridLayout, QVBoxLayout,
    QHBoxLayout, QPushButton, QGroupBox, QFormLayout, QFileDialog, QCheckBox
)

# Configuration file name
DEFAULT_CONFIG_FILE = "bird_eye_config.json"

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
        cam_h = 0.45   # Camera height (default)
        
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
    front_lens="left"
):
    """
    Computes maps for cv2.remap that project a dual-fisheye image onto a horizontal floor plane.
    """
    # 1. Lens coordinates base
    radius = min(in_w / 4.0, in_h / 2.0) * radius_scale
    cy_base = in_h / 2.0
    
    if front_lens == "left":
        front_cx_base = in_w * 0.25
        back_cx_base = in_w * 0.75
    else:
        front_cx_base = in_w * 0.75
        back_cx_base = in_w * 0.25

    front_cx = front_cx_base + front_cx_offset
    front_cy = cy_base + front_cy_offset
    back_cx = back_cx_base + back_cx_offset
    back_cy = cy_base + back_cy_offset

    # 2. Setup ground grid in meters
    # Target center is (out_w/2, out_h/2).
    # X_w represents right-left axis, Z_w represents forward-backward axis.
    xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))
    X_w = (xs - out_w / 2.0) * scale
    Z_w = (out_h / 2.0 - ys) * scale
    
    if bowl_curve > 0.0:
        # X方向（左右）に 1.6 倍の重み、Z方向（前後）に 0.6 倍の重みをかけて d を計算
        # これにより、横方向は素早く立ち上がってお椀壁になり引き伸ばしが緩和され、
        # 正面方向は平らな地面が広く保たれるため直線歪みが小さくなります
        d = np.sqrt(1.6 * X_w * X_w + 0.6 * Z_w * Z_w)
        Y_w = -camera_height * np.exp(-bowl_curve * d)
    else:
        Y_w = -np.ones_like(X_w) * camera_height

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

        # Camera streams setup
        self.cap = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        
        self.map_x = None
        self.map_y = None
        self.map_dirty = True

        self.init_ui()
        self.start_capture()

    def load_config(self):
        defaults = {
            "camera_height": 0.45,
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
            "car_width": 0.354,
            "car_length": 0.354,
            "show_circles": 1,
            "bowl_curve": 0.0
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
            "camera_height": 0.45,
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
            "car_width": 0.354,
            "car_length": 0.354,
            "show_circles": 1,
            "bowl_curve": 0.0
        }
        self.update_sliders()
        self.map_dirty = True

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
        main_layout.addLayout(left_layout)

        # 2. Center Layout - Fisheye Label
        center_layout = QVBoxLayout()
        fisheye_title = QLabel("RAW DUAL-FISHEYE FEED & CALIBRATION SECTIONS")
        fisheye_title.setFont(QFont("Arial", 11, QFont.Bold))
        fisheye_title.setStyleSheet("color: #00e5ff;")
        center_layout.addWidget(fisheye_title)

        self.fisheye_label = QLabel()
        self.fisheye_label.setFixedSize(640, 360)
        self.fisheye_label.setStyleSheet("border: 2px solid #282830; background-color: #050508;")
        center_layout.addWidget(self.fisheye_label)

        # Bottom info section
        info_box = QGroupBox("Kobuki Robot Specifications")
        info_layout = QGridLayout()
        info_layout.addWidget(QLabel("Chassis:"), 0, 0)
        info_layout.addWidget(QLabel("Circular (Diameter: 354 mm / 0.354 m)"), 0, 1)
        info_layout.addWidget(QLabel("Default Height:"), 1, 0)
        info_layout.addWidget(QLabel("Camera is mounted at ~450 mm (0.45 m) above floor"), 1, 1)
        info_box.setLayout(info_layout)
        center_layout.addWidget(info_box)
        main_layout.addLayout(center_layout)

        # 3. Right Layout - Calibration Sliders & Actions
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(10, 0, 10, 0)
        
        # Projection Calibration Group
        proj_group = QGroupBox("1. Floor Projection Math")
        proj_layout = QFormLayout()
        
        self.sl_height = self.create_slider(20, 200, int(self.params["camera_height"] * 100), self.on_proj_slider_changed)
        proj_layout.addRow(self.create_slider_label("Cam Height (H)", "m"), self.sl_height)
        
        self.sl_scale = self.create_slider(1, 20, int(self.params["scale"] * 1000), self.on_proj_slider_changed)
        proj_layout.addRow(self.create_slider_label("Scale (mm/px)", "mm"), self.sl_scale)
        
        self.sl_pitch = self.create_slider(-30, 30, int(self.params["pitch_deg"]), self.on_proj_slider_changed)
        proj_layout.addRow(self.create_slider_label("Pitch (Tilt Forward)", "deg"), self.sl_pitch)
        
        self.sl_roll = self.create_slider(-30, 30, int(self.params["roll_deg"]), self.on_proj_slider_changed)
        proj_layout.addRow(self.create_slider_label("Roll (Tilt Side)", "deg"), self.sl_roll)
        
        self.sl_yaw = self.create_slider(-180, 180, int(self.params["yaw_deg"]), self.on_proj_slider_changed)
        proj_layout.addRow(self.create_slider_label("Yaw (Rotate)", "deg"), self.sl_yaw)
        
        self.sl_bowl = self.create_slider(0, 200, int(self.params.get("bowl_curve", 0.0) * 100), self.on_proj_slider_changed)
        proj_layout.addRow(self.create_slider_label("Bowl Distortion", ""), self.sl_bowl)
        
        proj_group.setLayout(proj_layout)
        right_layout.addWidget(proj_group)

        # Lens Calibration Group
        lens_group = QGroupBox("2. Fisheye Lens Calibration")
        lens_layout = QFormLayout()
        
        self.sl_rad_scale = self.create_slider(80, 120, int(self.params["radius_scale"] * 100), self.on_proj_slider_changed)
        lens_layout.addRow(self.create_slider_label("Lens Radius Scale", "%"), self.sl_rad_scale)
        
        self.sl_fcx = self.create_slider(-100, 100, int(self.params["front_cx_offset"]), self.on_proj_slider_changed)
        lens_layout.addRow(self.create_slider_label("Front Lens CX Off", "px"), self.sl_fcx)
        
        self.sl_fcy = self.create_slider(-100, 100, int(self.params["front_cy_offset"]), self.on_proj_slider_changed)
        lens_layout.addRow(self.create_slider_label("Front Lens CY Off", "px"), self.sl_fcy)

        self.sl_bcx = self.create_slider(-100, 100, int(self.params["back_cx_offset"]), self.on_proj_slider_changed)
        lens_layout.addRow(self.create_slider_label("Back Lens CX Off", "px"), self.sl_bcx)
        
        self.sl_bcy = self.create_slider(-100, 100, int(self.params["back_cy_offset"]), self.on_proj_slider_changed)
        lens_layout.addRow(self.create_slider_label("Back Lens CY Off", "px"), self.sl_bcy)

        lens_group.setLayout(lens_layout)
        right_layout.addWidget(lens_group)

        # Kobuki Robot Offset Group
        robot_group = QGroupBox("3. Kobuki Silhouette Offset")
        robot_layout = QFormLayout()
        
        self.sl_car_x = self.create_slider(-100, 100, int(self.params["car_offset_x"] * 100), self.on_car_slider_changed)
        robot_layout.addRow(self.create_slider_label("Offset X", "cm"), self.sl_car_x)
        
        self.sl_car_z = self.create_slider(-100, 100, int(self.params["car_offset_z"] * 100), self.on_car_slider_changed)
        robot_layout.addRow(self.create_slider_label("Offset Z (Fwd/Bwd)", "cm"), self.sl_car_z)
        
        self.sl_car_size = self.create_slider(10, 300, int(self.params["car_width"] * 100), self.on_car_slider_changed)
        robot_layout.addRow(self.create_slider_label("Chassis Size", "cm"), self.sl_car_size)
        
        robot_group.setLayout(robot_layout)
        right_layout.addWidget(robot_group)

        # Action layout
        btn_layout = QVBoxLayout()
        
        self.chk_circles = QCheckBox("Show lens calibration circles on raw feed")
        self.chk_circles.setChecked(self.params["show_circles"] == 1)
        self.chk_circles.stateChanged.connect(self.on_checkbox_changed)
        btn_layout.addWidget(self.chk_circles)
        
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

    def create_slider(self, min_v, max_v, init_v, callback):
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(min_v)
        slider.setMaximum(max_v)
        slider.setValue(init_v)
        slider.setTickInterval(1)
        slider.valueChanged.connect(callback)
        return slider

    def create_slider_label(self, name, unit):
        lbl = QLabel(f"{name} ({unit}):")
        lbl.setMinimumWidth(120)
        return lbl

    def update_sliders(self):
        # Temporarily block signals to avoid triggering multiple map updates
        self.sl_height.blockSignals(True)
        self.sl_scale.blockSignals(True)
        self.sl_pitch.blockSignals(True)
        self.sl_roll.blockSignals(True)
        self.sl_yaw.blockSignals(True)
        self.sl_rad_scale.blockSignals(True)
        self.sl_fcx.blockSignals(True)
        self.sl_fcy.blockSignals(True)
        self.sl_bcx.blockSignals(True)
        self.sl_bcy.blockSignals(True)
        self.sl_car_x.blockSignals(True)
        self.sl_car_z.blockSignals(True)
        self.sl_bowl.blockSignals(True)
        self.sl_car_size.blockSignals(True)

        self.sl_height.setValue(int(self.params["camera_height"] * 100))
        self.sl_scale.setValue(int(self.params["scale"] * 1000))
        self.sl_pitch.setValue(int(self.params["pitch_deg"]))
        self.sl_roll.setValue(int(self.params["roll_deg"]))
        self.sl_yaw.setValue(int(self.params["yaw_deg"]))
        self.sl_rad_scale.setValue(int(self.params["radius_scale"] * 100))
        self.sl_fcx.setValue(int(self.params["front_cx_offset"]))
        self.sl_fcy.setValue(int(self.params["front_cy_offset"]))
        self.sl_bcx.setValue(int(self.params["back_cx_offset"]))
        self.sl_bcy.setValue(int(self.params["back_cy_offset"]))
        self.sl_car_x.setValue(int(self.params["car_offset_x"] * 100))
        self.sl_car_z.setValue(int(self.params["car_offset_z"] * 100))
        self.sl_bowl.setValue(int(self.params.get("bowl_curve", 0.0) * 100))
        self.sl_car_size.setValue(int(self.params["car_width"] * 100))

        self.sl_height.blockSignals(False)
        self.sl_scale.blockSignals(False)
        self.sl_pitch.blockSignals(False)
        self.sl_roll.blockSignals(False)
        self.sl_yaw.blockSignals(False)
        self.sl_rad_scale.blockSignals(False)
        self.sl_fcx.blockSignals(False)
        self.sl_fcy.blockSignals(False)
        self.sl_bcx.blockSignals(False)
        self.sl_bcy.blockSignals(False)
        self.sl_car_x.blockSignals(False)
        self.sl_car_z.blockSignals(False)
        self.sl_bowl.blockSignals(False)
        self.sl_car_size.blockSignals(False)

    def on_proj_slider_changed(self):
        # Update values from sliders
        self.params["camera_height"] = self.sl_height.value() / 100.0
        self.params["scale"] = self.sl_scale.value() / 1000.0
        self.params["pitch_deg"] = float(self.sl_pitch.value())
        self.params["roll_deg"] = float(self.sl_roll.value())
        self.params["yaw_deg"] = float(self.sl_yaw.value())
        self.params["radius_scale"] = self.sl_rad_scale.value() / 100.0
        self.params["front_cx_offset"] = float(self.sl_fcx.value())
        self.params["front_cy_offset"] = float(self.sl_fcy.value())
        self.params["back_cx_offset"] = float(self.sl_bcx.value())
        self.params["back_cy_offset"] = float(self.sl_bcy.value())
        self.params["bowl_curve"] = self.sl_bowl.value() / 100.0
        
        # Mark remapping matrices as dirty to force rebuild
        self.map_dirty = True

    def on_car_slider_changed(self):
        self.params["car_offset_x"] = self.sl_car_x.value() / 100.0
        self.params["car_offset_z"] = self.sl_car_z.value() / 100.0
        self.params["car_width"] = self.sl_car_size.value() / 100.0
        self.params["car_length"] = self.sl_car_size.value() / 100.0

    def on_checkbox_changed(self, state):
        self.params["show_circles"] = 1 if self.chk_circles.isChecked() else 0

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
                bowl_curve=self.params.get("bowl_curve", 0.0)
            )
            self.map_dirty = False

        # Apply floor projection mapping
        bev_img = cv2.remap(
            frame,
            self.map_x,
            self.map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0)
        )

        # Draw overlays on BEV and Fisheye
        self.draw_bev_overlays(bev_img)
        
        # Display Raw Fisheye View
        raw_display = frame.copy()
        if self.params["show_circles"] == 1:
            self.draw_fisheye_calibration_circles(raw_display)

        # Convert to QPixmap and display
        self.display_image(self.bev_label, bev_img)
        self.display_image(self.fisheye_label, raw_display)

    def draw_fisheye_calibration_circles(self, frame):
        """
        Draws circles in the raw camera view to align lens radii and centers.
        """
        h, w = frame.shape[:2]
        radius = int(min(w / 4.0, h / 2.0) * self.params["radius_scale"])
        cy_base = h / 2.0
        
        front_cx_base = w * 0.25
        back_cx_base = w * 0.75
        
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
        Draws the Kobuki robot silhouette and corner guide lines.
        """
        h, w = bev_img.shape[:2]
        center_x = w // 2
        center_y = h // 2

        # 1. Draw Diagonal Corner Guide Lines (Standard AVM grid seams)
        # Bounding box of the robot in pixels:
        robot_radius_m = self.params["car_width"] / 2.0
        r_px = int(robot_radius_m / self.params["scale"])
        
        # Bounding box corners relative to the robot center
        corners = [
            (-r_px, -r_px),  # Top-Left
            (r_px, -r_px),   # Top-Right
            (-r_px, r_px),   # Bottom-Left
            (r_px, r_px)     # Bottom-Right
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

        # 2. Draw Kobuki Mobile Robot in the center (overwriting the blind spot)
        # Apply robot center offset
        rob_offset_x_px = int(self.params["car_offset_x"] / self.params["scale"])
        rob_offset_z_px = int(self.params["car_offset_z"] / self.params["scale"])
        
        rx = center_x + rob_offset_x_px
        ry = center_y - rob_offset_z_px  # -Z is forward (up) in pixel coords

        # Draw Kobuki circular body (solid charcoal grey base)
        cv2.circle(bev_img, (rx, ry), r_px, (45, 45, 48), -1)
        cv2.circle(bev_img, (rx, ry), r_px, (0, 229, 255), 2)  # Glowing cyan ring border

        # Draw Wheel cutouts (left/right wheel positions)
        wheel_w = int(r_px * 0.15)
        wheel_h = int(r_px * 0.4)
        # Left wheel
        cv2.rectangle(bev_img, 
                      (rx - r_px + 2, ry - wheel_h // 2), 
                      (rx - r_px + 2 + wheel_w, ry + wheel_h // 2), 
                      (20, 20, 20), -1)
        # Right wheel
        cv2.rectangle(bev_img, 
                      (rx + r_px - 2 - wheel_w, ry - wheel_h // 2), 
                      (rx + r_px - 2, ry + wheel_h // 2), 
                      (20, 20, 20), -1)

        # Draw Front Bumper Arc (Thick semi-circle at front edge)
        # Forward is top (-Y in screen space, angle range 180 to 360)
        cv2.ellipse(bev_img, (rx, ry), (r_px, r_px), 0, 200, 340, (80, 80, 85), 4)

        # Draw Status LEDs (two small green dots at the front left/right nose)
        led_offset = int(r_px * 0.5)
        cv2.circle(bev_img, (rx - led_offset, ry - led_offset), 4, (0, 255, 0), -1)
        cv2.circle(bev_img, (rx + led_offset, ry - led_offset), 4, (0, 255, 0), -1)

        # Draw Direction Arrow (triangle pointing forward/up)
        arrow_w = int(r_px * 0.25)
        arrow_h = int(r_px * 0.35)
        pts = np.array([
            [rx, ry - r_px + 10],                     # Top tip
            [rx - arrow_w, ry - r_px + 10 + arrow_h], # Bottom-left
            [rx + arrow_w, ry - r_px + 10 + arrow_h]  # Bottom-right
        ], np.int32)
        cv2.fillPoly(bev_img, [pts], (0, 229, 255))

        # Text indicating camera center crosshair
        cv2.drawMarker(bev_img, (center_x, center_y), (0, 0, 255), 
                       cv2.MARKER_CROSS, markerSize=12, thickness=1, line_type=cv2.LINE_AA)

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
    
    args = parser.parse_args()

    app = QApplication(sys.argv)
    win = CalibrationWindow(args)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
