"""Experimental velocity-evidence checks for OFFLINE replay only.

Nothing imports this module from the camera application or hardware adapter.
These empirical checks do not establish calibrated safety confidence.
"""

from collections import deque
from dataclasses import dataclass
import math
import statistics


@dataclass(frozen=True)
class ConfidenceSettings:
    window_sec: float = 0.3
    minimum_span_sec: float = 0.2
    minimum_samples: int = 5
    maximum_gap_sec: float = 0.1
    minimum_pair_span_sec: float = 0.06
    residual_tolerance_m: float = 0.03
    agreement_absolute_mps: float = 0.1
    agreement_relative: float = 0.35
    maximum_samples: int = 32
    fast_critical_evidence: bool = True

    def __post_init__(self):
        values = [self.window_sec, self.minimum_span_sec, self.maximum_gap_sec,
                  self.minimum_pair_span_sec, self.residual_tolerance_m,
                  self.agreement_absolute_mps, self.agreement_relative]
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("confidence thresholds must be finite and positive")
        if not 3 <= self.minimum_samples <= self.maximum_samples <= 128:
            raise ValueError("invalid confidence sample bounds")
        if not self.minimum_pair_span_sec <= self.minimum_span_sec <= self.window_sec:
            raise ValueError("pair span <= minimum span <= window is required")


def robust_line(points, minimum_pair_span_sec):
    """Median of pair slopes; only past/current samples are supplied.

    Same slope definition as Theil-Sen, with short noisy pairs excluded.
    This is not SciPy's confidence-interval implementation.
    """
    slopes = [(b[1] - a[1]) / (b[0] - a[0])
              for i, a in enumerate(points) for b in points[i + 1:]
              if b[0] - a[0] >= minimum_pair_span_sec - 1e-9]
    if not slopes:
        return None
    slope = statistics.median(slopes)
    # Relative times avoid cancellation with large monotonic timestamps.
    base = points[0][0]
    intercept = statistics.median(z - slope * (t - base) for t, z in points)
    residuals = [abs(z - (intercept + slope * (t - base))) for t, z in points]
    return slope, statistics.median(residuals), residuals[-1]


class OfflineVelocityConfidence:
    def __init__(self, settings=None):
        self.settings = settings or ConfidenceSettings()
        self.points = deque(maxlen=self.settings.maximum_samples)
        self.fast_points = deque(maxlen=self.settings.maximum_samples)
        self.last_timestamp = None

    def reset(self):
        self.points.clear()
        self.fast_points.clear()
        self.last_timestamp = None

    def update(self, *, timestamp, raw_z_m, visual_vz_mps,
               measurement_valid, track_available, initialized=False,
               critical_requested=False):
        now = float(timestamp)
        if not math.isfinite(now):
            raise ValueError("timestamp must be finite")
        reversed_time = self.last_timestamp is not None and now <= self.last_timestamp
        if initialized or reversed_time or not track_available:
            self.reset()
        self.last_timestamp = now
        while self.points and now - self.points[0][0] > self.settings.window_sec:
            self.points.popleft()
        while self.fast_points and now - self.fast_points[0][0] > 0.1 + 1e-9:
            self.fast_points.popleft()
        result = {"trusted": False, "reason": "no_track", "samples": len(self.points),
                  "span_sec": 0.0, "robust_vz_mps": None,
                  "median_residual_m": None, "latest_residual_m": None}
        if not track_available:
            return result
        finite = all(v is not None and math.isfinite(float(v)) for v in (raw_z_m, visual_vz_mps))
        if not measurement_valid or not finite or float(raw_z_m) <= 0:
            self.fast_points.clear()
            result["reason"] = "invalid_measurement"
            return result
        if self.points and now - self.points[-1][0] > self.settings.maximum_gap_sec:
            self.points.clear()
            self.fast_points.clear()
        point = (now, float(raw_z_m))
        self.points.append(point)
        self.fast_points.append(point)
        span = self.points[-1][0] - self.points[0][0]
        result.update(samples=len(self.points), span_sec=span)
        fit = robust_line(list(self.points), self.settings.minimum_pair_span_sec)
        if fit:
            result.update(robust_vz_mps=fit[0], median_residual_m=fit[1], latest_residual_m=fit[2])
        result["reason"] = "insufficient_history"
        if reversed_time:
            result["reason"] = "non_increasing_time_reset"
            return result
        if (len(self.points) >= self.settings.minimum_samples
                and span >= self.settings.minimum_span_sec - 1e-9 and fit):
            if max(fit[1], fit[2]) > self.settings.residual_tolerance_m:
                result["reason"] = "position_trend_inconsistent"
            elif abs(float(visual_vz_mps) - fit[0]) > (
                    self.settings.agreement_absolute_mps + self.settings.agreement_relative * abs(fit[0])):
                result["reason"] = "velocity_disagreement"
            else:
                result.update(trusted=True, reason="mature_consistent_history")
                return result
        # Independent fast evidence is tested only when CRITICAL is requested.
        # It does not assume an obstacle is static or clip velocity to ego speed.
        fast = list(self.fast_points)
        if self.settings.fast_critical_evidence and critical_requested and len(fast) >= 3:
            a, b, c = fast[0], fast[len(fast) // 2], fast[-1]
            if c[0] - a[0] >= 0.05 - 1e-9 and b[0] > a[0] and c[0] > b[0]:
                slopes = [(b[1] - a[1]) / (b[0] - a[0]), (c[1] - b[1]) / (c[0] - b[0])]
                center = statistics.median(slopes)
                stable = (max(slopes) < -0.03
                          and abs(slopes[0] - slopes[1]) <= 0.2 + 0.2 * abs(center)
                          and abs(float(visual_vz_mps) - center) <= 0.1 + 0.35 * abs(center))
                if stable:
                    result.update(trusted=True, reason="fast_consistent_critical_evidence")
        return result
