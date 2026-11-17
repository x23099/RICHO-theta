"""Local bounded fragmentation and latest-pending scheduling; no live IO.

All methods belong to one worker/event owner (NOT thread-safe). Codec work and
packet validation are NOT for RTC callbacks. Hand-off is not successful send.
Local deadlines are not source freshness or cross-PC synchronization proofs.
"""
from dataclasses import dataclass
import hashlib
import struct

from driver_frame_packet import MAX_HEADER, MAX_PAYLOAD, PREFIX, unpack_packet
from driver_motion_handoff import session_ok
from driver_odometry_observation import clock_time

MAGIC = b'THFRAG1\x00'
HEADER = struct.Struct('!8s16s16sQIHH32s')
MAX_PACKET = PREFIX.size+MAX_HEADER+MAX_PAYLOAD


def message_limit(value):
    if type(value) is not int or not 1024 <= value <= 16384:
        raise ValueError('explicit message cap within 1024..16384 required')
    return value


def age_limit(value):
    if type(value) not in (int, float) or not clock_time(value) or not 0 < value <= 1:
        raise ValueError('explicit local age limit within (0,1] required')
    return value


@dataclass(frozen=True)
class FragmentPlan:
    wire: bytes
    sender_id: str
    stream_id: str
    sequence: int
    captured_at_sec: float
    associated_at_sec: float
    message_bytes: int
    digest: bytes

    @property
    def body_bytes(self):
        return self.message_bytes-HEADER.size

    @property
    def count(self):
        return (len(self.wire)+self.body_bytes-1)//self.body_bytes

    def fragment(self, index):
        if type(index) is not int or not 0 <= index < self.count:
            raise ValueError('valid bounded fragment index required')
        return HEADER.pack(MAGIC, bytes.fromhex(self.sender_id), bytes.fromhex(self.stream_id),
            self.sequence, len(self.wire), index, self.count, self.digest)+self.wire[
                index*self.body_bytes:(index+1)*self.body_bytes]


def fragment_plan(wire, *, message_bytes):
    message_limit(message_bytes)
    header, _ = unpack_packet(wire)
    value = header['candidate']
    return FragmentPlan(wire, value['sender_id'], value['stream_id'], value['capture_sequence'],
        value['captured_at_sec'], value['associated_at_sec'], message_bytes, hashlib.sha256(wire).digest())


@dataclass(frozen=True)
class CompletedPacket:
    wire: bytes
    first_received_at_sec: float
    completed_at_sec: float
    deadline_sec: float
    sequence: int


class PacketReassembler:
    """One bounded active/completed packet; old sequence cannot revive it."""
    def __init__(self, *, sender_id, stream_id, message_bytes, timeout_sec):
        if not session_ok(sender_id) or not session_ok(stream_id):
            raise ValueError('explicit expected connection scope required')
        self.sender_id, self.stream_id = bytes.fromhex(sender_id), bytes.fromhex(stream_id)
        self.message_bytes, self.timeout = message_limit(message_bytes), age_limit(timeout_sec)
        self.high_sequence = 0
        self.last_time = self.active = self.complete = None
        self.closed = False
        self.counts = dict(completed=0, delivered=0, replaced=0, expired=0, stale=0,
            foreign=0, duplicates=0, invalid=0, conflicts=0)
        self.peak_retained_bytes = 0

    @property
    def retained_bytes(self):
        return len(self.active['buffer']) if self.active is not None else len(self.complete.wire) if self.complete else 0

    def _clear(self):
        self.active = self.complete = None

    def _tick(self, now):
        if (self.closed or not clock_time(now)
                or self.last_time is not None and now < self.last_time):
            self.closed = True
            self._clear()
            return False
        self.last_time = now
        start = self.active['start'] if self.active is not None else self.complete.first_received_at_sec if self.complete else None
        if start is not None and now-start > self.timeout:
            self.counts['expired'] += 1
            self._clear()
        return True

    def accept(self, message, *, received_at_sec):
        if not self._tick(received_at_sec):
            return False
        try:
            if type(message) is not bytes or not HEADER.size < len(message) <= self.message_bytes:
                raise ValueError('bounded binary fragment required')
            magic, sender, stream, seq, total, index, count, digest = HEADER.unpack_from(message)
            body_size = self.message_bytes-HEADER.size
            expected_count = (total+body_size-1)//body_size
            expected_size = body_size if index+1 < count else total-index*body_size
            if (magic != MAGIC or not 0 < seq < 2**63 or not PREFIX.size+10 <= total <= MAX_PACKET
                    or count != expected_count or not 0 <= index < count
                    or len(message)-HEADER.size != expected_size):
                raise ValueError('bounded canonical fragment layout required')
            if (sender, stream) != (self.sender_id, self.stream_id):
                self.counts['foreign'] += 1
                return False  # Retired peer cannot alter a current peer's assembly.
            if seq < self.high_sequence or seq == self.high_sequence and self.active is None:
                self.counts['stale'] += 1
                return False
            if seq > self.high_sequence:
                if self.active is not None or self.complete is not None:
                    self.counts['replaced'] += 1
                self._clear()
                self.high_sequence = seq
                self.active = dict(total=total, count=count, digest=digest, start=received_at_sec,
                                   buffer=bytearray(total), seen=set())
                self.peak_retained_bytes = max(self.peak_retained_bytes, total)
            current = self.active
            if (total, count, digest) != (current['total'], current['count'], current['digest']):
                self.counts['conflicts'] += 1
                raise ValueError('fragment identity changed within a packet')
            start, body = index*body_size, message[HEADER.size:]
            if index in current['seen']:
                if current['buffer'][start:start+len(body)] != body:
                    self.counts['conflicts'] += 1
                    raise ValueError('conflicting duplicate fragment')
                self.counts['duplicates'] += 1
                return False  # Never extend the initial receive deadline.
            current['buffer'][start:start+len(body)] = body
            current['seen'].add(index)
            if len(current['seen']) < count:
                return False
            wire = bytes(current['buffer'])
            if hashlib.sha256(wire).digest() != digest:
                raise ValueError('reassembled packet digest mismatch')
            head, _ = unpack_packet(wire)  # Worker-side JSON/integrity only, no decode.
            value = head['candidate']
            if (bytes.fromhex(value['sender_id']), bytes.fromhex(value['stream_id']), value['capture_sequence']) != (sender, stream, seq):
                raise ValueError('fragment wrapper and inner source packet differ')
            self.complete = CompletedPacket(wire, current['start'], received_at_sec,
                current['start']+self.timeout, seq)
            self.active = None
            self.counts['completed'] += 1
            return True
        except (ValueError, TypeError, KeyError, struct.error):
            self.counts['invalid'] += 1
            self._clear()
            return False

    def take(self, now):
        if not self._tick(now) or self.complete is None:
            return None
        packet, self.complete = self.complete, None
        self.counts['delivered'] += 1
        return packet

    def close(self):
        self.closed = True
        self._clear()


class LatestPacketSender:
    """One in-progress packet + one latest pending; caller performs actual send.

    A new pending packet does not repeatedly interrupt a progressing packet.
    Source capture age uses the SAME sender monotonic clock as the candidate.
    Already handed-off transport bytes cannot be recalled by this scheduler.
    """
    def __init__(self, *, sender_id, stream_id, message_bytes, max_capture_age_sec, max_buffered_bytes):
        if not session_ok(sender_id) or not session_ok(stream_id):
            raise ValueError('explicit sender connection scope required')
        self.sender_id, self.stream_id = sender_id, stream_id
        self.message_bytes, self.max_age = message_limit(message_bytes), age_limit(max_capture_age_sec)
        if type(max_buffered_bytes) is not int or not message_bytes <= max_buffered_bytes <= 1024**2:
            raise ValueError('bounded channel byte threshold required')
        self.max_buffered = max_buffered_bytes
        self.active = self.pending = self.last_time = None
        self.index = self.high_sequence = 0
        self.closed = False
        self.counts = dict(offered=0, pending_replaced=0, expired=0, held_for_buffer=0,
            chunks_handed_off=0, packets_handed_off=0, invalid=0, channel_unavailable=0)
        self.peak_retained_bytes = 0

    @property
    def retained_bytes(self):
        return sum(len(p.wire) for p in (self.active, self.pending) if p is not None)

    def _clear(self):
        self.active = self.pending = None
        self.index = 0

    def _tick(self, now):
        if self.closed or not clock_time(now) or self.last_time is not None and now < self.last_time:
            self.closed = True
            self._clear()
            return False
        self.last_time = now
        return True

    def offer(self, wire, *, now):
        try:
            plan = fragment_plan(wire, message_bytes=self.message_bytes)
        except (ValueError, TypeError, KeyError, OverflowError):
            self.counts['offered'] += 1
            self._tick(now)
            self.counts['invalid'] += 1
            self._clear()
            return False
        return self._offer_prepared(plan, now=now)

    def _offer_prepared(self, plan, *, now):
        """Internal worker handoff only; never accept caller-created plans.

        The channel adapter constructs this immutable plan using fragment_plan
        in its codec worker. Avoid JSON/hash/codec work on the RTC owner.
        """
        self.counts['offered'] += 1
        if not self._tick(now):
            return False
        try:
            if (type(plan) is not FragmentPlan or plan.message_bytes != self.message_bytes
                    or (plan.sender_id, plan.stream_id) != (self.sender_id, self.stream_id)
                    or plan.sequence <= self.high_sequence or now < plan.associated_at_sec):
                raise ValueError('matching ordered source packet in the same sender clock required')
            self.high_sequence = plan.sequence
            if now-plan.captured_at_sec > self.max_age:
                self.counts['expired'] += 1
                self._clear()
                return False
            if self.active is None:
                if self.pending is not None:
                    self.counts['pending_replaced'] += 1
                    self.pending = None
                self.active, self.index = plan, 0
            else:
                if self.pending is not None:
                    self.counts['pending_replaced'] += 1
                self.pending = plan
            self.peak_retained_bytes = max(self.peak_retained_bytes, self.retained_bytes)
            return True
        except (ValueError, TypeError, KeyError, OverflowError):
            self.counts['invalid'] += 1
            self._clear()
            return False

    def next_fragment(self, *, now, buffered_amount, channel_open):
        if not self._tick(now):
            return None
        if (type(buffered_amount) is not int or not 0 <= buffered_amount < 2**63
                or type(channel_open) is not bool):
            self.counts['invalid'] += 1
            self._clear()
            return None
        if not channel_open:
            self.counts['channel_unavailable'] += 1
            self._clear()
            return None
        while self.active is not None or self.pending is not None:
            if self.active is None:
                self.active, self.pending, self.index = self.pending, None, 0
            if now-self.active.captured_at_sec > self.max_age:
                self.counts['expired'] += 1
                self.active, self.index = None, 0
                continue
            message = self.active.fragment(self.index)
            if buffered_amount+len(message) > self.max_buffered:
                self.counts['held_for_buffer'] += 1
                return None
            self.index += 1
            self.counts['chunks_handed_off'] += 1
            if self.index == self.active.count:
                self.counts['packets_handed_off'] += 1
                self.active, self.index = None, 0
            return message
        return None

    def close(self):
        self.closed = True
        self._clear()
