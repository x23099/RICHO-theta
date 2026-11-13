"""Serialized stream prototype tests; no camera/GPU/network/ROS/control."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cone_distance_core import load_config
from cone_guarded_stream_comparison import GuardedStreamComparison
from cone_motion_range import FLAGS, MotionRangeEngine, load_motion_profile
from cone_upper_support_candidate import observe_upper_completion
from theta_rtc_frames import NativeFrame

SESSION = 'a' * 32
BOX = dict(x1=301., y1=305., x2=339., y2=399.6, confidence=.95, class_id=0)


class StreamComparisonTests(unittest.TestCase):
    def setUp(self):
        self.settings, self.camera, _, _ = load_config()
        profile_path = ROOT / ('Experimental_results/2026-11-09/'
            'cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json')
        self.profile, self.sha = load_motion_profile(profile_path, self.settings)
        self.time = 10.
        self.stream = self.new_stream()
        self.image = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillPoly(self.image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
        self.image.flags.writeable = False
        ok, encoded = cv2.imencode('.png', self.image)
        self.assertTrue(ok)
        self.png = encoded.tobytes()
        self.reference = dict(schema='offline_self_body_boundary_v1', image_size=[1280, 720],
            layout='dual_fisheye_front_left_unremapped', session=SESSION, source_frame=1,
            source_png_sha256=hashlib.sha256(self.png).hexdigest(),
            boundary_xy=[[280, 458], [360, 458]], independent_physical_measurement=False,
            cross_session_mount_verified=False, live_authorized=False, floor_contact_verified=False)

    def new_stream(self):
        return GuardedStreamComparison(self.settings, self.camera, self.profile, self.sha,
            acknowledged=True, clock=lambda: self.time)

    def frame(self, sequence=1, source=10., session=SESSION):
        return NativeFrame(session, sequence, source-10., source, self.image)

    def admit(self, frame):
        self.time = frame.received_at+.01
        self.stream.admit(frame.session, frame.sequence, frame.received_at)

    def main_result(self, frame, boxes=None):
        engine = MotionRangeEngine(self.settings, self.camera, self.profile, self.sha,
            acknowledged=True, observer=observe_upper_completion)
        return engine.measure(frame, [BOX] if boxes is None else boxes, frame.received_at+.005)

    def activate(self):
        frame = self.frame()
        self.admit(frame)
        self.stream.pin_reference_frame(frame)
        self.stream.activate(self.reference, self.png)

    def next_result(self, sequence=2, source=10.03, boxes=None):
        frame = self.frame(sequence, source)
        self.admit(frame)
        return self.stream.compare(frame, [BOX] if boxes is None else boxes, self.main_result(frame, boxes))

    def test_explicit_opt_in_required(self):
        with self.assertRaises(ValueError):
            GuardedStreamComparison(self.settings, self.camera, self.profile, self.sha)

    def test_no_reference_never_outputs_a_comparison_distance(self):
        row = self.next_result()
        self.assertFalse(row['comparison_distance_available'])
        self.assertEqual(row['reason'], 'comparison_reference_not_loaded')

    def test_future_frame_can_use_verified_reference_without_changing_main(self):
        self.activate()
        frame = self.frame(2, 10.03);self.admit(frame)
        original = self.main_result(frame);before = copy.deepcopy(original)
        image_before = frame.image.tobytes()
        row = self.stream.compare(frame, [BOX], original)
        self.assertTrue(row['baseline_reproduced'])
        self.assertTrue(row['comparison_distance_available'])
        self.assertEqual(row['comparison_support_pixel'], [320, 400])
        self.assertFalse(row['original_distance_available'])
        self.assertFalse(row['reference_used_posthoc'])
        self.assertEqual(original, before);self.assertEqual(frame.image.tobytes(), image_before)
        self.assertEqual(self.stream.poll(SESSION), row)

    def test_source_or_pre_activation_frame_is_never_recomputed(self):
        self.activate()
        frame = self.frame()
        row = self.stream.compare(frame, [BOX], self.main_result(frame))
        self.assertFalse(row['comparison_distance_available'])
        self.assertEqual(row['reason'], 'comparison_waiting_for_post_activation_frame')

    def test_queued_frame_received_before_load_completion_is_not_used(self):
        self.activate()
        row = self.next_result(2, 10.005)
        self.assertFalse(row['comparison_distance_available'])
        self.assertEqual(row['reason'], 'comparison_waiting_for_post_activation_frame')
        self.assertTrue(self.next_result(3, 10.03)['comparison_distance_available'])

    def test_self_body_veto_preserved(self):
        self.reference['boundary_xy'] = [[280, 400], [360, 400]]
        self.activate()
        row = self.next_result()
        self.assertFalse(row['comparison_distance_available'])
        self.assertEqual(row['body_review_reason'], 'possible_self_body_occlusion')

    def test_current_no_candidate_never_holds_previous_number(self):
        self.activate();self.assertTrue(self.next_result()['comparison_distance_available'])
        row = self.next_result(3, 10.06, boxes=[])
        self.assertFalse(row['comparison_distance_available'])
        self.assertIsNone(self.stream.poll(SESSION)['comparison_range_m'])

    def test_wrong_session_reference_rejected_without_rebinding(self):
        self.activate();self.next_result()
        bad = dict(self.reference, session='b'*32)
        with self.assertRaisesRegex(ValueError, 'session mismatch'):
            self.stream.activate(bad, self.png)
        self.assertIsNone(self.stream.poll(SESSION))
        self.assertFalse(self.next_result(3, 10.06)['comparison_distance_available'])

    def test_unpinned_source_frame_cannot_activate(self):
        self.admit(self.frame())
        with self.assertRaisesRegex(ValueError, 'not explicitly pinned'):
            self.stream.activate(self.reference, self.png)

    def test_png_digest_and_decoded_pixels_are_both_required(self):
        self.activate()
        with self.assertRaisesRegex(ValueError, 'PNG/hash'):
            self.stream.activate(dict(self.reference, source_png_sha256='0'*64), self.png)
        ok, other = cv2.imencode('.png', np.zeros((720, 1280, 3), np.uint8))
        other = other.tobytes();self.assertTrue(ok)
        with self.assertRaisesRegex(ValueError, 'admitted native pixels'):
            self.stream.activate(dict(self.reference, source_png_sha256=hashlib.sha256(other).hexdigest()), other)

    def test_corrupt_or_wrong_sized_or_unbounded_png_rejected(self):
        self.activate()
        for data in (b'bad', b'x'*(4*1024*1024+1), cv2.imencode('.png', np.zeros((2, 2, 3), np.uint8))[1].tobytes()):
            with self.assertRaises(ValueError):self.stream.activate(self.reference, data)

    def test_reference_ownership_no_mutable_alias(self):
        self.activate();self.reference['boundary_xy'] = [[280, 400], [360, 400]]
        self.assertTrue(self.next_result()['comparison_distance_available'])

    def test_session_change_clears_reference_witnesses_and_number(self):
        self.activate();self.next_result()
        frame = self.frame(1, 10.06, 'b'*32);self.admit(frame)
        row = self.stream.compare(frame, [BOX], self.main_result(frame))
        self.assertFalse(row['comparison_distance_available'])
        self.assertFalse(row['reference_scope_verified'])
        with self.assertRaises(ValueError):self.stream.activate(dict(self.reference, session='b'*32), self.png)

    def test_poll_expiry_clears_reference_and_requires_explicit_reactivation(self):
        self.activate();self.next_result()
        self.time = 11.
        self.assertIsNone(self.stream.poll(SESSION))
        self.assertFalse(self.next_result(3, 11.03)['comparison_distance_available'])
        with self.assertRaises(ValueError):self.stream.activate(self.reference, self.png)

    def test_input_gap_invalidates_even_without_poll(self):
        self.activate();self.next_result()
        row = self.next_result(3, 11.)
        self.assertFalse(row['comparison_distance_available'])
        self.assertEqual(row['reason'], 'comparison_input_gap')

    def test_gap_after_pin_before_first_load_erases_witness(self):
        frame=self.frame();self.admit(frame)
        self.stream.pin_reference_frame(frame)
        row=self.next_result(2,11.)
        self.assertEqual(row['reason'],'comparison_input_gap')
        with self.assertRaisesRegex(ValueError,'not explicitly pinned'):
            self.stream.activate(self.reference,self.png)

    def test_gap_on_pin_frame_before_pin_can_leave_same_reason_with_valid_witness(self):
        self.admit(self.frame())
        frame=self.frame(2,11.);self.admit(frame)
        self.assertEqual(self.stream.reason,'comparison_input_gap')
        self.stream.pin_reference_frame(frame)
        self.assertEqual(self.stream.reason,'comparison_input_gap')
        ref=dict(self.reference,source_frame=2)
        self.stream.activate(ref,self.png)
        self.assertIsNotNone(self.stream.verified_reference_snapshot())

    def test_explicit_disconnect_does_not_reuse_reference(self):
        self.activate();self.next_result()
        self.stream.invalidate('disconnected')
        self.assertIsNone(self.stream.poll(SESSION))
        self.assertFalse(self.next_result(3, 10.06)['comparison_distance_available'])

    def test_backward_duplicate_stale_and_future_inputs_rejected(self):
        for seq, source, now in ((1, 10., 10.02), (2, 9.9, 10.01), (2, 10.03, 11.), (2, 11., 10.03)):
            self.stream = self.new_stream()
            self.activate()
            with self.assertRaises(ValueError):self.stream.admit(SESSION, seq, source, now=now)
            self.assertIsNone(self.stream.poll(SESSION))

    def test_late_retired_session_cannot_revive_a_connection(self):
        self.activate()
        self.admit(self.frame(1, 10.03, 'b'*32))
        with self.assertRaisesRegex(ValueError, 'retired session'):
            self.admit(self.frame(2, 10.06, SESSION))
        self.assertIsNone(self.stream.poll(SESSION))

    def test_mismatched_result_profile_flags_and_baseline_fail_closed(self):
        for change in (dict(frame=99), dict(profile_sha256='0'*64), dict(published_to_ros=True),
                       dict(reason='invented'), dict(horizontal_camera_foot_range_m=2.)):
            self.stream = self.new_stream();self.activate()
            frame = self.frame(2, 10.03);self.admit(frame)
            result = self.main_result(frame);result.update(change)
            row = self.stream.compare(frame, [BOX], result)
            self.assertEqual(row['reason'], 'comparison_failed')
            self.assertFalse(row['comparison_distance_available'])
            self.assertIsNone(self.stream.poll(SESSION))

    def test_comparison_cost_and_clock_rollback_revoke_number(self):
        from cone_guarded_stream_comparison import compare_guarded_lower_edge
        for late in (11., 10.):
            self.stream = self.new_stream();self.activate()
            def slow(*args, **kwargs):
                result = compare_guarded_lower_edge(*args, **kwargs)
                self.time = late
                return result
            with patch('cone_guarded_stream_comparison.compare_guarded_lower_edge', side_effect=slow):
                row = self.next_result()
            self.assertFalse(row['comparison_distance_available'])
            self.assertIsNone(row['comparison_range_m'])
            self.assertIsNone(self.stream.poll(SESSION))

    def test_comparator_exception_is_isolated_to_comparison(self):
        self.activate()
        with patch('cone_guarded_stream_comparison.compare_guarded_lower_edge', side_effect=RuntimeError('failure')):
            row = self.next_result()
        self.assertEqual(row['reason'], 'comparison_failed')
        self.assertFalse(row['comparison_distance_available'])

    def test_poll_returns_copy_and_never_relabels_result_frame(self):
        self.activate();self.next_result()
        self.admit(self.frame(3, 10.06))
        row = self.stream.poll(SESSION);self.assertEqual(row['frame'], 2)
        row['comparison_range_m'] = 999
        self.assertNotEqual(self.stream.poll(SESSION)['comparison_range_m'], 999)
        self.assertIsNone(self.stream.poll('b'*32))

    def test_witness_capacity_is_bounded_and_no_silent_eviction(self):
        for seq in range(1, 9):
            frame = self.frame(seq, 10.+seq*.02);self.admit(frame)
            self.stream.pin_reference_frame(frame)
        frame = self.frame(9, 10.18);self.admit(frame)
        with self.assertRaisesRegex(ValueError, 'capacity'):self.stream.pin_reference_frame(frame)
        with self.assertRaises(ValueError):self.stream.activate(self.reference, self.png)

    def test_pin_wrong_frame_or_changed_pixels_invalidates(self):
        self.activate()
        with self.assertRaises(ValueError):self.stream.pin_reference_frame(self.frame(2))
        self.stream = self.new_stream();self.activate()
        self.image = np.zeros((720, 1280, 3), np.uint8)
        with self.assertRaisesRegex(ValueError, 'pixels changed'):self.stream.pin_reference_frame(self.frame())

    def test_close_cannot_be_restarted(self):
        self.activate();self.next_result();self.stream.close()
        self.assertIsNone(self.stream.poll(SESSION))
        with self.assertRaises(ValueError):self.admit(self.frame(3, 10.06))
        with self.assertRaises(ValueError):self.stream.activate(self.reference, self.png)

    def test_all_physical_and_control_flags_false_and_no_live_entry_import(self):
        self.activate();row = self.next_result()
        for name in FLAGS:self.assertIs(row[name], False)
        self.assertFalse(row['main_display_modified'])
        for name in ('driver_motion_process.py', 'driver_motion_bridge.py', 'cone_motion_range.py',
                     'run_cone_motion_live.py', 'cone_motion_worker.py'):
            # A provenance filename string is not a runtime import.
            import ast
            tree=ast.parse((ROOT/'src'/name).read_text())
            imported=[alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
            imported += [node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
            self.assertNotIn('cone_guarded_stream_comparison',imported)


if __name__ == '__main__':
    unittest.main()
