"""Bounded OFFLINE motion recording and receiver-time range pairing.

Not wired to telemetry, ROS, UI or G923. A pairing is NOT exposure-time
synchronization, vehicle position, a risk evaluation or output permission.
"""
import hashlib
import json
import math
import re

from driver_motion_handoff import OfflineRangeReceiver, session_ok

SCHEMA = 'offline_measured_motion_record_v1'
FLAGS = dict(replay_only=True, usable_for_ffb=False, published_to_ros=False)
FIELDS = {'schema', 'session', 'receiver_clock_id', 'sequence', 'logged_at_sec',
          'received_at_sec', 'source_kind', 'motion_frame_id', 'source_clock_id',
          'source_stamp_ns', 'measurement_valid', 'linear_mps', 'angular_radps', *FLAGS}
MAX_LINE_BYTES = 16*1024


def identifier(value):
    return isinstance(value, str) and re.fullmatch('[A-Za-z0-9_.:/-]{1,128}', value) is not None


def real(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def finite(value):
    return real(value) and value >= 0


def stamp(value):
    return type(value) is int and 0 <= value <= 2**63-1


def checked_motion_record(value):
    if (not isinstance(value, dict) or set(value) != FIELDS or value['schema'] != SCHEMA
            or not session_ok(value['session']) or not identifier(value['receiver_clock_id'])
            or type(value['sequence']) is not int or value['sequence'] < 1
            or not finite(value['logged_at_sec'])
            or any(value[k] is not v for k, v in FLAGS.items())):
        raise ValueError('explicit bounded offline motion identity required')
    for key in ('source_clock_id', 'motion_frame_id'):
        if value[key] is not None and not identifier(value[key]):
            raise ValueError('explicit clock/frame identifier or null required')
    if (value['received_at_sec'] is not None and (not finite(value['received_at_sec'])
            or value['received_at_sec'] > value['logged_at_sec'])):
        raise ValueError('motion reception must precede logging')
    if (value['source_kind'] not in (None, 'measured_odometry', 'legacy_telemetry', 'command')
            or (value['source_stamp_ns'] is not None and not stamp(value['source_stamp_ns']))
            or (value['measurement_valid'] is not None and type(value['measurement_valid']) is not bool)
            or any(value[k] is not None and not real(value[k]) for k in ('linear_mps', 'angular_radps'))):
        raise ValueError('finite signed measurements and original integer stamp or null required')
    return dict(value)


def motion_record(*, session, receiver_clock_id, sequence, logged_at_sec,
                  received_at_sec=None, source_kind=None, motion_frame_id=None,
                  source_clock_id=None, source_stamp_ns=None, measurement_valid=None,
                  linear_mps=None, angular_radps=None):
    """Normalize explicit facts only. None is unknown; measured zero is valid."""
    return checked_motion_record(dict(schema=SCHEMA, session=session, receiver_clock_id=receiver_clock_id,
        sequence=sequence, logged_at_sec=logged_at_sec, received_at_sec=received_at_sec,
        source_kind=source_kind, motion_frame_id=motion_frame_id, source_clock_id=source_clock_id,
        source_stamp_ns=source_stamp_ns, measurement_valid=measurement_valid,
        linear_mps=linear_mps, angular_radps=angular_radps, **FLAGS))


class MotionLog:
    """Exclusive bounded local JSONL writer; never called from a live callback."""
    def __init__(self, path, *, session, receiver_clock_id, max_records, max_bytes):
        if (not session_ok(session) or not identifier(receiver_clock_id)
                or type(max_records) is not int or not 0 < max_records <= 1_000_000
                or type(max_bytes) is not int or not 0 < max_bytes <= 1024**3):
            raise ValueError('explicit bounded log identity and limits required')
        self.session, self.clock = session, receiver_clock_id
        self.max_records, self.max_bytes = max_records, max_bytes
        self.records, self.bytes, self.last_sequence, self.last_time = 0, 0, 0, None
        self.stream = open(path, 'xb')

    def write(self, record):
        value = checked_motion_record(record)
        if (value['session'] != self.session or value['receiver_clock_id'] != self.clock
                or value['sequence'] <= self.last_sequence
                or (self.last_time is not None and value['logged_at_sec'] < self.last_time)):
            raise ValueError('log session/clock/record order mismatch')
        wire = (json.dumps(value, allow_nan=False, separators=(',', ':'))+'\n').encode()
        if len(wire) > MAX_LINE_BYTES or self.records >= self.max_records or self.bytes+len(wire) > self.max_bytes:
            raise ValueError('offline motion log limit reached')
        self.stream.write(wire)
        self.stream.flush()
        self.records += 1; self.bytes += len(wire)
        self.last_sequence, self.last_time = value['sequence'], value['logged_at_sec']

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def read_motion_records(path, *, max_records=1_000_000, max_bytes=1024**3):
    if (type(max_records) is not int or not 0 < max_records <= 1_000_000
            or type(max_bytes) is not int or not 0 < max_bytes <= 1024**3):
        raise ValueError('bounded reader limits required')
    def pairs(items):
        value = {}
        for k, v in items:
            if k in value:
                raise ValueError('duplicate motion JSON key')
            value[k] = v
        return value

    def invalid(_):
        raise ValueError('nonfinite motion JSON value')

    count, total = 0, 0
    with open(path, 'rb') as stream:
        while True:
            line = stream.readline(MAX_LINE_BYTES+1)
            if not line:
                return
            if len(line) > MAX_LINE_BYTES or not line.endswith(b'\n'):
                raise ValueError('bounded complete motion record required')
            count += 1; total += len(line)
            if count > max_records or total > max_bytes:
                raise ValueError('offline motion reader limit reached')
            yield checked_motion_record(json.loads(line, object_pairs_hook=pairs, parse_constant=invalid))


def checked_clock_binding(value):
    fields = {'schema', 'session', 'receiver_clock_id', 'source_clock_id', 'source_anchor_ns',
              'receiver_anchor_sec', 'valid_from_ns', 'valid_to_ns', 'error_bound_sec',
              'evidence_kind', 'evidence_id'}
    if (not isinstance(value, dict) or set(value) != fields
            or value['schema'] != 'offline_motion_clock_binding_v1' or not session_ok(value['session'])
            or not all(identifier(value[k]) for k in ('receiver_clock_id', 'source_clock_id', 'evidence_id'))
            or not all(stamp(value[k]) for k in ('source_anchor_ns', 'valid_from_ns', 'valid_to_ns'))
            or not value['valid_from_ns'] <= value['source_anchor_ns'] <= value['valid_to_ns']
            or not finite(value['receiver_anchor_sec']) or not finite(value['error_bound_sec'])
            or value['error_bound_sec'] > .5
            or value['evidence_kind'] not in ('synthetic_fixture_only', 'external_clock_alignment_record')):
        raise ValueError('explicit scoped clock anchors, error bound and evidence required')
    return dict(value)


class OfflineMotionJoiner:
    """Past-only last-measured sample, no interpolation, prediction or commands.

    All time tolerances are mandatory caller policy, not adopted FFB limits.
    A clock binding is a declaration with an evidence ID, NOT an independently
    verified physical-clock certificate. Output remains offline/non-controlling.
    """
    def __init__(self, *, session, receiver_clock_id, motion_frame_id, range_reference,
                 clock_binding, max_skew_sec, max_motion_age_sec, max_clock_error_sec):
        if (not session_ok(session) or not identifier(receiver_clock_id) or not identifier(motion_frame_id)
                or not all(real(v) and 0 < v <= .5 for v in (max_skew_sec, max_motion_age_sec))
                or not finite(max_clock_error_sec) or max_clock_error_sec > .5):
            raise ValueError('explicit session/clock/frame and bounded timing policy required')
        self.range = OfflineRangeReceiver(session, **range_reference)
        self.binding = None if clock_binding is None else checked_clock_binding(clock_binding)
        if self.binding is not None and (self.binding['session'] != session
                or self.binding['receiver_clock_id'] != receiver_clock_id):
            raise ValueError('clock binding scope mismatch')
        self.session, self.clock, self.frame_id = session, receiver_clock_id, motion_frame_id
        self.max_skew, self.max_age, self.max_error = max_skew_sec, max_motion_age_sec, max_clock_error_sec
        self.current, self.reason = None, 'motion_not_received'
        self.last_sequence, self.last_received, self.last_stamp, self.last_now = 0, None, None, None
        self.last_logged = None

    def _time(self, now):
        if not finite(now) or (self.last_now is not None and now < self.last_now):
            self.current, self.reason = None, 'receiver_clock_invalid_or_reversed'
            # Revoke a previous range too, without resetting its order counters.
            self.range.receive({}, now_source_clock_sec=0.)
            raise ValueError('finite nondecreasing receiver time required')
        self.last_now = now

    def push_motion(self, record, *, now_sec):
        self.current, self.reason = None, 'invalid_motion_record'
        self._time(now_sec)
        try:
            value = checked_motion_record(record)
        except (ValueError, TypeError, KeyError):
            return self.reason
        if value['session'] != self.session or value['receiver_clock_id'] != self.clock:
            self.reason = 'motion_session_or_clock_mismatch'
        elif (value['sequence'] <= self.last_sequence or value['logged_at_sec'] > now_sec
              or (self.last_logged is not None and value['logged_at_sec'] < self.last_logged)):
            self.reason = 'motion_out_of_order_or_future_record'
        else:
            self.last_sequence = value['sequence']
            self.last_logged = value['logged_at_sec']
            if value['received_at_sec'] is None:
                self.reason = 'motion_not_received'
            elif self.last_received is not None and value['received_at_sec'] <= self.last_received:
                self.reason = 'motion_repeated_or_reversed_reception'
            else:
                self.last_received = value['received_at_sec']
                self.reason = self._accept(value)
                if self.reason == 'motion_candidate':
                    self.current = value
        return self.reason

    def _accept(self, value):
        if value['source_kind'] != 'measured_odometry':
            return 'motion_not_measured_odometry'
        if value['measurement_valid'] is not True or any(value[k] is None for k in ('linear_mps', 'angular_radps')):
            return 'motion_measurement_invalid_or_missing'
        if value['motion_frame_id'] != self.frame_id:
            return 'motion_frame_mismatch'
        if value['source_clock_id'] is None or value['source_stamp_ns'] is None or self.binding is None:
            return 'motion_clock_mapping_missing'
        b, t = self.binding, value['source_stamp_ns']
        if value['source_clock_id'] != b['source_clock_id']:
            return 'motion_source_clock_mismatch'
        if not b['valid_from_ns'] <= t <= b['valid_to_ns']:
            return 'motion_clock_binding_out_of_scope'
        if self.last_stamp is not None and t <= self.last_stamp:
            return 'motion_source_stamp_repeated_or_reversed'
        self.last_stamp = t
        if b['error_bound_sec'] > self.max_error:
            return 'motion_clock_error_too_large'
        mapped = b['receiver_anchor_sec']+(t-b['source_anchor_ns'])/1e9
        lo, hi = mapped-b['error_bound_sec'], mapped+b['error_bound_sec']
        if not finite(mapped) or lo < 0 or hi > value['received_at_sec']:
            return 'motion_measurement_interval_after_reception'
        value.update(mapped_source_time_sec=mapped, earliest_time_sec=lo, latest_time_sec=hi)
        return 'motion_candidate'

    def join(self, range_packet, *, now_sec):
        self._time(now_sec)
        try:
            distance = self.range.receive(range_packet, now_source_clock_sec=now_sec)
        except OverflowError:
            # The older scalar validator may overflow on an enormous integer.
            # Revoke it without changing the SHA-bound original implementation.
            distance = self.range.receive({}, now_source_clock_sec=now_sec)
        result = dict(schema='offline_receiver_time_range_motion_pair_v1', range_sample=distance,
            pair_available=False, measured_motion=None, reason='range_withheld',
            target_time_basis='receiver_video_decode_NOT_camera_exposure',
            vehicle_xy_m=None, steering_gradient_available=False, exposure_time_alignment_verified=False,
            clock_alignment_independently_verified=False, controlling_distance=False,
            physical_metric_verified=False, floor_contact_verified=False, **FLAGS)
        if not distance['range_available']:
            return result
        result['reason'] = self.reason
        value = self.current
        if value is None:
            return result
        if now_sec-value['earliest_time_sec'] > self.max_age:
            self.current, self.reason = None, 'motion_measurement_stale'
            result['reason'] = self.reason
        elif value['latest_time_sec'] > distance['source_time_sec']:
            result['reason'] = 'motion_not_entirely_past_video_receive'
        elif distance['source_time_sec']-value['earliest_time_sec'] > self.max_skew:
            result['reason'] = 'motion_video_receive_skew_too_large'
        else:
            b = self.binding
            digest = hashlib.sha256(json.dumps(b, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            result.update(pair_available=True, reason='offline_receiver_time_pair_only', measured_motion=dict(
                record_sequence=value['sequence'], source_stamp_ns=value['source_stamp_ns'],
                source_clock_id=value['source_clock_id'], motion_frame_id=value['motion_frame_id'],
                received_at_sec=value['received_at_sec'], mapped_source_time_sec=value['mapped_source_time_sec'],
                mapping_error_bound_sec=b['error_bound_sec'], clock_binding_sha256=digest,
                clock_evidence_kind=b['evidence_kind'], clock_evidence_id=b['evidence_id'],
                linear_mps=value['linear_mps'], angular_radps=value['angular_radps']))
        return result
