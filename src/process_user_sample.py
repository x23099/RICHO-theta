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
    front_cx,
    front_cy,
    back_cx,
    back_cy,
    bowl_curve=0.0,
    flip_y=False
):
    # Radius calculated from the height of the fisheye area
    radius = (in_h / 2.0) * radius_scale

    xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))
    X_w = (xs - out_w / 2.0) * scale
    Z_w = (out_h / 2.0 - ys) * scale
    Y_w = -np.ones_like(X_w) * camera_height

    yaw = np.deg2rad(yaw_deg)
    pitch = np.deg2rad(pitch_deg)
    roll = np.deg2rad(roll_deg)

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
    cx = np.where(use_front, front_cx, back_cx)
    cy = np.where(use_front, front_cy, back_cy)

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
    if flip_y:
        map_dy[valid] = r[valid] * (lens_y[valid] / sin_lens_theta[valid])
    else:
        map_dy[valid] = -r[valid] * (lens_y[valid] / sin_lens_theta[valid])

    map_x = cx + map_dx
    map_y = cy + map_dy

    invalid = lens_theta > (np.pi / 2.0)
    map_x[invalid] = -1
    map_y[invalid] = -1

    return map_x.astype(np.float32), map_y.astype(np.float32)

def main():
    img_path = "/home/hsr/yopi_ws/RICHO-theta/images/image.png"
    out_dir = "/home/hsr/.gemini/antigravity-ide/brain/41d4f52c-f2ed-4e0b-8e8c-1313f00c857a"
    
    img = cv2.imread(img_path)
    if img is None:
        print("Error loading image")
        return
        
    h, w = img.shape[:2]
    fisheye_h = h // 2
    fisheye = img[0:fisheye_h, 0:w]

    bev_w, bev_h = 800, 800
    
    # We detected:
    # Left circle (front) center = 375, cy = 225, radius = 225
    # Right circle (back) center = 825, cy = 225, radius = 225
    
    # Run with original (flip_y=False) and corrected Y (flip_y=True)
    # also we'll test rotating yaw to align the seam nicely.
    for name, flip, yaw_deg in [
        ("original_centered", False, 0.0),
        ("corrected_centered", True, 0.0),
        ("original_centered_yaw90", False, 90.0),
        ("original_centered_yaw180", False, 180.0),
        ("original_centered_yaw270", False, 270.0),
    ]:
        mx, my = make_floor_projection_map(
            in_w=w,
            in_h=fisheye_h,
            out_w=bev_w,
            out_h=bev_h,
            camera_height=0.45,
            scale=0.005,
            pitch_deg=0.0,
            roll_deg=0.0,
            yaw_deg=yaw_deg,
            radius_scale=1.0,
            front_cx=375.0,
            front_cy=225.0,
            back_cx=825.0,
            back_cy=225.0,
            flip_y=flip
        )
        
        bev = cv2.remap(
            fisheye,
            mx,
            my,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0)
        )
        
        # Draw a small robot silhouette in the center
        robot_r = int((0.354 / 2.0) / 0.005)
        cv2.circle(bev, (bev_w // 2, bev_h // 2), robot_r, (45, 45, 48), -1)
        cv2.circle(bev, (bev_w // 2, bev_h // 2), robot_r, (0, 229, 255), 2)
        
        cv2.imwrite(os.path.join(out_dir, f"sample_bev_{name}.png"), bev)
        print(f"Saved sample_bev_{name}.png")

if __name__ == "__main__":
    main()
