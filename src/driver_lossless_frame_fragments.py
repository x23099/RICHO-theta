"""Offline PNG-only bounded fragmentation, NOT a network sender/scheduler.

Single worker owner, fixed 16KiB messages and first-arrival 200ms deadline.
Distinct magic prevents accidental admission on the frozen VP8 fragment path.
"""
from dataclasses import dataclass
import hashlib
import struct

from driver_lossless_frame_packet import MAX_PACKET, DEADLINE_SEC, unpack_packet
from driver_motion_handoff import session_ok
from driver_odometry_observation import clock_time

MAGIC = b'THPNGF1\x00'
HEADER = struct.Struct('!8s16s16sQIHH32s')
MESSAGE_BYTES = 16384
BODY_BYTES = MESSAGE_BYTES-HEADER.size


def fragments(wire):
    """Worker-side generator: validate once, never retain a list of fragments."""
    value = unpack_packet(wire)[0]['candidate']
    sequence = value['capture_sequence']
    if type(sequence) is not int or not 0 < sequence < 2**64:
        raise ValueError('bounded source sequence required')
    digest = hashlib.sha256(wire).digest()
    count = (len(wire)+BODY_BYTES-1)//BODY_BYTES
    for index in range(count):
        yield HEADER.pack(MAGIC, bytes.fromhex(value['sender_id']), bytes.fromhex(value['stream_id']),
            sequence, len(wire), index, count, digest)+wire[index*BODY_BYTES:(index+1)*BODY_BYTES]


@dataclass(frozen=True)
class Arrival:
    wire: bytes
    first_received_at_sec: float
    completed_at_sec: float
    deadline_sec: float


class LosslessReassembler:
    """Retains at most one bounded byte buffer; all failures clear old output.

    Reordered fragments of the active packet are allowed; old packets, expired
    packets and completed packets cannot be replayed. New packet replaces old.
    Duplicates never reset first arrival time. Decode is a separate worker step.
    """
    def __init__(self, *, sender_id, stream_id):
        if not session_ok(sender_id) or not session_ok(stream_id):
            raise ValueError('explicit expected source scope required')
        self.sender, self.stream = bytes.fromhex(sender_id), bytes.fromhex(stream_id)
        self.active = self.last_time = None
        self.high_sequence = 0
        self.closed = False
        self.peak_retained_bytes = 0
        self.counts = dict(completed=0, expired=0, replaced=0, duplicates=0, stale=0, invalid=0)

    def _tick(self, now):
        if (self.closed or not clock_time(now)
                or self.last_time is not None and now < self.last_time):
            self.closed, self.active = True, None
            return False
        self.last_time = now
        if self.active is not None and now-self.active['start'] > DEADLINE_SEC:
            self.active = None
            self.counts['expired'] += 1
        return True

    def accept(self, message, now):
        if not self._tick(now):
            return None
        try:
            return self._accept(message, now)
        except (ValueError, struct.error):
            self.active = None
            self.counts['invalid'] += 1
            return None

    def _accept(self, message, now):
        if type(message) is not bytes or not HEADER.size < len(message) <= MESSAGE_BYTES:
            raise ValueError('bounded fragment required')
        magic, sender, stream, sequence, total, index, count, digest = HEADER.unpack_from(message)
        body = message[HEADER.size:]
        if (magic != MAGIC or sender != self.sender or stream != self.stream
                or not 0 < sequence < 2**64 or not 0 < total <= MAX_PACKET
                or count != (total+BODY_BYTES-1)//BODY_BYTES or not 0 <= index < count
                or len(body) != min(BODY_BYTES, total-index*BODY_BYTES)):
            raise ValueError('canonical scoped fragment required')
        if sequence < self.high_sequence or sequence == self.high_sequence and self.active is None:
            self.counts['stale'] += 1
            return None
        if sequence > self.high_sequence:
            if self.active is not None:
                self.counts['replaced'] += 1
            self.high_sequence = sequence
            self.active = dict(sequence=sequence, total=total, count=count, digest=digest,
                               start=now, seen=set(), buffer=bytearray(total))
            self.peak_retained_bytes = max(self.peak_retained_bytes, total)
        active = self.active
        if (total, count, digest) != (active['total'], active['count'], active['digest']):
            raise ValueError('conflicting fragment envelope')
        offset = index*BODY_BYTES
        if index in active['seen']:
            if active['buffer'][offset:offset+len(body)] != body:
                raise ValueError('conflicting duplicate fragment')
            self.counts['duplicates'] += 1
            return None
        active['buffer'][offset:offset+len(body)] = body
        active['seen'].add(index)
        if len(active['seen']) < count:
            return None
        self.active = None
        wire = bytes(active['buffer'])
        if hashlib.sha256(wire).digest() != digest:
            raise ValueError('whole packet digest mismatch')
        # Bind fragment envelope to inner image/motion identity before delivery.
        value = unpack_packet(wire)[0]['candidate']
        if (bytes.fromhex(value['sender_id']), bytes.fromhex(value['stream_id']), value['capture_sequence']) != (sender, stream, sequence):
            raise ValueError('fragment and PNG candidate scope differ')
        self.counts['completed'] += 1
        return Arrival(wire, active['start'], now, active['start']+DEADLINE_SEC)

    def poll(self, now):
        """Allow idle expiry without receiving another fragment."""
        self._tick(now)

    def close(self):
        self.closed, self.active = True, None
