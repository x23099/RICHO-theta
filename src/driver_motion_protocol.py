"""Bounded local pipe protocol; no network, ROS, images on disk or model import."""
import json
import re

import numpy as np

from theta_rtc_frames import NativeFrame, finite_time, native_frame

PROFILE = dict(schema="theta_driver_motion_native_v1", width=1280, height=720,
    layout="dual_fisheye_front_left_unremapped", new_capture_only=True,
    max_capture_age_sec=.2)
PREFIX = b"THETA_RANGE_IPC_V1 "
MAX_MESSAGE = 64*1024
IMAGE_BYTES = 1280*720*3


def profile_matches(value):
    return (isinstance(value, dict) and set(value) == set(PROFILE)
        and all(type(value[k]) is type(v) and value[k] == v for k,v in PROFILE.items()))


def write_message(stream, value):
    data = PREFIX+json.dumps(value, allow_nan=False, separators=(",", ":")).encode()+b"\n"
    if len(data) > MAX_MESSAGE:
        raise ValueError("oversized motion IPC message")
    stream.write(data)
    stream.flush()


def read_message(stream):
    data = stream.readline(MAX_MESSAGE+1)
    if not data:
        raise EOFError("motion IPC peer closed")
    if len(data) > MAX_MESSAGE or not data.endswith(b"\n") or not data.startswith(PREFIX):
        raise ValueError("invalid motion IPC message framing")
    def invalid(value):
        raise ValueError("nonfinite IPC value: "+value)
    value = json.loads(data[len(PREFIX):], parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("motion IPC object required")
    return value


def write_frame(stream, frame):
    native_frame(frame.image)
    # This copy and all pipe I/O run in the dedicated I/O thread, NEVER in RTC.
    write_message(stream, dict(type="frame", session=frame.session, sequence=frame.sequence,
        media_time=frame.media_time, received_at=frame.received_at, bytes=IMAGE_BYTES))
    stream.write(frame.image.tobytes(order="C"))
    stream.flush()


def read_frame(stream):
    value = read_message(stream)
    if (set(value) != {"type","session","sequence","media_time","received_at","bytes"}
            or value["type"] != "frame" or type(value["bytes"]) is not int or value["bytes"] != IMAGE_BYTES
            or not isinstance(value["session"], str) or not re.fullmatch("[0-9a-f]{32}",value["session"])
            or type(value["sequence"]) is not int or value["sequence"] < 1):
        raise ValueError("bounded native frame identity required")
    media, received = finite_time(value["media_time"]), finite_time(value["received_at"])
    chunks, remaining = [], IMAGE_BYTES
    while remaining:
        part = stream.read(remaining)
        if not part:
            raise EOFError("truncated native motion frame")
        chunks.append(part)
        remaining -= len(part)
    image = np.frombuffer(b"".join(chunks),np.uint8).reshape((720,1280,3))
    return NativeFrame(value["session"],value["sequence"],media,received,image)


BOX_FIELDS = {"class_id","confidence","x1","y1","x2","y2"}
BOX_IDENTITY_FIELDS = {"image","prediction_index"}


def checked_boxes(value):
    """Bounded detector boxes for the same-frame FFB intent; no images.

    The engine always emits the six numeric fields. Detector provenance
    (``image``, ``prediction_index``) is optional because not every predictor
    returns it. Unsigned images and support arrays never cross the pipe.
    """
    if type(value) is not list or len(value) > 8:
        raise ValueError("bounded detector box list required")
    result = []
    for box in value:
        if (type(box) is not dict or not BOX_FIELDS <= set(box)
                or set(box) - (BOX_FIELDS|BOX_IDENTITY_FIELDS)):
            raise ValueError("bounded detector box fields required")
        if "image" in box and (type(box["image"]) is not str or not 0 < len(box["image"]) <= 128):
            raise ValueError("bounded detector box fields required")
        if "prediction_index" in box and (type(box["prediction_index"]) is not int
                                          or box["prediction_index"] < 0):
            raise ValueError("bounded detector box fields required")
        class_id, confidence = box["class_id"], box["confidence"]
        if (type(class_id) not in (int, float) or not np.isfinite(class_id) or class_id < 0
                or type(confidence) not in (int, float) or not np.isfinite(confidence)
                or not 0.0 <= confidence <= 1.0):
            raise ValueError("bounded detector box fields required")
        coordinates = []
        for name, limit in (("x1", 1280.0), ("y1", 720.0), ("x2", 1280.0), ("y2", 720.0)):
            coordinate = box[name]
            if type(coordinate) not in (int, float) or not np.isfinite(coordinate) or not 0.0 <= coordinate <= limit:
                raise ValueError("bounded detector coordinates required")
            coordinates.append(coordinate)
        if not (coordinates[0] < coordinates[2] and coordinates[1] < coordinates[3]):
            raise ValueError("ordered detector coordinates required")
        result.append(dict(box))
    return result


def checked_result(value, frame):
    """Only bounded scalar metadata crosses back into the driver UI."""
    keys = {"session","frame","source_time_sec","distance_available",
            "horizontal_camera_foot_range_m","reason","primary_model"}
    optional = {"selected_detector_boxes","support_pixel"}
    flags = ("physical_metric_verified","floor_contact_verified","controlling_distance",
             "usable_for_ffb","published_to_ros")
    if (not isinstance(value,dict) or not keys|set(flags) <= set(value)
            or set(value) - (keys|set(flags)|optional)
            or value.get("session") != frame.session or type(value.get("frame")) is not int
            or value["frame"] != frame.sequence or value.get("source_time_sec") != frame.received_at
            or any(value.get(k) is not False for k in flags)
            or type(value.get("distance_available")) is not bool
            or not isinstance(value.get("reason"),str) or len(value["reason"]) > 300
            or not isinstance(value.get("primary_model"),str) or len(value["primary_model"]) > 100):
        raise ValueError("non-controlling matching motion result required")
    number = value["horizontal_camera_foot_range_m"]
    if value["distance_available"]:
        if type(number) not in (int,float) or not np.isfinite(number) or not 0 < number <= 100:
            raise ValueError("finite positive motion range required")
    elif number is not None:
        raise ValueError("withheld result must not contain a range")
    result = dict(value)
    if "selected_detector_boxes" in value:
        result["selected_detector_boxes"] = checked_boxes(value["selected_detector_boxes"])
    if "support_pixel" in value:
        pixel = value["support_pixel"]
        if pixel is not None and (type(pixel) is not list or len(pixel) != 2
                                  or any(type(v) is not int for v in pixel)
                                  or not 0 <= pixel[0] < 1280 or not 0 <= pixel[1] < 720):
            raise ValueError("bounded support pixel required")
        result["support_pixel"] = pixel
    return result


def compact_result(result):
    names = ("session","frame","source_time_sec","distance_available",
        "horizontal_camera_foot_range_m","reason","primary_model","physical_metric_verified",
        "floor_contact_verified","controlling_distance","usable_for_ffb","published_to_ros")
    compact = {name: result[name] for name in names}
    compact["selected_detector_boxes"] = [dict(b) for b in result.get("selected_detector_boxes", [])]
    compact["support_pixel"] = result.get("support_pixel")
    return compact
