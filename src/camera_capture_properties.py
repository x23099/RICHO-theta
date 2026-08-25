#!/usr/bin/env python3
"""Read reproducibility-relevant OpenCV capture properties without mutation."""

from __future__ import annotations

import math

import cv2


PROPERTY_NAMES = (
    ("frame_width", "CAP_PROP_FRAME_WIDTH"),
    ("frame_height", "CAP_PROP_FRAME_HEIGHT"),
    ("fps", "CAP_PROP_FPS"),
    ("fourcc", "CAP_PROP_FOURCC"),
    ("auto_exposure", "CAP_PROP_AUTO_EXPOSURE"),
    ("exposure", "CAP_PROP_EXPOSURE"),
    ("gain", "CAP_PROP_GAIN"),
    ("brightness", "CAP_PROP_BRIGHTNESS"),
    ("contrast", "CAP_PROP_CONTRAST"),
    ("saturation", "CAP_PROP_SATURATION"),
    ("hue", "CAP_PROP_HUE"),
    ("auto_white_balance", "CAP_PROP_AUTO_WB"),
    ("white_balance_blue_u", "CAP_PROP_WHITE_BALANCE_BLUE_U"),
    ("white_balance_temperature", "CAP_PROP_WB_TEMPERATURE"),
)


def _fourcc_text(value):
    integer = int(round(value))
    text = "".join(chr((integer >> (8 * index)) & 0xFF) for index in range(4))
    return text if all(32 <= ord(character) <= 126 for character in text) else ""


def read_capture_properties(capture):
    """Return raw backend values; unsupported controls commonly report -1."""

    properties = {}
    try:
        properties["backend"] = capture.getBackendName()
    except (AttributeError, cv2.error):
        properties["backend"] = ""
    for output_name, constant_name in PROPERTY_NAMES:
        property_id = getattr(cv2, constant_name, None)
        if property_id is None:
            continue
        try:
            value = float(capture.get(property_id))
        except (TypeError, ValueError, cv2.error):
            continue
        if not math.isfinite(value):
            continue
        properties[output_name] = value
        if output_name == "fourcc":
            properties["fourcc_text"] = _fourcc_text(value)
    return properties


def exposure_summary(properties):
    control_fields = (
        "auto_exposure",
        "exposure",
        "gain",
        "auto_white_balance",
        "white_balance_temperature",
    )
    control_values = [
        properties[field]
        for field in control_fields
        if field in properties and properties[field] != ""
    ]
    if control_values and all(value == -1.0 for value in control_values):
        backend = properties.get("backend", "unknown")
        return f"backend={backend}, exposure controls unavailable via OpenCV (-1)"
    fields = ("backend", *control_fields)
    return ", ".join(
        f"{field}={properties[field]}"
        for field in fields
        if field in properties and properties[field] != ""
    ) or "exposure controls unavailable"
