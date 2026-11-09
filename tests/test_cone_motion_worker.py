"""Synthetic lifecycle tests; no CUDA/camera/socket/ROS/control."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cone_distance_core import load_config
from cone_motion_range import MotionRangeEngine
from cone_motion_worker import MotionRangeWorker
from theta_rtc_frames import LatestNativeFrame
from test_cone_motion_range import cone_box, profile_fixture, support_observation


class MotionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        settings,camera,_,_=load_config()
        engine=MotionRangeEngine(settings,camera,profile_fixture(settings),"0"*64,
            acknowledged=True,observer=lambda *args:support_observation())
        self.now=10.;self.slot=LatestNativeFrame();self.slot.begin("old")
        self.worker=MotionRangeWorker(self.slot,engine,lambda frame:[cone_box()],Path(self.tmp.name)/"motion.jsonl",clock=lambda:self.now)
        self.addCleanup(self.worker.close)

    def publish(self,sequence=1,session="old"):
        self.now=10.+sequence*.01
        self.slot.publish(session,np.zeros((720,1280,3),np.uint8),sequence*.01,self.now)

    def wait_for(self,predicate):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if predicate():return
            self.worker.updated.wait(.005);self.worker.updated.clear()
        self.fail("bounded wait expired: "+str(self.worker.error))

    def test_first_frame_distance_is_paired_with_its_own_image(self):
        self.publish();self.worker.start()
        self.wait_for(lambda:self.worker.latest is not None)
        paired,_=self.worker.poll(self.now,self.slot.current(self.now)[0])
        self.assertTrue(paired[1]["distance_available"])
        self.assertEqual(paired[0].sequence,paired[1]["frame"])
        self.assertEqual(paired[1]["inference_source"],"injected_predictor_NOT_live_cuda")

    def test_stale_disconnect_and_session_change_never_display_old_number(self):
        self.publish();self.worker.start();self.wait_for(lambda:self.worker.latest is not None)
        current=self.slot.current(self.now)[0]
        self.assertIsNone(self.worker.poll(self.now+.51,current)[0])
        self.slot.end("old")
        self.assertIsNone(self.worker.poll(self.now,None)[0])
        self.slot.begin("new");self.publish(2,"new")
        new=self.slot.current(self.now)[0]
        self.assertIsNone(self.worker.poll(self.now,new)[0])

    def test_slow_predictor_skips_to_latest_without_catchup_queue(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
        seen=[]
        def predict(frame):
            seen.append(frame.sequence)
            if frame.sequence==1:
                entered.set()
                if not release.wait(2):raise RuntimeError("test timeout")
            return [cone_box()]
        self.worker.predictor=predict;self.publish();self.worker.start()
        try:
            self.assertTrue(entered.wait(1))
            for n in (2,3,4):self.publish(n)
            release.set()
            self.wait_for(lambda:self.worker.latest is not None and self.worker.latest[0].sequence==4)
            self.assertEqual(seen,[1,4])
        finally:release.set()

    def test_reconnect_during_inference_discards_retired_frame(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
        def predict(frame):
            if frame.session=="old":
                entered.set()
                if not release.wait(2):raise RuntimeError("test timeout")
            return [cone_box()]
        self.worker.predictor=predict;self.publish();self.worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.slot.begin("new");self.publish(2,"new");release.set()
            self.wait_for(lambda:self.worker.latest is not None and self.worker.latest[0].session=="new")
            self.assertEqual(self.worker.retired_results,1)
            rows=[json.loads(x) for x in self.worker.log_path.read_text().splitlines()]
            self.assertTrue(all(r["session"]=="new" for r in rows))
        finally:release.set()

    def test_predictor_exception_is_visible_failure_not_no_cone(self):
        def predict(frame):raise RuntimeError("synthetic detector failure")
        self.worker.predictor=predict;self.publish();self.worker.start()
        self.wait_for(lambda:self.worker.error is not None)
        self.assertIn("synthetic detector failure",self.worker.error)
        self.assertIsNone(self.worker.latest)

    def test_close_during_inference_reports_incomplete_then_never_restores_result(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
        def predict(frame):
            entered.set()
            if not release.wait(2):raise RuntimeError("test timeout")
            return [cone_box()]
        self.worker.predictor=predict;self.publish();self.worker.start()
        try:
            self.assertTrue(entered.wait(1))
            status=self.worker.close(.001)
            self.assertFalse(status["shutdown_complete"])
            self.assertTrue(status["inference_may_still_be_running"])
            release.set();self.worker.thread.join(1)
            self.assertIsNone(self.worker.latest)
            self.assertTrue(self.worker.close()["shutdown_complete"])
        finally:release.set()

    def test_closed_worker_cannot_start_and_bad_timeout_does_not_close(self):
        with self.assertRaises(ValueError):self.worker.close(-1.)
        self.assertFalse(self.worker.stop_event.is_set())
        self.assertTrue(self.worker.close()["shutdown_complete"])
        with self.assertRaises(RuntimeError):self.worker.start()


if __name__=="__main__":unittest.main()
