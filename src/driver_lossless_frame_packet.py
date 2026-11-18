"""Offline PNG atomic packet, deliberately NOT a live channel codec.

Strict native RGB8 PNG profile; original BGR pixels must survive exactly.
Digests detect accidental corruption, NOT hostile peers or wrong capture pairs.
No source timestamp is subtracted from a receiver timestamp.
"""
import copy
from dataclasses import dataclass
import hashlib
import json
import math
import struct
import zlib

from driver_frame_packet import checked_candidate, MAX_HEADER, MAX_PAYLOAD, _json
from driver_motion_handoff import session_ok
from driver_odometry_observation import clock_time
from theta_rtc_frames import native_frame

MAGIC = b'THETA_PNG_V1\x00'
PREFIX = struct.Struct('!%dsII32s' % len(MAGIC))
MAX_PACKET = PREFIX.size + MAX_HEADER + MAX_PAYLOAD
DEADLINE_SEC = .2
SCHEMA = 'sender_lossless_frame_motion_packet_v1'
FIELDS = {'schema', 'codec', 'width', 'height', 'encoded_pts', 'clock_rate',
          'bgr_sha256', 'candidate'}
FILTERED_BYTES = 720 * (1280 * 3 + 1)


def _finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('nonfinite JSON number')
    if isinstance(value, dict):
        for child in value.values():
            _finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            _finite_tree(child)


def checked_png(payload):
    """Validate the encoder's deliberately narrow PNG profile before decode.

    At most 4096 chunks, bounded compressed and decompressed streams, no color
    profiles, alpha, palette, interlacing, animation, ancillary or trailing data.
    """
    if (type(payload) is not bytes or not 45 <= len(payload) <= MAX_PAYLOAD
            or payload[:8] != b'\x89PNG\r\n\x1a\n'):
        raise ValueError('bounded PNG payload required')
    offset, chunks, data, ended = 8, 0, bytearray(), False
    while offset < len(payload):
        chunks += 1
        if chunks > 4096 or len(payload)-offset < 12:
            raise ValueError('bounded complete PNG chunks required')
        size, kind = struct.unpack_from('!I4s', payload, offset)
        end = offset+12+size
        if end > len(payload):
            raise ValueError('truncated PNG chunk')
        body = payload[offset+8:end-4]
        crc = struct.unpack_from('!I', payload, end-4)[0]
        if zlib.crc32(kind+body) & 0xffffffff != crc:
            raise ValueError('PNG CRC mismatch')
        if chunks == 1:
            if (kind != b'IHDR' or size != 13
                    or struct.unpack('!IIBBBBB', body) != (1280,720,8,2,0,0,0)):
                raise ValueError('native RGB8 noninterlaced IHDR required')
        elif kind == b'IDAT':
            data.extend(body)
        elif kind == b'IEND' and size == 0 and data and end == len(payload):
            ended = True
        else:
            raise ValueError('only IHDR, consecutive IDAT, final IEND allowed')
        offset = end
    if not ended:
        raise ValueError('complete PNG ending required')
    decoder = zlib.decompressobj()
    try:
        filtered = decoder.decompress(data, FILTERED_BYTES+1)
    except zlib.error as error:
        raise ValueError('invalid PNG deflate stream') from error
    if (len(filtered) != FILTERED_BYTES or not decoder.eof
            or decoder.unused_data or decoder.unconsumed_tail
            or any(filtered[y*(1280*3+1)] > 4 for y in range(720))):
        raise ValueError('exact bounded filtered PNG scanlines required')


def _wrap(header, payload):
    """Internal framing only, also used to construct invalid test inputs."""
    data = json.dumps(header, allow_nan=False, separators=(',', ':')).encode()
    if not 0 < len(data) <= MAX_HEADER or not 0 < len(payload) <= MAX_PAYLOAD:
        raise ValueError('packet limits exceeded')
    return PREFIX.pack(MAGIC, len(data), len(payload), hashlib.sha256(data+payload).digest())+data+payload


def encode_packet(image, candidate):
    import cv2
    native_frame(image)
    candidate = checked_candidate(candidate)
    pts = candidate['sender_media_pts']
    if type(pts) is not int or not 0 <= pts < 2**32:
        raise ValueError('uint32 source media PTS required')
    # Caller-owned input is never modified. Worker must supply a stable image.
    ok, encoded = cv2.imencode('.png', image, [])
    if not ok:
        raise ValueError('PNG encode failed')
    payload = encoded.tobytes()
    checked_png(payload)
    return _wrap(dict(schema=SCHEMA, codec='PNG_RGB8_LOSSLESS', width=1280, height=720,
        encoded_pts=pts, clock_rate=90000, bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
        candidate=candidate), payload)


def unpack_packet(wire):
    if type(wire) is not bytes or not PREFIX.size <= len(wire) <= MAX_PACKET:
        raise ValueError('bounded complete PNG packet required')
    magic, hsize, psize, digest = PREFIX.unpack_from(wire)
    if (magic != MAGIC or not 0 < hsize <= MAX_HEADER or not 45 <= psize <= MAX_PAYLOAD
            or len(wire) != PREFIX.size+hsize+psize):
        raise ValueError('exact PNG packet framing required')
    body = wire[PREFIX.size:]
    if hashlib.sha256(body).digest() != digest:
        raise ValueError('PNG packet integrity mismatch')
    header = _json(body[:hsize])
    _finite_tree(header)
    if (type(header) is not dict or set(header) != FIELDS or header['schema'] != SCHEMA
            or header['codec'] != 'PNG_RGB8_LOSSLESS'
            or any(type(header[k]) is not int for k in ('width','height','encoded_pts','clock_rate'))
            or (header['width'], header['height'], header['clock_rate']) != (1280,720,90000)
            or not 0 <= header['encoded_pts'] < 2**32
            or type(header['bgr_sha256']) is not str or len(header['bgr_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in header['bgr_sha256'])):
        raise ValueError('exact lossless PNG header required')
    header['candidate'] = checked_candidate(header['candidate'])
    if header['encoded_pts'] != header['candidate']['sender_media_pts']:
        raise ValueError('PNG and candidate media identity differ')
    payload = body[hsize:]
    checked_png(payload)
    return header, payload


def decode_packet(wire):
    import cv2
    import numpy as np
    header, payload = unpack_packet(wire)
    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    native_frame(image)
    if hashlib.sha256(image.tobytes()).hexdigest() != header['bgr_sha256']:
        raise ValueError('decoded PNG pixels differ from bound original')
    image.flags.writeable = False
    return header['candidate'], image


@dataclass(frozen=True)
class ReceivedPair:
    candidate: dict
    image: object
    deadline_sec: float
    packet_sha256: str


class LosslessPacketReceiver:
    """Single-owner, one-shot delivery; caller supplies receiver-local clock.

    first_received_at_sec MUST originate from the fragment assembler, not from
    completion/decode. No async worker or claim of bounded callback time here.
    """
    def __init__(self, *, sender_id, stream_id):
        if not session_ok(sender_id) or not session_ok(stream_id):
            raise ValueError('explicit source scope required')
        self.sender_id, self.stream_id = sender_id, stream_id
        self.latest = self.last_time = self.last_source = None
        self.high_sequence = 0
        self.closed = False

    def _tick(self, now):
        if (self.closed or not clock_time(now)
                or self.last_time is not None and now < self.last_time):
            self.closed, self.latest = True, None
            return False
        self.last_time = now
        return True

    def accept(self, wire, *, first_received_at_sec, now):
        self.latest = None
        before = now()
        if (not self._tick(before) or not clock_time(first_received_at_sec)
                or not 0 <= before-first_received_at_sec <= DEADLINE_SEC):
            return False
        candidate, image = decode_packet(wire)
        after = now()
        if not self._tick(after):
            return False
        source = tuple(candidate[k] for k in ('sender_media_pts','captured_at_sec','associated_at_sec'))
        if (candidate['sender_id'] != self.sender_id or candidate['stream_id'] != self.stream_id
                or candidate['capture_sequence'] <= self.high_sequence
                or self.last_source is not None and (source[0] <= self.last_source[0]
                    or source[1] <= self.last_source[1] or source[2] < self.last_source[2])):
            raise ValueError('foreign, duplicate or reversed source packet')
        # A valid but slow decode also consumes its source identity, never revives.
        self.high_sequence, self.last_source = candidate['capture_sequence'], source
        if after-first_received_at_sec > DEADLINE_SEC:
            return False
        self.latest = ReceivedPair(candidate, image, first_received_at_sec+DEADLINE_SEC,
                                   hashlib.sha256(wire).hexdigest())
        return True

    def take(self, now):
        if not self._tick(now):
            return None
        value, self.latest = self.latest, None
        if value is None or now > value.deadline_sec:
            return None
        image = value.image.copy()
        image.flags.writeable = False
        return ReceivedPair(copy.deepcopy(value.candidate), image, value.deadline_sec, value.packet_sha256)

    def close(self):
        self.closed, self.latest = True, None
