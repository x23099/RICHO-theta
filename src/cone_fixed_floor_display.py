"""Comparison-only GUI panel. Never changes a distance/log/model decision.

No retained result cache. Display-time freshness and current local loader
generation are checked again. The input image and result mapping stay intact.
"""
import math

import cv2
import numpy as np

from summarize_cone_distance_live import validate_row, validate_fixed_floor_load
from theta_rtc_frames import native_frame

PANEL_HEIGHT = 260
VISIBLE_MODELS = 4


def _text(value, limit=115):
    return "".join(c if 32 <= ord(c) <= 126 else "?" for c in str(value))[:limit]


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def comparison_view_model(row=None, *, model_state=None, now=None, expected_session=None,
                          expected_frame=None, expected_source_time=None,
                          mode="live", unavailable_reason="no_fresh_result"):
    if mode not in ("live", "recorded", "synthetic"):
        raise ValueError("explicit live/recorded/synthetic display mode required")
    if model_state is None and mode != "live" and isinstance(row, dict):
        model_state = row.get("fixed_floor_load")  # Historical state, NOT current live ownership.
    state = model_state if isinstance(model_state, dict) else {}
    view = dict(mode=mode, status="WITHHELD", reason=unavailable_reason, range_span_m=None,
        model_count=0, available_model_count=0, models=[], support_source=None,
        loader_state=state.get("state", "startup_bundle"),
        generation=state.get("generation"), frame=expected_frame,
        physical_metric_verified=False, controlling_distance=False, usable_for_ffb=False)
    def withheld(reason):
        view["reason"] = reason
        return view
    if model_state is not None and not isinstance(model_state, dict):
        return withheld("invalid_current_model_state")
    if row is None:
        return view
    if not isinstance(row, dict):
        return withheld("invalid_result")
    if expected_session is not None and row.get("session") != expected_session:
        return withheld("display_session_changed")
    if expected_frame is not None and row.get("frame") != expected_frame:
        return withheld("display_frame_mismatch")
    if expected_source_time is not None and row.get("source_time_sec") != expected_source_time:
        return withheld("display_source_time_mismatch")
    load = row.get("fixed_floor_load")
    if model_state is not None:
        if model_state.get("state") != "active":
            return withheld("loader_"+_text(model_state.get("state"))+":"+_text(model_state.get("reason")))
        if not isinstance(load, dict) or any(load.get(k) != model_state.get(k) for k in
                ("generation", "bundle_sha256", "requested_session")):
            return withheld("awaiting_current_model_result")
        try:
            validate_fixed_floor_load(dict(row, fixed_floor_load=model_state))
        except (ValueError, TypeError, KeyError):
            return withheld("invalid_current_model_state")
    elif mode == "live" and load is not None:
        return withheld("current_model_state_unavailable")
    source = row.get("source_time_sec")
    current_time = row.get("completed_time_sec") if now is None else now
    age = row.get("frame_age_ms")
    if (not _finite(source) or not _finite(current_time) or not _finite(age)
            or current_time < source or age < 0):
        return withheld("invalid_display_time")
    if age > 500. or 1000*(current_time-source) > 500.:
        return withheld("display_result_stale")
    if row.get("fixed_floor_shadow") is None:
        return withheld("no_comparison_result")
    try:
        validate_row(row)
    except (ValueError, TypeError, KeyError):
        return withheld("invalid_comparison_result")
    shadow = row["fixed_floor_shadow"]
    models = shadow["models"]
    values = [m["horizontal_camera_foot_range_m"] for m in models if m["range_available"]]
    view.update(status="UNVERIFIED_COMPARISON" if values else "WITHHELD", reason=shadow["reason"],
        range_span_m=[min(values), max(values)] if values else None,
        model_count=len(models), available_model_count=len(values),
        models=[dict(name=m["model_name"], value_m=m["horizontal_camera_foot_range_m"],
                     available=m["range_available"], reason=m["reason"]) for m in models],
        support_source=shadow["support_source"], frame=row["frame"])
    return view


def panel_lines(view):
    context = dict(live="LIVE VIEW", recorded="RECORDED RECOMPUTATION", synthetic="SYNTHETIC PREVIEW - NOT REAL CAMERA")
    title = "UNVERIFIED COMPARISON ONLY | "+context[view["mode"]]+" | NO CONTROL / FFB"
    span = view["range_span_m"]
    value = ("COMPARISON: WITHHELD" if span is None else
             f"MODEL SPAN {span[0]:.3f} - {span[1]:.3f} m | available {view['available_model_count']}/{view['model_count']}")
    lines = [title, value,
        f"{view['reason']} | loader={view['loader_state']} gen={view['generation']} | result frame={view['frame']}",
        "Horizontal camera-foot range; NOT forward/base_link/contact. Model span is NOT accuracy or a confidence interval.",
        f"Bundle order, NOT ranking | support={view['support_source']} | showing up to {VISIBLE_MODELS} of {view['model_count']}"]
    for index, model in enumerate(view["models"][:VISIBLE_MODELS], 1):
        value = f"{model['value_m']:.3f} m (UNVERIFIED)" if model["available"] else "WITHHELD: "+_text(model["reason"], 36)
        lines.append(f"{index:02d} {_text(model['name'], 62)} | {value}")
    while len(lines) < 9:
        lines.append("")
    omitted = max(0, view["model_count"]-VISIBLE_MODELS)
    help_text = "L: explicit load | S: unedited PNG | Q: stop" if view["mode"] == "live" else "Historical/synthetic display only; NOT live validation"
    lines.append(f"{omitted} more models not shown; ALL results in JSONL. {help_text}")
    return [_text(line, 145) for line in lines]


def append_comparison_panel(image, row=None, **kwargs):
    """Append a separate 260px panel to a COPY; raw S-key saving is untouched."""
    native_frame(image)
    view = comparison_view_model(row, **kwargs)
    panel = np.zeros((PANEL_HEIGHT, 1280, 3), np.uint8)
    for index, line in enumerate(panel_lines(view)):
        y = 23+23*index if index < 9 else 246
        size = .54 if index < 2 else .45
        colour = (255, 210, 90) if index < 2 else (225, 225, 225)
        cv2.putText(panel, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, size, colour, 1, cv2.LINE_AA)
    return np.concatenate((image, panel), axis=0)
