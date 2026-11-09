"""Latest-frame-only experimental range worker, with no scene or control jobs."""
import json
import math
from pathlib import Path
import threading
import time

from cone_motion_range import revoke_range


class MotionRangeWorker:
    def __init__(self, slot, engine, predictor, log_path, *, clock=time.monotonic):
        self.slot, self.engine, self.predictor, self.clock = slot, engine, predictor, clock
        self.log_path = Path(log_path)
        self.lock = threading.Lock()
        self.stop_event, self.updated = threading.Event(), threading.Event()
        self.latest, self.error = None, None
        self.processed = self.available = self.retired_results = 0
        self.thread = threading.Thread(target=self._run, name="cone-motion-range-experiment", daemon=True)

    def start(self):
        if self.stop_event.is_set():
            raise RuntimeError("closed motion worker cannot be restarted")
        self.thread.start()

    def poll(self, now, current):
        with self.lock:
            if self.stop_event.is_set():
                return None, "motion_worker_stopped"
            if self.error:
                return None, "motion_worker_failed:"+self.error
            if current is None or self.latest is None:
                return None, "waiting_for_current_motion_range"
            frame, result = self.latest
            if frame.session != current.session:
                return None, "motion_session_changed"
            if not 0 <= now-frame.received_at <= self.engine.settings["frame_max_age_sec"]:
                return None, "motion_result_stale"
            # Result is paired with its OWN image, never the newer input image.
            return (frame, result), result["reason"]

    def _run(self):
        last_key = None
        try:
            with self.log_path.open("x") as stream:
                while not self.stop_event.is_set():
                    frame, _ = self.slot.current(self.clock())
                    if frame is None:
                        with self.lock:
                            self.latest = None
                        self.stop_event.wait(.01)
                        continue
                    key = frame.session, frame.sequence
                    if key == last_key:
                        self.stop_event.wait(.005)
                        continue
                    last_key = key
                    started = self.clock()
                    boxes = self.predictor(frame)
                    inferred = self.clock()
                    if self.stop_event.is_set():
                        break
                    current, _ = self.slot.current(self.clock())
                    if current is None or current.session != frame.session:
                        self.retired_results += 1
                        with self.lock:
                            self.latest = None
                        continue
                    result = self.engine.measure(frame, boxes, inferred)
                    finished = self.clock()
                    result.update(completed_time_sec=finished, frame_age_ms=1000*(finished-frame.received_at),
                        predict_ms=1000*(inferred-started), support_geometry_ms=1000*(finished-inferred),
                        service_ms=1000*(finished-started),
                        inference_source=getattr(self.predictor, "inference_source", "injected_predictor_NOT_live_cuda"))
                    if finished-frame.received_at > self.engine.settings["frame_max_age_sec"]:
                        revoke_range(result, "frame_processing_too_old")
                    stream.write(json.dumps(result, allow_nan=False)+"\n")
                    stream.flush()
                    self.processed += 1
                    self.available += int(result["distance_available"])
                    current, _ = self.slot.current(self.clock())
                    with self.lock:
                        self.latest = ((frame, result) if not self.stop_event.is_set()
                            and current is not None and current.session == frame.session else None)
                    self.updated.set()
        except Exception as error:
            with self.lock:
                self.error, self.latest = f"{type(error).__name__}: {error}", None
            self.updated.set()
        finally:
            with self.lock:
                self.latest = None

    def close(self, timeout=2.):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("finite nonnegative close timeout required")
        self.stop_event.set()
        with self.lock:
            self.latest = None
        if self.thread.ident is not None:
            self.thread.join(timeout)
        stopped = not self.thread.is_alive()
        return dict(worker_stopped=stopped, shutdown_complete=stopped,
                    inference_may_still_be_running=not stopped)
