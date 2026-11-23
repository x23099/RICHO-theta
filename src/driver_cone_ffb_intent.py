"""Cone-distance to FFB intent (policy B), offline prototype.

Inputs: measured radial range, detector-box centre x, command speed/yaw.
The lateral offset is an empirical calibration (mounting-dependent), not a
physical mount model. The force direction comes from the obstacle side; the
steering-risk gradient only scales the magnitude. A 3-consecutive consistency
gate withholds the direction during disagreement.

Not wired to ROS/G923/FFB. No authority flags.
"""
from collections import deque
import math

from collision_risk import (assess_path_collision, classify_candidate_risk,
                            evaluate_candidate_steering, predict_unicycle_path)
from driver_ffb_side_mapping import command as side_mapping_command

SCHEMA = 'cone_ffb_intent_v1'
CALIBRATION_SCHEMA = 'lateral_calibration_table_v1'
WIDTH_M = 0.354
MARGIN_M = 0.10
FLAGS = dict(controlling_distance=False, physical_metric_verified=False,
             floor_contact_verified=False, usable_for_ffb=False, published_to_ros=False)


def checked_calibration(value):
    """distances ascending; cx_ref and k the same length; bounded numbers."""
    if type(value) is not dict or value.get('schema') != CALIBRATION_SCHEMA:
        raise ValueError('explicit lateral calibration table required')
    distances = value.get('distances')
    centres = value.get('cx_ref')
    common = value.get('k_m_per_px')
    left = value.get('k_left_m_per_px', common)
    right = value.get('k_right_m_per_px', common)
    if not all(type(items) is list for items in (distances, centres, left, right)):
        raise ValueError('calibration lists required')
    if not (len(distances) == len(centres) == len(left) == len(right) >= 2):
        raise ValueError('matching calibration columns required')
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in distances + centres + left + right):
        raise ValueError('finite calibration values required')
    if any(b <= a for a, b in zip(distances, distances[1:])):
        raise ValueError('ascending distances required')
    if any(v <= 0 for v in left + right):
        raise ValueError('positive pixel scale required')
    return dict(schema=CALIBRATION_SCHEMA, distances=list(distances),
                cx_ref=list(centres), k_left_m_per_px=list(left), k_right_m_per_px=list(right),
                mounting_dependent=True)


def _interpolate(x, xs, ys):
    if x < xs[0] or x > xs[-1]:
        return None
    for index in range(len(xs) - 1):
        if xs[index] <= x <= xs[index + 1]:
            span = xs[index + 1] - xs[index]
            ratio = 0.0 if span == 0 else (x - xs[index]) / span
            return ys[index] + ratio * (ys[index + 1] - ys[index])
    return ys[-1]


def estimate_left(range_m, box_center_x, calibration):
    """left > 0 means the obstacle is on the left of the optical reference.

    Distances outside the calibrated table are clamped to the nearest edge and
    reported, because the measured radial range varies by a few cm with the
    lateral placement.
    """
    if not _finite(range_m) or range_m <= 0 or not _finite(box_center_x):
        return None, 'invalid_range_or_box'
    distances = calibration['distances']
    clamped = range_m < distances[0] or range_m > distances[-1]
    distance = min(max(range_m, distances[0]), distances[-1])
    centre = _interpolate(distance, distances, calibration['cx_ref'])
    offset = centre - box_center_x
    key = 'k_left_m_per_px' if offset >= 0 else 'k_right_m_per_px'
    scale = _interpolate(distance, distances, calibration[key])
    if centre is None or scale is None:
        return None, 'outside_calibration_distance'
    reason = 'estimated_from_box_centre' + (' / clamped_to_calibration_edge' if clamped else '')
    return offset * scale, reason


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class SideGate:
    """Three consecutive equal obstacle sides within a bounded age."""

    def __init__(self, *, window=3, max_age_sec=0.5):
        if type(window) is not int or not 2 <= window <= 9:
            raise ValueError('bounded side window required')
        if type(max_age_sec) not in (int, float) or not 0 < max_age_sec <= 5:
            raise ValueError('bounded side sample age required')
        self.window, self.max_age = window, float(max_age_sec)
        self.samples = deque(maxlen=window)
        self.last = None

    def reset(self, reason='reset'):
        self.samples.clear()
        self.last = None
        return reason

    def offer(self, side, *, at_sec, valid=True):
        if not valid:
            self.samples.clear()
            return dict(confirmed=False, direction=0, reason='invalid_snapshot')
        if self.last is not None and at_sec < self.last:
            self.samples.clear()
            return dict(confirmed=False, direction=0, reason='clock_reversed')
        self.last = at_sec
        while self.samples and at_sec - self.samples[0][0] > self.max_age:
            self.samples.popleft()
        self.samples.append((at_sec, side))
        if len(self.samples) < self.window:
            return dict(confirmed=False, direction=0, reason='warming_up')
        sides = {value for _, value in self.samples}
        if len(sides) != 1:
            return dict(confirmed=False, direction=0, reason='disagreement')
        side = sides.pop()
        return dict(confirmed=True, direction=side, reason='confirmed')


class ConeFfbIntent:
    def __init__(self, calibration, *, width_m=WIDTH_M, window=3, max_age_sec=0.5):
        self.calibration = checked_calibration(calibration)
        self.width_m = float(width_m)
        self.gate = SideGate(window=window, max_age_sec=max_age_sec)

    def reset(self, reason='reset'):
        self.gate.reset(reason)

    def offer(self, range_m, box_center_x, linear_mps, angular_radps, *, valid=True, at_sec=None):
        left, left_reason = estimate_left(range_m, box_center_x, self.calibration)
        if not valid or left is None or not _finite(linear_mps) or not _finite(angular_radps):
            self.gate.reset('invalid_snapshot')
            return self._result(None, None, None, None, 0, False, left_reason if left is None else 'invalid_snapshot')
        forward = math.sqrt(max(0.0, range_m * range_m - left * left))
        horizon = min(15.0, max(3.5, (forward + 0.5) / max(abs(linear_mps), 0.1)))
        level = self._level(linear_mps, angular_radps, forward, left, horizon)
        gradient = evaluate_candidate_steering(linear_mps, angular_radps, forward, left,
                                               self.width_m, safety_margin_m=MARGIN_M,
                                               prediction_time_sec=horizon)
        value = gradient['gradient_normalized']
        mapping = side_mapping_command(level, left, value)
        gate = self.gate.offer(mapping['direction'], at_sec=at_sec, valid=mapping['direction'] != 0)
        direction = gate['direction'] if gate['confirmed'] else 0
        magnitude = mapping['normalized_magnitude'] if direction else 0.0
        return self._result(round(left, 4), round(forward, 4), round(value, 4), level,
                            direction, bool(gate['confirmed']),
                            left_reason + ' / ' + mapping['reason'],
                            magnitude=round(magnitude, 4),
                            consistency_reason=gate['reason'])

    def _level(self, speed, yaw, forward, left, horizon):
        path = predict_unicycle_path(speed, yaw, prediction_time_sec=horizon)
        if not path:
            return 'CLEAR'
        assessment = assess_path_collision(path, obstacle_forward_m=forward, obstacle_left_m=left,
                                           vehicle_width_m=self.width_m, safety_margin_m=MARGIN_M,
                                           path_speed_mps=speed)
        return classify_candidate_risk(assessment['in_collision_corridor'], assessment['path_eta_sec'])

    def _result(self, left, forward, gradient, level, direction, confirmed, reason, *,
                magnitude=0.0, consistency_reason='not_evaluated'):
        return dict(schema=SCHEMA, left_m=left, forward_m=forward, gradient=gradient,
                    risk_level=level, direction=direction, normalized_magnitude=magnitude,
                    confirmed=confirmed, reason=reason, consistency_reason=consistency_reason,
                    mapping_policy='side_direction', **FLAGS)
