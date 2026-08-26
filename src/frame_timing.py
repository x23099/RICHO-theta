#!/usr/bin/env python3
"""Shared schema and helpers for per-frame processing telemetry."""

from __future__ import annotations

import math
import time


PROCESSING_TIMING_FIELDS = (
    "processing_odom_poll_ms",
    "processing_capture_read_ms",
    "processing_bev_preprocess_ms",
    "processing_blue_pipeline_ms",
    "processing_ai_perception_ms",
    "processing_overlay_render_ms",
    "processing_display_ms",
    "processing_video_write_ms",
    "processing_total_before_csv_ms",
)


def elapsed_ms(started, now=None):
    """Return elapsed monotonic high-resolution time in milliseconds."""

    if now is None:
        now = time.perf_counter()
    return max(0.0, (float(now) - float(started)) * 1000.0)


def format_processing_timings(values):
    """Serialize timing values in the same order as the recording schema."""

    serialized = []
    for field in PROCESSING_TIMING_FIELDS:
        try:
            value = float(values.get(field, math.nan))
        except (TypeError, ValueError):
            value = math.nan
        serialized.append(f"{value:.3f}" if math.isfinite(value) else "")
    return serialized
