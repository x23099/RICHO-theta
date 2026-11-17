"""Opt-in actual connection handler + real codec/pipe, synthetic detector only."""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from driver_frame_packet_runtime import (PacketSource,PacketMotionBridge,ReceiverPacketBinding,
    SenderPacketBinding,connection_profile,checked_profile,common_message_limit,
    add_sender_arguments,validate_sender_args)
from driver_frame_packet_channel import PROTOCOL
from driver_frame_packet import encode_packet,FramePacketReceiver,DecodedFramePacket
from driver_motion_bridge import add_motion_arguments,bridge_from_args
from driver_motion_protocol import PROFILE
from test_driver_motion_bridge import FAKE_CHILD,valid_result
from test_driver_motion_integration import receiver_class
from test_driver_frame_packet import candidate,image,SENDER,STREAM
from test_driver_frame_motion import observation
from test_driver_odometry_observation import message as base_message


def message(**kwargs):
    return base_message(child='base_footprint',**kwargs)


def save_evidence(name,value):
    output=os.environ.get('THETA_PACKET_RUNTIME_AUDIT_DIR')
    if output is None:return
    output=Path(output).resolve()
    if ROOT/'Experimental_results/2026-11-18/frame_packet_runtime_r01' not in output.parents:
        raise ValueError('test evidence restricted to this experiment')
    with (output/name).open('x') as stream:
        json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')


def sdp(cap=65536,mid='data'):
    return ('v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n'
            'm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=mid:'+mid+
            '\r\na=sctp-port:5000\r\na=max-message-size:'+str(cap)+'\r\n')


class Clock:
    def __init__(self,value):self.value=value
    def __call__(self):return self.value


class Channel:
    def __init__(self,label=PROTOCOL,**kwargs):
        self.label=label;self.protocol=kwargs.get('protocol',PROTOCOL)
        self.ordered=kwargs.get('ordered',False);self.maxRetransmits=kwargs.get('maxRetransmits',0)
        self.maxPacketLifeTime=None;self.readyState='open';self.bufferedAmount=0
        self.handlers={};self.other=None;self.sent=0
    def on(self,event):
        def register(fn):self.handlers[event]=fn;return fn
        return register
    def send(self,value):
        self.sent+=1
        if self.other is not None:self.other.handlers['message'](value)
    def close(self):
        if self.readyState=='closed':return
        self.readyState='closed'
        if self.other is not None and 'close' in self.other.handlers:self.other.handlers['close']()


class Peer:
    def __init__(self):
        self.handlers={};self.connectionState='connected'
        self.localDescription=NS(sdp=sdp(),type='answer')
        self.remoteDescription=NS(sdp=sdp(),type='offer')
    def on(self,event):
        def register(fn):self.handlers.setdefault(event,[]).append(fn);return fn
        return register
    def createDataChannel(self,label,**kwargs):
        self.channel=Channel(label,**kwargs);return self.channel
    async def setRemoteDescription(self,value):self.remoteDescription=value
    async def createAnswer(self):return NS(sdp=sdp(),type='answer')
    async def setLocalDescription(self,value):self.localDescription=value
    def datachannel(self,channel):
        for fn in self.handlers.get('datachannel',[]):fn(channel)


class Reader:
    def __init__(self):self.value=None
    def after(self,sequence):return self.value if self.value and self.value[0]>sequence else None


class ProfileSourceTests(unittest.TestCase):
    def test_argument_default_off_and_no_extra_camera(self):
        parser=argparse.ArgumentParser();add_sender_arguments(parser)
        args=parser.parse_args([])
        self.assertFalse(args.frame_motion_packets)
        self.assertEqual(args.frame_packet_hz,10)
        with self.assertRaises(ValueError):
            validate_sender_args(NS(frame_motion_packets=True,motion_native=False))
        for bad in ('0','30'):
            with self.assertRaises(SystemExit):parser.parse_args(['--frame-packet-hz',bad])

    def test_receiver_default_rtp_and_packet_requires_opt_in(self):
        parser=argparse.ArgumentParser();add_motion_arguments(parser)
        args=parser.parse_args([])
        self.assertEqual(args.motion_input,'rtp')
        self.assertIsNone(bridge_from_args(args))
        with self.assertRaises(ValueError):bridge_from_args(parser.parse_args(['--motion-input','packet']))

    def test_packet_cli_reuses_one_unstarted_inference_bridge_and_pipe(self):
        parser=argparse.ArgumentParser();add_motion_arguments(parser)
        with tempfile.TemporaryDirectory() as directory:
            args=parser.parse_args(['--motion-distance','--motion-input','packet',
                '--motion-python',sys.executable,'--motion-weights',str(Path(__file__)),
                '--motion-profile',str(Path(__file__)),  # Only file validation, NOT a real model/profile load.
                '--motion-output-dir',str(Path(directory)/'new'),
                '--motion-experimental-rigid-mount'])
            args.cam_width,args.cam_height,args.front_lens,args.mock_camera=1280,720,'left',False
            bridge=bridge_from_args(args)
            try:
                self.assertIsInstance(bridge,PacketMotionBridge)
                self.assertEqual(bridge.command.count('--packet-input'),1)
                self.assertIsNone(bridge.process)
                self.assertIsNone(bridge.thread.ident)
            finally:bridge.close()

    def test_exact_profile_and_no_permission_or_rate_upgrade(self):
        profile=connection_profile(SENDER,STREAM,10)
        self.assertEqual(checked_profile(profile),profile)
        for changes in (dict(rate_hz=30),dict(rate_hz=10.),dict(usable_for_ffb=True),
                        dict(usable_for_ffb=0),dict(message_cap=65536),dict(extra=1)):
            with self.assertRaises(ValueError):checked_profile(dict(profile,**changes))

    def test_applied_sdp_common_caps_and_mid_must_agree(self):
        self.assertEqual(common_message_limit(sdp(2048),sdp(4096)),2048)
        self.assertEqual(common_message_limit(sdp(0),sdp(0)),16384)
        for local,remote in ((sdp(mid='one'),sdp(mid='two')),('x'*65537,sdp()),(sdp(100),sdp())):
            with self.assertRaises(ValueError):common_message_limit(local,remote)

    def test_source_latest_observed_past_callback_and_capture_identity(self):
        clock=Clock(10.)
        source=PacketSource(10,clock=clock)
        source.observe_odom(message(sec=1000,v=-.2,w=.1))
        clock.value=10.05
        value=source.candidate(51,10.04)
        self.assertTrue(value['local_pair_available'])
        self.assertEqual(value['capture_sequence'],51)
        self.assertEqual(value['odometry_observation']['linear_mps'],-.2)
        self.assertIsNone(value['receiver_media_pts'])
        clock.value=10.08
        self.assertIsNone(source.candidate(52,10.07))

    def test_unreceived_zero_and_repeated_or_invalid_callback_not_rescued(self):
        clock=Clock(10.)
        source=PacketSource(10,clock=clock)
        self.assertFalse(source.candidate(1,10.)['local_pair_available'])
        clock.value=10.11
        source.observe_odom(message(sec=1000,v=0.))
        first=source.candidate(2,10.11)
        self.assertEqual(first['odometry_observation']['linear_mps'],0.)
        clock.value=10.22
        source.observe_odom(message(sec=1000,v=.9))
        value=source.candidate(3,10.22)
        self.assertFalse(value['local_pair_available'])
        self.assertIsNone(value['odometry_observation'])

    def test_future_callback_is_not_applied_to_earlier_capture(self):
        clock=Clock(10.)
        source=PacketSource(10,clock=clock);source.observe_odom(message(sec=1000,v=.2))
        clock.value=10.02;source.observe_odom(message(sec=1001,v=.9))
        self.assertEqual(source.candidate(100,10.01)['odometry_observation']['linear_mps'],.2)

    def test_capture_reversal_even_among_rate_skipped_frames_fails(self):
        clock=Clock(10.1);source=PacketSource(10,clock=clock)
        source.candidate(1,10.)
        self.assertIsNone(source.candidate(2,10.05))
        with self.assertRaises(ValueError):source.candidate(3,10.04)


class PacketBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.clock=Clock(500.)
        self.bridge=PacketMotionBridge([sys.executable,'-c','pass'],Path(self.temp.name)/'bridge',clock=self.clock)
        self.addCleanup(self.bridge.close)
        self.bridge.begin_packet(connection_profile(SENDER,STREAM,10))
        wire=encode_packet(image(),candidate(sequence=42,v=-.2,w=.1))
        self.packet=FramePacketReceiver(sender_id=SENDER,stream_id=STREAM,max_receive_age_sec=.2).accept(wire,received_at_sec=500.)

    def test_capture_sequence_not_receiver_counter_through_existing_pipe(self):
        self.assertTrue(self.bridge.publish_packet(self.packet))
        frame=self.bridge._next_frame(None)
        self.assertEqual(frame.sequence,42)
        self.assertEqual(frame.session,STREAM)
        self.assertIs(frame.image,self.packet.image)
        value=valid_result(frame)
        self.assertTrue(self.bridge._accept_result(value))
        event=self.bridge._result_event(value,True)
        self.assertEqual(event['source_candidate'],self.packet.candidate)
        self.assertEqual(event['packet_sha256'],self.packet.packet_sha256)
        self.assertFalse(event['usable_for_ffb'])

    def test_rtp_publish_never_falls_back_in_packet_mode(self):
        self.assertFalse(self.bridge.publish(STREAM,self.packet.image,.1,500.))
        self.assertIsNone(self.bridge.latest)

    def test_receive_deadline_includes_inflight_and_snapshot(self):
        self.bridge.publish_packet(self.packet);frame=self.bridge._next_frame(None)
        value=valid_result(frame);self.bridge.result=value
        self.clock.value=500.201
        self.assertFalse(self.bridge._accept_result(value))
        self.assertFalse(self.bridge.snapshot()['available'])

    def test_stale_or_duplicate_input_clears_old_value(self):
        self.bridge.publish_packet(self.packet)
        self.bridge.result=valid_result(self.bridge.latest)
        self.assertFalse(self.bridge.publish_packet(self.packet))
        self.assertIsNone(self.bridge.latest)
        self.assertIsNone(self.bridge.result)

    def test_old_inflight_result_keeps_old_metadata_but_not_new_scope_acceptance(self):
        self.bridge.publish_packet(self.packet);frame=self.bridge._next_frame(None)
        self.bridge.begin_packet(connection_profile(SENDER,'c'*32,10))
        value=valid_result(frame)
        self.assertFalse(self.bridge._accept_result(value))
        self.assertEqual(self.bridge._result_event(value,False)['source_candidate']['stream_id'],STREAM)

    def test_copy_candidate_and_reject_permission_or_mutable_image(self):
        old=copy.deepcopy(self.packet.candidate)
        self.bridge.publish_packet(self.packet)
        self.packet.candidate['capture_sequence']=999
        self.assertEqual(self.bridge.packet_latest.candidate,old)
        bad=DecodedFramePacket(dict(old,usable_for_ffb=True),self.packet.image,500.,self.packet.packet_sha256)
        with self.assertRaises(ValueError):self.bridge.publish_packet(bad)

    def test_panel_does_not_claim_packet_is_displayed_rtp_frame(self):
        from driver_motion_presentation import panel_text
        snapshot=self.bridge.snapshot()
        self.assertIn('表示中のRTPフレームとの一致は未認定',panel_text(snapshot))


class BindingPipeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'bridge'
        # Actual old engine/serve/pipe, but entirely synthetic predictor/support.
        child=FAKE_CHILD.replace('Path(sys.argv[2])/"synthetic_measurements.jsonl")',
            'Path(sys.argv[2])/"synthetic_measurements.jsonl",packet_input=True)')
        self.bridge=PacketMotionBridge([sys.executable,'-u','-c',child,str(ROOT),str(self.directory),'normal'],self.directory)
        self.bridge.start()
        deadline=time.monotonic()+3.
        while not self.bridge.ready.is_set():
            if time.monotonic()>deadline:raise AssertionError('child not ready')
            await asyncio.sleep(.01)
        cls=receiver_class()
        cls.handle_offer.__globals__['RTCPeerConnection']=Peer
        self.signals=NS(telemetry_received=NS(emit=Mock()),latency_updated=NS(emit=Mock()))
        self.server=cls(self.signals,motion=self.bridge)
        self.links=[]

    async def asyncTearDown(self):
        for link in self.links:await asyncio.wait_for(link.close(),2.)
        if self.server.packet_binding is not None:self.assertTrue(self.server.packet_binding.close())
        self.assertTrue(self.bridge.close()['shutdown_complete'])

    async def offer(self,profile,native=dict(PROFILE)):
        class Request:
            async def json(inner):return dict(sdp=sdp(),type='offer',frame_motion_profile=profile,motion_native_profile=native)
        response=await self.server.handle_offer(Request())
        return json.loads(response.text)

    async def test_actual_offer_ack_capture_worker_codec_and_inference_pipe(self):
        source,reader=PacketSource(10),Reader()
        peer=Peer();tx=SenderPacketBinding(peer,reader,source);self.links.append(tx)
        answer=await self.offer(tx.profile)
        remote=Channel()
        self.server.pc.datachannel(remote)
        tx.channel.other=remote
        self.assertTrue(tx.activate(answer['frame_motion_ack']))
        source.observe_odom(message(sec=1000,v=-.2,w=.1))
        reader.value=(723,time.monotonic(),image(5))
        deadline=time.monotonic()+3.
        while self.bridge.returned<1:
            if time.monotonic()>deadline:raise AssertionError(str(self.bridge.error or tx.error))
            await asyncio.sleep(.005)
        event=json.loads((self.directory/'motion_bridge_events.jsonl').read_text().splitlines()[0])
        self.assertEqual(event['result']['frame'],723)
        self.assertEqual(event['result']['session'],source.stream_id)
        self.assertEqual(event['source_candidate']['capture_sequence'],723)
        self.assertEqual(event['source_candidate']['odometry_observation']['linear_mps'],-.2)
        self.assertFalse(event['source_freshness_verified'])
        self.assertTrue(event['accepted_current_session_and_age'])
        raw=json.loads((self.directory/'synthetic_measurements.jsonl').read_text().splitlines()[0])
        self.assertEqual(raw['input_source'],'independent_frame_motion_packet_NOT_RTP')
        save_evidence('representative_bridge_event.json',event)
        save_evidence('representative_measurement.json',raw)
        control=Channel('control');self.server.pc.datachannel(control)
        self.assertIs(self.server.control_channel,control)
        telemetry=Channel('telemetry');self.server.pc.datachannel(telemetry)
        telemetry.handlers['message']('{"linear_x":0.0}')
        self.signals.telemetry_received.emit.assert_called_once_with(dict(linear_x=0.))

    async def test_missing_or_invalid_offer_keeps_control_but_no_rtp_fallback(self):
        response=await self.offer(None)
        self.assertNotIn('frame_motion_ack',response)
        self.assertFalse(self.bridge.valid_source)
        self.assertFalse(self.bridge.publish('a'*32,image(),0.,time.monotonic()))
        control=Channel('control');self.server.pc.datachannel(control)
        self.assertIs(self.server.control_channel,control)

    async def test_duplicate_packet_channel_retires_only_measurement(self):
        await self.offer(connection_profile(SENDER,STREAM,10))
        peer=self.server.pc;peer.datachannel(Channel());duplicate=Channel();peer.datachannel(duplicate)
        self.assertTrue(self.server.packet_binding.stop.is_set())
        self.assertFalse(self.bridge.valid_source)
        self.assertEqual(peer.connectionState,'connected')
        self.assertEqual(duplicate.readyState,'closed')

    async def test_old_peer_disconnect_cannot_retire_new_packet_session(self):
        await self.offer(connection_profile(SENDER,STREAM,10));old=self.server.pc
        await self.offer(connection_profile(SENDER,'c'*32,10))
        old.connectionState='closed'
        for fn in old.handlers['connectionstatechange']:await fn()
        self.assertTrue(self.bridge.valid_source)
        self.assertEqual(self.bridge.session,'c'*32)

    async def test_sender_decline_cap_mismatch_and_typed_ack_fail_closed(self):
        for ack in (None,dict(profile=connection_profile(SENDER,STREAM,10),message_bytes=1024)):
            peer,source=Peer(),PacketSource(10)
            tx=SenderPacketBinding(peer,Reader(),source);self.links.append(tx)
            self.assertFalse(tx.activate(ack))
            self.assertTrue(tx.closed)
            self.assertIsNone(tx.thread)
            self.assertEqual(peer.connectionState,'connected')

    async def test_false_flags_cannot_be_replaced_by_integer_in_ack(self):
        source=PacketSource(10);tx=SenderPacketBinding(Peer(),Reader(),source);self.links.append(tx)
        profile=tx.profile;profile['usable_for_ffb']=0
        self.assertFalse(tx.activate(dict(profile=profile,message_bytes=16384)))
