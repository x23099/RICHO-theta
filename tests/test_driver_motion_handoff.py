"""Offline data transport only. No ROS, hardware or G923 commands."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_body_display_guard import CLEAR, FLAGS, SCHEMA as REVIEW_SCHEMA
from driver_motion_handoff import MAX_AGE_SEC, OfflineRangeReceiver, checked_sample, make_range_sample

SESSION = 'a'*32
PNG = 'b'*64


def event(frame=20, source=10., *, available=True, reason='experimental'):
    value = dict(session=SESSION, frame=frame, source_time_sec=source,
        distance_available=True, horizontal_camera_foot_range_m=1.2,
        reason='experimental', primary_model='ippe_0', **{k: False for k in FLAGS})
    review = dict(schema=REVIEW_SCHEMA, session=SESSION, frame=frame, source_time_sec=source,
        original_available=True, original_range_m=1.2, display_available=available,
        display_range_m=1.2 if available else None, reason=reason,
        body_review_reason=CLEAR if available else reason,
        reference_generation=1, reference_frame=5, reference_png_sha256=PNG,
        reference_scope_verified=True, completed_time_sec=source+.02, **{k: False for k in FLAGS})
    return dict(result=value, display_review=review, accepted_current_session_and_age=True)


def receiver():
    return OfflineRangeReceiver(SESSION, reference_frame=5, reference_png_sha256=PNG)


def packet(item=None, now=10.03):
    return make_range_sample(event() if item is None else item, session=SESSION, now_source_clock_sec=now)


class MotionHandoffTests(unittest.TestCase):
    def test_valid_distance_survives_json_without_unit_or_value_change(self):
        sample = packet()
        decision = receiver().receive(json.loads(json.dumps(sample, allow_nan=False)), now_source_clock_sec=10.04)
        self.assertTrue(decision['range_available'])
        self.assertEqual(decision['distance_m'], 1.2)
        self.assertEqual(decision['frame'], 20)
        self.assertEqual(decision['source_time_sec'], 10.)
        self.assertAlmostEqual(decision['age_sec'], .04)
        self.assertIn('camera_foot', decision['metric'])
        self.assertIsNone(decision['vehicle_xy_m'])
        self.assertIsNone(decision['object_id'])
        for key in (*FLAGS, 'steering_gradient_available', 'ffb_command_generated'):
            self.assertIs(decision[key], False)

    def test_source_and_nested_review_not_mutated(self):
        item = event()
        before = copy.deepcopy(item)
        packet(item)
        self.assertEqual(item, before)

    def test_display_veto_revokes_raw_numeric_value_and_clears_previous(self):
        inbox = receiver()
        self.assertTrue(inbox.receive(packet(), now_source_clock_sec=10.03)['range_available'])
        item = event(21, 10.1, available=False, reason='possible_self_body_occlusion')
        sample = packet(item, now=10.13)
        self.assertTrue(sample['input_verified'])
        self.assertIsNone(sample['distance_m'])
        result = inbox.receive(sample, now_source_clock_sec=10.14)
        self.assertFalse(result['range_available'])
        self.assertIsNone(result['distance_m'])
        self.assertEqual(result['reason'], 'possible_self_body_occlusion')

    def test_original_no_candidate_is_unknown_not_clear_or_zero(self):
        item = event(available=False, reason='no_candidate')
        item['result'].update(distance_available=False, horizontal_camera_foot_range_m=None, reason='no_candidate')
        item['display_review'].update(original_available=False, original_range_m=None,
            reference_scope_verified=False, reference_generation=None, reference_frame=None,
            reference_png_sha256=None, body_review_reason='original_withheld')
        sample = packet(item)
        self.assertTrue(sample['input_verified'])
        self.assertIsNone(sample['distance_m'])
        result = receiver().receive(sample, now_source_clock_sec=10.04)
        self.assertEqual(result['reason'], 'no_candidate')
        self.assertIsNone(result['distance_m'])

    def test_source_stale_and_future_produce_no_distance(self):
        for now, reason in ((10.501, 'handoff_sample_stale'), (10.01, 'handoff_source_or_review_in_future')):
            with self.subTest(now=now):
                sample = packet(now=now)
                self.assertFalse(sample['range_available'])
                self.assertIsNone(sample['distance_m'])
                self.assertEqual(sample['reason'], reason)

    def test_exact_age_boundary_and_late_delivery(self):
        sample = packet(now=10.5)
        self.assertTrue(receiver().receive(sample, now_source_clock_sec=10.5)['range_available'])
        decision = receiver().receive(sample, now_source_clock_sec=10.500001)
        self.assertFalse(decision['range_available'])
        self.assertIsNone(decision['distance_m'])

    def test_snapshot_timeout_clears_value_permanently(self):
        inbox = receiver()
        inbox.receive(packet(), now_source_clock_sec=10.03)
        self.assertFalse(inbox.snapshot(now_source_clock_sec=10.6)['range_available'])
        self.assertFalse(inbox.snapshot(now_source_clock_sec=10.04)['range_available'])

    def test_invalid_consumer_clock_clears_value_even_if_caller_catches_exception(self):
        for method in ('receive', 'snapshot'):
            with self.subTest(method=method):
                inbox = receiver()
                inbox.receive(packet(), now_source_clock_sec=10.03)
                with self.assertRaises(ValueError):
                    if method == 'receive':
                        inbox.receive(packet(), now_source_clock_sec=float('nan'))
                    else:
                        inbox.snapshot(now_source_clock_sec=float('nan'))
                result = inbox.snapshot(now_source_clock_sec=10.04)
                self.assertIsNone(result['distance_m'])
                self.assertEqual(result['reason'], 'handoff_invalid_clock')

    def test_duplicate_or_reverse_frame_clears_previous_value(self):
        for frame in (20, 19):
            with self.subTest(frame=frame):
                inbox = receiver()
                inbox.receive(packet(), now_source_clock_sec=10.03)
                result = inbox.receive(packet(event(frame, 10.1), now=10.13), now_source_clock_sec=10.14)
                self.assertEqual(result['reason'], 'handoff_duplicate_or_out_of_order')
                self.assertIsNone(result['distance_m'])

    def test_reverse_source_time_rejected_even_with_new_frame(self):
        inbox = receiver()
        inbox.receive(packet(), now_source_clock_sec=10.03)
        result = inbox.receive(packet(event(21, 9.9), now=9.93), now_source_clock_sec=10.04)
        self.assertEqual(result['reason'], 'handoff_duplicate_or_out_of_order')

    def test_other_session_rejected_in_converter_and_receiver(self):
        item = event()
        item['result']['session'] = 'c'*32
        self.assertFalse(packet(item)['input_verified'])
        other = dict(packet(), session='c'*32)
        self.assertEqual(receiver().receive(other, now_source_clock_sec=10.04)['reason'], 'handoff_session_mismatch')

    def test_reference_generation_frame_and_digest_mismatch_rejected(self):
        for change in (dict(reference_generation=2), dict(reference_frame=6), dict(reference_png_sha256='c'*64)):
            with self.subTest(change=change):
                result = receiver().receive(dict(packet(), **change), now_source_clock_sec=10.04)
                self.assertEqual(result['reason'], 'handoff_reference_mismatch')
                self.assertIsNone(result['distance_m'])

    def test_retired_bridge_result_never_revives(self):
        item = event()
        item['accepted_current_session_and_age'] = False
        sample = packet(item)
        self.assertFalse(sample['input_verified'])
        self.assertEqual(sample['reason'], 'handoff_bridge_result_retired')
        self.assertIsNone(receiver().receive(sample, now_source_clock_sec=10.04)['distance_m'])

    def test_bridge_acceptance_requires_bool_not_integer(self):
        item = event()
        item['accepted_current_session_and_age'] = 1
        sample = packet(item)
        self.assertEqual(sample['reason'], 'handoff_invalid_bridge_acceptance')
        self.assertIsNone(sample['distance_m'])

    def test_missing_or_extra_wire_fields_clear_previous_distance(self):
        for change in ('missing', 'extra'):
            with self.subTest(change=change):
                inbox = receiver()
                inbox.receive(packet(), now_source_clock_sec=10.03)
                changed = packet(event(21, 10.1), now=10.13)
                if change == 'missing':
                    del changed['replay_only']
                else:
                    changed['normalized_magnitude'] = .05
                result = inbox.receive(changed, now_source_clock_sec=10.14)
                self.assertEqual(result['reason'], 'handoff_invalid_packet')
                self.assertIsNone(result['distance_m'])

    def test_wire_future_evaluation_and_invalid_review_time_rejected(self):
        future = dict(packet(), evaluated_time_sec=10.2)
        self.assertEqual(receiver().receive(future, now_source_clock_sec=10.04)['reason'],
                         'handoff_source_or_review_in_future')
        with self.assertRaises(ValueError):
            checked_sample(dict(packet(), review_completed_time_sec=float('nan')))

    def test_offline_module_has_no_live_entrypoint_imports(self):
        import ast
        source = (ROOT/'src/driver_motion_handoff.py').read_text()
        imports = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertFalse(any(name.startswith(('rclpy', 'evdev', 'collision_ffb', 'virtual_ffb', 'torch')) for name in imports))
        for name in ('webrtc_receive_ui.py', 'driver_motion_bridge.py', 'driver_motion_process.py',
                     'collision_ffb_publisher.py', 'collision_ffb_relay.py', 'bird_eye.py'):
            self.assertNotIn('driver_motion_handoff', (ROOT/'src'/name).read_text())

    def test_invalid_raw_or_review_cannot_grant_authority(self):
        changes = (('result', 'horizontal_camera_foot_range_m', float('nan')),
                   ('result', 'controlling_distance', True), ('display_review', 'usable_for_ffb', True),
                   ('display_review', 'frame', 21), ('display_review', 'display_range_m', 1.3))
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                item = event()
                item[section][key] = value
                sample = packet(item)
                self.assertFalse(sample['input_verified'])
                self.assertIsNone(sample['distance_m'])

    def test_wire_schema_nonfinite_null_and_permission_tampering_rejected(self):
        for change in (dict(schema='CollisionFfbCommand'), dict(distance_m=float('inf')),
                       dict(range_available=False), dict(usable_for_ffb=True), dict(published_to_ros=True),
                       dict(object_id=1), dict(vehicle_xy_m=[1.2, 0]), dict(max_age_sec=1.),
                       dict(evaluated_time_sec=float('nan')), dict(frame=True)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                checked_sample(dict(packet(), **change))

    def test_input_clock_and_session_are_explicit_not_wall_time_defaults(self):
        for now in (True, -1., float('nan'), float('inf')):
            with self.subTest(now=now), self.assertRaises(ValueError):
                packet(now=now)
        with self.assertRaises(ValueError):
            OfflineRangeReceiver('not-a-session', reference_frame=5, reference_png_sha256=PNG)

    def test_late_source_clock_does_not_retime_historical_sample(self):
        sample = packet()
        self.assertFalse(receiver().receive(sample, now_source_clock_sec=1_000_000.)['range_available'])
        self.assertEqual(sample['source_time_sec'], 10.)
        self.assertEqual(sample['evaluated_time_sec'], 10.03)


if __name__ == '__main__':
    unittest.main()
