"""Deterministic finite virtual link; no sockets, sleeping, GPU or file output.

Simulation oracle times are NOT available to production peers. Separate local
clock offsets are passed to sender and receiver; neither subtracts peer clocks.
Pre-encoded saved payloads exercise actual PNG framing/scheduler/reassembly.
CPU service durations are explicit model inputs, not newly measured load.
"""
from collections import deque
from dataclasses import dataclass
import hashlib
import heapq
import math

from driver_frame_motion import SenderFrameMotion, FLAGS
import driver_lossless_frame_packet as packet
import driver_lossless_frame_fragments as flow
from driver_lossless_frame_sender import LosslessLatestSender

SCOPE=dict(sender_id='a'*32,stream_id='b'*32)
SENDER_OFFSET=1000.
RECEIVER_OFFSET=5000.
BUFFER_BYTES=32768
FLIGHT_CAP=8*packet.MAX_PACKET
TICK_SEC=.001


@dataclass(frozen=True)
class Template:
    name: str
    header: dict
    payload: bytes
    sender_ms: float
    receiver_ms: float


def wire_for(template,sequence,captured_at,hz):
    source=SenderFrameMotion(**SCOPE,capacity=4,max_callback_lag_sec=.1,
        max_progress_lag_sec=.1,max_capture_wait_sec=.2,motion_frame_id='base_footprint')
    candidate=source.associate(capture_sequence=sequence,captured_at_sec=SENDER_OFFSET+captured_at,
        associated_at_sec=SENDER_OFFSET+captured_at,media_pts=(sequence-1)*90000//hz)
    header=dict(template.header,candidate=candidate,encoded_pts=candidate['sender_media_pts'])
    return packet._wrap(header,template.payload)


def simulate(templates,*,name,hz,rate_mbps,duration_sec=4.,stall=None,
             loss_every=0,receiver_scale=1.,sender_scale=1.,transit_delay_sec=0.):
    if (not 1<=len(templates)<=4 or hz not in (5,10) or rate_mbps not in (15,30,100)
            or not 0<duration_sec<=10 or receiver_scale<=0 or sender_scale<=0
            or not 0<=transit_delay_sec<=1 or type(loss_every) is not int or loss_every<0):
        raise ValueError('bounded explicit virtual scenario required')
    if stall is not None and not (0<=stall[0]<stall[1]<=duration_sec):
        raise ValueError('bounded stall interval required')
    if any(not math.isfinite(v) or v<=0 for t in templates for v in (t.sender_ms,t.receiver_ms)):
        raise ValueError('finite positive explicit CPU model costs required')
    count=int(duration_sec*hz)
    if count!=duration_sec*hz:raise ValueError('integral capture count required')
    sender=LosslessLatestSender(**SCOPE,max_buffered_bytes=BUFFER_BYTES)
    assembler=flow.LosslessReassembler(**SCOPE)
    receiver=packet.LosslessPacketReceiver(**SCOPE)
    queue=deque();deliveries=[]
    buffer_amount=0.;flight_bytes=0
    raw_active=raw_pending=decode_active=decode_pending=None
    counts=dict(captured=0,raw_pending_replaced=0,encoded=0,decode_pending_replaced=0,
        decode_expired_before_start=0,decode_rejected_or_expired=0,consumed=0,
        fragment_drops=0,flight_overflow_drops=0)
    peaks=dict(channel_buffer_bytes=0,channel_retained_message_bytes=0,flight_bytes=0,
        raw_slots=0,decode_slots=0,decode_retained_bytes=0)
    captures={};trace=[];handed=0;sequence=0

    def start_raw(value,at):
        return dict(value,ready=at+value['template'].sender_ms*sender_scale/1000)

    def start_decode(value,at):
        if RECEIVER_OFFSET+at>value.first_received_at_sec+packet.DEADLINE_SEC:
            counts['decode_expired_before_start']+=1
            return None
        seq=flow_header_sequence(value.wire)
        template=captures[seq]['template']
        return dict(arrival=value,sequence=seq,start=at,
                    ready=at+template.receiver_ms*receiver_scale/1000)

    for step in range(math.ceil((duration_sec+2.)/TICK_SEC)+1):
        at=step*TICK_SEC
        if step%int(1/(hz*TICK_SEC))==0 and sequence<count:
            sequence+=1
            value=dict(sequence=sequence,captured=at,template=templates[(sequence-1)%len(templates)])
            captures[sequence]=value;counts['captured']+=1
            if raw_active is None:raw_active=start_raw(value,at)
            else:
                if raw_pending is not None:counts['raw_pending_replaced']+=1
                raw_pending=value
        if raw_active is not None and at>=raw_active['ready']:
            value=raw_active
            wire=wire_for(value['template'],value['sequence'],value['captured'],hz)
            sender.offer(wire,now=SENDER_OFFSET+at)
            counts['encoded']+=1
            raw_active=None
            if raw_pending is not None:
                raw_active=start_raw(raw_pending,at);raw_pending=None
        if decode_active is not None and at>=decode_active['ready']:
            value=decode_active;arrival=value['arrival']
            times=iter((RECEIVER_OFFSET+value['start'],RECEIVER_OFFSET+at))
            accepted=receiver.accept(arrival.wire,first_received_at_sec=arrival.first_received_at_sec,now=times.__next__)
            pair=receiver.take(RECEIVER_OFFSET+at) if accepted else None
            if pair is None:counts['decode_rejected_or_expired']+=1
            else:
                seq=pair.candidate['capture_sequence'];original=captures[seq]
                if (seq!=value['sequence'] or pair.candidate['local_pair_available']
                        or any(pair.candidate[k] is not False for k in FLAGS)
                        or hashlib.sha256(pair.image.tobytes()).hexdigest()!=original['template'].header['bgr_sha256']):
                    raise ValueError('simulated transport changed image/candidate/authority')
                counts['consumed']+=1
                trace.append(dict(scenario=name,sequence=seq,image=original['template'].name,
                    capture_oracle_sec=original['captured'],take_oracle_sec=at,
                    oracle_capture_to_take_ms=(at-original['captured'])*1000,
                    receiver_local_first_to_take_ms=(RECEIVER_OFFSET+at-arrival.first_received_at_sec)*1000,
                    exact_pixels=True,local_pair_available=False,source_freshness_verified=False,
                    physical_metric_verified=False,controlling_distance=False,usable_for_ffb=False,published_to_ros=False))
            decode_active=None
            if decode_pending is not None:
                decode_active=start_decode(decode_pending,at);decode_pending=None
        # The production policy is driven only by sender-local time/buffer size.
        sender.poll(SENDER_OFFSET+at)
        for _ in range(2):
            message=sender.next_fragment(now=SENDER_OFFSET+at,
                buffered_amount=math.ceil(buffer_amount),channel_open=True)
            if message is None:break
            queue.append([message,float(len(message))]);buffer_amount+=len(message)
            peaks['channel_buffer_bytes']=max(peaks['channel_buffer_bytes'],math.ceil(buffer_amount))
            peaks['channel_retained_message_bytes']=max(peaks['channel_retained_message_bytes'],sum(len(m[0]) for m in queue))
        # Ideal fluid drain; completion is rounded UP to a 1ms model boundary.
        stalled=stall is not None and stall[0]<=at<stall[1]
        credit=0. if stalled else rate_mbps*1e6/8*TICK_SEC
        while queue and credit>0:
            item=queue[0];used=min(credit,item[1]);credit-=used;item[1]-=used;buffer_amount-=used
            if item[1]>1e-8:break
            message,_=queue.popleft();handed+=1
            if loss_every and handed%loss_every==0:
                counts['fragment_drops']+=1
            elif flight_bytes+len(message)>FLIGHT_CAP:
                counts['flight_overflow_drops']+=1
            else:
                heapq.heappush(deliveries,(at+TICK_SEC+transit_delay_sec,handed,message))
                flight_bytes+=len(message)
                peaks['flight_bytes']=max(peaks['flight_bytes'],flight_bytes)
        buffer_amount=max(0.,buffer_amount)
        while deliveries and deliveries[0][0]<=at:
            _,_,message=heapq.heappop(deliveries);flight_bytes-=len(message)
            arrival=assembler.accept(message,RECEIVER_OFFSET+at)
            if arrival is not None:
                if decode_active is None:decode_active=start_decode(arrival,at)
                else:
                    if decode_pending is not None:counts['decode_pending_replaced']+=1
                    decode_pending=arrival
        assembler.poll(RECEIVER_OFFSET+at)
        peaks['raw_slots']=max(peaks['raw_slots'],int(raw_active is not None)+int(raw_pending is not None))
        peaks['decode_slots']=max(peaks['decode_slots'],int(decode_active is not None)+int(decode_pending is not None))
        peaks['decode_retained_bytes']=max(peaks['decode_retained_bytes'],
            (len(decode_active['arrival'].wire) if decode_active else 0)+(len(decode_pending.wire) if decode_pending else 0))
    if (queue or deliveries or raw_active or raw_pending or decode_active or decode_pending
            or buffer_amount>1e-8 or flight_bytes):
        raise ValueError('finite drain horizon insufficient; do not hide pending data')
    sender.poll(SENDER_OFFSET+duration_sec+2.)
    if (sender.retained_bytes or assembler.active is not None or sender.peak_slots>2
            or sender.peak_retained_bytes>2*packet.MAX_PACKET
            or sender.max_handoff_capture_age_sec>packet.DEADLINE_SEC
            or peaks['channel_buffer_bytes']>BUFFER_BYTES
            or peaks['decode_slots']>2 or peaks['raw_slots']>2
            or any(r['receiver_local_first_to_take_ms']>200.000001 for r in trace)):
        raise ValueError('bounded slot/byte/local deadline invariant violated')
    source_ages=[r['oracle_capture_to_take_ms'] for r in trace]
    summary=dict(name=name,hz=hz,ideal_rate_Mbps=rate_mbps,capture_duration_sec=duration_sec,
        stall_sec=stall,loss_every_nth_fragment=loss_every,sender_cpu_scale=sender_scale,
        receiver_cpu_scale=receiver_scale,transit_delay_sec=transit_delay_sec,
        counts=counts,consumed_fraction=counts['consumed']/counts['captured'],sender=sender.counts,
        reassembler=assembler.counts,peaks=dict(peaks,sender_slots=sender.peak_slots,
            sender_retained_bytes=sender.peak_retained_bytes,reassembly_bytes=assembler.peak_retained_bytes),
        max_sender_capture_age_at_handoff_ms=sender.max_handoff_capture_age_sec*1000,
        max_receiver_local_first_to_take_ms=max((r['receiver_local_first_to_take_ms'] for r in trace),default=None),
        oracle_max_capture_to_take_ms=max(source_ages,default=None),
        oracle_over_200ms_consumed=sum(v>200 for v in source_ages),
        real_clock_alignment_used=False,source_freshness_verified=False,
        actual_continuous_encoding_measured=False,real_network_measured=False,
        physical_metric_verified=False,controlling_distance=False,usable_for_ffb=False,published_to_ros=False)
    sender.close();assembler.close();receiver.close()
    return summary,trace


def flow_header_sequence(wire):
    # Already validated by the PNG reassembler; same frozen header validator.
    return packet.unpack_packet(wire)[0]['candidate']['capture_sequence']
