"""Causal IMAGE-SPACE support continuity; OFFLINE ONLY, not physical contact.

Input must already be associated to one intended cone. All actual columns are
retained; there is no line-fit prerequisite, motion prediction, metric geometry,
TTC, ROS, or hardware output. Acceptance never grants permission for FFB.
"""
from dataclasses import asdict, dataclass
from collections.abc import Mapping
import math

import numpy as np


@dataclass(frozen=True)
class SupportQualitySettings:
    confirmation_frames: int = 3
    min_columns: int = 8
    min_span_px: float = 6.
    min_coverage: float = .8
    max_column_gap_px: float = 2.
    min_width_ratio: float = .7
    max_width_ratio: float = 1.4
    min_common_columns: int = 8
    min_common_fraction: float = .5
    endpoint_floor_px: float = 4.
    endpoint_width_fraction: float = .2
    max_median_y_change_px: float = 4.
    max_p90_y_change_px: float = 6.
    max_frame_gap_sec: float = .2
    anchor_memory_sec: float = 1.

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("positive finite setting required: "+name)
        for name in ("confirmation_frames", "min_columns", "min_common_columns"):
            if type(getattr(self, name)) is not int or getattr(self, name) < (2 if name == "confirmation_frames" else 3):
                raise ValueError("integer sample count required: "+name)
        if not (0 < self.min_width_ratio < 1 < self.max_width_ratio
                and 0 < self.min_coverage <= 1 and 0 < self.min_common_fraction <= 1
                and self.anchor_memory_sec >= self.max_frame_gap_sec
                and self.max_p90_y_change_px >= self.max_median_y_change_px):
            raise ValueError("invalid ratio, memory, or Y change settings")


class ConeSupportQualityGate:
    """Consume every frame, including missing/rejected/ambiguous ones.

    candidates: associated records with ``support`` = actual integer (x,y) pairs.
    A single unavailable color observation may instead provide support=None and
    unavailable_reason. The last ACCEPTED support is the comparison anchor.
    A rejected observation never replaces it. After anchor expiry, a stable
    but physically incorrect boundary CAN initialize: no physical GT is assumed.
    """
    def __init__(self, settings=None):
        self.settings = settings or SupportQualitySettings()
        self.reset()

    def reset(self):
        self.anchor = None
        self.anchor_time = None
        self.pending = None
        self.pending_count = 0
        self.recovering = True
        self.last_time = None

    def _clear_pending(self):
        self.pending = None
        self.pending_count = 0
        self.recovering = True

    def _read(self, points, width, height):
        if points is None:
            return None, "unavailable_support"
        try:
            if np.iscomplexobj(np.asarray(points)):
                return None, "invalid_support"
            p = np.asarray(points, dtype=np.float64)
        except (ValueError, TypeError):
            return None, "invalid_support"
        if (p.ndim != 2 or p.shape[1] != 2 or len(p) < self.settings.min_columns
                or not np.isfinite(p).all() or not np.equal(p, np.rint(p)).all()):
            return None, "invalid_support"
        x, y = p[:, 0], p[:, 1]
        if (np.any(x < 0) or np.any(x >= width) or np.any(y < 0) or np.any(y >= height)
                or np.any(np.diff(x) <= 0)):
            return None, "invalid_or_unordered_native_columns"
        span = x[-1]-x[0]
        if span < self.settings.min_span_px:
            return None, "insufficient_support_span"
        if (len(p)/(span+1) < self.settings.min_coverage
                or max(np.diff(x)) > self.settings.max_column_gap_px):
            return None, "disconnected_support"
        # Immutable copies prevent caller mutation from changing past state.
        return tuple((int(a), int(b)) for a, b in p), ""

    def _compare(self, before, current):
        a, b = np.asarray(before), np.asarray(current)
        old_width, new_width = a[-1, 0]-a[0, 0]+1, b[-1, 0]-b[0, 0]+1
        ratio = float(new_width/old_width)
        end_change = float(max(abs(b[0, 0]-a[0, 0]), abs(b[-1, 0]-a[-1, 0])))
        allowed = max(self.settings.endpoint_floor_px, self.settings.endpoint_width_fraction*old_width)
        shared, ia, ib = np.intersect1d(a[:, 0], b[:, 0], assume_unique=True, return_indices=True)
        fraction = len(shared)/min(len(a), len(b))
        delta = np.abs(b[ib, 1]-a[ia, 1])
        median = float(np.median(delta)) if len(delta) else None
        p90 = float(np.percentile(delta, 90)) if len(delta) else None
        failures = []
        if not self.settings.min_width_ratio <= ratio <= self.settings.max_width_ratio:
            failures.append("abrupt_support_width_change")
        if end_change > allowed:
            failures.append("abrupt_support_endpoint_change")
        if len(shared) < self.settings.min_common_columns or fraction < self.settings.min_common_fraction:
            failures.append("insufficient_shared_observed_columns")
        elif median > self.settings.max_median_y_change_px or p90 > self.settings.max_p90_y_change_px:
            failures.append("abrupt_lower_boundary_y_change")
        return dict(width_ratio=ratio, endpoint_change_px=end_change, endpoint_limit_px=float(allowed),
                    common_columns=len(shared), common_fraction=fraction,
                    median_abs_y_change_px=median, p90_abs_y_change_px=p90), tuple(failures)

    def update(self, timestamp, candidates, *, frame_width=1280, frame_height=720):
        try:
            now = float(timestamp)
        except (TypeError, ValueError):
            self.reset()
            raise ValueError("finite strictly increasing timestamp required; state reset")
        if not math.isfinite(now) or (self.last_time is not None and now <= self.last_time):
            self.reset()
            raise ValueError("finite strictly increasing timestamp required; state reset")
        if self.last_time is not None and now-self.last_time > self.settings.max_frame_gap_sec:
            self._clear_pending()
        if self.anchor_time is not None and now-self.anchor_time > self.settings.anchor_memory_sec:
            self.anchor = None
            self.anchor_time = None
            self._clear_pending()
        self.last_time = now
        result = dict(quality_accepted=False, reason="", comparison_failures=(), confirmation_count=0,
                      pending_comparison_failures=(),
                      anchor_present=self.anchor is not None,
                      anchor_age_sec=now-self.anchor_time if self.anchor_time is not None else None,
                      width_ratio=None, endpoint_change_px=None, endpoint_limit_px=None,
                      common_columns=None, common_fraction=None, median_abs_y_change_px=None, p90_abs_y_change_px=None,
                      pending_width_ratio=None, pending_endpoint_change_px=None, pending_endpoint_limit_px=None,
                      pending_common_columns=None, pending_common_fraction=None,
                      pending_median_abs_y_change_px=None, pending_p90_abs_y_change_px=None,
                      candidate_x_lo=None, candidate_x_hi=None, candidate_y_min=None, candidate_y_max=None,
                      observed_support=None, observed_x_lo=None, observed_x_hi=None,
                      observed_y_min=None, observed_y_max=None,
                      floor_contact_verified=False, usable_for_ffb=False)

        def withheld(reason):
            self._clear_pending()
            return dict(result, reason=reason)

        if (frame_width, frame_height) != (1280, 720):
            return withheld("native_resolution_mismatch")
        if len(candidates) != 1:
            return withheld("no_candidate" if not candidates else "ambiguous_candidates")
        candidate = candidates[0]
        if not isinstance(candidate, Mapping):
            return withheld("invalid_associated_record")
        current, reason = self._read(candidate.get("support"), frame_width, frame_height)
        if current is None:
            if reason == "unavailable_support":
                reason += ":" + str(candidate.get("unavailable_reason", "not_provided"))
            return withheld(reason)
        xs, ys = zip(*current)
        result.update(candidate_x_lo=min(xs), candidate_x_hi=max(xs), candidate_y_min=min(ys), candidate_y_max=max(ys))
        if self.anchor is not None:
            metrics, failures = self._compare(self.anchor, current)
            result.update(metrics, comparison_failures=failures)
            if failures:
                return withheld(failures[0])
        if self.recovering:
            pending_ok = False
            if self.pending is not None:
                pending_metrics, pending_failures = self._compare(self.pending, current)
                result.update({"pending_"+k: v for k, v in pending_metrics.items()})
                result["pending_comparison_failures"] = pending_failures
                pending_ok = not pending_failures
            self.pending_count = self.pending_count+1 if pending_ok else 1
            self.pending = current
            result["confirmation_count"] = self.pending_count
            if self.pending_count < self.settings.confirmation_frames:
                return dict(result, reason="support_confirmation_pending")
        self.anchor, self.anchor_time = current, now
        self.pending, self.pending_count, self.recovering = None, 0, False
        return dict(result, quality_accepted=True, reason="temporally_consistent_IMAGE_support_NOT_verified_floor_contact",
                    observed_support=current, observed_x_lo=min(xs), observed_x_hi=max(xs),
                    observed_y_min=min(ys), observed_y_max=max(ys))
