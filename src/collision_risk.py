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

# Steering-risk gradient defaults.  The gradient is the sensitivity of the
# path-collision risk to a small change of the commanded yaw rate.  Positive
# angular velocity is a left turn, so g > 0 means that steering further left
# increases risk.
GRADIENT_MIN_TTC_SEC = 0.1
GRADIENT_MAX_TTC_SEC = 10.0
GRADIENT_DEFAULT_DELTA_RADPS = 0.15
GRADIENT_DEFAULT_G_SCALE = 1.0
GRADIENT_DEFAULT_EMA_ALPHA = 0.25
GRADIENT_DEFAULT_DEADBAND = 0.1
GRADIENT_MIN_SPEED_MPS = 0.02


def _finite_value(value):
    """Return a finite float, or None when the value is unusable."""

    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _ttc_bounds(min_ttc_sec, max_ttc_sec):
    """Validate and return the TTC clamp bounds used by the path risk."""

    min_ttc = float(min_ttc_sec)
    max_ttc = float(max_ttc_sec)
    if (
        not math.isfinite(min_ttc)
        or not math.isfinite(max_ttc)
        or min_ttc <= 0.0
        or max_ttc <= min_ttc
    ):
        raise ValueError("TTC bounds must satisfy 0 < min < max")
    return min_ttc, max_ttc


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
        # UNKNOWN can mean either that a confirmed warning's finite hold has
        # expired or that no valid obstacle observation has been established
        # yet.  Only the former has warning history to preserve.  Treating a
        # history-free UNKNOWN as alert context would let a subsequent PATH
        # sample inside the exit band create a WARNING without ever satisfying
        # the warning-entry confirmation.
        alert_context = self.state in self.ALERT_CONTEXT_STATES and (
            self.state != "UNKNOWN"
            or self.last_confirmed_warning_sec is not None
        )

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


def path_risk_from_eta(
    path_eta_sec,
    in_collision_corridor,
    *,
    min_ttc_sec=GRADIENT_MIN_TTC_SEC,
    max_ttc_sec=GRADIENT_MAX_TTC_SEC,
):
    """Return a scalar path risk from a closest-approach time.

    Phase 1 uses ``path_eta_sec`` from :func:`assess_path_collision` as a
    TTC proxy.  A clear path has zero risk.  An in-corridor path without a
    finite ETA, for example at near-zero speed, gets the floor risk.
    """

    min_ttc, max_ttc = _ttc_bounds(min_ttc_sec, max_ttc_sec)
    if not in_collision_corridor:
        return 0.0
    eta = _finite_value(path_eta_sec)
    if eta is None:
        return 1.0 / max_ttc
    eta = min(max(eta, min_ttc), max_ttc)
    return 1.0 / eta


def gradient_to_direction(
    gradient_normalized,
    *,
    threshold=GRADIENT_DEFAULT_DEADBAND,
):
    """Map a normalized gradient to the FFB direction field.

    ``-1`` means that a left turn is more dangerous, so the left-cut
    resistance must be increased.  ``+1`` is the mirrored case.
    """

    threshold = float(threshold)
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError("threshold must be finite and >= 0")
    value = _finite_value(gradient_normalized)
    if value is None:
        return 0
    if value > threshold:
        return -1
    if value < -threshold:
        return 1
    return 0


def _inactive_gradient(reason, delta_radps, *, valid=True):
    """Return an all-zero gradient result for a suppressed evaluation."""

    return {
        "valid": bool(valid),
        "reason": str(reason),
        "gradient_raw": 0.0,
        "gradient_normalized": 0.0,
        "direction": 0,
        "delta_radps": float(delta_radps),
        "risk_left": 0.0,
        "risk_center": 0.0,
        "risk_right": 0.0,
        "eta_left": None,
        "eta_center": None,
        "eta_right": None,
        "corridor_left": False,
        "corridor_center": False,
        "corridor_right": False,
    }


def evaluate_candidate_steering(
    linear_mps,
    angular_radps,
    obstacle_forward_m,
    obstacle_left_m,
    vehicle_width_m,
    *,
    delta_radps=GRADIENT_DEFAULT_DELTA_RADPS,
    path_factory=None,
    prediction_time_sec=3.5,
    step_sec=0.05,
    min_distance_m=1.5,
    max_prediction_time_sec=15.0,
    max_abs_yaw_deg=100.0,
    safety_margin_m=0.10,
    min_ttc_sec=GRADIENT_MIN_TTC_SEC,
    max_ttc_sec=GRADIENT_MAX_TTC_SEC,
    g_scale=GRADIENT_DEFAULT_G_SCALE,
    risk_level=None,
):
    """Evaluate the risk gradient for a small change of yaw rate.

    The same obstacle snapshot is assessed on three constant-twist paths:
    ``omega - delta``, ``omega`` and ``omega + delta``.  The result is only a
    display/recording signal in Phase 1; it does not produce a command.

    ``path_factory`` must accept ``(linear_mps, angular_radps)`` and return
    path points.  The default uses :func:`predict_unicycle_path`, so callers
    can later inject a path predictor with a different input mapping.
    """

    linear_mps = float(linear_mps)
    angular_radps = float(angular_radps)
    if not math.isfinite(linear_mps) or not math.isfinite(angular_radps):
        raise ValueError("linear and angular velocity must be finite")
    delta_radps = float(delta_radps)
    if not math.isfinite(delta_radps) or delta_radps <= 0.0:
        raise ValueError("delta_radps must be finite and > 0")
    g_scale = float(g_scale)
    if not math.isfinite(g_scale) or g_scale <= 0.0:
        raise ValueError("g_scale must be finite and > 0")
    vehicle_width_m = float(vehicle_width_m)
    if not math.isfinite(vehicle_width_m) or vehicle_width_m < 0.0:
        raise ValueError("vehicle_width_m must be finite and >= 0")
    _ttc_bounds(min_ttc_sec, max_ttc_sec)

    level = None if risk_level is None else str(risk_level).strip().upper()
    if level in {"CLEAR", "PATH"}:
        return _inactive_gradient("inactive_risk_level", delta_radps)
    if abs(linear_mps) < GRADIENT_MIN_SPEED_MPS:
        return _inactive_gradient("low_speed", delta_radps)

    obstacle_forward_m = _finite_value(obstacle_forward_m)
    obstacle_left_m = _finite_value(obstacle_left_m)
    if obstacle_forward_m is None or obstacle_left_m is None:
        return _inactive_gradient(
            "invalid_obstacle", delta_radps, valid=False
        )

    factory = path_factory

    def default_path_factory(v, w):
        return predict_unicycle_path(
            v,
            w,
            prediction_time_sec=prediction_time_sec,
            step_sec=step_sec,
            min_distance_m=min_distance_m,
            max_prediction_time_sec=max_prediction_time_sec,
            max_abs_yaw_deg=max_abs_yaw_deg,
        )

    if factory is None:
        factory = default_path_factory

    omegas = (
        angular_radps - delta_radps,
        angular_radps,
        angular_radps + delta_radps,
    )
    assessments = []
    risks = []
    for omega in omegas:
        path_points = factory(linear_mps, omega)
        assessment = assess_path_collision(
            path_points,
            obstacle_forward_m=obstacle_forward_m,
            obstacle_left_m=obstacle_left_m,
            vehicle_width_m=vehicle_width_m,
            safety_margin_m=safety_margin_m,
            path_speed_mps=linear_mps,
            ttc_sec=None,
        )
        assessments.append(assessment)
        risks.append(
            path_risk_from_eta(
                assessment["path_eta_sec"],
                assessment["in_collision_corridor"],
                min_ttc_sec=min_ttc_sec,
                max_ttc_sec=max_ttc_sec,
            )
        )

    gradient_raw = (risks[2] - risks[0]) / (2.0 * delta_radps)
    left_index, right_index = 2, 0
    if linear_mps < 0.0:
        # Reverse motion mirrors the yaw-rate sign in the vehicle frame, so
        # the travel-frame left/right candidates swap and the gradient flips.
        gradient_raw = -gradient_raw
        left_index, right_index = 0, 2
    gradient_normalized = min(1.0, max(-1.0, gradient_raw / g_scale))
    return {
        "valid": True,
        "reason": "ok",
        "gradient_raw": gradient_raw,
        "gradient_normalized": gradient_normalized,
        "direction": gradient_to_direction(gradient_normalized),
        "delta_radps": delta_radps,
        "risk_left": risks[left_index],
        "risk_center": risks[1],
        "risk_right": risks[right_index],
        "eta_left": assessments[left_index]["path_eta_sec"],
        "eta_center": assessments[1]["path_eta_sec"],
        "eta_right": assessments[right_index]["path_eta_sec"],
        "corridor_left": bool(
            assessments[left_index]["in_collision_corridor"]
        ),
        "corridor_center": bool(
            assessments[1]["in_collision_corridor"]
        ),
        "corridor_right": bool(
            assessments[right_index]["in_collision_corridor"]
        ),
    }


class SteeringGradientFilter:
    """Smooth and deadband a normalized steering-risk gradient.

    The internal value is reset to zero when the alert becomes inactive or a
    measurement is invalid.  This prevents a stale direction from surviving
    a CLEAR interval and biasing the next warning.
    """

    def __init__(
        self,
        ema_alpha=GRADIENT_DEFAULT_EMA_ALPHA,
        deadband=GRADIENT_DEFAULT_DEADBAND,
    ):
        self.ema_alpha = float(ema_alpha)
        self.deadband = float(deadband)
        if (
            not math.isfinite(self.ema_alpha)
            or not 0.0 < self.ema_alpha <= 1.0
        ):
            raise ValueError("ema_alpha must be within (0, 1]")
        if (
            not math.isfinite(self.deadband)
            or not 0.0 <= self.deadband <= 1.0
        ):
            raise ValueError("deadband must be within [0, 1]")
        self.value = 0.0

    def reset(self):
        """Return the filtered gradient to zero."""

        self.value = 0.0

    def update(self, gradient_normalized, *, risk_level=None, valid=True):
        """Return the filtered gradient for one evaluation."""

        level = None if risk_level is None else str(risk_level).strip().upper()
        value = _finite_value(gradient_normalized)
        if not valid or value is None or level in {"CLEAR", "PATH"}:
            self.reset()
            return 0.0
        value = min(1.0, max(-1.0, value))
        self.value = (
            self.ema_alpha * value + (1.0 - self.ema_alpha) * self.value
        )
        if abs(self.value) < self.deadband:
            self.value = 0.0
        return self.value
