"""No physical camera, socket, ROS or GPU; controlled outage/recovery tests."""
import asyncio
import csv
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from theta_rtc_diagnostic import (CaptureFrames, build_parser, capture_timeout, make_native_track,
                                  open_native_capture, probe, send, validate_args, wait_for_capture)
from theta_rtc_frames import LatestNativeFrame, PROFILE


class CaptureRig:
    """Real reader thread; test controls read-return times without sleeping 1s."""
    def __init__(self):
        self.now = 0.
        self.steps = queue.Queue()
        self.released = threading.Event()
        self.reader = CaptureFrames(self, clock=lambda: self.now)

    def read(self):
        timestamp, ok, image = self.steps.get(timeout=2)
        self.now = timestamp
        return ok, image

    def release(self):
        self.released.set()

    def start(self):
        self.reader.start()

    def push(self, timestamp, value=1, ok=True, image=None):
        self.steps.put((timestamp, ok, np.full((720, 1280, 3), value, np.uint8) if image is None else image))

    def wait(self, predicate):
        deadline = time.monotonic()+1
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("controlled camera wait expired; error="+str(self.reader.error))
            self.released.wait(.002)

    def close(self):
        self.reader.stopped.set()
        self.steps.put((self.now, False, None))
        self.reader.close()


class CaptureRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.rig = CaptureRig()
        self.addCleanup(self.rig.close)
        self.rig.start()

    def first(self):
        self.rig.push(0.)
        self.rig.wait(lambda: self.rig.reader.sequence == 1)

    def test_observed_957p4_ms_gap_recovers_without_old_frame(self):
        self.first()
        self.assertEqual(self.rig.reader.after(0)[0], 1)
        self.rig.now = .6
        self.assertIsNone(self.rig.reader.after(0))
        self.assertEqual(self.rig.reader.status()["state"], "capture_wait")
        self.rig.push(.9574, value=2)
        self.rig.wait(lambda: self.rig.reader.sequence == 2)
        frame = self.rig.reader.after(1)
        self.assertEqual(frame[:2], (2, .9574))
        self.assertEqual(int(frame[2][0, 0, 0]), 2)
        self.assertIsNone(self.rig.reader.after(2))
        self.assertEqual(self.rig.reader.status()["recovered_gaps"], 1)
        self.assertIsNone(self.rig.reader.error)

    def test_200_ms_freshness_boundary_remains_unchanged(self):
        self.first()
        self.rig.now = .2
        self.assertIsNotNone(self.rig.reader.after(0))
        self.rig.now = .200001
        self.assertIsNone(self.rig.reader.after(0))
        self.assertEqual(PROFILE["max_capture_age_sec"], .2)

    def test_no_first_frame_is_bounded_and_late_success_cannot_revive(self):
        self.rig.now = 2.99
        self.assertIsNone(self.rig.reader.after(0))
        self.rig.now = 3.
        with self.assertRaisesRegex(RuntimeError, "capture timeout"):
            self.rig.reader.status()
        self.rig.push(3.1)
        self.assertTrue(self.rig.released.wait(1))
        self.assertEqual(self.rig.reader.sequence, 0)
        with self.assertRaises(RuntimeError):
            self.rig.reader.after(0)

    def test_long_successful_read_is_rejected_even_without_monitor_poll(self):
        self.first()
        self.rig.push(3.01)
        self.assertTrue(self.rig.released.wait(1))
        self.assertEqual(self.rig.reader.sequence, 1)
        with self.assertRaisesRegex(RuntimeError, "stalled"):
            self.rig.reader.after(0)

    def test_failed_reads_can_recover_within_bounded_outage(self):
        self.first()
        self.rig.push(.3, ok=False)
        self.rig.wait(lambda: self.rig.reader.failed_reads == 1)
        self.rig.push(1., ok=False)
        self.rig.wait(lambda: self.rig.reader.failed_reads == 2)
        self.assertIsNone(self.rig.reader.after(1))
        self.rig.push(1.1, value=3)
        self.rig.wait(lambda: self.rig.reader.sequence == 2)
        self.assertEqual(self.rig.reader.after(1)[0], 2)

    def test_failed_reads_do_not_reset_timeout(self):
        self.first()
        self.rig.push(2.9, ok=False)
        self.rig.wait(lambda: self.rig.reader.failed_reads == 1)
        self.rig.push(3.01, ok=False)
        self.assertTrue(self.rig.released.wait(1))
        self.assertIsNotNone(self.rig.reader.error)

    def test_first_read_may_take_957p4_ms_without_becoming_stale_on_return(self):
        self.rig.push(.9574)
        self.rig.wait(lambda: self.rig.reader.sequence == 1)
        self.assertEqual(self.rig.reader.after(0)[0], 1)

    def test_receiver_still_hides_input_after_500_ms(self):
        self.first()
        slot = LatestNativeFrame()
        slot.begin("unchanged")
        image = self.rig.reader.after(0)[2]
        slot.publish("unchanged", image, 0., 10.)
        self.assertIsNotNone(slot.current(10.5)[0])
        self.assertIsNone(slot.current(10.500001)[0])
        slot.publish("unchanged", image, .9574, 10.9574)
        self.assertEqual(slot.current(10.96)[0].sequence, 2)

    def test_invalid_shape_is_still_immediately_fatal(self):
        self.rig.push(.01, image=np.zeros((480, 640, 3), np.uint8))
        self.assertTrue(self.rig.released.wait(1))
        with self.assertRaisesRegex(RuntimeError, "1280x720"):
            self.rig.reader.after(0)

    def test_close_clears_frame_and_does_not_allow_restart(self):
        self.first()
        self.rig.close()
        self.assertIsNone(self.rig.reader.latest)
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            self.rig.reader.after(0)
        with self.assertRaisesRegex(RuntimeError, "restarted"):
            self.rig.reader.start()


class MediaRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_actual_av_track_survives_gap_with_new_pts_not_repeated_pixels(self):
        rig = CaptureRig()
        rig.start()
        track = make_native_track(rig.reader)
        task = None
        try:
            rig.push(0., value=1)
            rig.wait(lambda: rig.reader.sequence == 1)
            first = await asyncio.wait_for(track.recv(), 1)
            self.assertEqual(first.pts, 0)
            rig.now = .6
            task = asyncio.create_task(track.recv())
            await asyncio.sleep(.02)
            self.assertFalse(task.done())
            self.assertEqual(track.readyState, "live")
            rig.push(.9574, value=2)
            second = await asyncio.wait_for(task, 1)
            self.assertEqual(second.pts, 86166)
            self.assertEqual(int(second.to_ndarray(format="bgr24")[0, 0, 0]), 2)
            self.assertEqual(track.readyState, "live")
        finally:
            track.stop()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            rig.close()

    async def test_track_ends_on_true_timeout(self):
        from aiortc.mediastreams import MediaStreamError
        rig = CaptureRig()
        rig.start()
        track = make_native_track(rig.reader)
        try:
            rig.now = 3.
            with self.assertRaises(MediaStreamError):
                await asyncio.wait_for(track.recv(), 1)
            self.assertEqual(track.readyState, "ended")
        finally:
            track.stop()
            rig.close()

    async def test_wait_can_be_cancelled_without_new_capture(self):
        rig = CaptureRig()
        rig.start()
        task = asyncio.create_task(wait_for_capture(rig.reader, 0))
        try:
            await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            rig.close()


class SenderControlLoopTest(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, timeout=False, peer_close_error=False):
        calls, states = [], iter(("capturing", "capture_wait", "capturing"))
        class Peer:
            connectionState = "connected"
            localDescription = SimpleNamespace(sdp="synthetic-offer", type="offer")
            def addTransceiver(self, track, direction):
                calls.append("sendonly:"+direction)
                return SimpleNamespace(setCodecPreferences=lambda codecs: calls.append("vp8_selected"))
            async def createOffer(self):
                return self.localDescription
            async def setLocalDescription(self, description):
                pass
            async def setRemoteDescription(self, description):
                calls.append("fake_answer_applied")
            async def close(self):
                calls.append("peer.close")
                if peer_close_error:
                    raise RuntimeError("synthetic peer cleanup error")
        peer = Peer()
        class Reader:
            timeout_sec = 3.
            thread = SimpleNamespace(ident=1)
            def __init__(self, *args, **kwargs):
                self.count = 0
            def start(self):
                calls.append("reader.start")
            def status(self):
                self.count += 1
                if timeout:
                    raise RuntimeError("synthetic capture timeout")
                state = next(states)
                calls.append(state)
                if self.count == 3:
                    peer.connectionState = "closed"
                return dict(state=state, age_sec=.9574 if state == "capture_wait" else 0., max_read_ms=957.4)
            def close(self):
                calls.append("reader.close")
        class Response:
            status = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def json(self):
                return dict(sdp="synthetic-answer", type="answer", diagnostic_profile=PROFILE)
        class Session(Response):
            def __init__(self, **kwargs):
                pass
            def post(self, url, json):
                calls.append("fake_offer_no_socket")
                return Response()
        async def inline(function, *args):
            return function(*args)
        args = validate_args(build_parser().parse_args(["send", "--receiver-ip", "localhost"]))
        with patch("theta_rtc_diagnostic.open_native_capture", return_value=object()), \
             patch("theta_rtc_diagnostic.CaptureFrames", Reader), \
             patch("theta_rtc_diagnostic.make_native_track", return_value=SimpleNamespace(readyState="live")), \
             patch("aiortc.RTCPeerConnection", return_value=peer), \
             patch("aiohttp.ClientSession", Session), patch("theta_rtc_diagnostic.asyncio.to_thread", inline):
            if timeout or peer_close_error:
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    await send(args)
            else:
                await send(args)
        self.assertIn("reader.close", calls)
        self.assertIn("peer.close", calls)
        return calls

    async def test_sender_monitor_keeps_connection_across_957_ms_capture_wait(self):
        calls = await self.exercise()
        self.assertEqual([value for value in calls if value in ("capturing", "capture_wait")],
                         ["capturing", "capture_wait", "capturing"])

    async def test_sender_timeout_still_cleans_up(self):
        await self.exercise(timeout=True)

    async def test_peer_cleanup_error_cannot_skip_reader_close(self):
        await self.exercise(peer_close_error=True)


class ProbeAndArgumentsTest(unittest.TestCase):
    def test_timeout_is_separate_from_frame_freshness_and_bounded(self):
        args = validate_args(build_parser().parse_args(["send", "--receiver-ip", "localhost"]))
        self.assertEqual(args.capture_timeout_sec, 3.)
        for value in (0, .5, -1, True, float("nan"), float("inf"), 11):
            with self.subTest(value=value), self.assertRaises(ValueError):
                capture_timeout(value)
        self.assertEqual(capture_timeout(1), 1.)
        self.assertEqual(capture_timeout(10), 10.)

    def test_probe_validates_duration_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "new"):
                validate_args(build_parser().parse_args(["probe", "--output-dir", directory]))
        for duration in ("0", "nan", "121"):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                validate_args(build_parser().parse_args(["probe", "--output-dir", "/nonexistent-probe-test", "--duration-sec", duration]))

    def test_shared_open_settings_are_native_mjpg_and_release_on_configuration_error(self):
        class Capture:
            released = False
            def isOpened(self):
                return True
            def set(self, prop, value):
                settings.append((prop, value))
                return True
            def release(self):
                self.released = True
        settings, cap = [], Capture()
        with patch("theta_rtc_diagnostic.cv2.VideoCapture", return_value=cap) as factory, \
             patch("theta_rtc_diagnostic.read_capture_properties", return_value={}):
            self.assertIs(open_native_capture("/dev/video2", 30), cap)
        factory.assert_called_once_with("/dev/video2", cv2.CAP_V4L2)
        self.assertIn((cv2.CAP_PROP_FRAME_WIDTH, 1280), settings)
        self.assertIn((cv2.CAP_PROP_FRAME_HEIGHT, 720), settings)
        self.assertIn((cv2.CAP_PROP_FPS, 30), settings)
        with patch("theta_rtc_diagnostic.cv2.VideoCapture", return_value=cap), \
             patch("theta_rtc_diagnostic.read_capture_properties", side_effect=RuntimeError("synthetic config failure")):
            with self.assertRaises(RuntimeError):
                open_native_capture("0", 30)
        self.assertTrue(cap.released)

    def test_local_probe_saves_exact_unannotated_pixels_without_network(self):
        self.run_probe_fixture()

    def test_local_probe_failure_still_records_summary(self):
        self.run_probe_fixture(failure=True)

    def run_probe_fixture(self, failure=False):
        images = [np.full((720, 1280, 3), value, np.uint8) for value in (12, 34)]
        class FakeReader:
            def __init__(self, *args, **kwargs):
                self.sequence = 0
                self.lock = threading.Lock()
                self.failed_reads = self.recovered_gaps = 0
                self.max_read_sec = 0.
                self.error = None
                self.thread = SimpleNamespace(is_alive=lambda: False)
            def start(self):
                pass
            def close(self):
                pass
            def status(self):
                if failure:
                    raise RuntimeError("synthetic probe failure")
                return dict(state="capturing", age_sec=0., max_read_ms=0.)
            def after(self, sequence):
                if self.sequence == 2:
                    return None
                self.sequence += 1
                return self.sequence, time.monotonic(), images[self.sequence-1]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"probe"
            args = validate_args(build_parser().parse_args(["probe", "--output-dir", str(output),
                                 "--duration-sec", ".06", "--headless"]))
            with patch("theta_rtc_diagnostic.open_native_capture", return_value=object()), \
                 patch("theta_rtc_diagnostic.read_capture_properties", return_value={}), \
                 patch("theta_rtc_diagnostic.CaptureFrames", FakeReader):
                if failure:
                    with self.assertRaisesRegex(RuntimeError, "synthetic probe"):
                        asyncio.run(probe(args))
                else:
                    asyncio.run(probe(args))
            summary = json.loads((output/"probe_summary.json").read_text())
            self.assertFalse(summary["network_started"])
            self.assertFalse(summary["physical_output"])
            self.assertFalse(summary["scene_content_verified"])
            self.assertIsNone(summary["no_signal_detected"])
            if failure:
                self.assertEqual(summary["status"], "LOCAL_CAPTURE_PROBE_FAILED")
            else:
                self.assertEqual(summary["observed_frames"], 2)
                np.testing.assert_array_equal(cv2.imread(str(output/"first_frame.png")), images[0])
                np.testing.assert_array_equal(cv2.imread(str(output/"last_frame.png")), images[1])
                with (output/"capture_observations.csv").open(newline="") as stream:
                    self.assertEqual(len(list(csv.DictReader(stream))), 2)


if __name__ == "__main__":
    unittest.main()
