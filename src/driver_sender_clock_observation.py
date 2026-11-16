"""Sender-node ROS clock read bracket; NOT a verified clock binding.

No ROS import, network, IO, clock adjustment or control. All times are integer
nanoseconds. A read bracket does not certify the driver's header clock origin.
"""
import re
import threading
import time

SCHEMA = 'driver_sender_ros_clock_observation_v1'
SCOPE = 'sender_node_clock_NOT_odom_publisher_or_sensor_clock_verified'
FLAGS = ('header_clock_relation_verified', 'receiver_clock_binding_verified',
         'source_freshness_verified', 'usable_for_ffb', 'published_to_ros')
SAMPLE = ('mono_before_ns', 'mono_after_ns', 'ros_now_ns', 'clock_type', 'use_sim_time',
          'ros_time_active', 'ros_minus_mono_lower_ns', 'ros_minus_mono_upper_ns',
          'bracket_width_ns', 'ros_time_status', 'configuration_changed')
FIELDS = {'schema', 'sender_id', 'sender_monotonic_clock_id', 'sample_sequence',
          'clock_generation', 'status', 'clock_scope', *SAMPLE, *FLAGS}


def ns(value):
    return type(value) is int and 0 <= value <= 2**63-1


def checked_clock_observation(value):
    if (type(value) is not dict or set(value) != FIELDS or value['schema'] != SCHEMA
            or type(value['sender_id']) is not str or re.fullmatch('[0-9a-f]{32}', value['sender_id']) is None
            or value['sender_monotonic_clock_id'] != 'sender-process/'+value['sender_id']
            or not ns(value['sample_sequence']) or not ns(value['clock_generation'])
            or value['clock_scope'] != SCOPE or any(value[k] is not False for k in FLAGS)):
        raise ValueError('exact bounded clock observation identity required')
    if value['status'] == 'sampled':
        before, after, ros = (value[k] for k in ('mono_before_ns', 'mono_after_ns', 'ros_now_ns'))
        if (not all(ns(t) for t in (before, after, ros)) or before > after
                or value['sample_sequence'] < 1 or value['clock_generation'] < 1
                or value['clock_type'] not in ('ROS_TIME', 'SYSTEM_TIME', 'STEADY_TIME')
                or type(value['use_sim_time']) is not bool
                or (type(value['ros_time_active']) is not bool if value['clock_type'] == 'ROS_TIME'
                    else value['ros_time_active'] is not None)
                or type(value['configuration_changed']) is not bool
                or value['ros_time_status'] not in ('first', 'advanced', 'repeated', 'reversed', 'zero')
                or (ros == 0) != (value['ros_time_status'] == 'zero')
                or any(type(value[k]) is not int for k in
                    ('ros_minus_mono_lower_ns', 'ros_minus_mono_upper_ns', 'bracket_width_ns'))
                or value['ros_minus_mono_lower_ns'] != ros-after
                or value['ros_minus_mono_upper_ns'] != ros-before
                or value['bracket_width_ns'] != after-before):
            raise ValueError('causal integer clock read bracket required')
    elif value['status'] in ('sampling_error', 'monotonic_invalid', 'observer_busy'):
        if any(value[k] is not None for k in SAMPLE):
            raise ValueError('failed clock observation must not carry cached timestamps')
    else:
        raise ValueError('known clock observation status required')
    return dict(value)


def decode_clock_observation(value):
    if type(value) is dict and value.get('schema') != SCHEMA:
        return None, 'unsupported_sender_clock_schema'
    try:
        return checked_clock_observation(value), 'versioned_sender_clock_observation'
    except (ValueError, TypeError, KeyError, OverflowError):
        return None, 'invalid_sender_clock_metadata'


class SenderClockObserver:
    def __init__(self, *, sender_id, read_clock, monotonic_ns=time.monotonic_ns):
        if type(sender_id) is not str or re.fullmatch('[0-9a-f]{32}', sender_id) is None:
            raise ValueError('explicit odometry observer sender identity required')
        if not callable(read_clock) or not callable(monotonic_ns):
            raise ValueError('clock readers required')
        self.sender_id, self.read_clock, self.monotonic_ns = sender_id, read_clock, monotonic_ns
        self.lock = threading.Lock()
        self.sequence, self.generation = 0, 1
        self.previous, self.last_after = None, None

    def _result(self, status, **sample):
        result = dict(schema=SCHEMA, sender_id=self.sender_id,
            sender_monotonic_clock_id='sender-process/'+self.sender_id,
            sample_sequence=self.sequence, clock_generation=self.generation,
            status=status, clock_scope=SCOPE, **{k:None for k in SAMPLE}, **{k:False for k in FLAGS})
        result.update(sample)
        return result

    def snapshot(self):
        if not self.lock.acquire(blocking=False):
            return self._result('observer_busy')
        try:
            self.sequence += 1
            try:
                before = self.monotonic_ns()
                raw = self.read_clock()
                after = self.monotonic_ns()
            except Exception:
                self.previous, self.last_after = None, None
                self.generation += 1
                return self._result('sampling_error')
            if (not ns(before) or not ns(after) or after < before
                    or (self.last_after is not None and before < self.last_after)):
                self.previous, self.last_after = None, None
                self.generation += 1
                return self._result('monotonic_invalid')
            if (type(raw) is not dict or set(raw) != {'ros_now_ns', 'clock_type', 'use_sim_time', 'ros_time_active'}
                    or not ns(raw['ros_now_ns']) or raw['clock_type'] not in ('ROS_TIME', 'SYSTEM_TIME', 'STEADY_TIME')
                    or type(raw['use_sim_time']) is not bool
                    or (type(raw['ros_time_active']) is not bool if raw['clock_type'] == 'ROS_TIME'
                        else raw['ros_time_active'] is not None)):
                self.previous, self.last_after = None, None
                self.generation += 1
                return self._result('sampling_error')
            config = (raw['clock_type'], raw['use_sim_time'], raw['ros_time_active'])
            previous = self.previous
            changed = previous is not None and config != previous[0]
            ros = raw['ros_now_ns']
            status = 'first' if previous is None or changed else (
                'advanced' if ros > previous[1] else 'repeated' if ros == previous[1] else 'reversed')
            if changed or status == 'reversed':
                self.generation += 1
            if ros == 0:
                status = 'zero'
            self.previous, self.last_after = (config, ros), after
            return self._result('sampled', **raw, mono_before_ns=before, mono_after_ns=after,
                ros_minus_mono_lower_ns=ros-after, ros_minus_mono_upper_ns=ros-before,
                bracket_width_ns=after-before, ros_time_status=status, configuration_changed=changed)
        finally:
            self.lock.release()
