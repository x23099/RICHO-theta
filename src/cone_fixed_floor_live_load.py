"""Explicit LOCAL comparison model loading, bounded to one asynchronous job.

No watching, remote write API, session rebinding, camera, inference, or FFB.
Evidence proves file/session correspondence, NOT a physically correct floor.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import threading
import time

from cone_fixed_floor_shadow import FixedFloorShadow, parse_bundle


def bounded_regular_bytes(path, maximum):
    """Reject symlinks/devices/FIFOs, limit allocation, never execute contents."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise ValueError("bounded nonempty regular file required")
        payload = stream.read(maximum+1)
    if not 0 < len(payload) <= maximum:
        raise ValueError("file exceeds size limit")
    return payload


def png_digest(path):
    import cv2
    import numpy as np
    payload = bounded_regular_bytes(path, 8*1024*1024)
    if (payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR"
            or len(payload) < 24 or struct.unpack(">II", payload[16:24]) != (1280, 720)):
        raise ValueError("native 1280x720 PNG evidence required")
    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("decodable native colour PNG evidence required")
    return hashlib.sha256(payload).hexdigest()


def validate_live_payload(payload, settings, config_sha256, evidence_dir, session, maximum_frame, support_source):
    bundle, _ = parse_bundle(payload, settings)
    if bundle["session"] != session:
        raise ValueError("live model session mismatch; no rebinding")
    evidence = bundle.get("live_evidence")
    if (not isinstance(evidence, dict) or evidence.get("schema") != "same_session_floor_evidence_v1"
            or evidence.get("session") != session or evidence.get("config_sha256") != config_sha256
            or evidence.get("camera_sha256") != settings["camera_sha256"]):
        raise ValueError("same-session/config/camera evidence manifest required")
    for key in ("board_on_floor_confirmed", "rigid_board_confirmed", "static_camera_confirmed"):
        if evidence.get(key) is not True:
            raise ValueError("explicit placement confirmation required: "+key)
    frames = evidence.get("source_frames")
    if not isinstance(frames, list) or not frames or len(frames) > 16:
        raise ValueError("1..16 explicit saved evidence frames required")
    numbers = []
    for item in frames:
        if not isinstance(item, dict):
            raise ValueError("source frame record required")
        number = item.get("frame")
        if type(number) is not int or not 1 <= number <= maximum_frame:
            raise ValueError("evidence must precede the load request")
        filename = item.get("file")
        expected = f"decoded_{session}_f{number:06d}.png"
        if filename != expected or Path(filename).name != filename:
            raise ValueError("session/frame PNG basename required")
        if png_digest(Path(evidence_dir)/filename) != item.get("sha256"):
            raise ValueError("saved evidence hash mismatch")
        numbers.append(number)
    if numbers != sorted(set(numbers)):
        raise ValueError("unique ordered evidence frames required")
    return FixedFloorShadow(None, settings, support_source, payload=payload), copy.deepcopy(evidence)


class LocalFloorModelLoader:
    """One pending/ready load, no queue. Application happens on the cone worker.

    Request/poll/close are thread-safe. Loader threads never touch engine state.
    A disconnect or stale input invalidates the active comparison; a new manual
    request is needed. A rejected load never restores the old comparison model.
    """
    def __init__(self, path, settings, config_sha256, evidence_dir, event_path, support_source,
                 *, clock=time.monotonic, executor=None):
        self.path, self.settings = Path(path), copy.deepcopy(settings)
        self.config_sha256, self.evidence_dir = config_sha256, Path(evidence_dir)
        self.support_source, self.clock = support_source, clock
        self.pool = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="floor-model-local")
        self.lock = threading.RLock()
        self.events = Path(event_path).open("x")
        self.future = self.ready = self.requested = self.active = None
        self.invalidated = False
        self.closed = False
        self.generation = 0
        self.info = dict(schema="fixed_floor_load_v1", state="waiting", reason="not_requested", generation=0,
            requested_session=None, bundle_sha256=None, evidence_frames=[], activated_frame=None,
            load_completed_at_sec=None, activated_at_sec=None,
            controlling_distance=False, physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False)

    def _event(self, action):
        self.events.write(json.dumps(dict(action=action, recorded_at_sec=self.clock(), **self.info))+"\n")
        self.events.flush()

    def _load(self, request):
        payload = bounded_regular_bytes(self.path, 512*1024)
        adapter, evidence = validate_live_payload(payload, self.settings, self.config_sha256,
            self.evidence_dir, request["session"], request["frame"], self.support_source)
        return adapter, evidence, self.clock()

    def request(self, frame):
        with self.lock:
            if self.closed or frame is None:
                return False, "closed_or_no_fresh_frame"
            if self.future is not None or self.ready is not None:
                return False, "load_already_pending"
            self.generation += 1
            self.requested = dict(session=frame.session, frame=frame.sequence)
            self.active = None
            self.invalidated = False
            self.info.update(state="loading", reason="explicit_local_request", generation=self.generation,
                requested_session=frame.session, bundle_sha256=None, evidence_frames=[], activated_frame=None,
                load_completed_at_sec=None, activated_at_sec=None, detail=None)
            self._event("requested")
            try:
                self.future = self.pool.submit(self._load, dict(self.requested))
            except Exception as exc:
                self.info.update(state="rejected", reason="submit_failed:"+type(exc).__name__, detail=str(exc)[:300])
                self._event("rejected")
                return False, "load_submit_failed"
            return True, "load_requested"

    def step(self, frame):
        """Called at worker frame boundary, and with None while input is absent."""
        with self.lock:
            if self.closed:
                return None
            request = self.requested
            if request and (frame is None or frame.session != request["session"]):
                if self.info["state"] in ("loading", "ready", "active"):
                    self.info.update(state="rejected", reason="input_unavailable_or_session_changed")
                    self.invalidated = True
                    self.active = self.ready = None
                    self._event("invalidated")
            if self.future is not None and self.future.done():
                future, self.future = self.future, None
                try:
                    loaded = future.result()
                    if not self.invalidated:
                        self.ready = loaded
                        self.info.update(state="ready", reason="awaiting_post_load_frame",
                            load_completed_at_sec=loaded[2])
                except Exception as exc:
                    self.ready = self.active = None
                    self.info.update(state="rejected", reason="load_failed:"+type(exc).__name__, detail=str(exc)[:300])
                    self._event("rejected")
            if self.ready is not None and frame is not None:
                adapter, evidence, finished = self.ready
                if (not self.invalidated and frame.session == request["session"]
                        and frame.sequence > request["frame"] and frame.received_at >= finished):
                    self.active, self.ready = adapter, None
                    adapter.reset()
                    self.info.update(state="active", reason="accepted_comparison_only",
                        bundle_sha256=adapter.bundle_sha256,
                        evidence_frames=[r["frame"] for r in evidence["source_frames"]],
                        activated_frame=frame.sequence, activated_at_sec=self.clock(), load_completed_at_sec=finished)
                    self._event("accepted")
            return self.active

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.info)

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.active = self.ready = None
                self.info.update(state="closed", reason="shutdown")
                self._event("closed")
                self.events.close()
                self.pool.shutdown(wait=False, cancel_futures=True)
            return dict(model_load_running=self.future is not None and not self.future.done())
