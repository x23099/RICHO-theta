"""Bounded observation metadata only. No ROS import, control, IO or clock sync."""
import math
import re
import threading
import time
import uuid

SCHEMA = 'driver_odometry_observation_v1'
FIELDS = {'schema', 'sender_id', 'sender_monotonic_clock_id', 'callback_received', 'callback_sequence',
    'callback_received_mono_sec', 'snapshot_mono_sec', 'callback_age_sec', 'header_stamp_ns',
    'motion_frame_id', 'pose_frame_id', 'linear_mps', 'angular_radps', 'stamp_status',
    'stamp_progress_mono_sec', 'stamp_progress_age_sec', 'sample_fields_valid', 'invalid_fields',
    'dropped_callbacks', 'header_clock_relation_verified', 'source_freshness_verified', 'usable_for_ffb', 'published_to_ros'}
FLAGS = ('header_clock_relation_verified', 'source_freshness_verified', 'usable_for_ffb', 'published_to_ros')
SAMPLE_FIELDS = ('header_stamp_ns', 'motion_frame_id', 'pose_frame_id', 'linear_mps', 'angular_radps')


def number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and abs(value) <= 1e15
    except OverflowError:
        return False


def clock_time(value):
    return number(value) and value >= 0


def frame_id(value):
    return isinstance(value, str) and re.fullmatch('[A-Za-z0-9_.:/-]{1,128}', value) is not None


def stamp_ns(sec, nanosec):
    if (type(sec) is int and 0 <= sec < 2**31 and type(nanosec) is int and 0 <= nanosec < 10**9
            and sec*10**9+nanosec > 0):
        return sec*10**9+nanosec
    return None


def checked_observation(value):
    if (type(value) is not dict or len(value) != len(FIELDS) or set(value) != FIELDS
            or value['schema'] != SCHEMA or not isinstance(value['sender_id'], str)
            or re.fullmatch('[0-9a-f]{32}', value['sender_id']) is None
            or value['sender_monotonic_clock_id'] != 'sender-process/'+value['sender_id']
            or any(value[k] is not False for k in FLAGS)
            or type(value['sample_fields_valid']) is not bool
            or type(value['dropped_callbacks']) is not int or not 0 <= value['dropped_callbacks'] <= 2**63-1):
        raise ValueError('bounded versioned odometry observation required')
    invalid = value['invalid_fields']
    if (type(invalid) is not list or len(invalid) > len(SAMPLE_FIELDS)
            or any(type(k) is not str or k not in SAMPLE_FIELDS for k in invalid)
            or len(set(invalid)) != len(invalid)):
        raise ValueError('bounded sample-field diagnostics required')
    now = value['snapshot_mono_sec']
    if now is not None and not clock_time(now):
        raise ValueError('finite sender snapshot time required')
    if value['stamp_status'] in ('not_received', 'observer_busy', 'clock_invalid'):
        received = False if value['stamp_status'] == 'not_received' else None
        sequence = 0 if received is False else None
        if (value['callback_received'] is not received or value['callback_sequence'] != sequence
                or (sequence == 0 and type(value['callback_sequence']) is not int)
                or any(value[k] is not None for k in (*SAMPLE_FIELDS, 'callback_received_mono_sec',
                    'callback_age_sec', 'stamp_progress_mono_sec', 'stamp_progress_age_sec'))
                or value['sample_fields_valid'] or invalid
                or (value['stamp_status'] != 'clock_invalid' and now is None)):
            raise ValueError('unobserved metadata must not carry a measurement')
    else:
        if (value['stamp_status'] not in ('missing', 'first', 'advanced', 'repeated', 'reversed')
                or value['callback_received'] is not True or type(value['callback_sequence']) is not int
                or not 0 < value['callback_sequence'] <= 2**63-1
                or now is None or not clock_time(value['callback_received_mono_sec'])
                or not clock_time(value['callback_age_sec'])
                or not 0 <= value['callback_received_mono_sec'] <= now
                or abs(value['callback_age_sec']-(now-value['callback_received_mono_sec'])) > 1e-9):
            raise ValueError('causal callback observation times required')
        required_invalid = []
        t = value['header_stamp_ns']
        if t is None:
            required_invalid.append('header_stamp_ns')
        elif type(t) is not int or not 0 < t < 2**31*10**9:
            raise ValueError('positive original ROS header integer nanoseconds required')
        if (t is None) != (value['stamp_status'] == 'missing'):
            raise ValueError('header presence/stamp status mismatch')
        for key in ('motion_frame_id', 'pose_frame_id', 'linear_mps', 'angular_radps'):
            item = value[key]
            if item is None:
                required_invalid.append(key)
            elif not (frame_id(item) if key.endswith('frame_id') else number(item)):
                raise ValueError('invalid sample field')
        if set(invalid) != set(required_invalid) or value['sample_fields_valid'] != (not required_invalid):
            raise ValueError('sample field validity differs from explicit facts')
        progress, age = value['stamp_progress_mono_sec'], value['stamp_progress_age_sec']
        if progress is None:
            if age is not None or t is not None:
                raise ValueError('known stamp needs progress observation time')
        elif (not clock_time(progress) or not clock_time(age)
                or not progress <= value['callback_received_mono_sec']
                or abs(age-(now-progress)) > 1e-9):
            raise ValueError('causal stamp progress times required')
        if value['stamp_status'] in ('first', 'advanced') and progress != value['callback_received_mono_sec']:
            raise ValueError('advanced stamp time must be the observed callback time')
    result = dict(value)
    result['invalid_fields'] = list(invalid)
    return result


def decode_observation(value):
    if type(value) is dict and value.get('schema') != SCHEMA:
        return None, 'unsupported_odometry_schema'
    try:
        return checked_observation(value), 'versioned_odometry_observation'
    except (ValueError, TypeError, KeyError, OverflowError):
        return None, 'invalid_odometry_metadata'


class OdometryObserver:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.sender_id = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.sample = None
        self.sequence = self.drops = 0
        self.high_stamp = self.progress = self.last_callback = self.last_snapshot = None
        self.error = False

    def observe(self, message):
        now = self.clock()
        if not self.lock.acquire(blocking=False):
            self.drops += 1
            return False
        try:
            if not clock_time(now) or (self.last_callback is not None and now < self.last_callback):
                self.sample, self.error = None, True
                return False
            self.sequence += 1
            header = getattr(message, 'header', None)
            stamp = getattr(header, 'stamp', None)
            t = stamp_ns(getattr(stamp, 'sec', None), getattr(stamp, 'nanosec', None))
            twist = getattr(getattr(message, 'twist', None), 'twist', None)
            raw = dict(header_stamp_ns=t, motion_frame_id=getattr(message, 'child_frame_id', None),
                pose_frame_id=getattr(header, 'frame_id', None),
                linear_mps=getattr(getattr(twist, 'linear', None), 'x', None),
                angular_radps=getattr(getattr(twist, 'angular', None), 'z', None))
            invalid = []
            for key, item in raw.items():
                valid = item is not None
                if key.endswith('frame_id'):
                    valid = frame_id(item)
                elif key != 'header_stamp_ns':
                    valid = number(item)
                if not valid:
                    invalid.append(key); raw[key] = None
            status = 'missing'
            if t is not None:
                status = 'first' if self.high_stamp is None else (
                    'advanced' if t > self.high_stamp else 'repeated' if t == self.high_stamp else 'reversed')
                if self.high_stamp is None or t > self.high_stamp:
                    self.high_stamp, self.progress = t, now
            self.sample = dict(raw, stamp_status=status, invalid_fields=invalid,
                               sample_fields_valid=not invalid, callback_received_mono_sec=now)
            self.last_callback, self.error = now, False
            return True
        finally:
            self.lock.release()

    def _empty(self, status, now):
        return dict(schema=SCHEMA, sender_id=self.sender_id,
            sender_monotonic_clock_id='sender-process/'+self.sender_id,
            callback_received=False if status=='not_received' else None,
            callback_sequence=0 if status=='not_received' else None,
            callback_received_mono_sec=None, snapshot_mono_sec=now if clock_time(now) else None,
            callback_age_sec=None, **{k:None for k in SAMPLE_FIELDS}, stamp_status=status,
            stamp_progress_mono_sec=None, stamp_progress_age_sec=None, sample_fields_valid=False,
            invalid_fields=[], dropped_callbacks=self.drops, **{k:False for k in FLAGS})

    def snapshot(self):
        now = self.clock()
        if not self.lock.acquire(blocking=False):
            return self._empty('observer_busy', now) if clock_time(now) else self._empty('clock_invalid', now)
        try:
            if (not clock_time(now) or (self.last_callback is not None and now < self.last_callback)
                    or (self.last_snapshot is not None and now < self.last_snapshot) or self.error):
                return self._empty('clock_invalid', now)
            self.last_snapshot = now
            if self.sample is None:
                return self._empty('not_received', now)
            value = dict(self.sample)
            value['invalid_fields'] = list(value['invalid_fields'])
            value.update(schema=SCHEMA, sender_id=self.sender_id,
                sender_monotonic_clock_id='sender-process/'+self.sender_id,
                callback_received=True, callback_sequence=self.sequence, snapshot_mono_sec=now,
                callback_age_sec=now-self.last_callback, stamp_progress_mono_sec=self.progress,
                stamp_progress_age_sec=None if self.progress is None else now-self.progress,
                dropped_callbacks=self.drops, **{k:False for k in FLAGS})
            return value
        finally:
            self.lock.release()
