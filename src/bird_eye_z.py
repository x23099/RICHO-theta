#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import cv2
import numpy as np

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
    # Note: If y_u is positive downwards, and we want positive displacement to be downwards in image:
    # Let's test both signs. In the original code, it was lens_y = y_u, map_dy = -r * (lens_y / sin_lens_theta)
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

def main():
    input_path = "/home/hsr/.gemini/antigravity-ide/brain/41d4f52c-f2ed-4e0b-8e8c-1313f00c857a/device_0.jpg"
    out_dir = "/home/hsr/.gemini/antigravity-ide/brain/41d4f52c-f2ed-4e0b-8e8c-1313f00c857a"
    
    img = cv2.imread(input_path)
    if img is None:
        print(f"Error: Could not load {input_path}")
        return

    h, w = img.shape[:2]
    print(f"Loaded image {w}x{h}")

    # Output dimensions for bird's eye view
    bev_w, bev_h = 800, 800

    # Let's generate a few variations:
    # 1. Original mapping configuration
    # 2. Corrected vertical direction (lens_y = -y_u or map_dy sign change)
    configs = [
        {"name": "original", "pitch": 0.0, "roll": 0.0, "yaw": 0.0, "flip_y": False},
        {"name": "corrected_y", "pitch": 0.0, "roll": 0.0, "yaw": 0.0, "flip_y": True},
        {"name": "tilt_pitch_10", "pitch": 10.0, "roll": 0.0, "yaw": 0.0, "flip_y": True},
    ]

    for cfg in configs:
        # Re-implement mapping locally for simple sign adjustment
        xs, ys = np.meshgrid(np.arange(bev_w), np.arange(bev_h))
        # Ground plane setup
        scale = 0.005 # 5mm per pixel -> 4 meters range
        camera_height = 0.45
        
        X_w = (xs - bev_w / 2.0) * scale
        Z_w = (bev_h / 2.0 - ys) * scale
        Y_w = -np.ones_like(X_w) * camera_height

        yaw = np.deg2rad(cfg["yaw"])
        pitch = np.deg2rad(cfg["pitch"])
        roll = np.deg2rad(cfg["roll"])

        # Rotations
        x1 = X_w * np.cos(yaw) + Z_w * np.sin(yaw)
        y1 = Y_w
        z1 = -X_w * np.sin(yaw) + Z_w * np.cos(yaw)

        x2 = x1
        y2 = y1 * np.cos(pitch) - z1 * np.sin(pitch)
        z2 = y1 * np.sin(pitch) + z1 * np.cos(pitch)

        x_c = x2 * np.cos(roll) - y2 * np.sin(roll)
        y_c = x2 * np.sin(roll) + y2 * np.cos(roll)
        z_c = z2

        norm = np.sqrt(x_c * x_c + y_c * y_c + z_c * z_c)
        norm = np.where(norm < 1e-6, 1.0, norm)
        x_u = x_c / norm
        y_u = y_c / norm
        z_u = z_c / norm

        use_front = z_u >= 0.0
        radius_scale = 0.96
        radius = min(w / 4.0, h / 2.0) * radius_scale
        cy_base = h / 2.0
        front_cx = w * 0.25
        back_cx = w * 0.75

        cx = np.where(use_front, front_cx, back_cx)
        cy = cy_base

        lens_x = np.where(use_front, x_u, -x_u)
        lens_y = y_u
        lens_z = np.clip(np.where(use_front, z_u, -z_u), -1.0, 1.0)

        lens_theta = np.arccos(lens_z)
        sin_lens_theta = np.sin(lens_theta)
        r = radius * lens_theta / (np.pi / 2.0)

        map_dx = np.zeros_like(lens_theta)
        map_dy = np.zeros_like(lens_theta)

        valid = sin_lens_theta > 1e-6
        map_dx[valid] = r[valid] * (lens_x[valid] / sin_lens_theta[valid])
        
        # Test original vs corrected Y direction
        if cfg["flip_y"]:
            # Corrected: positive lens_y maps to positive map_dy
            map_dy[valid] = r[valid] * (lens_y[valid] / sin_lens_theta[valid])
        else:
            map_dy[valid] = -r[valid] * (lens_y[valid] / sin_lens_theta[valid])

        map_x = cx + map_dx
        map_y = cy + map_dy

        invalid = lens_theta > (np.pi / 2.0)
        map_x[invalid] = -1
        map_y[invalid] = -1

        bev_img = cv2.remap(
            img,
            map_x.astype(np.float32),
            map_y.astype(np.float32),
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0)
        )

        # Draw a robot circle in the middle for reference
        robot_r = int((0.354 / 2.0) / scale)
        cv2.circle(bev_img, (bev_w // 2, bev_h // 2), robot_r, (100, 100, 100), -1)
        cv2.circle(bev_img, (bev_w // 2, bev_h // 2), robot_r, (0, 255, 0), 2)
        cv2.line(bev_img, (bev_w // 2, bev_h // 2), (bev_w // 2, bev_h // 2 - robot_r), (0, 0, 255), 2)

        out_name = f"bev_{cfg['name']}.jpg"
        out_path = os.path.join(out_dir, out_name)
        cv2.imwrite(out_path, bev_img)
        print(f"Saved BEV image to {out_path}")

if __name__ == "__main__":
    main()
