"""Offline atomic image/motion packet prototype; NOT live RTC/FFB wiring.

Independent VP8 intra frames avoid receiver RTP timestamp-origin guessing.
SHA256 binds packet bytes against accidental swaps; it is NOT authentication
or evidence that the caller supplied the physically correct capture/sample.
"""
import copy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import struct

from driver_frame_motion import SenderFrameMotion, SCHEMA as CANDIDATE_SCHEMA, FLAGS
from driver_motion_handoff import session_ok
from driver_odometry_observation import clock_time
from theta_rtc_frames import native_frame

MAGIC = b'THETA_FRAME_V1\x00'
PREFIX = struct.Struct('!%dsII32s' % len(MAGIC))
MAX_HEADER = 8192
MAX_PAYLOAD = 2*1024*1024
FIELDS = {'schema', 'sender_id', 'stream_id', 'sender_monotonic_clock_id',
    'capture_sequence', 'captured_at_sec', 'associated_at_sec', 'capture_time_basis',
    'sender_media_pts', 'media_clock_rate', 'receiver_media_pts', 'local_pair_available',
    'odometry_observation', 'callback_to_capture_sec', 'progress_to_capture_sec',
    'capture_wait_sec', 'policy', 'reason', *FLAGS}
WITHHELD = {'invalid_odometry_observation', 'foreign_sender_observation',
    'sender_clock_reversed_or_invalid', 'odometry_state_reset', 'odometry_order_reversed',
    'same_callback_identity_changed', 'odometry_drop_counter_reversed',
    'invalid_frame_identity_or_time', 'association_busy', 'odometry_history_gap',
    'source_frame_or_clock_order_reversed', 'capture_wait_exceeded', 'no_observed_past_callback',
    'latest_past_callback_invalid', 'motion_frame_mismatch', 'latest_past_source_stamp_not_advanced',
    'callback_to_capture_limit_exceeded', 'source_stamp_progress_limit_exceeded'}


def checked_candidate(value):
    """Check source candidates without certifying their physical provenance."""
    if (type(value) is not dict or set(value) != FIELDS or value['schema'] != CANDIDATE_SCHEMA
            or any(value[k] is not False for k in FLAGS)
            or type(value['local_pair_available']) is not bool
            or value['receiver_media_pts'] is not None or type(value['media_clock_rate']) is not int
            or value['media_clock_rate'] != 90000
            or value['sender_monotonic_clock_id'] != 'sender-process/'+str(value['sender_id'])
            or value['capture_time_basis'] != 'camera_read_return_NOT_sensor_exposure'
            or type(value['policy']) is not dict):
        raise ValueError('exact non-controlling source candidate required')
    try:
        source = SenderFrameMotion(sender_id=value['sender_id'], stream_id=value['stream_id'], **value['policy'])
        if value['local_pair_available']:
            if not source.offer(value['odometry_observation']):
                raise ValueError('invalid selected odometry')
        elif (value['odometry_observation'] is not None
                or value['callback_to_capture_sec'] is not None or value['progress_to_capture_sec'] is not None
                or value['reason'] not in WITHHELD):
            raise ValueError('withheld candidate must not carry previous motion')
        result = source.associate(capture_sequence=value['capture_sequence'],
            captured_at_sec=value['captured_at_sec'], media_pts=value['sender_media_pts'],
            associated_at_sec=value['associated_at_sec'])
        if value['local_pair_available']:
            if not result['local_pair_available'] or result != value:
                raise ValueError('source candidate does not reproduce from selected observation')
        elif (value['capture_wait_sec'] != result['capture_wait_sec']
                or type(value['capture_wait_sec']) not in (int, float)):
            raise ValueError('capture wait must match original source times')
    except (TypeError, KeyError, OverflowError) as error:
        raise ValueError('bounded typed source candidate required') from error
    return copy.deepcopy(value)


def _json(data):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate packet JSON key')
            out[key] = value
        return out
    def invalid(_):
        raise ValueError('nonfinite packet JSON')
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('bounded valid packet JSON required') from error


def _keyframe(payload):
    if type(payload) is not bytes or not 10 <= len(payload) <= MAX_PAYLOAD:
        raise ValueError('bounded elementary VP8 frame required')
    tag = int.from_bytes(payload[:3], 'little')
    width, height = struct.unpack_from('<HH', payload, 6)
    if (tag & 1 or (tag >> 1) & 7 > 3 or not tag & 16
            or payload[3:6] != b'\x9d\x01\x2a' or width != 1280 or height != 720
            or not 0 < tag >> 5 <= len(payload)-10):
        raise ValueError('independent visible VP8 keyframe with native dimensions required')


def _wrap(header, payload):
    """Internal framing, also used by malformed-input tests; not a validator."""
    data = json.dumps(header, allow_nan=False, separators=(',', ':')).encode()
    if len(data) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ValueError('packet size limit exceeded')
    return PREFIX.pack(MAGIC, len(data), len(payload), hashlib.sha256(data+payload).digest())+data+payload


def encode_packet(image, candidate):
    """CPU codec work: call outside live RTC/UI callbacks. No disk or network."""
    import av
    native_frame(image)
    candidate = checked_candidate(candidate)
    pts = candidate['sender_media_pts']
    if not 0 <= pts < 2**32:
        raise ValueError('prototype media span is bounded to uint32; start a new stream')
    frame = av.VideoFrame.from_ndarray(image, format='bgr24')
    frame.pts, frame.time_base = pts, Fraction(1, 90000)
    codec = av.CodecContext.create('libvpx', 'w')
    codec.width, codec.height = 1280, 720
    codec.pix_fmt, codec.time_base = 'yuv420p', Fraction(1, 90000)
    codec.framerate, codec.bit_rate, codec.gop_size, codec.thread_count = Fraction(30, 1), 1500000, 1, 2
    codec.options = {'deadline':'realtime', 'cpu-used':'-6', 'lag-in-frames':'0'}
    packets = codec.encode(frame)+codec.encode(None)
    if len(packets) != 1 or packets[0].pts != pts or packets[0].time_base != Fraction(1, 90000):
        raise ValueError('exact single-frame codec timestamp required')
    payload = bytes(packets[0])
    _keyframe(payload)
    header = dict(schema='sender_frame_motion_packet_v1', codec='VP8_INTRA', width=1280, height=720,
        encoded_pts=pts, clock_rate=90000, candidate=candidate,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    return _wrap(header, payload)


def unpack_packet(wire):
    """Validate before decoding; exact length, bounded JSON and elementary image."""
    if type(wire) is not bytes or not PREFIX.size <= len(wire) <= PREFIX.size+MAX_HEADER+MAX_PAYLOAD:
        raise ValueError('bounded complete binary packet required')
    magic, hsize, psize, digest = PREFIX.unpack_from(wire)
    if (magic != MAGIC or not 0 < hsize <= MAX_HEADER or not 10 <= psize <= MAX_PAYLOAD
            or len(wire) != PREFIX.size+hsize+psize):
        raise ValueError('exact packet framing and lengths required')
    body = wire[PREFIX.size:]
    if hashlib.sha256(body).digest() != digest:
        raise ValueError('packet integrity failure')
    header = _json(body[:hsize])
    if (type(header) is not dict or set(header) != {'schema', 'codec', 'width', 'height',
            'encoded_pts', 'clock_rate', 'candidate', 'physical_metric_verified', 'usable_for_ffb', 'published_to_ros'}
            or header['schema'] != 'sender_frame_motion_packet_v1' or header['codec'] != 'VP8_INTRA'
            or any(type(header[k]) is not int for k in ('width', 'height', 'clock_rate', 'encoded_pts'))
            or (header['width'], header['height'], header['clock_rate']) != (1280, 720, 90000)
            or not 0 <= header['encoded_pts'] < 2**32
            or any(header[k] is not False for k in ('physical_metric_verified', 'usable_for_ffb', 'published_to_ros'))):
        raise ValueError('exact non-controlling native codec header required')
    header['candidate'] = checked_candidate(header['candidate'])
    if header['encoded_pts'] != header['candidate']['sender_media_pts']:
        raise ValueError('encoded frame and source media identity differ')
    payload = body[hsize:]
    _keyframe(payload)
    return header, payload


@dataclass(frozen=True)
class DecodedFramePacket:
    candidate: dict
    image: object
    received_at_sec: float
    packet_sha256: str


class FramePacketReceiver:
    """Worker-thread prototype; no callbacks, joining, time sync or output.

    Freshness here is only local reception-to-consumption age. Sender timestamps
    are NEVER subtracted from receiver timestamps. Independent frames may skip.
    """
    def __init__(self, *, sender_id, stream_id, max_receive_age_sec):
        if (not session_ok(sender_id) or not session_ok(stream_id)
                or type(max_receive_age_sec) not in (int, float)
                or not clock_time(max_receive_age_sec) or not 0 < max_receive_age_sec <= 1):
            raise ValueError('explicit scoped receiver and local age policy required')
        self.sender_id, self.stream_id, self.max_age = sender_id, stream_id, max_receive_age_sec
        self.latest = None
        self.high_sequence = 0
        self.last_pts = self.last_capture = self.last_associate = self.last_receive = self.last_now = None
        self.closed = False

    def accept(self, wire, *, received_at_sec):
        self.latest = None  # Any failed update clears the old pair.
        if (self.closed or not clock_time(received_at_sec)
                or self.last_receive is not None and received_at_sec < self.last_receive
                or self.last_now is not None and received_at_sec < self.last_now):
            self.closed = True
            raise ValueError('retired/reversed receiver clock')
        self.last_receive = received_at_sec
        header, payload = unpack_packet(wire)
        value = header['candidate']
        if (value['sender_id'] != self.sender_id or value['stream_id'] != self.stream_id
                or value['capture_sequence'] <= self.high_sequence
                or self.last_pts is not None and value['sender_media_pts'] <= self.last_pts
                or self.last_capture is not None and value['captured_at_sec'] <= self.last_capture
                or self.last_associate is not None and value['associated_at_sec'] < self.last_associate):
            raise ValueError('foreign, duplicate or reordered source packet')
        import av
        decoder = av.CodecContext.create('libvpx', 'r')
        decoder.thread_count = 1
        packet = av.Packet(payload)
        packet.pts, packet.time_base = header['encoded_pts'], Fraction(1, 90000)
        try:
            frames = decoder.decode(packet)+decoder.decode(None)
        except av.FFmpegError as error:
            raise ValueError('invalid encoded frame') from error
        if (len(frames) != 1 or frames[0].pts != header['encoded_pts']
                or frames[0].time_base != Fraction(1, 90000)):
            raise ValueError('independent decoded image must match packet identity')
        image = frames[0].to_ndarray(format='bgr24')
        native_frame(image)
        image.flags.writeable = False
        self.high_sequence = value['capture_sequence']
        self.last_pts, self.last_capture = value['sender_media_pts'], value['captured_at_sec']
        self.last_associate = value['associated_at_sec']
        self.latest = DecodedFramePacket(value, image, received_at_sec, hashlib.sha256(wire).hexdigest())
        return self.snapshot(received_at_sec)

    def snapshot(self, now):
        if (not clock_time(now) or self.last_now is not None and now < self.last_now
                or self.last_receive is not None and now < self.last_receive):
            self.latest, self.closed = None, True
            return None
        self.last_now = now
        if self.closed or self.latest is None:
            return None
        if now-self.latest.received_at_sec > self.max_age:
            self.latest = None
            return None
        image = self.latest.image.copy()
        image.flags.writeable = False
        return DecodedFramePacket(copy.deepcopy(self.latest.candidate), image,
            self.latest.received_at_sec, self.latest.packet_sha256)

    def close(self):
        self.closed, self.latest = True, None
