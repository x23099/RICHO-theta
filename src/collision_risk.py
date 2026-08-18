#!/usr/bin/env python3
"""Pure geometry and candidate risk logic for one tracked obstacle.

Coordinates follow the vehicle convention used by the path predictor:
``forward_m`` is positive ahead and ``left_m`` is positive to the left.
The detected blue-obstacle coordinate is converted by the caller because its
``x_m`` axis is positive to the right.
"""

from __future__ import annotations

import math


RISK_LEVELS = {
    "CLEAR",
    "PATH",
    "WARNING",
    "CRITICAL",
    "WARNING_HOLD",
    "UNKNOWN",
}


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


class CollisionRiskHysteresis:
    """Stabilize a display-only collision warning without indefinite latching.

    Entry and exit confirmation are intentionally asymmetric.  A confirmed
    warning survives a short invalid-measurement interval, then degrades to
    ``UNKNOWN`` rather than pretending the path is clear or keeping a warning
    forever.  This class does not produce a control command.
    """

    ALERT_CONTEXT_STATES = {
        "WARNING",
        "CRITICAL",
        "WARNING_HOLD",
        "UNKNOWN",
    }

    def __init__(
        self,
        warning_ttc_sec=4.0,
        warning_exit_ttc_sec=5.0,
        warning_confirm_frames=3,
        warning_clear_frames=3,
        warning_hold_sec=0.8,
    ):
        self.warning_ttc_sec = float(warning_ttc_sec)
        self.warning_exit_ttc_sec = float(warning_exit_ttc_sec)
        self.warning_confirm_frames = max(1, int(warning_confirm_frames))
        self.warning_clear_frames = max(1, int(warning_clear_frames))
        self.warning_hold_sec = max(0.0, float(warning_hold_sec))
        if not math.isfinite(self.warning_ttc_sec):
            raise ValueError("warning TTC must be finite")
        if not math.isfinite(self.warning_exit_ttc_sec):
            raise ValueError("warning exit TTC must be finite")
        if self.warning_exit_ttc_sec <= self.warning_ttc_sec:
            raise ValueError("warning exit TTC must exceed warning TTC")
        if not math.isfinite(self.warning_hold_sec):
            raise ValueError("warning hold duration must be finite")
        self.reset()

    def reset(self):
        self.state = "CLEAR"
        self.warning_confirmation_count = 0
        self.clear_confirmation_count = 0
        self.last_confirmed_warning_sec = None
        self.last_update_sec = None

    @staticmethod
    def _finite_number(value):
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    def _result(self, raw_level, reason, now_sec, measurement_valid):
        hold_age_sec = None
        if self.last_confirmed_warning_sec is not None:
            hold_age_sec = max(0.0, now_sec - self.last_confirmed_warning_sec)
        return {
            "risk_level": self.state,
            "raw_risk_level": raw_level,
            "state_reason": reason,
            "hold_age_sec": hold_age_sec,
            "measurement_valid": bool(measurement_valid),
        }

    def _confirm_release(self, target_state, raw_level, now_sec, valid, reason):
        self.clear_confirmation_count += 1
        if self.clear_confirmation_count >= self.warning_clear_frames:
            self.state = target_state
            self.clear_confirmation_count = 0
            self.last_confirmed_warning_sec = None
            return self._result(
                raw_level, f"{reason}_confirmed", now_sec, valid
            )
        return self._result(
            raw_level, f"{reason}_confirmation", now_sec, valid
        )

    def _hold_or_unknown(self, raw_level, now_sec, valid):
        if self.last_confirmed_warning_sec is None:
            self.state = "UNKNOWN"
            return self._result(
                raw_level, "invalid_measurement", now_sec, valid
            )
        age_sec = max(0.0, now_sec - self.last_confirmed_warning_sec)
        if age_sec <= self.warning_hold_sec:
            self.state = "WARNING_HOLD"
            return self._result(raw_level, "finite_warning_hold", now_sec, valid)
        self.state = "UNKNOWN"
        return self._result(raw_level, "warning_hold_expired", now_sec, valid)

    def update(
        self,
        raw_level,
        timestamp_sec,
        measurement_valid,
        moving_forward,
        in_collision_corridor,
        ttc_sec=None,
    ):
        """Return filtered risk state and diagnostics for one timestamp."""

        raw_level = str(raw_level or "CLEAR").upper()
        if raw_level not in RISK_LEVELS:
            raise ValueError(f"unknown collision risk level: {raw_level}")
        now_sec = self._finite_number(timestamp_sec)
        if now_sec is None:
            raise ValueError("timestamp must be finite")
        if self.last_update_sec is not None and now_sec < self.last_update_sec:
            self.reset()
        self.last_update_sec = now_sec
        valid = bool(measurement_valid)
        moving_forward = bool(moving_forward)
        in_collision_corridor = bool(in_collision_corridor)
        ttc_value = self._finite_number(ttc_sec)
        alert_context = self.state in self.ALERT_CONTEXT_STATES

        # Imminent, valid evidence bypasses the entry debounce.
        if valid and raw_level == "CRITICAL":
            self.state = "CRITICAL"
            self.warning_confirmation_count = 0
            self.clear_confirmation_count = 0
            self.last_confirmed_warning_sec = now_sec
            return self._result(raw_level, "valid_critical", now_sec, valid)

        if valid and raw_level == "WARNING":
            self.clear_confirmation_count = 0
            if alert_context:
                self.state = "WARNING"
                self.warning_confirmation_count = 0
                self.last_confirmed_warning_sec = now_sec
                return self._result(
                    raw_level, "warning_reconfirmed", now_sec, valid
                )
            self.warning_confirmation_count += 1
            if self.warning_confirmation_count >= self.warning_confirm_frames:
                self.state = "WARNING"
                self.warning_confirmation_count = 0
                self.last_confirmed_warning_sec = now_sec
                return self._result(
                    raw_level, "warning_entry_confirmed", now_sec, valid
                )
            self.state = "PATH" if in_collision_corridor else "CLEAR"
            return self._result(
                raw_level, "warning_entry_confirmation", now_sec, valid
            )

        self.warning_confirmation_count = 0
        if alert_context:
            if valid and not in_collision_corridor:
                return self._confirm_release(
                    "CLEAR", raw_level, now_sec, valid, "outside_path"
                )
            if (
                valid
                and in_collision_corridor
                and ttc_value is not None
                and ttc_value >= self.warning_exit_ttc_sec
            ):
                return self._confirm_release(
                    "PATH", raw_level, now_sec, valid, "ttc_safe"
                )
            if (
                valid
                and in_collision_corridor
                and ttc_value is not None
                and self.warning_ttc_sec < ttc_value < self.warning_exit_ttc_sec
            ):
                self.state = "WARNING"
                self.clear_confirmation_count = 0
                self.last_confirmed_warning_sec = now_sec
                return self._result(
                    raw_level, "ttc_exit_hysteresis", now_sec, valid
                )
            if not moving_forward:
                target = "PATH" if in_collision_corridor else "CLEAR"
                return self._confirm_release(
                    target, raw_level, now_sec, valid, "not_approaching"
                )
            self.clear_confirmation_count = 0
            return self._hold_or_unknown(raw_level, now_sec, valid)

        self.clear_confirmation_count = 0
        if not valid and moving_forward and in_collision_corridor:
            self.state = "UNKNOWN"
            return self._result(
                raw_level, "invalid_measurement", now_sec, valid
            )
        self.state = raw_level
        return self._result(raw_level, "instantaneous", now_sec, valid)


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
