#!/usr/bin/env python3
"""Ground-contact localization for dual-fisheye obstacle masks.

The geometry in this module is intentionally independent from Qt and YOLO so
that recorded raw video can be evaluated on a headless machine.  Colour
segmentation is only an experiment adapter; ``estimate_ground_contact`` accepts
any contour supplied by a future segmentation or object-detection backend.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional, Tuple

import cv2
import numpy as np


def _lens_geometry(
    width: int,
    height: int,
    parameters: Mapping[str, float],
    lens: str,
    front_lens: str = "left",
) -> Tuple[float, float, float, bool]:
    if lens not in {"front", "back"}:
        raise ValueError(f"Unsupported lens: {lens}")
    if front_lens not in {"left", "right"}:
        raise ValueError(f"Unsupported front lens side: {front_lens}")

    front_is_left = front_lens == "left"
    is_front = lens == "front"
    use_left = front_is_left if is_front else not front_is_left
    center_x_base = width * (0.3125 if use_left else 0.6875)
    prefix = "front" if is_front else "back"
    center_x = center_x_base + float(parameters.get(f"{prefix}_cx_offset", 0.0))
    center_y = height / 2.0 + float(
        parameters.get(f"{prefix}_cy_offset", 0.0)
    )
    radius = min(width / 4.0, height / 2.0) * float(
        parameters.get("radius_scale", 1.0)
    )
    return center_x, center_y, radius, is_front


def dual_fisheye_pixels_to_vehicle_rays(
    pixels: np.ndarray,
    width: int,
    height: int,
    parameters: Mapping[str, float],
    lens: str = "front",
    front_lens: str = "left",
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert raw dual-fisheye pixels to unit rays in vehicle axes.

    Returns ``(valid_pixels, rays)``. Vehicle axes follow ``bird_eye.py``:
    +X right, +Y up, +Z forward. Rays point away from the camera.
    """

    points = np.asarray(pixels, dtype=np.float64).reshape(-1, 2)
    center_x, center_y, radius, is_front = _lens_geometry(
        width, height, parameters, lens, front_lens
    )
    dx = points[:, 0] - center_x
    dy = points[:, 1] - center_y
    rho = np.hypot(dx, dy)
    valid = (rho > 1e-9) & (rho < radius)
    points = points[valid]
    dx = dx[valid]
    dy = dy[valid]
    rho = rho[valid]
    if not len(points):
        return points, np.empty((0, 3), dtype=np.float64)

    theta = rho / radius * (np.pi / 2.0)
    sin_theta = np.sin(theta)
    lens_x = sin_theta * dx / rho
    lens_y = -sin_theta * dy / rho
    lens_z = np.cos(theta)
    if is_front:
        camera_rays = np.column_stack((lens_x, lens_y, lens_z))
    else:
        camera_rays = np.column_stack((-lens_x, lens_y, -lens_z))

    yaw, pitch, roll = np.deg2rad(
        [
            float(parameters.get("yaw_deg", 0.0)),
            float(parameters.get("pitch_deg", 0.0)),
            float(parameters.get("roll_deg", 0.0)),
        ]
    )
    rotation_yaw = np.array(
        [
            [math.cos(yaw), 0.0, math.sin(yaw)],
            [0.0, 1.0, 0.0],
            [-math.sin(yaw), 0.0, math.cos(yaw)],
        ]
    )
    rotation_pitch = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(pitch), -math.sin(pitch)],
            [0.0, math.sin(pitch), math.cos(pitch)],
        ]
    )
    rotation_roll = np.array(
        [
            [math.cos(roll), -math.sin(roll), 0.0],
            [math.sin(roll), math.cos(roll), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    # Forward projection is C = R_roll R_pitch R_yaw W. With row vectors,
    # inverse rotation is W_row = C_row R_roll R_pitch R_yaw.
    vehicle_rays = camera_rays @ (
        rotation_roll @ rotation_pitch @ rotation_yaw
    )
    return points, vehicle_rays


def estimate_ground_contact(
    contour: np.ndarray,
    frame_shape: Tuple[int, ...],
    parameters: Mapping[str, float],
    contact_fraction: float = 0.08,
    lens: str = "front",
    front_lens: str = "left",
    min_distance_m: float = 0.20,
    max_distance_m: float = 4.0,
) -> Optional[dict]:
    """Estimate the nearest floor-contact point represented by a contour.

    Only the lowest/nearest contour rays should intersect the floor at the
    physical object base. Selecting in metric ground space avoids projecting
    the complete vertical object surface into a floor-plane BEV first.
    """

    if contour is None or len(contour) < 3:
        return None
    height, width = frame_shape[:2]
    pixels, rays = dual_fisheye_pixels_to_vehicle_rays(
        contour[:, 0, :], width, height, parameters, lens, front_lens
    )
    if not len(rays):
        return None

    camera_height = float(parameters["camera_height"])
    downward = rays[:, 1] < -0.03
    pixels = pixels[downward]
    rays = rays[downward]
    if not len(rays):
        return None

    ray_scale = -camera_height / rays[:, 1]
    # Keep the physical ray/plane result in the camera-centred frame here.
    # ``car_offset_*`` currently controls where the robot overlay is drawn in
    # the BEV and is not a measured camera extrinsic. Mixing that UI offset
    # into this geometry caused an artificial +9 cm range bias.
    x_m = ray_scale * rays[:, 0]
    z_m = ray_scale * rays[:, 2]
    ground_points = np.column_stack((x_m, z_m))
    distances = np.linalg.norm(ground_points, axis=1)
    valid = (
        (ray_scale > 0.0)
        & (z_m > 0.0)
        & (distances >= float(min_distance_m))
        & (distances <= float(max_distance_m))
    )
    ground_points = ground_points[valid]
    pixels = pixels[valid]
    distances = distances[valid]
    if len(ground_points) < 3:
        return None

    fraction = min(max(float(contact_fraction), 0.01), 0.50)
    contact_count = max(3, int(math.ceil(len(ground_points) * fraction)))
    nearest = np.argpartition(distances, contact_count - 1)[:contact_count]
    contact = np.median(ground_points[nearest], axis=0)
    contact_pixel = np.median(pixels[nearest], axis=0)
    return {
        "x_m": float(contact[0]),
        "z_m": float(contact[1]),
        "distance_m": float(np.linalg.norm(contact)),
        "pixel_x": float(contact_pixel[0]),
        "pixel_y": float(contact_pixel[1]),
        "contact_samples": int(contact_count),
    }


def detect_blue_ground_contact(
    frame: np.ndarray,
    parameters: Mapping[str, float],
    min_area_px: float = 300.0,
    contact_fraction: float = 0.08,
    front_lens: str = "left",
) -> Tuple[Optional[dict], np.ndarray]:
    """Blue-target adapter for the generic ground-contact geometry."""

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (90, 70, 30), (140, 255, 255))
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    height, width = frame.shape[:2]
    center_x, center_y, radius, _ = _lens_geometry(
        width, height, parameters, "front", front_lens
    )
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    candidates = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < float(min_area_px):
            continue
        x, y, box_width, box_height = cv2.boundingRect(contour)
        box_center_x = x + box_width / 2.0
        box_center_y = y + box_height / 2.0
        # The evaluation target stands on the floor in the lower part of the
        # front lens. This rejects blue-tinted windows and the lens rim.
        if box_center_y < center_y - 0.04 * radius:
            continue
        if math.hypot(box_center_x - center_x, box_center_y - center_y) > 0.90 * radius:
            continue
        candidates.append(contour)
    if not candidates:
        return None, mask

    contour = max(candidates, key=cv2.contourArea)
    result = estimate_ground_contact(
        contour,
        frame.shape,
        parameters,
        contact_fraction=contact_fraction,
        lens="front",
        front_lens=front_lens,
    )
    if result is None:
        return None, mask
    result["area_px"] = float(cv2.contourArea(contour))
    result["contour"] = contour
    return result, mask
