"""Sender opt-in uses native fresh reader, legacy driver call passes through."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from driver_motion_camera import run_native_driver


class DriverNativeCameraTests(unittest.TestCase):
    def args(self,**kwargs):
        return SimpleNamespace(**dict(dict(motion_native=True,cam_width=1280,cam_height=720,
            mock_camera=False,device="synthetic",fps=30),**kwargs))

    def test_legacy_mode_calls_original_driver_without_opening_another_camera(self):
        args=self.args(motion_native=False);driver=AsyncMock(return_value=17)
        with patch("theta_rtc_diagnostic.open_native_capture",side_effect=AssertionError("camera opened")):
            self.assertEqual(asyncio.run(run_native_driver(args,driver)),17)
        driver.assert_awaited_once_with(args)

    def test_native_requires_real_input_and_exact_geometry_before_capture_or_ros(self):
        for args in (self.args(cam_width=1920,cam_height=960),self.args(mock_camera=True)):
            driver=AsyncMock()
            with patch("theta_rtc_diagnostic.open_native_capture",side_effect=AssertionError("camera opened")):
                with self.assertRaises(ValueError):asyncio.run(run_native_driver(args,driver))
            driver.assert_not_called()

    def test_one_native_reader_track_is_passed_to_original_control_driver(self):
        capture,reader,track=Mock(),Mock(),Mock();args=self.args()
        async def driver(value):
            self.assertIs(value._motion_video_track,track);return 23
        with patch("theta_rtc_diagnostic.open_native_capture",return_value=capture) as opened, \
             patch("theta_rtc_diagnostic.CaptureFrames",return_value=reader) as created, \
             patch("theta_rtc_diagnostic.make_native_track",return_value=track):
            self.assertEqual(asyncio.run(run_native_driver(args,driver)),23)
        opened.assert_called_once_with("synthetic",30);created.assert_called_once_with(capture)
        reader.start.assert_called_once();track.stop.assert_called_once();reader.close.assert_called_once()
        self.assertFalse(hasattr(args,"_motion_video_track"))

    def test_signaling_failure_or_early_return_cleans_native_reader(self):
        reader,track=Mock(),Mock();args=self.args()
        with patch("theta_rtc_diagnostic.open_native_capture",return_value=Mock()), \
             patch("theta_rtc_diagnostic.CaptureFrames",return_value=reader), \
             patch("theta_rtc_diagnostic.make_native_track",return_value=track):
            with self.assertRaisesRegex(RuntimeError,"signaling"):
                asyncio.run(run_native_driver(args,AsyncMock(side_effect=RuntimeError("signaling"))))
        track.stop.assert_called_once();reader.close.assert_called_once()


class DriverMotionShellTests(unittest.TestCase):
    def invoke(self,script,mode,python_env):
        with tempfile.TemporaryDirectory() as directory:
            # Test fixture executable records argv only; starts no app/ROS/camera.
            stub=Path(directory)/"python_stub"
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n');stub.chmod(0o700)
            env=dict(os.environ);env[python_env]=str(stub)
            return subprocess.run(["bash",str(ROOT/"src"/script),mode,"--receiver-ip","synthetic"],
                env=env,text=True,capture_output=True,check=True).stdout.splitlines()

    def test_receiver_opt_in_keeps_driver_ui_not_diagnostic_listener(self):
        args=self.invoke("start_theta_receive_rtc.sh","--motion-distance","THETA_UI_PYTHON")
        self.assertTrue(args[0].endswith("webrtc_receive_ui.py"))
        self.assertEqual(args[1:6],["--cam-width","1280","--cam-height","720","--motion-distance"])

    def test_sender_opt_in_keeps_driver_sender_with_control_channels(self):
        args=self.invoke("start_theta_stream_rtc.sh","--motion-native","THETA_RTC_PYTHON")
        self.assertTrue(args[0].endswith("webrtc_stream.py"))
        self.assertIn("--motion-native",args);self.assertNotIn("--diagnostic",args)

    def test_diagnostic_mode_still_selects_old_diagnostic_program(self):
        args=self.invoke("start_theta_stream_rtc.sh","--diagnostic","THETA_RTC_PYTHON")
        self.assertTrue(args[0].endswith("theta_rtc_diagnostic.py"));self.assertEqual(args[1],"send")

    def test_explicit_ui_python_is_not_overridden_by_legacy_venv_reexec(self):
        with tempfile.TemporaryDirectory() as directory:
            stub=Path(directory)/"python_stub"
            stub.write_text('#!/bin/sh\nprintf "%s" "$THETA_UI_NO_VENV"\n');stub.chmod(0o700)
            env=dict(os.environ,THETA_UI_PYTHON=str(stub),THETA_UI_NO_VENV="0")
            result=subprocess.run(["bash",str(ROOT/"src/start_theta_receive_rtc.sh"),"--motion-distance"],
                env=env,capture_output=True,text=True,check=True)
            self.assertEqual(result.stdout,"1")


if __name__ == "__main__":unittest.main()
