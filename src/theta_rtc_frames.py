"""Bounded native-frame intake for diagnostics, independent of ROS / WebRTC.

Reception age is NOT camera-to-receiver latency. A decoded VP8 frame is NOT a
lossless camera original. No geometry, calibration approval, or FFB is supplied.
"""
from dataclasses import dataclass
import math
import threading

import numpy as np


PROFILE = {
    "schema": "theta_native_diagnostic_v1",
    "width": 1280,
    "height": 720,
    "layout": "dual_fisheye_front_left_unremapped",
    "codec": "VP8",
    "new_capture_only": True,
    "max_capture_age_sec": 0.2,
    "ros_control": False,
    "ffb": False,
}


def validate_profile(profile):
    # Strict types: True must not accidentally satisfy an integer field.
    if not isinstance(profile, dict) or set(profile) != set(PROFILE):
        raise ValueError("both launchers need --diagnostic (native profile required)")
    if any(type(profile[key]) is not type(value) or profile[key] != value
           for key, value in PROFILE.items()):
        raise ValueError("incompatible native diagnostic profile; no resizing fallback")


def native_frame(image):
    if not isinstance(image, np.ndarray) or image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("1280x720 uint8 BGR required; do not resize to fit calibration")


def finite_time(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative local monotonic time required")
    return float(value)


@dataclass(frozen=True)
class NativeFrame:
    session: str
    sequence: int
    media_time: float
    received_at: float
    image: np.ndarray


class LatestNativeFrame:
    """Capacity one; a new peer invalidates all previous-session results.

    Frames own immutable pixel copies. Consumers must annotate a copy, never the
    stored image. A stale / invalid / disconnected input clears the visible slot.
    All times are local monotonic, except media_time (relative RTP presentation).
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._session = None
        self._used_sessions = set()
        self._frame = None
        self._last_media = None
        self._last_receive = None
        self._sequence = 0
        self.overwritten = 0
        self._consumed = 0
        self.reason = "waiting_for_sender"

    def begin(self, session):
        if not isinstance(session, str) or not session.strip():
            raise ValueError("nonempty session identity required")
        with self._lock:
            if session in self._used_sessions:
                raise ValueError("reconnect requires a new session identity")
            self._used_sessions.add(session)
            self._session = session
            self._frame = self._last_media = self._last_receive = None
            self._sequence = self._consumed = self.overwritten = 0
            self.reason = "waiting_for_frame"

    def end(self, session, reason="disconnected"):
        with self._lock:
            if self._session == session:
                self._frame = None
                self.reason = reason
                # Late frames from the retired connection must not revive it.
                self._session = None

    def publish(self, session, image, media_time, received_at):
        try:
            native_frame(image)
            media_time, received_at = finite_time(media_time), finite_time(received_at)
        except ValueError:
            self.end(session, "invalid_native_frame_or_time")
            raise
        with self._lock:
            if session != self._session or session is None:
                return False
            if (self._last_media is not None and media_time <= self._last_media
                    or self._last_receive is not None and received_at <= self._last_receive):
                self._frame = None
                self.reason = "nonincreasing_frame_time"
                raise ValueError(self.reason)
            if self._frame is not None and self._frame.sequence != self._consumed:
                self.overwritten += 1
            self._sequence += 1
            owned = image.copy()
            owned.flags.writeable = False
            self._frame = NativeFrame(session, self._sequence, media_time, received_at, owned)
            self._last_media, self._last_receive = media_time, received_at
            self.reason = "native_transport_only_distance_not_connected"
            return True

    def current(self, now, *, max_age=0.5):
        now, max_age = finite_time(now), finite_time(max_age)
        if max_age == 0:
            raise ValueError("positive age bound required")
        with self._lock:
            if self._frame is None:
                return None, self.reason
            age = now - self._frame.received_at
            if age < 0 or age > max_age:
                return None, "receiver_frame_stale"
            self._consumed = self._frame.sequence
            return self._frame, self.reason
