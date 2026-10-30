"""Read-only distance worker adapters. Never run inference in the RTC loop."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import threading
import time

from cone_distance_core import ConeDistanceEngine, digest
from cone_scene_diagnostic import estimate_scene


class YoloConePredictor:
    """Explicit trusted local checkpoint, CUDA only, no downloads or training."""
    inference_source = "live_cuda_yolo"

    def __init__(self, weights, settings, output_dir, device=0):
        weights = Path(weights).expanduser().resolve()
        if not weights.is_file() or digest(weights) != settings["weights_sha256"]:
            raise ValueError("explicit local checkpoint matching diagnostic weights_sha256 required")
        if type(device) is not int or device < 0:
            raise ValueError("CUDA device index required")
        # Reuse the established isolated/offline model setup. No environment
        # install, global settings directory, or fallback to CPU.
        from run_cone_yolo import check_cuda, configure_offline
        import torch
        self.gpu = check_cuda(torch, device)
        config_dir = Path(output_dir) / "ultralytics_config"
        (config_dir / "Ultralytics").mkdir(parents=True, exist_ok=False)
        os.environ["YOLO_CONFIG_DIR"] = str(config_dir)
        configure_offline(config_dir)
        from ultralytics import YOLO
        from ultralytics.utils import USER_CONFIG_DIR, ONLINE, AUTOINSTALL
        if ONLINE or AUTOINSTALL or Path(USER_CONFIG_DIR).resolve() != (config_dir / "Ultralytics").resolve():
            raise ValueError("isolated offline Ultralytics contract required")
        self.model = YOLO(str(weights))
        if self.model.names != {0: "traffic_cone"}:
            raise ValueError("single-class traffic_cone model required")
        self.kwargs = dict(device=device, imgsz=settings["imgsz"], conf=settings["confidence"],
            iou=settings["nms_iou"], max_det=settings["max_det"], rect=False, batch=1,
            augment=False, save=False, save_txt=False, save_crop=False, show=False,
            visualize=False, verbose=False, stream=False, quantize=32, half=False)
        self.weights_sha256 = digest(weights)

    def __call__(self, frame):
        from cone_detection_diagnostics import extract_predictions
        results = self.model.predict(source=frame.image, **self.kwargs)
        if len(results) != 1:
            raise ValueError("one native frame must produce exactly one detection result")
        return extract_predictions(results[0], dict(width=1280, height=720,
                                  image=f"{frame.session}:{frame.sequence}"))


class DistanceWorker:
    """Latest-only cone thread + one scene future. No queue of old camera jobs.

    Results retain their original frame. Never place an old distance over a
    newer image. Polling hides results on disconnect/session changes or after
    0.5 s from SOURCE reception, not 0.5 s from inference completion.
    """
    def __init__(self, slot, config, predictor, log_path, *, scene_function=estimate_scene, clock=time.monotonic, target_roi=None,
                 colour_support_shadow=False, support_completion_shadow=False, frame_evidence=False):
        self.slot, self.predictor, self.clock = slot, predictor, clock
        self.engine = ConeDistanceEngine(config, target_roi=target_roi, colour_support_shadow=colour_support_shadow,
                                         support_completion_shadow=support_completion_shadow,
                                         frame_evidence=frame_evidence)
        self.scene_function = scene_function
        self.log_path = Path(log_path)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.error = None
        self.scene_future = None
        self.retired_scene_jobs = 0
        self.updated = threading.Event()
        self.thread = threading.Thread(target=self._run, name="cone-distance-diagnostic", daemon=True)

    def start(self):
        if self.stop_event.is_set():
            raise RuntimeError("closed distance worker cannot be restarted")
        self.thread.start()

    def poll(self, now, current):
        with self.lock:
            if self.stop_event.is_set():
                return None, "distance_worker_stopped"
            if self.error:
                return None, "distance_worker_failed:" + self.error
            if current is None or self.latest is None:
                return None, "waiting_for_distance_result"
            frame, result = self.latest
            if frame.session != current.session:
                return None, "distance_session_changed"
            if not 0 <= now-frame.received_at <= self.engine.settings["frame_max_age_sec"]:
                return None, "distance_result_stale"
            return (frame, dict(result)), result["reason"]

    def _consume_scene(self, future, ticket):
        # Check ownership BEFORE result(): even an exception belonging to a
        # retired session must not kill the new session. A current-session
        # exception remains fatal; it is not a rejected geometric observation.
        if ticket.session != self.engine.session:
            self.retired_scene_jobs += 1
        else:
            self.engine.complete_scene(ticket, future.result(), self.clock())

    def _run(self):
        future, ticket, last_key = None, None, None
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cone-scene-diagnostic")
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
                    if self.engine.session != frame.session:
                        self.engine.reset(frame.session)
                        with self.lock:
                            self.latest = None
                    started = self.clock()
                    if future is not None and future.done():
                        self._consume_scene(future, ticket)
                        future = None
                    if future is None and self.engine.scene_due(frame.received_at):
                        ticket = self.engine.begin_scene(frame)
                        future = pool.submit(self.scene_function, frame.image, self.engine.camera, self.engine.prior_up)
                        with self.lock:
                            self.scene_future = future
                    predict_start = self.clock()
                    boxes = self.predictor(frame)
                    predict_end = self.clock()
                    if self.stop_event.is_set():
                        break
                    current, _ = self.slot.current(self.clock())
                    # Session changes can also happen during inference. Defer
                    # consumption until the next live session resets the engine.
                    if (future is not None and future.done() and current is not None
                            and current.session == frame.session):
                        self._consume_scene(future, ticket)
                        future = None
                    result = self.engine.measure(frame, boxes, self.clock)
                    finished = self.clock()
                    result.update(completed_time_sec=finished, frame_age_ms=1000*(finished-frame.received_at),
                                  predict_ms=1000*(predict_end-predict_start), support_geometry_ms=1000*(finished-predict_end),
                                  cone_service_ms=1000*(finished-started),
                                  inference_source=getattr(self.predictor, "inference_source",
                                                           "injected_predictor_not_verified_cuda"),
                                  retired_scene_jobs=self.retired_scene_jobs,
                                  scene_waiting_for_retired_job=(future is not None
                                      and ticket.session != frame.session))
                    if finished-frame.received_at > self.engine.settings["frame_max_age_sec"]:
                        result.update(distance_available=False, distance_forward_m=None, lateral_right_m=None,
                                      reason="frame_processing_too_old")
                        if result["reason"] not in result["blockers"]:
                            result["blockers"].insert(0, result["reason"])
                    stream.write(json.dumps(result) + "\n")
                    stream.flush()
                    current, _ = self.slot.current(self.clock())
                    with self.lock:
                        self.latest = ((frame, result) if not self.stop_event.is_set()
                            and current is not None and current.session == frame.session else None)
                    self.updated.set()
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
                self.latest = None
            self.updated.set()
        finally:
            with self.lock:
                self.latest = None
            # A running native call cannot safely be interrupted from Python.
            # shutdown(wait=False) does NOT guarantee process exit: executor
            # threads are joined by Python at exit. Report unfinished work.
            pool.shutdown(wait=False, cancel_futures=True)

    def close(self, timeout=2.):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("finite nonnegative close timeout required")
        self.stop_event.set()
        with self.lock:
            self.latest = None
        if self.thread.ident is not None:
            self.thread.join(timeout=timeout)
        with self.lock:
            scene_running = self.scene_future is not None and not self.scene_future.done()
            stopped = not self.thread.is_alive()
            return dict(worker_stopped=stopped, scene_job_running=scene_running,
                        shutdown_complete=stopped and not scene_running,
                        retired_scene_jobs=self.retired_scene_jobs)

