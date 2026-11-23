"""Experimental side-based FFB mapping (policy B), offline only.

The obstacle side sets the force direction; the steering-risk gradient only
scales the magnitude. This avoids the geometric sign inversion of the raw
gradient (a tight same-side turn can make "turn further" look safer), which
would otherwise reduce or reverse the resistance exactly while the driver
steers toward the obstacle.

Not wired to ROS/G923/FFB. No authority flags.
"""
import math

SCHEMA = 'ffb_side_gradient_mapping_v1'
LEVEL_MAGNITUDE = {'CLEAR': 0.0, 'PATH': 0.0, 'WARNING': 0.25, 'CRITICAL': 0.40, 'UNKNOWN': 0.15}
SIDE_DEADBAND_M = 0.05
GRADIENT_DEADBAND = 0.1
GRADIENT_GAIN = 0.6
FLAGS = dict(controlling_distance=False, physical_metric_verified=False,
             floor_contact_verified=False, usable_for_ffb=False, published_to_ros=False)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def command(risk_level, left_m, gradient_normalized=None, *, valid=True):
    """Return the experimental force command for one snapshot.

    direction: -1 = left is the obstacle side (resist left), +1 = right, 0 = none.
    normalized_magnitude: 0..1, base(level) scaled by (1 + gain*|gradient|).
    """
    level = str(risk_level).strip().upper() if risk_level is not None else 'UNKNOWN'
    if level not in LEVEL_MAGNITUDE:
        level = 'UNKNOWN'
    if not valid or not _finite(left_m):
        return _result(level, 0, 0.0, 'invalid_snapshot')
    base = LEVEL_MAGNITUDE[level]
    if base <= 0.0:
        return _result(level, 0, 0.0, 'inactive_level')
    side = -1 if left_m > SIDE_DEADBAND_M else 1 if left_m < -SIDE_DEADBAND_M else 0
    if side == 0:
        return _result(level, 0, base, 'centered_no_direction')
    gradient = gradient_normalized if _finite(gradient_normalized) else None
    if gradient is None or abs(gradient) <= GRADIENT_DEADBAND:
        return _result(level, side, base, 'base_without_gradient_modulation')
    magnitude = min(1.0, base * (1.0 + GRADIENT_GAIN * abs(gradient)))
    return _result(level, side, magnitude, 'side_direction_gradient_magnitude')


def _result(level, direction, magnitude, reason):
    return dict(schema=SCHEMA, risk_level=level, direction=direction,
                normalized_magnitude=round(magnitude, 6), reason=reason,
                side_deadband_m=SIDE_DEADBAND_M, gradient_deadband=GRADIENT_DEADBAND,
                gradient_gain=GRADIENT_GAIN, **FLAGS)
