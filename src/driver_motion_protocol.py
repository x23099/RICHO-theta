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


def checked_result(value, frame):
    """Only bounded scalar metadata crosses back into the driver UI."""
    keys = {"session","frame","source_time_sec","distance_available",
            "horizontal_camera_foot_range_m","reason","primary_model"}
    flags = ("physical_metric_verified","floor_contact_verified","controlling_distance",
             "usable_for_ffb","published_to_ros")
    if (not isinstance(value,dict) or set(value) != keys|set(flags)
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
    return dict(value)


def compact_result(result):
    names = ("session","frame","source_time_sec","distance_available",
        "horizontal_camera_foot_range_m","reason","primary_model","physical_metric_verified",
        "floor_contact_verified","controlling_distance","usable_for_ffb","published_to_ros")
    return {name:result[name] for name in names}
