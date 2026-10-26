"""Camera-free, socket-free intake tests. No ROS/GPU/physical output."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from theta_rtc_frames import PROFILE, LatestNativeFrame, native_frame, validate_profile
from theta_rtc_diagnostic import CaptureFrames, Receiver, build_parser, save_decoded_frame, validate_args


class NativeFramesTest(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((720, 1280, 3), np.uint8)
        self.slot = LatestNativeFrame()
        self.slot.begin("a")

    def publish(self, media=0.0, now=10.0):
        return self.slot.publish("a", self.image, media, now)

    def test_exact_profile_roundtrip(self):
        validate_profile(json.loads(json.dumps(PROFILE)))

    def test_wrong_legacy_or_missing_profile_refused(self):
        for profile in (None, {}, [], dict(PROFILE, width=1920), dict(PROFILE, height=960),
                        dict(PROFILE, ros_control=True), dict(PROFILE, ffb=True),
                        dict(PROFILE, new_capture_only=1), dict(PROFILE, extra=True)):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                validate_profile(profile)

    def test_native_shape_is_not_silently_resized(self):
        for image in (None, np.zeros((960, 1920, 3), np.uint8),
                      np.zeros((720, 1280), np.uint8), self.image.astype(float)):
            with self.subTest(), self.assertRaises(ValueError):
                native_frame(image)

    def test_owned_full_frame_immutable_copy(self):
        self.image[719, 1279] = (12, 34, 56)
        self.publish()
        self.image[:] = 255
        frame, _ = self.slot.current(10.01)
        self.assertEqual(frame.image.shape, (720, 1280, 3))
        np.testing.assert_array_equal(frame.image[719, 1279], (12, 34, 56))
        with self.assertRaises(ValueError):
            frame.image[0, 0] = 1

    def test_latest_slot_overwrites_instead_of_queueing(self):
        for n in range(20):
            self.image[:] = n
            self.publish(n / 30, 10 + n / 30)
        frame, _ = self.slot.current(10.65)
        self.assertEqual(frame.sequence, 20)
        self.assertEqual(self.slot.overwritten, 19)
        self.assertEqual(int(frame.image[0, 0, 0]), 19)
        self.publish(1.0, 11)
        self.assertEqual(self.slot.overwritten, 19)  # previous was consumed

    def test_stale_and_future_input_never_displayed(self):
        self.publish()
        for now in (9.9, 10.50001):
            frame, reason = self.slot.current(now)
            self.assertIsNone(frame)
            self.assertEqual(reason, "receiver_frame_stale")

    def test_equal_or_decreasing_pts_invalidates_slot(self):
        for later in (0.0, 0.05):
            slot = LatestNativeFrame()
            slot.begin("test")
            slot.publish("test", self.image, .1, 1)
            with self.assertRaises(ValueError):
                slot.publish("test", self.image, later, 2)
            self.assertIsNone(slot.current(2)[0])

    def test_nonincreasing_reception_time_invalidates(self):
        self.publish()
        with self.assertRaises(ValueError):
            self.publish(.1, 10)
        self.assertIsNone(self.slot.current(10)[0])

    def test_nonfinite_or_negative_time_invalidates(self):
        for invalid in (float("nan"), float("inf"), -1, True):
            slot = LatestNativeFrame()
            slot.begin("test")
            slot.publish("test", self.image, 0, 1)
            with self.assertRaises(ValueError):
                slot.publish("test", self.image, invalid, 2)
            self.assertIsNone(slot.current(2)[0])

    def test_bad_shape_clears_previous_frame(self):
        self.publish()
        with self.assertRaises(ValueError):
            self.slot.publish("a", self.image[:, :640], .1, 10.1)
        self.assertIsNone(self.slot.current(10.1)[0])

    def test_disconnect_and_late_frames_do_not_revive(self):
        self.publish()
        self.slot.end("a")
        self.assertFalse(self.publish(.1, 10.1))
        self.assertIsNone(self.slot.current(10.1)[0])

    def test_reconnect_does_not_reuse_old_session_or_pts(self):
        self.publish(100, 10)
        self.slot.begin("b")
        self.assertIsNone(self.slot.current(10.1)[0])
        self.assertFalse(self.publish(101, 10.2))
        self.slot.publish("b", self.image, 0, 10.2)
        self.slot.end("a")  # delayed old connection shutdown
        frame, _ = self.slot.current(10.3)
        self.assertEqual((frame.session, frame.sequence, frame.media_time), ("b", 1, 0))

    def test_active_session_identity_must_be_unique(self):
        with self.assertRaises(ValueError):
            self.slot.begin("a")
        self.slot.end("a")
        with self.assertRaises(ValueError):
            self.slot.begin("a")

    def test_snapshots_keep_decoded_pixels_without_hud_or_resize(self):
        self.image[0, 0] = (11, 22, 33)
        self.image[719, 1279] = (44, 55, 66)
        self.publish()
        frame, _ = self.slot.current(10)
        with tempfile.TemporaryDirectory() as directory:
            path = save_decoded_frame(Path(directory), frame)
            self.assertTrue(path.name.startswith("decoded_a_"))
            np.testing.assert_array_equal(cv2.imread(str(path)), self.image)
            with self.assertRaises(ValueError):
                save_decoded_frame(Path(directory), frame)


class CameraReaderTest(unittest.TestCase):
    def test_after_never_repeats_capture_or_returns_stale_capture(self):
        camera = CaptureFrames(None, clock=lambda: 10.1)
        image = np.zeros((720, 1280, 3), np.uint8)
        camera.latest = (1, 10, image)
        self.assertIsNotNone(camera.after(0))
        self.assertIsNone(camera.after(1))
        camera.clock = lambda: 10.20001
        self.assertIsNone(camera.after(0))
        camera.clock = lambda: 9.9
        self.assertIsNone(camera.after(0))

    def test_actual_bad_capture_shape_stops_and_releases(self):
        class Camera:
            released = False
            def read(self):
                return True, np.zeros((960, 1920, 3), np.uint8)
            def release(self):
                self.released = True
        device = Camera()
        camera = CaptureFrames(device)
        camera.start()
        camera.thread.join(1)
        self.assertFalse(camera.thread.is_alive())
        self.assertTrue(device.released)
        with self.assertRaisesRegex(RuntimeError, "1280x720"):
            camera.after(0)

    def test_failed_capture_never_returns_old_pixels(self):
        class Camera:
            released = False
            def read(self):
                return False, None
            def release(self):
                self.released = True
        times = iter((0, 1))
        device = Camera()
        camera = CaptureFrames(device, clock=lambda: next(times))
        camera.start()
        camera.thread.join(1)
        self.assertTrue(device.released)
        with self.assertRaisesRegex(RuntimeError, "read failed"):
            camera.after(0)


class CLIAndIsolationTest(unittest.TestCase):
    def test_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            args = build_parser().parse_args(["receive", "--output-dir", directory])
            with self.assertRaises(ValueError):
                validate_args(args)

    def test_invalid_ports_durations_and_address(self):
        for argv in (["send", "--receiver-ip", "localhost", "--port", "0"],
                     ["send", "--receiver-ip", "localhost", "--port", "65536"],
                     ["send", "--receiver-ip", "http://localhost"],
                     ["receive", "--output-dir", "/nonexistent-test-output", "--duration-sec", "nan"],
                     ["receive", "--output-dir", "/nonexistent-test-output", "--duration-sec", "0"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                validate_args(build_parser().parse_args(argv))

    def test_no_ros_driver_torch_or_ffb_imports(self):
        forbidden = {"rclpy", "webrtc_stream", "webrtc_receive_ui", "evdev", "torch", "ultralytics"}
        for name in ("theta_rtc_diagnostic.py", "theta_rtc_frames.py"):
            tree = ast.parse((ROOT / "src" / name).read_text())
            for node in ast.walk(tree):
                imported = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                            else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                self.assertFalse(forbidden.intersection(n.split(".")[0] for n in imported))

    def test_existing_shells_dispatch_only_explicit_diagnostic_flag(self):
        for name, role in (("start_theta_stream_rtc.sh", "send"), ("start_theta_receive_rtc.sh", "receive")):
            import os
            completed = subprocess.run(["bash", str(ROOT / "src" / name), "--diagnostic", "--help"],
                env=dict(os.environ, THETA_RTC_PYTHON="/bin/echo"), capture_output=True, text=True, check=True)
            self.assertEqual(completed.stdout.strip(), str(ROOT / "src/theta_rtc_diagnostic.py") + f" {role} --help")

    def test_help_does_not_start_camera_or_listener(self):
        for role in ("send", "receive"):
            completed = subprocess.run([sys.executable, str(ROOT / "src/theta_rtc_diagnostic.py"), role, "--help"],
                                       capture_output=True, text=True, check=True)
            self.assertIn("usage:", completed.stdout)


class ReceiverLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_decoded_native_frame_is_consumed_without_remap(self):
        slot = LatestNativeFrame()
        slot.begin("a")
        image = np.zeros((720, 1280, 3), np.uint8)
        image[719, 1279] = (12, 34, 56)
        seen = asyncio.Event()
        class Frame:
            pts = 3000
            time_base = 1 / 90000
            def to_ndarray(self, format):
                self.format = format
                return image
        frame = Frame()
        class Track:
            count = 0
            async def recv(self):
                self.count += 1
                if self.count == 1:
                    return frame
                seen.set()
                await asyncio.Future()
        class Peer:
            async def close(self):
                raise AssertionError("valid frame must not close peer")
        task = asyncio.create_task(Receiver(slot).consume(Track(), "a", Peer()))
        try:
            await asyncio.wait_for(seen.wait(), timeout=1)
            import time
            current, _ = slot.current(time.monotonic())
            self.assertEqual(frame.format, "bgr24")
            self.assertEqual(current.sequence, 1)
            np.testing.assert_array_equal(current.image, image)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_missing_presentation_time_retires_peer_and_frame(self):
        slot = LatestNativeFrame()
        slot.begin("a")
        slot.publish("a", np.zeros((720, 1280, 3), np.uint8), 0, 0)
        class Track:
            async def recv(self):
                return SimpleNamespace(pts=None, time_base=None)
        class Peer:
            closed = False
            async def close(self):
                self.closed = True
        peer = Peer()
        await Receiver(slot).consume(Track(), "a", peer)
        self.assertTrue(peer.closed)
        self.assertIsNone(slot.current(0.1)[0])

    async def test_bad_profile_refused_without_creating_peer_or_socket(self):
        if importlib.util.find_spec("aiohttp") is None or importlib.util.find_spec("aiortc") is None:
            self.skipTest("WebRTC dependencies unavailable")
        class Request:
            async def json(self):
                return dict(sdp="not even parsed", type="offer")
        receiver = Receiver(LatestNativeFrame())
        response = await receiver.offer(Request())
        self.assertEqual(response.status, 400)
        self.assertIsNone(receiver.pc)


class InMemoryVP8Test(unittest.TestCase):
    def test_actual_codec_preserves_dimensions_and_media_time_but_is_lossy(self):
        if importlib.util.find_spec("aiortc") is None or importlib.util.find_spec("av") is None:
            self.skipTest("WebRTC codec dependencies unavailable")
        import av
        from fractions import Fraction
        from aiortc.codecs.vpx import Vp8Encoder, Vp8Decoder, vp8_depayload
        from aiortc.jitterbuffer import JitterFrame
        yy, xx = np.indices((720, 1280))
        image = np.stack((xx % 256, yy % 256, (xx + yy) % 256), axis=-1).astype(np.uint8)
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts, frame.time_base = 3000, Fraction(1, 90000)
        payloads, timestamp = Vp8Encoder().encode(frame)
        decoded = Vp8Decoder().decode(JitterFrame(b"".join(vp8_depayload(p) for p in payloads), timestamp))
        self.assertEqual(len(decoded), 1)
        pixels = decoded[0].to_ndarray(format="bgr24")
        self.assertEqual(pixels.shape, image.shape)
        self.assertFalse(np.array_equal(image, pixels))
        # aiortc's rational-timebase conversion can round down by one RTP tick.
        # Media PTS is presentation time, never a cross-PC capture-clock value.
        self.assertLessEqual(abs(timestamp - 3000), 1)
        self.assertEqual(decoded[0].pts, timestamp)
        slot = LatestNativeFrame()
        slot.begin("codec-test")
        self.assertTrue(slot.publish("codec-test", pixels, float(decoded[0].pts * decoded[0].time_base), 10))
        np.testing.assert_array_equal(slot.current(10)[0].image, pixels)


if __name__ == "__main__":
    unittest.main()
