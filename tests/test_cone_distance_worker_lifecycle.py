"""Deterministic lifecycle checks; no camera, GPU, socket, ROS or FFB."""
from concurrent.futures import Future
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG
from cone_distance_worker import DistanceWorker
from theta_rtc_frames import LatestNativeFrame


class ControlledPool:
    """Futures are completed by the test, not by a background native call."""
    def __init__(self, **kwargs):
        self.jobs = []

    def submit(self, function, *args):
        future = Future()
        future.set_running_or_notify_cancel()
        self.jobs.append(future)
        return future

    def shutdown(self, **kwargs):
        pass


class WorkerLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.slot = LatestNativeFrame()
        self.slot.begin("old")
        self.now = 10.
        self.pool = ControlledPool()
        self.patch_pool = patch("cone_distance_worker.ThreadPoolExecutor", return_value=self.pool)
        self.patch_pool.start()
        self.addCleanup(self.patch_pool.stop)
        self.worker = DistanceWorker(self.slot, DEFAULT_CONFIG, lambda frame: [],
            Path(self.directory.name)/"frames.jsonl", clock=lambda: self.now)
        self.addCleanup(self.finish)

    def finish(self):
        for job in self.pool.jobs:
            if not job.done():
                job.set_result(dict(accepted=False, reason="synthetic_cleanup"))
        if self.worker.thread.ident is not None:
            self.worker.close()

    def publish(self, session="old", timestamp=10., media=0.):
        self.now = timestamp
        self.slot.publish(session, np.zeros((720, 1280, 3), np.uint8), media, timestamp)

    def wait_for(self, predicate):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            if predicate():
                return
            self.worker.updated.wait(.005)
            self.worker.updated.clear()
        self.fail("bounded lifecycle wait expired; worker error=" + str(self.worker.error))

    def latest(self, session, sequence):
        with self.worker.lock:
            return (self.worker.latest is not None and
                    (self.worker.latest[0].session, self.worker.latest[0].sequence) == (session, sequence))

    def start_old(self):
        self.publish()
        self.worker.start()
        self.wait_for(lambda: self.latest("old", 1))

    def test_retired_scene_exception_does_not_kill_new_session(self):
        self.start_old()
        self.slot.begin("new")
        self.pool.jobs[0].set_exception(RuntimeError("retired scene failure"))
        self.publish("new", 10.1)
        self.wait_for(lambda: self.latest("new", 1) or self.worker.error is not None)
        self.assertIsNone(self.worker.error)
        self.assertTrue(self.latest("new", 1))
        self.assertEqual(len(self.pool.jobs), 2)
        self.assertFalse(self.worker.latest[1]["scene_initialized"])

    def test_current_scene_exception_still_fails_closed(self):
        self.start_old()
        self.pool.jobs[0].set_exception(RuntimeError("current scene failure"))
        self.publish(timestamp=10.1, media=.1)
        self.wait_for(lambda: self.worker.error is not None)
        self.assertIn("current scene failure", self.worker.error)
        self.assertIsNone(self.worker.poll(10.1, self.slot.current(10.1)[0])[0])

    def test_unfinished_retired_job_does_not_create_scene_queue(self):
        self.start_old()
        self.slot.begin("new")
        self.publish("new", 10.1)
        self.wait_for(lambda: self.latest("new", 1))
        self.publish("new", 11.1, 1.)
        self.wait_for(lambda: self.latest("new", 2))
        self.assertEqual(len(self.pool.jobs), 1)
        self.assertFalse(self.worker.latest[1]["distance_available"])
        self.assertTrue(self.worker.latest[1]["scene_waiting_for_retired_job"])
        self.pool.jobs[0].set_result(dict(accepted=False, reason="retired_scene"))
        self.publish("new", 11.2, 1.1)
        self.wait_for(lambda: self.latest("new", 3))
        self.assertEqual(len(self.pool.jobs), 2)
        self.assertFalse(self.worker.latest[1]["scene_waiting_for_retired_job"])

    def test_reconnect_during_inference_defers_retired_scene_exception(self):
        entered, release = threading.Event(), threading.Event()
        def predictor(frame):
            if frame.session == "old":
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test release timeout")
            return []
        self.worker.predictor = predictor
        self.publish()
        self.worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.slot.begin("new")
            self.pool.jobs[0].set_exception(RuntimeError("retired during inference"))
            self.publish("new", 10.1)
            release.set()
            self.wait_for(lambda: self.latest("new", 1) or self.worker.error is not None)
            self.assertIsNone(self.worker.error)
            self.assertTrue(self.latest("new", 1))
            self.assertEqual(self.worker.retired_scene_jobs, 1)
        finally:
            release.set()

    def test_retired_success_does_not_seed_new_pose(self):
        self.start_old()
        self.slot.begin("new")
        self.pool.jobs[0].set_result(dict(accepted=True,
            up=self.worker.engine.prior_up.tolist(), reason="old_accepted_scene"))
        self.publish("new", 10.1)
        self.wait_for(lambda: self.latest("new", 1))
        result = self.worker.latest[1]
        self.assertFalse(result["scene_initialized"])
        self.assertFalse(result["distance_available"])
        self.assertEqual(result["retired_scene_jobs"], 1)

    def test_predictor_failure_is_not_silently_downgraded_to_no_cone(self):
        def predictor(frame):
            raise RuntimeError("synthetic detector failure")
        self.worker.predictor = predictor
        self.publish()
        self.worker.start()
        self.wait_for(lambda: self.worker.error is not None)
        self.assertIn("synthetic detector failure", self.worker.error)
        self.assertIsNone(self.worker.latest)

    def test_injected_predictor_log_does_not_claim_cuda_inference(self):
        self.start_old()
        row = json.loads(self.worker.log_path.read_text().splitlines()[0])
        self.assertEqual(row["inference_source"], "injected_predictor_not_verified_cuda")

    def test_close_before_start_is_safe_and_hides_results(self):
        status = self.worker.close()
        self.assertTrue(status["shutdown_complete"])
        self.assertIsNone(self.worker.poll(10., None)[0])
        with self.assertRaisesRegex(RuntimeError, "cannot be restarted"):
            self.worker.start()

    def test_invalid_shutdown_timeout_does_not_stop_worker(self):
        for invalid in (True, -1., float("nan"), float("inf"), "2"):
            with self.subTest(timeout=invalid), self.assertRaises(ValueError):
                self.worker.close(timeout=invalid)
        self.assertFalse(self.worker.stop_event.is_set())

    def test_real_scene_executor_shutdown_reports_then_clears_running_job(self):
        from concurrent.futures import ThreadPoolExecutor
        entered, release = threading.Event(), threading.Event()
        def scene(*args):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test scene release timeout")
            return dict(accepted=False, reason="synthetic")
        self.worker.scene_function = scene
        with patch("cone_distance_worker.ThreadPoolExecutor", ThreadPoolExecutor):
            self.publish()
            self.worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.wait_for(lambda: self.latest("old", 1))
                status = self.worker.close()
                self.assertTrue(status["worker_stopped"])
                self.assertTrue(status["scene_job_running"])
                self.assertFalse(status["shutdown_complete"])
            finally:
                release.set()
            self.worker.scene_future.result(timeout=1)
        self.assertTrue(self.worker.close()["shutdown_complete"])

    def test_shutdown_reports_scene_job_still_running(self):
        self.start_old()
        status = self.worker.close()
        self.assertTrue(status["worker_stopped"])
        self.assertTrue(status["scene_job_running"])
        self.assertFalse(status["shutdown_complete"])
        self.assertIsNone(self.worker.latest)
        self.pool.jobs[0].set_result(dict(accepted=False, reason="synthetic_cleanup"))
        self.assertTrue(self.worker.close()["shutdown_complete"])

    def test_slow_predictor_uses_latest_frame_and_no_catchup_queue(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        seen = []
        def predictor(frame):
            seen.append(frame.sequence)
            if frame.sequence == 1:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test release timeout")
            return []
        self.worker.predictor = predictor
        self.publish()
        self.worker.start()
        try:
            self.assertTrue(entered.wait(1))
            for sequence in range(2, 5):
                self.publish(timestamp=10.+sequence/100, media=sequence/100)
            release.set()
            self.wait_for(lambda: self.latest("old", 4))
            self.assertEqual(seen, [1, 4])
        finally:
            release.set()

    def test_stop_during_predictor_never_restores_visible_result(self):
        entered, release = threading.Event(), threading.Event()
        def predictor(frame):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test release timeout")
            return []
        self.worker.predictor = predictor
        self.publish()
        self.worker.start()
        try:
            self.assertTrue(entered.wait(1))
            status = self.worker.close(timeout=.01)
            self.assertFalse(status["worker_stopped"])
            self.assertFalse(status["shutdown_complete"])
            self.assertIsNone(self.worker.poll(10., self.slot.current(10.)[0])[0])
        finally:
            release.set()
        self.worker.close()
        self.assertIsNone(self.worker.latest)
        self.assertEqual(self.worker.log_path.read_text(), "")


if __name__ == "__main__":
    unittest.main()
