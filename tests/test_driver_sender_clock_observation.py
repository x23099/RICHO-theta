"""Fake ROS clock brackets and passive recording; no live ROS/RTC."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_sender_clock_observation import SenderClockObserver, checked_clock_observation, decode_clock_observation
from driver_odometry_observation import OdometryObserver
from driver_telemetry_recording import TelemetryRecorder
from test_driver_odometry_observation import sender_node, message

SENDER = 'a'*32


class ClockObservationTests(unittest.TestCase):
    def setUp(self):
        self.ticks = iter([10_000_000_000+i*100 for i in range(100)])
        self.ros = 1794822450209981778
        self.config = dict(clock_type='ROS_TIME', use_sim_time=False, ros_time_active=False)
        self.observer = SenderClockObserver(sender_id=SENDER,
            read_clock=lambda:dict(ros_now_ns=self.ros, **self.config), monotonic_ns=lambda:next(self.ticks))

    def sample(self):
        result = self.observer.snapshot()
        self.assertEqual(checked_clock_observation(result), result)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        return result

    def test_integer_epoch_and_monotonic_bracket_preserved(self):
        value = self.sample()
        self.assertEqual(value['ros_now_ns'], self.ros)
        self.assertEqual(value['mono_before_ns'], 10_000_000_000)
        self.assertEqual(value['mono_after_ns'], 10_000_000_100)
        self.assertEqual(value['bracket_width_ns'], 100)
        self.assertEqual(value['ros_minus_mono_lower_ns'], self.ros-10_000_000_100)
        self.assertEqual(value['ros_minus_mono_upper_ns'], self.ros-10_000_000_000)
        for key in ('header_clock_relation_verified', 'receiver_clock_binding_verified',
                    'source_freshness_verified', 'usable_for_ffb', 'published_to_ros'):
            self.assertIs(value[key], False)

    def test_sequence_progress_and_ros_status(self):
        self.assertEqual(self.sample()['ros_time_status'], 'first')
        self.assertEqual(self.sample()['ros_time_status'], 'repeated')
        self.ros += 1
        value = self.sample()
        self.assertEqual(value['ros_time_status'], 'advanced')
        self.assertEqual(value['sample_sequence'], 3)

    def test_ros_reversal_changes_generation_without_certifying_binding(self):
        old = self.sample(); self.ros -= 1000
        value = self.sample()
        self.assertEqual(value['ros_time_status'], 'reversed')
        self.assertEqual(value['clock_generation'], old['clock_generation']+1)
        self.assertEqual(value['ros_now_ns'], self.ros)

    def test_configuration_changes_split_generations(self):
        old = self.sample()
        self.config.update(use_sim_time=True, ros_time_active=True)
        value = self.sample()
        self.assertTrue(value['configuration_changed'])
        self.assertEqual(value['ros_time_status'], 'first')
        self.assertEqual(value['clock_generation'], old['clock_generation']+1)

    def test_system_clock_active_state_is_null(self):
        self.config.update(clock_type='SYSTEM_TIME', ros_time_active=None)
        self.assertIsNone(self.sample()['ros_time_active'])

    def test_zero_ros_time_not_claimed_initialized(self):
        self.ros = 0
        self.assertEqual(self.sample()['ros_time_status'], 'zero')

    def test_failed_reader_does_not_replay_previous_bracket(self):
        old = self.sample()
        self.observer.read_clock = Mock(side_effect=RuntimeError('synthetic clock read error'))
        value = self.sample()
        self.assertEqual(value['status'], 'sampling_error')
        self.assertIsNone(value['ros_now_ns']); self.assertIsNone(value['mono_before_ns'])
        self.assertGreater(value['clock_generation'], old['clock_generation'])

    def test_monotonic_reversal_and_invalid_type_clear_sample(self):
        for ticks in ((10, 9), (False, 10), (float('nan'), 10), (-1, 1), (2**64, 2**64+1)):
            self.observer.monotonic_ns = iter(ticks).__next__
            value = self.sample()
            self.assertEqual(value['status'], 'monotonic_invalid')
            self.assertIsNone(value['ros_now_ns'])

    def test_inter_sample_monotonic_reversal_changes_generation(self):
        self.sample()
        self.observer.monotonic_ns = iter([9_000_000_000, 9_000_000_001]).__next__
        self.assertEqual(self.sample()['status'], 'monotonic_invalid')

    def test_contention_does_not_wait_or_replay_values(self):
        self.sample()
        with self.observer.lock:
            value = self.sample()
        self.assertEqual(value['status'], 'observer_busy'); self.assertIsNone(value['ros_now_ns'])

    def test_bad_reader_data_not_promoted(self):
        for change in (dict(ros_now_ns=True), dict(ros_now_ns=2**63), dict(use_sim_time=0),
                       dict(ros_time_active=None), dict(clock_type='unknown'), dict(extra='secret')):
            data = dict(ros_now_ns=self.ros, **self.config, **{})
            data.update(change); self.observer.read_clock = lambda:data
            self.assertEqual(self.sample()['status'], 'sampling_error')

    def test_decoder_rejects_authority_types_and_equation_changes(self):
        valid = self.sample()
        for key, item in (('usable_for_ffb', True), ('ros_now_ns', float(self.ros)),
            ('sample_sequence', True), ('mono_before_ns', True), ('configuration_changed', 0),
            ('ros_minus_mono_lower_ns', valid['ros_minus_mono_lower_ns']+1),
            ('bracket_width_ns', 200), ('extra', 'arbitrary')):
            value = dict(valid, **{key:item})
            self.assertEqual(decode_clock_observation(value), (None, 'invalid_sender_clock_metadata'))
        self.assertEqual(decode_clock_observation(dict(valid, schema='future')),
                         (None, 'unsupported_sender_clock_schema'))

    def test_no_input_identity_defaults(self):
        for sender in (None, '', 'future', True):
            with self.assertRaises(ValueError):
                SenderClockObserver(sender_id=sender, read_clock=lambda:None)


class SenderClockPipelineTests(unittest.TestCase):
    def node(self):
        node = sender_node()
        node.get_clock = Mock(return_value=NS(clock_type=NS(name='ROS_TIME'), ros_time_is_active=False,
                                             now=lambda:NS(nanoseconds=1794822450209981778)))
        node.get_parameter = Mock(return_value=NS(value=False))
        return node

    def record(self, payloads):
        with tempfile.TemporaryDirectory() as temp:
            recorder = TelemetryRecorder(Path(temp)/'log', max_bytes=200000, max_records=50,
                                         queue_size=50, clock=lambda:100.)
            recorder.start()
            try:
                for i, payload in enumerate(payloads, 1):
                    self.assertTrue(recorder.offer('b'*32, payload, float(i)))
            finally:
                summary = recorder.close()
            self.assertIsNone(summary['error'])
            return [json.loads(line) for line in (recorder.directory/'received_telemetry.jsonl').read_bytes().splitlines()]

    def test_actual_sender_getter_and_v3_record_preserve_independent_observations(self):
        node = self.node(); node.odom_callback(message(v=.2, w=-.1))
        payload = node.get_telemetry_dict(); before = copy.deepcopy(payload)
        row = self.record([payload])[0]
        self.assertEqual(payload, before)
        self.assertEqual(row['schema'], 'driver_received_telemetry_v3')
        self.assertEqual(row['sender_clock_metadata_state'], 'versioned_sender_clock_observation')
        self.assertEqual(row['sender_clock_observation'], payload['sender_clock_observation'])
        self.assertEqual(row['odometry_observation'], payload['odometry_observation'])
        self.assertEqual(row['linear_mps'], .2); self.assertIsNone(row['source_clock_id'])
        self.assertIsNone(row['measurement_valid'])

    def test_clock_failures_preserve_old_values_and_odom_observation(self):
        node = self.node(); node.odom_callback(message(v=.2, w=-.1))
        node.get_clock.side_effect = RuntimeError('synthetic ROS clock error')
        payload = node.get_telemetry_dict()
        self.assertEqual(payload['sender_clock_observation']['status'], 'sampling_error')
        self.assertEqual(payload['linear_x'], .2)
        self.assertTrue(payload['odometry_observation']['callback_received'])

    def test_clock_constructor_or_snapshot_failure_is_optional(self):
        with patch('driver_sender_clock_observation.SenderClockObserver', side_effect=RuntimeError('synthetic init')):
            node = sender_node()
        node.odom_callback(message(v=.2, w=-.1))
        self.assertIsNone(node.get_telemetry_dict()['sender_clock_observation'])
        node._sender_clock_observer = NS(snapshot=Mock(side_effect=RuntimeError('synthetic snapshot')))
        self.assertEqual(node.get_telemetry_dict()['linear_x'], .2)
        self.assertIsNone(node.get_telemetry_dict()['sender_clock_observation'])

    def test_config_change_during_actual_ROS_read_rejected(self):
        node = self.node()
        node.get_parameter.side_effect = [NS(value=False), NS(value=True)]
        self.assertEqual(node.get_telemetry_dict()['sender_clock_observation']['status'], 'sampling_error')

    def test_foreign_sender_clock_not_associated_with_odom(self):
        payload = self.node().get_telemetry_dict()
        payload['sender_clock_observation']['sender_id'] = 'c'*32
        payload['sender_clock_observation']['sender_monotonic_clock_id'] = 'sender-process/'+'c'*32
        row = self.record([payload])[0]
        self.assertEqual(row['sender_clock_metadata_state'], 'sender_clock_scope_mismatch')
        self.assertIsNone(row['sender_clock_observation'])
        self.assertIsNotNone(row['odometry_observation'])

    def test_legacy_v1_v2_and_unknown_or_invalid_clock_are_preserved(self):
        full = self.node().get_telemetry_dict()
        v2 = dict(full); del v2['sender_clock_observation']
        v1 = dict(v2); del v1['odometry_observation']
        invalid = dict(full, sender_clock_observation=None)
        unknown = dict(full, sender_clock_observation={'schema':'future'})
        rows = self.record([v1, v2, invalid, unknown])
        self.assertEqual([r['schema'] for r in rows], ['driver_received_telemetry_v1',
            'driver_received_telemetry_v2', 'driver_received_telemetry_v3', 'driver_received_telemetry_v3'])
        self.assertEqual(rows[2]['sender_clock_metadata_state'], 'invalid_sender_clock_metadata')
        self.assertEqual(rows[3]['sender_clock_metadata_state'], 'unsupported_sender_clock_schema')

    def test_passive_queue_owns_clock_dictionary(self):
        payload = self.node().get_telemetry_dict()
        with tempfile.TemporaryDirectory() as temp:
            recorder = TelemetryRecorder(Path(temp)/'log', max_bytes=20000, max_records=10,
                                         queue_size=10, clock=lambda:100.)
            recorder.start()
            expected = dict(payload['sender_clock_observation'])
            try:
                recorder.offer('b'*32, payload, 1.)
                payload['sender_clock_observation']['ros_now_ns'] = 1
            finally:
                recorder.close()
            row = json.loads((recorder.directory/'received_telemetry.jsonl').read_bytes())
            self.assertEqual(row['sender_clock_observation'], expected)
