"""Origin-anchored scene deadlines, no accumulated frame-quantization drift.

Only local source time is used; no NTP, metric labels, future frames, or queued
catch-up jobs. Multiple expired deadlines are consumed by ONE available frame.
Busy workers leave deadlines pending until a fresh frame can be processed.
"""
import math


def valid_time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative source time required")
    return float(value)


class FixedSceneCadence:
    def __init__(self, interval=1.0):
        if type(interval) not in (int, float) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("positive finite interval required")
        self.interval = float(interval)
        self.origin = None
        self.next_index = 0
        self.last_source = None

    @property
    def next_target(self):
        return None if self.origin is None else self.origin+self.next_index*self.interval

    def due(self, source_time, *, busy=False):
        source_time = valid_time(source_time)
        if self.last_source is not None and source_time < self.last_source:
            raise ValueError("source time cannot precede the last selected image")
        return not busy and (self.origin is None or source_time >= self.next_target)

    def take(self, source_time):
        source_time = valid_time(source_time)
        if not self.due(source_time):
            raise ValueError("scene deadline not reached")
        if self.origin is None:
            self.origin = source_time
        target = self.next_target
        previous_index = self.next_index
        # Jump across outages in constant time, not a loop/queue of old jobs.
        index = max(previous_index+1, math.floor((source_time-self.origin)/self.interval)+1)
        # Account for floating-point division rounding near exact boundaries.
        while self.origin+index*self.interval <= source_time:
            index += 1
        self.next_index = index
        self.last_source = source_time
        return dict(target_time_sec=target, source_time_sec=source_time,
                    skipped_targets=index-previous_index-1,
                    lateness_sec=source_time-target, next_target_time_sec=self.next_target)
