"""Execute receiver connection code with fake peers; never start ROS/Qt/RTC."""
import ast
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock

from aiohttp import web
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from driver_motion_bridge import DriverMotionBridge
from driver_motion_protocol import PROFILE
from test_driver_motion_bridge import SESSION_A,image


def selected_node(source,*names):
    node=ast.parse(source)
    for name in names:
        node=next(item for item in node.body if getattr(item,"name",None)==name)
    return node


def receiver_class():
    node=selected_node((ROOT/"src/webrtc_receive_ui.py").read_text(),"WebRTCServerThread")
    scope=dict(threading=threading,asyncio=asyncio,time=time,json=json,uuid=uuid,
        logger=logging.getLogger("driver_motion_test"),web=web,RTCPeerConnection=FakePeer,
        RTCSessionDescription=lambda **kw:SimpleNamespace(**kw))
    exec(compile(ast.Module(body=[node],type_ignores=[]),"receiver_class_under_test","exec"),scope)
    return scope["WebRTCServerThread"]


class FakePeer:
    def __init__(self):self.handlers={};self.connectionState="connected"
    def on(self,event):
        def decorator(function):self.handlers[event]=function;return function
        return decorator
    async def setRemoteDescription(self,value):self.remote=value
    async def createAnswer(self):return SimpleNamespace(sdp="synthetic answer",type="answer")
    async def setLocalDescription(self,value):self.localDescription=value


class FakeRequest:
    def __init__(self,profile):self.profile=profile
    async def json(self):return dict(sdp="synthetic offer",type="offer",motion_native_profile=self.profile)


class FakeVideo:
    kind="video"
    def __init__(self):self.count=0;self.delivered=asyncio.Event();self.hold=asyncio.Event()
    async def recv(self):
        self.count+=1
        if self.count>2:
            self.delivered.set();await self.hold.wait()
            raise RuntimeError("synthetic track ended")
        return SimpleNamespace(time=self.count/30.,to_ndarray=lambda **kw:np.full((720,1280,3),self.count,np.uint8))


class ReceiverTapIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.bridge=DriverMotionBridge([sys.executable,"-c","pass"],Path(self.temp.name)/"tap")
        self.addCleanup(self.bridge.close)
        signals=SimpleNamespace(telemetry_received=SimpleNamespace(emit=Mock()),
            latency_updated=SimpleNamespace(emit=Mock()))
        self.server=receiver_class()(signals,motion=self.bridge)

    async def test_offer_keeps_control_and_telemetry_handlers_with_valid_motion_profile(self):
        response=await self.server.handle_offer(FakeRequest(dict(PROFILE)))
        self.assertEqual(response.status,200);self.assertTrue(self.bridge.valid_source)
        peer=self.server.pc
        control=SimpleNamespace(label="control")
        peer.handlers["datachannel"](control)
        self.assertIs(self.server.control_channel,control)
        handlers={}
        def on(event):
            def decorator(fn):handlers[event]=fn;return fn
            return decorator
        peer.handlers["datachannel"](SimpleNamespace(label="telemetry",on=on))
        handlers["message"]('{"speed_mps":0.2}')
        self.server.signals.telemetry_received.emit.assert_called_once_with(dict(speed_mps=.2))

    async def test_legacy_profile_does_not_reject_driving_connection(self):
        response=await self.server.handle_offer(FakeRequest(None))
        self.assertEqual(response.status,200);self.assertFalse(self.bridge.valid_source)
        control=SimpleNamespace(label="control")
        self.server.pc.handlers["datachannel"](control)
        self.assertIs(self.server.control_channel,control)

    async def test_native_frame_tap_is_before_remap_and_does_not_modify_pixels(self):
        await self.server.handle_offer(FakeRequest(dict(PROFILE)))
        video=FakeVideo();task=asyncio.create_task(self.server.process_video(video,self.bridge.session))
        try:
            await asyncio.wait_for(video.delivered.wait(),1.)
            self.assertIs(self.bridge.latest.image,self.server.latest_frame)
            self.assertEqual(self.bridge.latest.sequence,2)
            self.assertFalse(self.server.latest_frame.flags.writeable)
            self.assertTrue(np.all(self.server.latest_frame==2))
            display=self.server.latest_frame.copy();display[:]=99
            self.assertTrue(np.all(self.bridge.latest.image==2))
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNone(self.bridge.latest)
        self.assertFalse(self.bridge.valid_source)

    async def test_tap_failure_disables_distance_without_terminating_video_or_control(self):
        class BrokenTap:
            def begin(self,*args):pass
            def publish(self,*args):raise RuntimeError("synthetic tap failure")
            def fail(self,error):self.failed=str(error)
        broken=BrokenTap();self.server.motion=broken
        await self.server.handle_offer(FakeRequest(dict(PROFILE)))
        video=FakeVideo();task=asyncio.create_task(self.server.process_video(video,"a"*32))
        try:
            await asyncio.wait_for(video.delivered.wait(),1.)
            self.assertIn("synthetic",broken.failed);self.assertIsNone(self.server.motion)
            self.assertTrue(np.all(self.server.latest_frame==2))
            control=SimpleNamespace(label="control")
            self.server.pc.handlers["datachannel"](control)
            self.assertIs(self.server.control_channel,control)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task

    async def test_old_peer_disconnect_does_not_invalidate_new_session(self):
        await self.server.handle_offer(FakeRequest(dict(PROFILE)))
        old=self.server.pc;old_session=self.bridge.session
        await self.server.handle_offer(FakeRequest(dict(PROFILE)))
        new_session=self.bridge.session;self.assertNotEqual(old_session,new_session)
        old.connectionState="closed";await old.handlers["connectionstatechange"]()
        self.assertTrue(self.bridge.valid_source);self.assertEqual(self.bridge.session,new_session)
        self.server.pc.connectionState="failed"
        await self.server.pc.handlers["connectionstatechange"]()
        self.assertFalse(self.bridge.valid_source)

    async def test_disabled_tap_keeps_legacy_frame_mutability_and_needs_no_profile(self):
        self.server.motion=None
        response=await self.server.handle_offer(FakeRequest(None));self.assertEqual(response.status,200)
        self.assertNotIn("connectionstatechange",self.server.pc.handlers)
        video=FakeVideo();video.hold.set()
        await self.server.process_video(video)
        self.assertTrue(self.server.latest_frame.flags.writeable)


class DriverControlInvarianceTests(unittest.TestCase):
    # Frozen normalized AST hashes of commit 142aadf (before this change), not
    # hashes of whatever HEAD happens to be when the tests are later executed.
    UI={
        "ControlBridgeNode":"b0d1ba5f65da0006e35f2df2ea496ec5d80cd06ab0ce4b8240209bd89b219d13",
        "ThetaDriverUI.process_keyboard_control":"0221ca082f20ad0ab640c278571223b52c77f21701aa41646a1bd2bb307cdd9f",
        "ThetaDriverUI.keyPressEvent":"dcee23294d585d3a048218413db9348141ae0400f192459193a0f5f55e355e96",
        "ThetaDriverUI.keyReleaseEvent":"778bfe6a1ed9db82b8ecafacad668dec911c948f006d717e1d37cbfbaffd8cdc",
        "WebRTCServerThread.send_control_data":"266812c042fc67f3e6c9973f39cca1e9fb337fca97ad0eef6f6fe252b1201022",
        "WebRTCServerThread._async_send":"03eb247019af06dcdd62add2bad05ceb83fd2251c632105caae8cf421c7eb536",
        "WebRTCServerThread.handle_offer.on_datachannel":"6a44e5f46d15d79fb93f2a3bb6e949615d59310509c8b0de9071e61bffc1482f"}
    SENDER={
        "TelemetryNode":"b3da15ed1c0a4a4c8ddc301968607df569adef3a339cc9e5a04c7cfba6705cc2",
        "CameraVideoTrack":"310ffb3114a92417478e346b6395b5659fd431621b27e3193a037172aa44e6f9",
        "ros2_spin_thread":"4ce28feb3ed8ff1de7784659c092dd1b35362a503b07761be75a03c200ca1028",
        "_run_driver.on_control_message":"433772682e6e1c869358542ff1dba4136a9ddc6c7ed96618784ab079804cb064"}

    def assert_hashes(self,path,expected):
        source=(ROOT/path).read_text()
        for key,sha in expected.items():
            with self.subTest(function=key):
                node=selected_node(source,*key.split("."))
                actual=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
                self.assertEqual(actual,sha)

    def test_receiver_control_ros_and_keyboard_function_bodies_unchanged(self):
        self.assert_hashes("src/webrtc_receive_ui.py",self.UI)

    def test_sender_control_publish_and_legacy_camera_unchanged(self):
        self.assert_hashes("src/webrtc_stream.py",self.SENDER)

    def test_legacy_shell_commands_are_byte_identical_after_opt_in_branches(self):
        for name,marker,sha in (
            ("start_theta_receive_rtc.sh",'\nDIR="',"a9487940b099d8acdec86924e9d56b376d9b349073641d5dfa04079c73d7f161"),
            ("start_theta_stream_rtc.sh","# IP address of the receiver PC","e2227ecb9b1e875ce410a0e4f458a48694babc8f8ffb738edf623c0efe618135")):
            source=(ROOT/"src"/name).read_text()
            self.assertEqual(hashlib.sha256(source[source.index(marker):].encode()).hexdigest(),sha)

    def test_panel_updates_even_when_driver_has_no_frame_to_render(self):
        node=selected_node((ROOT/"src/webrtc_receive_ui.py").read_text(),"ThetaDriverUI","update_frame")
        scope={};exec(compile(ast.Module(body=[node],type_ignores=[]),"ui_tick","exec"),scope)
        label=SimpleNamespace(setText=Mock())
        ui=SimpleNamespace(motion=SimpleNamespace(snapshot=lambda:dict(available=False,reason="motion_result_stale")),
            motion_label=label,server_thread=SimpleNamespace(frame_lock=threading.Lock(),latest_frame=None))
        scope["update_frame"](ui)
        text=label.setText.call_args[0][0]
        self.assertIn("WITHHELD",text);self.assertIn("motion_result_stale",text)


class SenderConnectionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,native):
        payloads=[];channels={};track=object();telemetry=Mock()
        class Channel:
            def __init__(self,label):self.label=label;self.handlers={}
            def on(self,event):
                def decorator(fn):self.handlers[event]=fn;return fn
                return decorator
        class Peer(FakePeer):
            iceGatheringState="complete"
            def __init__(self):
                super().__init__();self.connectionState="failed";self.closed=False;self.seen_track=None
            def addTransceiver(self,value,**kwargs):
                self.seen_track=value
                return SimpleNamespace(setCodecPreferences=Mock(),sender=SimpleNamespace(
                    getParameters=Mock(side_effect=RuntimeError("synthetic unavailable optional bitrate API"))))
            def createDataChannel(self,label):
                channels[label]=Channel(label);return channels[label]
            async def createOffer(self):return SimpleNamespace(sdp="v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 97\r\n",type="offer")
            async def close(self):self.closed=True
        peer=Peer()
        class Context:
            status=200
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def json(self):return dict(sdp="synthetic answer",type="answer")
            def post(self,url,json):payloads.append(json);return Context()
        ros=SimpleNamespace(init=Mock(),shutdown=Mock())
        legacy_camera=Mock(return_value=object())
        scope=dict(rclpy=ros,TelemetryNode=Mock(return_value=telemetry),
            threading=SimpleNamespace(Thread=lambda **kw:SimpleNamespace(start=Mock())),
            ros2_spin_thread=Mock(),logger=logging.getLogger("sender_motion_test"),
            RTCPeerConnection=lambda:peer,RTCSessionDescription=lambda **kw:SimpleNamespace(**kw),
            CameraVideoTrack=legacy_camera,json=json,asyncio=asyncio,
            aiohttp=SimpleNamespace(ClientSession=lambda:Context()))
        node=selected_node((ROOT/"src/webrtc_stream.py").read_text(),"_run_driver")
        exec(compile(ast.Module(body=[node],type_ignores=[]),"sender_under_test","exec"),scope)
        args=SimpleNamespace(odom_topic="/odom",mode_topic="/mode",page_delta_topic="/page",battery_topic="/battery",
            imu_topic="/imu",pedal_topic="/cmd_vel",device="synthetic",cam_width=1280,cam_height=720,
            fps=30,mock_camera=False,bitrate="15M",receiver_ip="synthetic",telemetry_hz=24,motion_native=native)
        if native:args._motion_video_track=track
        await scope["_run_driver"](args)
        self.assertEqual(set(channels),{"control","telemetry"})
        channels["control"].handlers["message"]('{"linear_x":0.2,"angular_z":0.1}')
        telemetry.publish_control.assert_called_once_with(dict(linear_x=.2,angular_z=.1))
        self.assertTrue(peer.closed);ros.shutdown.assert_called_once()
        self.assertEqual(len(payloads),1)
        if native:
            legacy_camera.assert_not_called();self.assertIs(peer.seen_track,track)
            self.assertEqual(payloads[0]["motion_native_profile"],dict(PROFILE))
        else:
            legacy_camera.assert_called_once();self.assertNotIn("motion_native_profile",payloads[0])

    async def test_native_driver_still_negotiates_control_and_telemetry(self):
        await self.exercise(True)

    async def test_legacy_driver_has_no_new_profile_or_extra_capture(self):
        await self.exercise(False)


if __name__ == "__main__":unittest.main()
