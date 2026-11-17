"""Explicit opt-in source/connection/recognition binding, never FFB authority.

Normal driver RTP/control stays separate. Public aiortc APIs only. No peer,
camera, ROS node or model is created by importing this module.
"""
import asyncio
import copy
import threading
import time
import uuid

from driver_frame_motion import SenderFrameMotion
from driver_frame_packet import checked_candidate,DecodedFramePacket
from driver_frame_packet_channel import (PROTOCOL, FramePacketChannelSender,
    FramePacketReceiveWorker, negotiated_message_bytes)
from driver_motion_bridge import DriverMotionBridge
from driver_motion_handoff import session_ok
from driver_motion_protocol import PROFILE as NATIVE_PROFILE, profile_matches
from driver_odometry_observation import OdometryObserver, clock_time
from theta_rtc_frames import NativeFrame,native_frame

PROFILE_SCHEMA='frame_motion_connection_v1'


def connection_profile(sender,stream,hz):
    if not session_ok(sender) or not session_ok(stream) or type(hz) is not int or hz not in (5,10):
        raise ValueError('explicit packet scope and 5/10Hz probe required')
    return dict(schema=PROFILE_SCHEMA,sender_id=sender,stream_id=stream,rate_hz=hz,
        message_cap=16384,receive_age_limit_sec=.2,physical_metric_verified=False,
        usable_for_ffb=False,published_to_ros=False)


def checked_profile(value):
    if type(value) is not dict:
        raise ValueError('explicit packet offer required')
    expected=connection_profile(value.get('sender_id'),value.get('stream_id'),value.get('rate_hz'))
    if (set(value)!=set(expected) or any(type(value[k]) is not type(v) or value[k]!=v for k,v in expected.items())):
        raise ValueError('exact non-controlling packet profile required')
    return copy.deepcopy(value)


def common_message_limit(local_sdp,remote_sdp):
    from aiortc.sdp import SessionDescription
    if any(type(s) is not str or len(s)>65536 for s in (local_sdp,remote_sdp)):
        raise ValueError('bounded applied descriptions required')
    mids=[]
    for sdp in (local_sdp,remote_sdp):
        media=[m for m in SessionDescription.parse(sdp).media if m.kind=='application']
        if len(media)!=1:
            raise ValueError('one explicitly scoped SCTP application required')
        mids.append(media[0].rtp.muxId)
    if mids[0]!=mids[1]:
        raise ValueError('applied SDP MID differs')
    local=negotiated_message_bytes(local_sdp,mid=mids[0],local_max_message_size=0)
    return negotiated_message_bytes(remote_sdp,mid=mids[0],local_max_message_size=local)


def add_sender_arguments(parser):
    parser.add_argument('--frame-motion-packets',action='store_true',help='OFF by default; independent experimental packet input, requires motion-native')
    parser.add_argument('--frame-packet-hz',type=int,choices=(5,10),default=10,help='probe rate, NOT FFB update-rate approval')


def validate_sender_args(args):
    if getattr(args,'frame_motion_packets',False) and (not getattr(args,'motion_native',False)
            or (args.cam_width,args.cam_height)!=(1280,720) or args.mock_camera):
        raise ValueError('frame packets need the same real native reader; no extra camera/fallback')


class PacketSource:
    def __init__(self,rate_hz,*,clock=time.monotonic):
        self.clock=clock
        self.observer=OdometryObserver(clock=clock)
        self.stream_id=uuid.uuid4().hex
        self.profile=connection_profile(self.observer.sender_id,self.stream_id,rate_hz)
        self.history=SenderFrameMotion(sender_id=self.observer.sender_id,stream_id=self.stream_id,
            capacity=128,max_callback_lag_sec=.1,max_progress_lag_sec=.1,
            max_capture_wait_sec=.2,motion_frame_id='base_footprint')
        self.last_capture=self.origin=None
        self.last_seen_capture=None
        self.error=None;self.closed=False

    def observe_odom(self,message):
        if self.closed:return
        try:
            self.observer.observe(message)
            if not self.history.offer(self.observer.snapshot()):
                # Busy offer is already a history barrier, permanent faults stay faults.
                if self.history.fault:self.error=self.history.fault
        except Exception as error:
            self.error=type(error).__name__+': '+str(error)[:160]

    def candidate(self,sequence,captured):
        if self.error or self.closed:
            raise ValueError(self.error or 'packet source closed')
        if (not clock_time(captured) or self.last_seen_capture is not None and captured<=self.last_seen_capture):
            raise ValueError('capture clock/order reversed')
        self.last_seen_capture=captured
        if self.origin is None:self.origin=captured
        if self.last_capture is not None and captured-self.last_capture<1/self.profile['rate_hz']:
            return None
        self.last_capture=captured
        return self.history.associate(capture_sequence=sequence,captured_at_sec=captured,
            media_pts=round((captured-self.origin)*90000),associated_at_sec=self.clock())


class SenderPacketBinding:
    """One offered connection; channel operations run on the caller's RTC loop."""
    def __init__(self,peer,reader,source):
        self.peer,self.reader,self.source=peer,reader,source
        self.channel=peer.createDataChannel(PROTOCOL,ordered=False,maxRetransmits=0,protocol=PROTOCOL)
        self.tx=self.task=self.thread=None
        self.stop=threading.Event();self.error=None
        self.closed=False

    @property
    def profile(self):return copy.deepcopy(self.source.profile)

    def activate(self,ack):
        try:
            if self.closed or self.tx is not None:raise ValueError('packet binding already activated/retired')
            cap=common_message_limit(self.peer.localDescription.sdp,self.peer.remoteDescription.sdp)
            if (type(ack) is not dict or set(ack)!= {'profile','message_bytes'}
                    or checked_profile(ack['profile'])!=self.profile
                    or type(ack['message_bytes']) is not int or ack['message_bytes']!=cap):
                raise ValueError('receiver did not explicitly accept this packet scope/cap')
            self.tx=FramePacketChannelSender(self.channel,sender_id=self.profile['sender_id'],
                stream_id=self.profile['stream_id'],message_bytes=cap,
                max_capture_age_sec=.2,max_buffered_bytes=32768)
            self.task=asyncio.create_task(self._pump())
            self.thread=threading.Thread(target=self._produce,name='packet-source-reader',daemon=True)
            self.thread.start()
            return True
        except Exception as error:
            self.error=type(error).__name__+': '+str(error)[:160]
            self.request_stop()
            return False

    def _produce(self):
        sequence=0
        try:
            while not self.stop.is_set():
                value=self.reader.after(sequence)
                if value is not None:
                    sequence,captured,image=value
                    candidate=self.source.candidate(sequence,captured)
                    if candidate is not None and not self.tx.submit(image,candidate):
                        raise ValueError('packet encoder submission failed')
                self.stop.wait(.005)
        except Exception as error:
            self.error=type(error).__name__+': '+str(error)[:160]
            self.stop.set()  # Owner pump performs channel close.

    async def _pump(self):
        try:
            while not self.stop.is_set():
                if self.peer.connectionState in ('failed','closed','disconnected'):
                    break
                self.tx.pump(budget=8)
                if self.tx.closed:
                    self.error=self.tx.error
                    break
                await asyncio.sleep(.005)
        finally:self.request_stop()

    def request_stop(self):
        self.stop.set();self.closed=True
        self.source.closed=True
        try:
            if self.tx is not None:self.tx.close(timeout_sec=0)
            else:self.channel.close()
        except Exception as error:self.error=self.error or str(error)[:160]

    async def close(self):
        self.request_stop()
        if self.task is not None:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
        # No new executor queue or non-daemon shutdown worker. Codec threads
        # already have done/retirement flags; poll those within a finite span.
        deadline=asyncio.get_running_loop().time()+.5
        while True:
            done=(self.thread is None or not self.thread.is_alive()) and (self.tx is None or self.tx.worker.done.is_set())
            if done or asyncio.get_running_loop().time()>=deadline:return done
            await asyncio.sleep(.005)


class PacketMotionBridge(DriverMotionBridge):
    """Reuses ONE old inference pipe, never publishes RTP or local odom defaults."""
    packet_input=True
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.packet_latest=self.packet_inflight=None
        self.packet_sender_id=None

    def begin_packet(self,profile):
        profile=checked_profile(profile)
        super().begin(profile['stream_id'],dict(NATIVE_PROFILE))
        with self.lock:
            self.packet_sender_id=profile['sender_id'];self.packet_latest=None

    def publish(self,*args):
        return False  # Never fall back to decoded RTP or pair it by arrival time.

    def publish_packet(self,packet):
        value=checked_candidate(packet.candidate)
        native_frame(packet.image)
        if (type(packet.packet_sha256) is not str or len(packet.packet_sha256)!=64
                or any(c not in '0123456789abcdef' for c in packet.packet_sha256)):
            raise ValueError('validated packet digest required')
        if not self.lock.acquire(blocking=False):
            self.dropped+=1;return False
        try:
            if (self.stop_event.is_set() or not self.valid_source or value['stream_id']!=self.session
                    or value['sender_id']!=self.packet_sender_id):return False
            if (packet.image.flags.writeable or not 0<=self.clock()-packet.received_at_sec<=.2
                    or value['capture_sequence']<=self.sequence):
                self.latest=self.result=self.packet_latest=None
                return False
            self.sequence=value['capture_sequence']
            self.latest=NativeFrame(self.session,self.sequence,value['sender_media_pts']/90000,
                packet.received_at_sec,packet.image)
            self.packet_latest=DecodedFramePacket(value,packet.image,packet.received_at_sec,packet.packet_sha256)
            self.reason='waiting_for_current_packet_range'
            return True
        finally:self.lock.release()

    def _next_frame(self,last_key):
        while not self.stop_event.is_set():
            if self.process is not None and self.process.poll() is not None:raise EOFError('packet inference child exited')
            with self.lock:
                if self.error:return None
                frame=self.latest if self.valid_source else None
                if (frame is not None and (frame.session,frame.sequence)!=last_key
                        and 0<=self.clock()-frame.received_at<=.2):
                    self.packet_inflight=self.packet_latest
                    return frame
            self.stop_event.wait(.005)
        return None

    def _accept_result(self,value):
        packet=self.packet_inflight
        return (super()._accept_result(value) and packet is not None
            and packet.candidate['stream_id']==value['session']
            and packet.candidate['capture_sequence']==value['frame']
            and packet.received_at_sec==value['source_time_sec']
            and 0<=self.clock()-packet.received_at_sec<=.2)

    def _result_event(self,value,accepted):
        packet=self.packet_inflight
        if (packet is None or packet.candidate['stream_id']!=value['session']
                or packet.candidate['capture_sequence']!=value['frame']
                or packet.received_at_sec!=value['source_time_sec']):
            raise ValueError('packet result lost its exact inflight source')
        return dict(result=value,accepted_current_session_and_age=accepted,
            source_candidate=copy.deepcopy(packet.candidate),packet_sha256=packet.packet_sha256,
            input_source='independent_frame_motion_packet_NOT_RTP',original_RTP_frame_matched=False,
            source_freshness_verified=False,physical_metric_verified=False,usable_for_ffb=False,published_to_ros=False)

    def snapshot(self,now=None):
        now=self.clock() if now is None else now
        result=super().snapshot(now)
        if 'result' in result and not 0<=now-result['result']['source_time_sec']<=.2:
            return dict(available=False,reason='packet_receive_age_exceeded',input_source='independent_packet_NOT_displayed_RTP')
        result['input_source']='independent_packet_NOT_displayed_RTP'
        return result


class ReceiverPacketBinding:
    def __init__(self,peer,bridge,profile,native_profile):
        if not profile_matches(native_profile):raise ValueError('packet mode requires native sender profile')
        self.profile=checked_profile(profile)
        self.peer,self.bridge=peer,bridge
        self.rx=self.channel=self.thread=None
        self.stop=threading.Event();self.error=None
        self.cap=None
        bridge.begin_packet(self.profile)

    def configure(self):
        if self.stop.is_set() or self.rx is not None:raise ValueError('packet connection already configured/retired')
        self.cap=common_message_limit(self.peer.localDescription.sdp,self.peer.remoteDescription.sdp)
        self.rx=FramePacketReceiveWorker(sender_id=self.profile['sender_id'],stream_id=self.profile['stream_id'],
            message_bytes=self.cap,timeout_sec=.2)
        self.thread=threading.Thread(target=self._consume,name='packet-recognition-tap',daemon=True)
        self.thread.start()
        return dict(profile=copy.deepcopy(self.profile),message_bytes=self.cap)

    def attach(self,channel):
        if channel.label!=PROTOCOL:return False
        try:
            if (self.stop.is_set() or self.channel is not None or channel.protocol!=PROTOCOL
                    or channel.ordered is not False or type(channel.maxRetransmits) is not int
                    or channel.maxRetransmits!=0 or channel.maxPacketLifeTime is not None):
                raise ValueError('duplicate or incompatible packet channel')
            self.channel=channel
            @channel.on('message')
            def message(value):
                if self.rx is None or not self.rx.offer_message(value):self.request_stop('packet_ingress_rejected')
            @channel.on('close')
            def closed():self.request_stop('packet_channel_closed')
        except Exception as error:
            self.request_stop(str(error));channel.close()
        return True

    def _consume(self):
        try:
            while not self.stop.is_set():
                if self.bridge.stop_event.is_set():
                    self.request_stop('packet_inference_stopped');break
                if self.rx.retired.is_set():raise ValueError('packet decoder retired: '+str(self.rx.error))
                packet=self.rx.take()
                if packet is not None:self.bridge.publish_packet(packet)
                self.stop.wait(.005)
        except Exception as error:self.request_stop(str(error))

    def request_stop(self,reason='packet_connection_ended'):
        self.error=self.error or reason
        self.stop.set()
        self.bridge.end(self.profile['stream_id'],reason)
        if self.rx is not None:self.rx.close(timeout_sec=0)

    def close(self):
        self.request_stop()
        if self.thread is not None and self.thread is not threading.current_thread():self.thread.join(.25)
        done=self.rx is None or self.rx.close(timeout_sec=.25)
        return done and (self.thread is None or not self.thread.is_alive())
