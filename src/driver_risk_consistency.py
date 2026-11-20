"""Confirm a steering-risk direction with a 2-of-3 window; NOT wired to FFB.

The consumer must treat ``confirmed=False`` as "withhold", never as "keep the
previous direction". Steady agreement confirms immediately; only a change has
to survive the window, so the worst added latency is (window-1) frames
(0.4 s at 5 Hz for window=3). No ROS, camera, clock sync or command output.
"""
import collections
import math
import time

SCHEMA = 'risk_direction_consistency_v1'
FLAGS = dict(controlling_distance=False, physical_metric_verified=False,
             usable_for_ffb=False, published_to_ros=False)
RISK_LEVELS = ('CLEAR', 'PATH', 'WARNING', 'CRITICAL', 'UNKNOWN')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _direction(value, deadband):
    if value > deadband:
        return -1
    if value < -deadband:
        return 1
    return 0


class DirectionConsistency:
    def __init__(self, *, window=3, required=2, deadband=0.1, max_sample_age_sec=0.5,
                 clock=time.monotonic):
        if type(window) is not int or not 1 <= window <= 9:
            raise ValueError('bounded odd window required')
        if type(required) is not int or not 1 <= required <= window:
            raise ValueError('required count must be within the window')
        if not _finite(deadband) or not 0 <= deadband <= 1:
            raise ValueError('deadband must be within [0,1]')
        if not _finite(max_sample_age_sec) or not 0 < max_sample_age_sec <= 5:
            raise ValueError('bounded sample age required')
        if not callable(clock):
            raise ValueError('callable monotonic clock required')
        self.window, self.required, self.deadband = window, required, deadband
        self.max_age, self.clock = max_sample_age_sec, clock
        self.samples = collections.deque(maxlen=window)
        self.last_attempt = None
        self.closed = False
        self.reason = 'no_samples'

    def reset(self, reason='reset'):
        self.samples.clear()
        self.last_attempt = None
        self.closed = False
        self.reason = reason

    def offer(self, gradient_normalized, *, risk_level='UNKNOWN', valid=True, at_sec=None):
        """One per-frame sample. Invalid samples break the window on purpose."""
        if self.closed:
            return self.snapshot(reason='closed')
        now = self.clock() if at_sec is None else at_sec
        if not _finite(now) or (self.last_attempt is not None and now < self.last_attempt):
            self.reset('clock_reversed')
            self.closed = True
            return self.snapshot(reason='clock_reversed')
        self.last_attempt = now
        level = str(risk_level).strip().upper() if risk_level is not None else 'UNKNOWN'
        if level not in RISK_LEVELS:
            level = 'UNKNOWN'
        if not valid or not _finite(gradient_normalized):
            self.samples.clear()
            self.reason = 'invalid_sample'
            return self.snapshot(reason='invalid_sample')
        direction = _direction(float(gradient_normalized), self.deadband)
        self.samples.append(dict(at_sec=now, direction=direction,
                                 gradient=float(gradient_normalized), level=level))
        return self.snapshot()

    def snapshot(self, reason=None):
        now = self.clock()
        if self.closed:
            return self._result(False, None, None, reason or 'closed', None)
        if len(self.samples) < self.window:
            return self._result(False, None, None, reason or 'warming_up', None)
        newest = self.samples[-1]
        if now - newest['at_sec'] > self.max_age:
            return self._result(False, None, None, 'stale', None)
        counts = collections.Counter(sample['direction'] for sample in self.samples)
        direction, count = counts.most_common(1)[0]
        if count < self.required:
            return self._result(False, None, None, 'disagreement', None)
        matching = [sample for sample in self.samples if sample['direction'] == direction]
        added = max(0., newest['at_sec'] - matching[-1]['at_sec'])
        return self._result(True, direction, matching[-1]['gradient'],
                            reason or 'confirmed', added, level=newest['level'])

    def _result(self, confirmed, direction, gradient, reason, added, level=None):
        return dict(schema=SCHEMA, confirmed=confirmed, direction=direction,
                    gradient_normalized=gradient, risk_level=level,
                    reason=reason, window=self.window, required=self.required,
                    samples=len(self.samples),
                    added_latency_sec=added, deadband=self.deadband,
                    **FLAGS)
