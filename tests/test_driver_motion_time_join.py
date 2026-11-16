"""Synthetic timestamps are not measured clock synchronization or FFB tests."""
import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_motion_handoff import FALSE_FLAGS, SCHEMA as RANGE_SCHEMA
from driver_motion_time_join import (MAX_LINE_BYTES, MotionLog, OfflineMotionJoiner,
    checked_clock_binding, checked_motion_record, motion_record, read_motion_records)

SESSION, CLOCK, SOURCE, PNG = 'a'*32, 'receiver/test-boot', 'ros/test-boot', 'b'*64
ANCHOR = 1_800_000_000_000_000_000


def binding(**changes):
    result = dict(schema='offline_motion_clock_binding_v1', session=SESSION,
        receiver_clock_id=CLOCK, source_clock_id=SOURCE, source_anchor_ns=ANCHOR,
        receiver_anchor_sec=10., valid_from_ns=ANCHOR-1_000_000_000,
        valid_to_ns=ANCHOR+1_000_000_000, error_bound_sec=.001,
        evidence_kind='synthetic_fixture_only', evidence_id='synthetic/clock-fixture')
    result.update(changes)
    return result


def measured(**changes):
    facts = dict(session=SESSION, receiver_clock_id=CLOCK, sequence=1, logged_at_sec=10.01,
        received_at_sec=10.005, source_kind='measured_odometry', motion_frame_id='base_link',
        source_clock_id=SOURCE, source_stamp_ns=ANCHOR, measurement_valid=True,
        linear_mps=.2, angular_radps=-.1)
    facts.update(changes)
    return motion_record(**facts)


def distance(frame=20, time=10.02, **changes):
    result = dict(schema=RANGE_SCHEMA, session=SESSION, frame=frame, source_time_sec=time,
        review_completed_time_sec=time+.01, evaluated_time_sec=time+.01,
        clock_basis='recorded_receiver_monotonic_NOT_ROS_or_wall_time', max_age_sec=.5,
        metric='horizontal_camera_foot_range_m_NOT_base_link_or_contact', input_verified=True,
        range_available=True, distance_m=1.2, reason='experimental', primary_model='ippe_0',
        reference_generation=1, reference_frame=5, reference_png_sha256=PNG,
        vehicle_xy_m=None, object_id=None, replay_only=True, **{k: False for k in FALSE_FLAGS})
    result.update(changes)
    return result


def joiner(**changes):
    args = dict(session=SESSION, receiver_clock_id=CLOCK, motion_frame_id='base_link',
        range_reference=dict(reference_frame=5, reference_png_sha256=PNG), clock_binding=binding(),
        max_skew_sec=.05, max_motion_age_sec=.1, max_clock_error_sec=.005)
    args.update(changes)
    return OfflineMotionJoiner(**args)


class MotionRecordTests(unittest.TestCase):
    def test_unknown_is_null_and_real_stop_preserved(self):
        unknown = motion_record(session=SESSION, receiver_clock_id=CLOCK, sequence=1, logged_at_sec=10.)
        self.assertIsNone(unknown['measurement_valid'])
        self.assertIsNone(unknown['linear_mps'])
        self.assertIsNone(unknown['received_at_sec'])
        stop = measured(linear_mps=0., angular_radps=0.)
        self.assertIs(stop['measurement_valid'], True)
        self.assertEqual(stop['linear_mps'], 0.)

    def test_strict_fields_flags_and_finite_values(self):
        for key, value in (('source_stamp_ns', True), ('source_stamp_ns', 1.5),
            ('source_stamp_ns', -1), ('source_stamp_ns', 2**63), ('sequence', True),
            ('linear_mps', True), ('linear_mps', float('nan')), ('angular_radps', float('inf')),
            ('logged_at_sec', True), ('received_at_sec', 10.02), ('measurement_valid', 1),
            ('source_kind', 'guess'), ('receiver_clock_id', ''), ('session', 'unknown')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                measured(**{key: value})
        for key, value in (('usable_for_ffb', True), ('published_to_ros', 0),
                           ('replay_only', False), ('ffb_command', 1)):
            value_dict = dict(measured(), **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                checked_motion_record(value_dict)

    def test_exclusive_json_log_roundtrip_and_no_input_mutation(self):
        record = measured(); before = copy.deepcopy(record)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'motion.jsonl'
            with MotionLog(path, session=SESSION, receiver_clock_id=CLOCK, max_records=2, max_bytes=4000) as log:
                log.write(record)
                log.write(measured(sequence=2, logged_at_sec=10.02, received_at_sec=10.015,
                                   source_stamp_ns=ANCHOR+10_000_000))
                self.assertEqual(log.records, 2)
                self.assertEqual(log.bytes, path.stat().st_size)
            restored = list(read_motion_records(path))
            self.assertEqual(restored[0], before)
            self.assertEqual(record, before)
            self.assertIs(type(restored[0]['source_stamp_ns']), int)
            saved = path.read_bytes()
            with self.assertRaises(FileExistsError):
                MotionLog(path, session=SESSION, receiver_clock_id=CLOCK, max_records=2, max_bytes=4000)
            self.assertEqual(path.read_bytes(), saved)

    def test_log_limits_reject_without_extra_bytes(self):
        for max_records, max_bytes in ((1, 4000), (2, 1)):
            with self.subTest(max_records=max_records), tempfile.TemporaryDirectory() as temp:
                path = Path(temp)/'log.jsonl'
                with MotionLog(path, session=SESSION, receiver_clock_id=CLOCK,
                               max_records=max_records, max_bytes=max_bytes) as log:
                    if max_bytes > 1:
                        log.write(measured())
                    before = path.read_bytes()
                    with self.assertRaises(ValueError):
                        log.write(measured(sequence=2))
                    self.assertEqual(path.read_bytes(), before)

    def test_log_scope_and_record_order(self):
        with tempfile.TemporaryDirectory() as temp:
            with MotionLog(Path(temp)/'log', session=SESSION, receiver_clock_id=CLOCK,
                           max_records=10, max_bytes=20000) as log:
                log.write(measured())
                for item in (measured(), measured(sequence=2, session='c'*32),
                             measured(sequence=2, receiver_clock_id='other'),
                             measured(sequence=2, logged_at_sec=10.006)):
                    with self.assertRaises(ValueError):
                        log.write(item)
                self.assertEqual(log.records, 1)

    def test_reader_rejects_truncation_duplicate_nonfinite_oversize_and_limits(self):
        valid = json.dumps(measured()).encode()+b'\n'
        invalids = (valid[:-1], b'{"sequence":1,"sequence":2}\n',
                    valid.replace(b'0.2', b'NaN'), b' '*MAX_LINE_BYTES+b'\n')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'log'
            for data in invalids:
                path.write_bytes(data)  # test corruption fixture only, never user evidence
                with self.subTest(data=data[:30]), self.assertRaises(ValueError):
                    list(read_motion_records(path))
            path.write_bytes(valid+valid)
            with self.assertRaises(ValueError):
                list(read_motion_records(path, max_records=1))
            with self.assertRaises(ValueError):
                list(read_motion_records(path, max_bytes=1))

    def test_invalid_writer_and_reader_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'log'
            for args in (dict(max_records=True, max_bytes=100), dict(max_records=1, max_bytes=0)):
                with self.assertRaises(ValueError):
                    MotionLog(path, session=SESSION, receiver_clock_id=CLOCK, **args)
                self.assertFalse(path.exists())
            with self.assertRaises(ValueError):
                list(read_motion_records(path, max_records=False))


class MotionJoinTests(unittest.TestCase):
    def test_signed_measured_values_and_measured_stop_survive_pairing(self):
        for v, w in ((.2, -.1), (-.2, .1), (0., 0.)):
            engine = joiner()
            record = measured(linear_mps=v, angular_radps=w)
            before = copy.deepcopy(record)
            self.assertEqual(engine.push_motion(record, now_sec=10.01), 'motion_candidate')
            result = engine.join(distance(), now_sec=10.03)
            self.assertTrue(result['pair_available'])
            self.assertEqual(result['measured_motion']['linear_mps'], v)
            self.assertEqual(result['measured_motion']['angular_radps'], w)
            self.assertEqual(result['measured_motion']['source_stamp_ns'], ANCHOR)
            self.assertEqual(result['measured_motion']['clock_evidence_kind'], 'synthetic_fixture_only')
            self.assertIsNone(result['vehicle_xy_m'])
            for flag in ('usable_for_ffb', 'published_to_ros', 'steering_gradient_available',
                         'exposure_time_alignment_verified', 'clock_alignment_independently_verified'):
                self.assertIs(result[flag], False)
            self.assertEqual(before, record)

    def test_missing_motion_keeps_distance_but_not_a_pair(self):
        result = joiner().join(distance(), now_sec=10.03)
        self.assertFalse(result['pair_available'])
        self.assertIsNone(result['measured_motion'])
        self.assertEqual(result['reason'], 'motion_not_received')
        self.assertEqual(result['range_sample']['distance_m'], 1.2)

    def test_unknown_motion_and_invalid_updates_clear_old_candidate(self):
        cases = [({}, 'invalid_motion_record'),
            (measured(sequence=2, received_at_sec=None), 'motion_not_received'),
            (measured(sequence=2, received_at_sec=10.006, source_kind='command'), 'motion_not_measured_odometry'),
            (measured(sequence=2, received_at_sec=10.006, source_kind='legacy_telemetry'), 'motion_not_measured_odometry'),
            (measured(sequence=2, received_at_sec=10.006, measurement_valid=None), 'motion_measurement_invalid_or_missing'),
            (measured(sequence=2, received_at_sec=10.006, measurement_valid=False), 'motion_measurement_invalid_or_missing'),
            (measured(sequence=2, received_at_sec=10.006, linear_mps=None), 'motion_measurement_invalid_or_missing'),
            (measured(sequence=2, received_at_sec=10.006, motion_frame_id='map'), 'motion_frame_mismatch')]
        for update, reason in cases:
            with self.subTest(reason=reason):
                engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
                engine.push_motion(update, now_sec=10.015)
                result = engine.join(distance(), now_sec=10.03)
                self.assertFalse(result['pair_available'])
                self.assertIsNone(result['measured_motion'])
                self.assertEqual(result['reason'], reason)

    def test_missing_wrong_and_out_of_scope_clock_declarations(self):
        cases = [({'clock_binding': None}, measured(), 'motion_clock_mapping_missing'),
            ({}, measured(source_stamp_ns=None), 'motion_clock_mapping_missing'),
            ({}, measured(source_clock_id=None), 'motion_clock_mapping_missing'),
            ({}, measured(source_clock_id='wall/other'), 'motion_source_clock_mismatch'),
            ({}, measured(source_stamp_ns=ANCHOR-2_000_000_000), 'motion_clock_binding_out_of_scope'),
            ({'clock_binding': binding(error_bound_sec=.006)}, measured(), 'motion_clock_error_too_large')]
        for options, record, reason in cases:
            with self.subTest(reason=reason):
                engine = joiner(**options)
                self.assertEqual(engine.push_motion(record, now_sec=10.01), reason)
                self.assertFalse(engine.join(distance(), now_sec=10.03)['pair_available'])

    def test_clock_binding_validation_scope_and_input_copy(self):
        for changes in (dict(source_anchor_ns=True), dict(error_bound_sec=-.1),
                        dict(error_bound_sec=float('nan')), dict(valid_to_ns=ANCHOR-1),
                        dict(evidence_kind='assumed'), dict(evidence_id='')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                checked_clock_binding(binding(**changes))
        for changes in (dict(session='b'*32), dict(receiver_clock_id='other')):
            with self.assertRaises(ValueError):
                joiner(clock_binding=binding(**changes))
        b = binding(); engine = joiner(clock_binding=b)
        b['receiver_anchor_sec'] = 999.
        self.assertEqual(engine.push_motion(measured(), now_sec=10.01), 'motion_candidate')

    def test_no_policy_defaults_and_invalid_tolerances(self):
        for key in ('max_skew_sec', 'max_motion_age_sec', 'max_clock_error_sec'):
            for val in (True, -.1, .501, float('nan')):
                with self.subTest(key=key, val=val), self.assertRaises(ValueError):
                    joiner(**{key: val})
        with self.assertRaises(TypeError):
            OfflineMotionJoiner(session=SESSION)

    def test_future_measurement_interval_after_actual_receive_rejected(self):
        engine = joiner(clock_binding=binding(error_bound_sec=.01), max_clock_error_sec=.01)
        self.assertEqual(engine.push_motion(measured(), now_sec=10.01),
                         'motion_measurement_interval_after_reception')
        self.assertFalse(engine.join(distance(), now_sec=10.03)['pair_available'])

    def test_future_to_video_receive_not_nearest_selected(self):
        engine = joiner()
        engine.push_motion(measured(source_stamp_ns=ANCHOR+4_000_000,
                                    received_at_sec=10.006), now_sec=10.01)
        result = engine.join(distance(time=10.002), now_sec=10.03)
        self.assertEqual(result['reason'], 'motion_not_entirely_past_video_receive')
        self.assertIsNone(result['measured_motion'])

    def test_error_interval_not_just_midpoint_used_for_skew_and_age(self):
        engine = joiner(max_skew_sec=.02)
        engine.push_motion(measured(), now_sec=10.01)
        result = engine.join(distance(time=10.02), now_sec=10.03)
        self.assertEqual(result['reason'], 'motion_video_receive_skew_too_large')
        engine = joiner(max_motion_age_sec=.05)
        engine.push_motion(measured(), now_sec=10.01)
        result = engine.join(distance(time=10.04), now_sec=10.05)
        self.assertEqual(result['reason'], 'motion_measurement_stale')

    def test_old_measurement_not_rejuvenated_by_new_reception_or_logging(self):
        engine = joiner()
        engine.push_motion(measured(source_stamp_ns=ANCHOR-200_000_000), now_sec=10.01)
        result = engine.join(distance(), now_sec=10.03)
        self.assertEqual(result['reason'], 'motion_measurement_stale')
        self.assertIsNone(engine.current)

    def test_duplicate_reversed_source_and_record_revoke_candidate(self):
        cases = [(measured(), 'motion_out_of_order_or_future_record'),
            (measured(sequence=2, received_at_sec=10.004), 'motion_repeated_or_reversed_reception'),
            (measured(sequence=2, received_at_sec=10.006), 'motion_source_stamp_repeated_or_reversed'),
            (measured(sequence=2, received_at_sec=10.006, source_stamp_ns=ANCHOR-1), 'motion_source_stamp_repeated_or_reversed'),
            (measured(sequence=2, received_at_sec=10.006, logged_at_sec=10.009), 'motion_out_of_order_or_future_record'),
            (measured(sequence=2, received_at_sec=10.006, logged_at_sec=11.), 'motion_out_of_order_or_future_record')]
        for update, reason in cases:
            with self.subTest(reason=reason):
                engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
                self.assertEqual(engine.push_motion(update, now_sec=10.015), reason)
                self.assertFalse(engine.join(distance(), now_sec=10.03)['pair_available'])

    def test_foreign_motion_session_or_clock_clears_candidate(self):
        for changes in (dict(session='c'*32), dict(receiver_clock_id='other/boot')):
            engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
            reason = engine.push_motion(measured(sequence=2, **changes), now_sec=10.015)
            self.assertEqual(reason, 'motion_session_or_clock_mismatch')
            self.assertFalse(engine.join(distance(), now_sec=10.03)['pair_available'])

    def test_receiver_invalid_clock_and_rollback_clear_both(self):
        for now in (float('nan'), float('inf'), True, -.1, 9.):
            engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
            self.assertTrue(engine.join(distance(), now_sec=10.03)['pair_available'])
            with self.subTest(now=now), self.assertRaises(ValueError):
                engine.join(distance(frame=21), now_sec=now)
            self.assertIsNone(engine.current)
            self.assertIsNone(engine.range.current)

    def test_range_veto_stale_foreign_and_duplicate_never_get_pair(self):
        cases = [(distance(range_available=False, distance_m=None, reason='possible_self_body_occlusion'), 10.03),
            (distance(), 10.6), (distance(session='d'*32), 10.03),
            (distance(reference_generation=2), 10.03), (distance(frame=20), 10.04)]
        for packet, now in cases:
            engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
            engine.join(distance(frame=20 if now == 10.04 else 19, time=10.015), now_sec=10.025)
            result = engine.join(packet, now_sec=now)
            self.assertFalse(result['pair_available'])
            self.assertIsNone(result['measured_motion'])

    def test_after_withheld_fresh_actual_measurement_can_resume_without_old_pair(self):
        engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
        self.assertTrue(engine.join(distance(), now_sec=10.03)['pair_available'])
        result = engine.join(distance(frame=21, time=10.04, range_available=False,
                                      distance_m=None, reason='no_candidate'), now_sec=10.05)
        self.assertFalse(result['pair_available'])
        self.assertIsNone(result['measured_motion'])
        engine.push_motion(measured(sequence=2, source_stamp_ns=ANCHOR+50_000_000,
            received_at_sec=10.055, logged_at_sec=10.06), now_sec=10.06)
        self.assertTrue(engine.join(distance(frame=22, time=10.07), now_sec=10.08)['pair_available'])

    def test_binding_changes_pair_provenance_digest(self):
        digests = []
        for evidence in ('synthetic/A', 'synthetic/B'):
            engine = joiner(clock_binding=binding(evidence_id=evidence))
            engine.push_motion(measured(), now_sec=10.01)
            digests.append(engine.join(distance(), now_sec=10.03)['measured_motion']['clock_binding_sha256'])
        self.assertNotEqual(*digests)

    def test_integer_ns_mapping_uses_anchor_delta_not_large_epoch_float(self):
        # A 100 ns delta survives because integer subtraction precedes /1e9.
        engine = joiner(clock_binding=binding(error_bound_sec=0.))
        engine.push_motion(measured(source_stamp_ns=ANCHOR+100), now_sec=10.01)
        result = engine.join(distance(), now_sec=10.03)
        self.assertEqual(result['measured_motion']['mapped_source_time_sec'], 10.0000001)

    def test_inclusive_binary_exact_policy_boundaries(self):
        engine = joiner(clock_binding=binding(error_bound_sec=0.), max_clock_error_sec=0.,
                        max_skew_sec=.0625, max_motion_age_sec=.125)
        engine.push_motion(measured(), now_sec=10.01)
        self.assertTrue(engine.join(distance(time=10.0625), now_sec=10.125)['pair_available'])
        # The entire uncertainty interval ends exactly at video reception.
        engine = joiner(clock_binding=binding(error_bound_sec=.00390625),
            max_clock_error_sec=.00390625, max_skew_sec=.0078125, max_motion_age_sec=.25)
        engine.push_motion(measured(), now_sec=10.01)
        self.assertTrue(engine.join(distance(time=10.00390625), now_sec=10.03)['pair_available'])

    def test_enormous_numbers_cannot_bypass_clock_revocation(self):
        huge = 10**1000
        with self.assertRaises(ValueError):
            measured(linear_mps=huge)
        engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
        self.assertTrue(engine.join(distance(), now_sec=10.03)['pair_available'])
        with self.assertRaises(ValueError):
            engine.join(distance(frame=21), now_sec=huge)
        self.assertIsNone(engine.current)
        self.assertIsNone(engine.range.current)
        engine = joiner(); engine.push_motion(measured(), now_sec=10.01)
        result = engine.join(distance(source_time_sec=huge), now_sec=10.03)
        self.assertFalse(result['pair_available'])
        self.assertIsNone(result['measured_motion'])

    def test_no_ros_torch_hardware_or_live_imports(self):
        source = ROOT/'src/driver_motion_time_join.py'
        tree = ast.parse(source.read_text())
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imports, {'driver_motion_handoff'})
        normal = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual(normal, {'hashlib', 'json', 'math', 're'})
        for path in (ROOT/'src').glob('*.py'):
            if path != source:
                self.assertNotIn('driver_motion_time_join', path.read_text(), str(path))


if __name__ == '__main__':
    unittest.main()
