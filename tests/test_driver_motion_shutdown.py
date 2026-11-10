"""Only owned local synthetic children; no camera/CUDA/ROS/network/robot."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from driver_motion_bridge import DriverMotionBridge
from driver_motion_protocol import PROFILE

CHILD = r'''
import signal,sys,time
sys.path.insert(0,sys.argv[1]+'/src')
from driver_motion_protocol import read_frame,write_message
def delayed(signum,frame):
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    time.sleep(.1)
    raise SystemExit(0)
if sys.argv[2]=='ignore':signal.signal(signal.SIGTERM,signal.SIG_IGN)
elif sys.argv[2]=='delay':signal.signal(signal.SIGTERM,delayed)
write_message(sys.stdout.buffer,dict(type='request'))
read_frame(sys.stdin.buffer)
while True:time.sleep(.01)
'''


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = None

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():return
            time.sleep(.005)
        self.fail("bounded synthetic child wait expired")

    def start(self, mode="ignore"):
        self.bridge = DriverMotionBridge([sys.executable, "-u", "-c", CHILD, str(ROOT), mode],
                                          Path(self.temp.name) / "worker")
        self.addCleanup(self.cleanup_child)
        self.bridge.start();self.wait(lambda: self.bridge.ready.is_set())
        self.bridge.begin("a" * 32, dict(PROFILE))
        image = np.zeros((720, 1280, 3), np.uint8);image.flags.writeable = False
        self.assertTrue(self.bridge.publish("a" * 32, image, .1, time.monotonic()))
        self.wait(lambda: self.bridge.sent == 1)
        return self.bridge

    def cleanup_child(self):
        if self.bridge.process is not None and self.bridge.process.poll() is None:
            self.bridge.process.kill();self.bridge.process.wait(timeout=2.)
        self.bridge.close()

    def fast_close(self):
        with patch("driver_motion_bridge._SHUTDOWN_GRACE_SEC", .05), \
             patch("driver_motion_bridge._SHUTDOWN_FORCE_SEC", .8):
            return self.bridge.close()

    def test_ignored_sigterm_and_blocked_stdout_are_stopped_by_deadline(self):
        bridge = self.start()
        started = time.monotonic();status = self.fast_close()
        self.assertLess(time.monotonic()-started, 1.5)
        self.assertTrue(status["child_stopped"])
        self.assertTrue(status["io_thread_stopped"])
        self.assertTrue(status["forced_worker_kill"])
        self.assertTrue(status["shutdown_complete"])
        self.assertEqual(status["child_exitcode"], -9)
        self.assertIsNone(status["worker_error"])
        self.assertFalse(bridge.snapshot()["available"])

    def test_graceful_delayed_exit_is_not_force_killed(self):
        self.start("delay")
        with patch("driver_motion_bridge._SHUTDOWN_GRACE_SEC", .6):
            status = self.bridge.close()
        self.assertTrue(status["shutdown_complete"])
        self.assertFalse(status["forced_worker_kill"])
        self.assertEqual(status["child_exitcode"], 0)

    def test_default_sigterm_exit_is_not_force_killed(self):
        self.start("normal")
        status = self.bridge.close()
        self.assertTrue(status["shutdown_complete"])
        self.assertFalse(status["forced_worker_kill"])
        self.assertEqual(status["child_exitcode"], -15)

    def test_kill_failure_is_bounded_and_truthfully_incomplete(self):
        bridge = self.start()
        with patch.object(bridge.process, "kill", side_effect=PermissionError("synthetic kill failure")):
            status = self.fast_close()
        self.assertFalse(status["shutdown_complete"])
        self.assertFalse(status["child_stopped"])
        self.assertFalse(status["io_thread_stopped"])
        self.assertEqual(status["shutdown_reason"], "shutdown_incomplete")
        self.assertIn("PermissionError", status["shutdown_error"])
        self.assertFalse(status["forced_worker_kill"])

    def test_second_close_preserves_forced_kill_history(self):
        self.start();first = self.fast_close();second = self.bridge.close()
        self.assertTrue(first["forced_worker_kill"])
        self.assertTrue(second["forced_worker_kill"])
        self.assertTrue(second["shutdown_complete"])

    def test_no_signal_to_an_unrelated_child(self):
        other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.start();self.fast_close()
            self.assertIsNone(other.poll())
        finally:
            other.terminate();other.wait(timeout=2.)

    def test_summary_is_persisted_without_granting_control_or_image_proof(self):
        bridge = self.start();status = self.fast_close()
        self.assertEqual(status, json.loads((bridge.output_dir / "driver_motion_summary.json").read_text()))
        for flag in ("physical_metric_verified", "usable_for_ffb", "distance_published_to_ros",
                     "control_channel_modified", "image_files_written"):
            self.assertIs(status[flag], False)

    def test_never_started_bridge_closes_without_starting_a_child(self):
        bridge = DriverMotionBridge([sys.executable, "-c", "pass"], Path(self.temp.name) / "not_started")
        status = bridge.close()
        self.assertIsNone(bridge.process)
        self.assertTrue(status["shutdown_complete"])
        self.assertFalse(status["forced_worker_kill"])


if __name__ == "__main__":
    unittest.main()
