"""Offline worker-owned PNG pacing/backpressure policy, no channel/network IO.

One progressing packet plus one latest pending, fixed existing PNG limits.
offer does full PNG validation: NEVER use it on a live RTC/UI callback.
Handing off a fragment neither proves delivery nor recalls old transport bytes.
"""
from dataclasses import dataclass
import hashlib

from driver_lossless_frame_packet import unpack_packet, DEADLINE_SEC
from driver_lossless_frame_fragments import HEADER, MAGIC, BODY_BYTES, MESSAGE_BYTES
from driver_motion_handoff import session_ok
from driver_odometry_observation import clock_time


@dataclass(frozen=True)
class _Packet:
    wire: bytes
    sequence: int
    pts: int
    captured_at_sec: float
    associated_at_sec: float
    digest: bytes

    @property
    def count(self):
        return (len(self.wire)+BODY_BYTES-1)//BODY_BYTES


class LosslessLatestSender:
    """Single owner; sender now and candidate times MUST share one clock.

    New pending input does not interrupt the active packet every frame. An
    expired active packet is dropped even when blocked by a full channel.
    Invalid updates clear both retained slots, never rescue an older packet.
    """
    def __init__(self, *, sender_id, stream_id, max_buffered_bytes):
        if (not session_ok(sender_id) or not session_ok(stream_id)
                or type(max_buffered_bytes) is not int
                or not MESSAGE_BYTES <= max_buffered_bytes <= 1024**2):
            raise ValueError('explicit scope and 16KiB..1MiB channel bound required')
        self.sender_id, self.stream_id = sender_id, stream_id
        self.sender, self.stream = bytes.fromhex(sender_id), bytes.fromhex(stream_id)
        self.max_buffered_bytes = max_buffered_bytes
        self.active = self.pending = self.last_time = self.last_source = None
        self.index = self.high_sequence = 0
        self.closed = False
        self.peak_retained_bytes = self.peak_slots = 0
        self.max_handoff_capture_age_sec = 0.
        self.counts = dict(offered=0, admitted=0, pending_replaced=0, expired=0,
            invalid=0, held_for_buffer=0, channel_unavailable=0,
            fragments_handed_off=0, packets_handed_off=0)

    @property
    def retained_bytes(self):
        return sum(len(p.wire) for p in (self.active,self.pending) if p is not None)

    def _clear(self):
        self.active = self.pending = None
        self.index = 0

    def _tick(self, now):
        if (self.closed or not clock_time(now)
                or self.last_time is not None and now < self.last_time):
            self.closed = True
            self._clear()
            return False
        self.last_time = now
        for slot in ('active','pending'):
            value = getattr(self,slot)
            if value is not None and now-value.captured_at_sec > DEADLINE_SEC:
                self.counts['expired'] += 1
                setattr(self,slot,None)
                if slot == 'active':self.index = 0
        return True

    def offer(self, wire, *, now):
        """Validate synchronously in a worker; now is POST-validation local time.

        Offline owner supplies the modeled post-validation time. A future live
        adapter must timestamp after actual work, not reuse its callback entry.
        """
        self.counts['offered'] += 1
        if not self._tick(now):return False
        try:
            value = unpack_packet(wire)[0]['candidate']
            source = tuple(value[k] for k in ('sender_media_pts','captured_at_sec','associated_at_sec'))
            if (value['sender_id'] != self.sender_id or value['stream_id'] != self.stream_id
                    or not 0 < value['capture_sequence'] < 2**64
                    or value['capture_sequence'] <= self.high_sequence
                    or now < source[2]
                    or self.last_source is not None and (source[0] <= self.last_source[0]
                        or source[1] <= self.last_source[1] or source[2] < self.last_source[2])):
                raise ValueError('ordered PNG source in same sender clock required')
            self.high_sequence, self.last_source = value['capture_sequence'], source
            if now-source[1] > DEADLINE_SEC:
                self.counts['expired'] += 1
                self._clear()
                return False
            packet = _Packet(wire,value['capture_sequence'],*source,hashlib.sha256(wire).digest())
            if self.active is None:
                # A pending surviving expiration of active remains newer than
                # active but older than this just-validated offer.
                if self.pending is not None:self.counts['pending_replaced'] += 1
                self.active, self.pending, self.index = packet, None, 0
            else:
                if self.pending is not None:self.counts['pending_replaced'] += 1
                self.pending = packet
            self.peak_retained_bytes = max(self.peak_retained_bytes,self.retained_bytes)
            self.peak_slots = max(self.peak_slots,sum(p is not None for p in (self.active,self.pending)))
            self.counts['admitted'] += 1
            return True
        except (ValueError,TypeError,KeyError,OverflowError):
            self.counts['invalid'] += 1
            self._clear()
            return False

    def next_fragment(self, *, now, buffered_amount, channel_open):
        if not self._tick(now):return None
        if (type(buffered_amount) is not int or not 0 <= buffered_amount < 2**63
                or type(channel_open) is not bool):
            self.counts['invalid'] += 1
            self._clear()
            return None
        if not channel_open:
            self.counts['channel_unavailable'] += 1
            self._clear()
            return None
        if self.active is None and self.pending is not None:
            self.active, self.pending, self.index = self.pending, None, 0
        value = self.active
        if value is None:return None
        offset = self.index*BODY_BYTES
        size = HEADER.size+min(BODY_BYTES,len(value.wire)-offset)
        if buffered_amount+size > self.max_buffered_bytes:
            self.counts['held_for_buffer'] += 1
            return None
        message = HEADER.pack(MAGIC,self.sender,self.stream,value.sequence,len(value.wire),
            self.index,value.count,value.digest)+value.wire[offset:offset+BODY_BYTES]
        self.max_handoff_capture_age_sec = max(self.max_handoff_capture_age_sec,now-value.captured_at_sec)
        self.counts['fragments_handed_off'] += 1
        self.index += 1
        if self.index == value.count:
            self.counts['packets_handed_off'] += 1
            self.active, self.index = None, 0
        return message

    def poll(self, now):
        self._tick(now)

    def close(self):
        self.closed = True
        self._clear()
