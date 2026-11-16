"""Offline transfer invariants. Fixtures are not physical measurements."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


adapter = module('received_motion_adapter',
    'Experimental_results/2026-11-16/received_motion_handoff_r01/adapter.py')
fixtures = module('received_motion_fixtures', 'tests/test_odometry_metadata_live_audit.py')
join_fixtures = module('existing_join_fixtures', 'tests/test_driver_motion_time_join.py')
from driver_odometry_observation import OdometryObserver


def row(v=0., w=0., received=True):
    rows, _, _ = fixtures.fixture()
    result = rows[1]
    if received:
        observer = OdometryObserver(clock=lambda: 10.)
        observer.observe(NS(header=NS(stamp=NS(sec=1794822450, nanosec=209981778), frame_id='odom'),
            child_frame_id='base_footprint', twist=NS(twist=NS(linear=NS(x=v), angular=NS(z=w)))))
        result['odometry_observation'] = observer.snapshot()
    return result


def transfer(value):
    return adapter.transfer(value, session=value['session'], receiver_clock_id=value['receiver_clock_id'])


class ReceivedMotionHandoffTests(unittest.TestCase):
    def test_received_zero_stamp_frame_and_scope_preserved_without_authority(self):
        value = row(); output = transfer(value); m = output['motion_record']
        self.assertEqual(m['source_stamp_ns'], 1794822450209981778)
        self.assertEqual(m['motion_frame_id'], 'base_footprint')
        for key in ('sequence', 'session', 'receiver_clock_id', 'received_at_sec', 'logged_at_sec'):
            self.assertEqual(m[key], value[key])
        self.assertEqual((m['linear_mps'], m['angular_radps']), (0., 0.))
        self.assertIsNone(m['source_clock_id']); self.assertIsNone(m['measurement_valid'])
        self.assertFalse(output['pairing_eligible']); self.assertFalse(m['usable_for_ffb'])

    def test_forward_reverse_signed_values_preserved(self):
        for v, w in ((.2, -.1), (-.2, .1), (0., 0.)):
            m = transfer(row(v, w))['motion_record']
            self.assertEqual((m['linear_mps'], m['angular_radps']), (v, w))

    def test_not_received_and_legacy_zero_do_not_become_observed_zero(self):
        a = row(received=False)
        b = dict(a); b.pop('odometry_observation'); b.pop('odometry_metadata_state')
        b['schema'] = 'driver_received_telemetry_v1'
        for value in (a, b):
            output = transfer(value); m = output['motion_record']
            self.assertIsNone(m['linear_mps']); self.assertIsNone(m['angular_radps'])
            self.assertIsNone(m['source_stamp_ns']); self.assertIsNone(m['source_kind'])
            self.assertTrue(output['hold_reasons'])

    def test_bad_metadata_rejected_without_legacy_fallback(self):
        for state in ('unsupported_odometry_schema', 'invalid_odometry_metadata'):
            value = row(); value.update(odometry_observation=None, odometry_metadata_state=state)
            result = transfer(value)
            self.assertIsNone(result['motion_record']['linear_mps'])
            self.assertIn(state, result['hold_reasons'])

    def test_input_and_returned_observation_are_independent(self):
        value = row(); before = copy.deepcopy(value); out = transfer(value)
        out['observation']['invalid_fields'].append('changed')
        self.assertEqual(value, before)

    def test_scope_invalid_fields_authority_and_lifecycle_rejected(self):
        for key, item in (('schema', 'unknown'), ('measurement_valid', True), ('usable_for_ffb', True),
                          ('event_kind', 'peer_begin'), ('logged_at_sec', 0.), ('unexpected', 1)):
            value = row(); value[key] = item
            with self.subTest(key=key), self.assertRaises(ValueError):
                transfer(value)
        value = row()
        for args in (dict(session='e'*32, receiver_clock_id=value['receiver_clock_id']),
                     dict(session=value['session'], receiver_clock_id='another/clock')):
            with self.assertRaises(ValueError):
                adapter.transfer(value, **args)

    def test_structure_valid_does_not_grant_measurement_validity(self):
        value = row(); self.assertTrue(value['odometry_observation']['sample_fields_valid'])
        output = transfer(value)
        self.assertIsNone(output['motion_record']['measurement_valid'])
        self.assertIn('measurement_validity_unverified', output['hold_reasons'])
        self.assertIn('clock_mapping_missing', output['hold_reasons'])

    def test_repeated_or_reversed_stamp_kept_with_hold_diagnostic(self):
        for status in ('repeated', 'reversed'):
            value = row(); value['odometry_observation']['stamp_status'] = status
            output = transfer(value)
            self.assertIn('original_stamp_'+status, output['hold_reasons'])
            self.assertFalse(output['pairing_eligible'])

    def test_unverified_new_observation_clears_old_synthetic_join_candidate(self):
        engine = join_fixtures.joiner()
        self.assertEqual(engine.push_motion(join_fixtures.measured(), now_sec=10.01), 'motion_candidate')
        value = row(); value.update(session=engine.session, receiver_clock_id=engine.clock,
            sequence=2, received_at_sec=10.006, logged_at_sec=10.015)
        reason = engine.push_motion(transfer(value)['motion_record'], now_sec=10.015)
        self.assertEqual(reason, 'motion_measurement_invalid_or_missing')
        result = engine.join(join_fixtures.distance(), now_sec=10.03)
        self.assertTrue(result['range_sample']['range_available'])
        self.assertFalse(result['pair_available']); self.assertIsNone(result['measured_motion'])

    def test_observer_unknown_is_not_an_observed_measurement(self):
        value = row(received=False)
        value['odometry_observation'].update(stamp_status='observer_busy',
            callback_received=None, callback_sequence=None)
        result = transfer(value)
        self.assertIn('odometry_callback_state_unknown', result['hold_reasons'])
        self.assertIsNone(result['motion_record']['linear_mps'])
