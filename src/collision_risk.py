#!/usr/bin/env python3
"""Pure geometry and candidate risk logic for one tracked obstacle.

Coordinates follow the vehicle convention used by the path predictor:
``forward_m`` is positive ahead and ``left_m`` is positive to the left.
The detected blue-obstacle coordinate is converted by the caller because its
``x_m`` axis is positive to the right.
"""

from __future__ import annotations

import math


def predict_unicycle_path(
    linear_mps,
    angular_radps,
    prediction_time_sec=3.5,
    step_sec=0.05,
    min_distance_m=1.5,
    max_prediction_time_sec=15.0,
    max_abs_yaw_deg=100.0,
):
    """Return sampled ``(forward, left, yaw)`` points for constant twist."""

    linear_mps = float(linear_mps)
    angular_radps = float(angular_radps)
    prediction_time_sec = max(0.0, float(prediction_time_sec))
    step_sec = max(1e-3, float(step_sec))
    if not math.isfinite(linear_mps) or not math.isfinite(angular_radps):
        raise ValueError("linear and angular velocity must be finite")
    if abs(linear_mps) < 1e-9 and abs(angular_radps) < 1e-9:
        return []

    if abs(linear_mps) > 1e-9:
        required_time = max(
            prediction_time_sec,
            max(0.0, float(min_distance_m)) / abs(linear_mps),
        )
    else:
        required_time = prediction_time_sec
    required_time = min(
        required_time, max(0.0, float(max_prediction_time_sec))
    )

    forward_m = 0.0
    left_m = 0.0
    yaw_rad = 0.0
    points = []
    max_abs_yaw_rad = math.radians(max(0.0, float(max_abs_yaw_deg)))
    for _ in range(int(required_time / step_sec)):
        forward_m += linear_mps * math.cos(yaw_rad) * step_sec
        left_m += linear_mps * math.sin(yaw_rad) * step_sec
        yaw_rad += angular_radps * step_sec
        points.append((forward_m, left_m, yaw_rad))
        if max_abs_yaw_rad > 0.0 and abs(yaw_rad) >= max_abs_yaw_rad:
            break
    return points


def _point_to_path(point, path_points):
    """Return minimum distance and arc length to a sampled polyline."""

    if not path_points:
        return math.inf, math.nan
    px, py = (float(point[0]), float(point[1]))
    best_distance = math.inf
    best_arc_length = math.nan
    accumulated = 0.0
    for start, end in zip(path_points, path_points[1:]):
        ax, ay = float(start[0]), float(start[1])
        bx, by = float(end[0]), float(end[1])
        dx = bx - ax
        dy = by - ay
        segment_length_sq = dx * dx + dy * dy
        if segment_length_sq <= 1e-12:
            continue
        projection = ((px - ax) * dx + (py - ay) * dy) / segment_length_sq
        projection = min(1.0, max(0.0, projection))
        closest_x = ax + projection * dx
        closest_y = ay + projection * dy
        distance = math.hypot(px - closest_x, py - closest_y)
        segment_length = math.sqrt(segment_length_sq)
        if distance < best_distance:
            best_distance = distance
            best_arc_length = accumulated + projection * segment_length
        accumulated += segment_length

    if math.isinf(best_distance):
        first = path_points[0]
        return math.hypot(px - float(first[0]), py - float(first[1])), 0.0
    return best_distance, best_arc_length


def classify_candidate_risk(
    in_collision_corridor,
    ttc_sec,
    warning_ttc_sec=4.0,
    critical_ttc_sec=2.0,
):
    """Classify a display/logging candidate; this is not a safety command."""

    if not in_collision_corridor:
        return "CLEAR"
    if ttc_sec is None or not math.isfinite(float(ttc_sec)):
        return "PATH"
    if float(ttc_sec) <= float(critical_ttc_sec):
        return "CRITICAL"
    if float(ttc_sec) <= float(warning_ttc_sec):
        return "WARNING"
    return "PATH"


def assess_path_collision(
    path_points,
    obstacle_forward_m,
    obstacle_left_m,
    vehicle_width_m,
    safety_margin_m=0.10,
    path_speed_mps=None,
    ttc_sec=None,
    warning_ttc_sec=4.0,
    critical_ttc_sec=2.0,
):
    """Assess whether an obstacle surface point lies in the swept corridor."""

    path = [(0.0, 0.0, 0.0)] + list(path_points)
    distance_to_centerline_m, path_distance_m = _point_to_path(
        (obstacle_forward_m, obstacle_left_m), path
    )
    half_width_m = max(0.0, float(vehicle_width_m)) / 2.0
    safety_margin_m = max(0.0, float(safety_margin_m))
    clearance_m = distance_to_centerline_m - half_width_m
    in_corridor = (
        bool(path_points)
        and math.isfinite(distance_to_centerline_m)
        and clearance_m <= safety_margin_m
    )
    path_eta_sec = None
    if (
        path_speed_mps is not None
        and math.isfinite(float(path_speed_mps))
        and abs(float(path_speed_mps)) > 1e-6
        and math.isfinite(path_distance_m)
    ):
        path_eta_sec = path_distance_m / abs(float(path_speed_mps))
    risk_level = classify_candidate_risk(
        in_corridor,
        ttc_sec,
        warning_ttc_sec=warning_ttc_sec,
        critical_ttc_sec=critical_ttc_sec,
    )
    return {
        "in_collision_corridor": in_corridor,
        "distance_to_path_center_m": distance_to_centerline_m,
        "clearance_from_vehicle_m": clearance_m,
        "path_distance_m": path_distance_m,
        "path_eta_sec": path_eta_sec,
        "risk_level": risk_level,
    }
