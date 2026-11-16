"""Sender-local candidates and actual in-memory codec; no sockets/ROS/FFB."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_frame_motion import SenderFrameMotion, FLAGS
from driver_odometry_observation import OdometryObserver
from test_driver_odometry_observation import message

SENDER, STREAM = 'a'*32, 'b'*32


def associator(**changes):
    options = dict(sender_id=SENDER, stream_id=STREAM, capacity=4,
        max_callback_lag_sec=.1, max_progress_lag_sec=.1,
        max_capture_wait_sec=.2, motion_frame_id='base_footprint')
    options.update(changes)
    return SenderFrameMotion(**options)


def observation(at, *, sec=1000, v=0., w=0., child='base_footprint'):
    observer = OdometryObserver(clock=lambda:at)
    observer.sender_id = SENDER
    observer.observe(message(sec=sec, v=v, w=w, child=child))
    return observer.snapshot()


def associate(source, at=10.05, *, sequence=1, pts=0, now=None):
    return source.associate(capture_sequence=sequence, captured_at_sec=at,
        media_pts=pts, associated_at_sec=at if now is None else now)


class FrameMotionTests(unittest.TestCase):
    def setUp(self):
        self.source = associator()
        self.now = 10.
        self.observer = OdometryObserver(clock=lambda:self.now)
        self.observer.sender_id = SENDER

    def offer(self, *, sec=1000, v=0., w=0., child='base_footprint'):
        self.observer.observe(message(sec=sec, v=v, w=w, child=child))
        value = self.observer.snapshot()
        self.assertTrue(self.source.offer(value))
        return value

    def check(self, value, available, reason=None):
        self.assertIs(value['local_pair_available'], available)
        if reason is not None:
            self.assertEqual(value['reason'], reason)
        self.assertEqual(json.loads(json.dumps(value, allow_nan=False)), value)
        for key in FLAGS:
            self.assertIs(value[key], False)
        self.assertIsNone(value['receiver_media_pts'])
        if not available:
            self.assertIsNone(value['odometry_observation'])
            self.assertIsNone(value['callback_to_capture_sec'])
            self.assertIsNone(value['progress_to_capture_sec'])
        return value

    def test_received_stop_is_zero_but_unreceived_is_null(self):
        self.source.offer(self.observer.snapshot())
        self.check(associate(self.source, 10.), False, 'no_observed_past_callback')
        self.now = 10.01
        value = self.offer()
        result = self.check(associate(self.source, 10.02, sequence=2, pts=900), True)
        self.assertEqual(result['odometry_observation'], value)
        self.assertEqual(result['odometry_observation']['linear_mps'], 0.)

    def test_forward_reverse_and_yaw_signs_preserved(self):
        for i, (v, w) in enumerate(((.2, -.1), (-.2, .1), (0., 0.)), 1):
            self.now = 10.+i
            expected = self.offer(sec=1000+i, v=v, w=w)
            result = self.check(associate(self.source, self.now+.01, sequence=i, pts=i*3000), True)
            self.assertEqual(result['odometry_observation'], expected)

    def test_future_callback_does_not_replace_past_sample(self):
        past = self.offer(v=.1)
        self.now = 10.06
        self.offer(sec=1001, v=.9)
        result = self.check(associate(self.source, 10.05, now=10.07), True)
        self.assertEqual(result['odometry_observation'], past)
        self.assertAlmostEqual(result['callback_to_capture_sec'], .05)

    def test_future_only_is_withheld(self):
        self.offer()
        self.check(associate(self.source, 9.99, now=10.01), False, 'no_observed_past_callback')

    def test_stale_callback_has_no_valid_old_value_rescue(self):
        self.offer()
        self.check(associate(self.source, 10.101), False, 'callback_to_capture_limit_exceeded')

    def test_repeated_source_stamp_with_recent_callback_is_withheld(self):
        self.offer()
        self.now = 10.02
        self.offer()
        self.check(associate(self.source, 10.03), False, 'latest_past_source_stamp_not_advanced')

    def test_invalid_latest_past_callback_is_barrier(self):
        self.offer()
        self.now = 10.02
        self.offer(sec=1001, v=float('nan'))
        self.check(associate(self.source, 10.03), False, 'latest_past_callback_invalid')

    def test_future_invalid_callback_does_not_rewrite_past(self):
        past = self.offer()
        self.now = 10.02
        self.offer(sec=1001, v=float('nan'))
        result = self.check(associate(self.source, 10.01, now=10.03), True)
        self.assertEqual(result['odometry_observation'], past)

    def test_reversed_source_stamp_is_barrier(self):
        self.offer()
        self.now = 10.02
        self.offer(sec=999)
        self.check(associate(self.source, 10.03), False, 'latest_past_source_stamp_not_advanced')

    def test_wrong_motion_frame_is_not_silently_relabelled(self):
        self.offer(child='base_link')
        self.check(associate(self.source), False, 'motion_frame_mismatch')

    def test_image_wait_is_not_odometry_measurement_age(self):
        self.offer()
        self.check(associate(self.source, now=10.3), False, 'capture_wait_exceeded')

    def test_progress_age_policy_is_explicit(self):
        source = associator(max_progress_lag_sec=.01)
        source.offer(observation(10.))
        self.check(associate(source), False, 'source_stamp_progress_limit_exceeded')

    def test_snapshots_cannot_rejuvenate_callback_age(self):
        self.offer()
        self.now = 10.2
        self.source.offer(self.observer.snapshot())
        self.check(associate(self.source, 10.21), False, 'callback_to_capture_limit_exceeded')
        self.assertEqual(len(self.source.history), 1)

    def test_bounded_history_does_not_guess_an_evicted_past(self):
        for i in range(10):
            self.now = 10.+i*.01
            self.offer(sec=1000+i)
        self.assertEqual(len(self.source.history), 4)
        self.assertEqual(self.source.evicted, 6)
        self.check(associate(self.source, 10.02, now=10.1), False, 'no_observed_past_callback')

    def test_foreign_sender_and_bad_metadata_retire_stream(self):
        for change in (dict(sender_id='c'*32, sender_monotonic_clock_id='sender-process/'+'c'*32),
                       dict(usable_for_ffb=True), dict(extra='arbitrary')):
            source = associator()
            source.offer(observation(10.))
            self.assertFalse(source.offer(dict(observation(10.01), **change)))
            self.assertFalse(source.offer(observation(10.02)))
            self.check(associate(source), False)
            self.assertEqual(len(source.history), 0)

    def test_snapshot_order_reversal_retires_stream(self):
        self.offer()
        self.now = 10.02
        self.source.offer(self.observer.snapshot())
        self.now = 10.01
        self.assertFalse(self.source.offer(self.observer.snapshot()))
        self.check(associate(self.source), False, 'sender_clock_reversed_or_invalid')

    def test_callback_sequence_reversal_and_identity_change_retire(self):
        first = self.offer()
        self.now = 10.01
        self.offer(sec=1001)
        self.assertFalse(self.source.offer(dict(first, snapshot_mono_sec=10.02,
            callback_age_sec=.02, stamp_progress_age_sec=.02)))
        source = associator()
        source.offer(first)
        self.assertFalse(source.offer(dict(first, linear_mps=.9)))
        self.assertEqual(source.fault, 'same_callback_identity_changed')

    def test_busy_observer_clears_history_until_a_new_callback(self):
        self.offer()
        with self.observer.lock:
            self.assertTrue(self.source.offer(self.observer.snapshot()))
        self.source.offer(self.observer.snapshot())
        self.check(associate(self.source), False, 'no_observed_past_callback')
        self.now = 10.06
        self.offer(sec=1001)
        self.check(associate(self.source, 10.07, sequence=2, pts=1000), True)

    def test_skipped_callbacks_prevent_guessing_during_an_unobserved_gap(self):
        self.offer()
        self.now = 10.01
        self.observer.observe(message(sec=1001, v=float('nan')))
        self.now = 10.03
        self.offer(sec=1002)
        self.check(associate(self.source, 10.02, now=10.04), False, 'no_observed_past_callback')
        self.check(associate(self.source, 10.04, sequence=2, pts=1000), True)

    def test_dropped_callback_blocks_old_value_until_new_callback(self):
        self.offer()
        with self.observer.lock:
            self.observer.observe(message(sec=1001))
        self.source.offer(self.observer.snapshot())
        self.check(associate(self.source), False, 'no_observed_past_callback')

    def test_odometry_state_reset_is_not_a_new_stream(self):
        self.offer()
        empty = OdometryObserver(clock=lambda:10.01)
        empty.sender_id = SENDER
        self.assertFalse(self.source.offer(empty.snapshot()))
        self.check(associate(self.source), False, 'odometry_state_reset')

    def test_receiver_and_wall_clocks_are_not_inputs(self):
        from unittest.mock import patch
        with patch('time.time', side_effect=AssertionError('wall clock must not be read')):
            self.offer()
            self.check(associate(self.source), True)

    def test_nonblocking_lock_contention_does_not_return_a_cached_pair(self):
        self.offer()
        with self.source.lock:
            self.assertFalse(self.source.offer(self.observer.snapshot()))
            self.check(associate(self.source), False, 'association_busy')
        self.assertEqual(self.source.busy_offers, 1)
        self.check(associate(self.source), False, 'odometry_history_gap')
        self.source.offer(self.observer.snapshot())
        self.check(associate(self.source), False, 'no_observed_past_callback')
        self.now = 10.06
        self.offer(sec=1001)
        self.check(associate(self.source, 10.07, sequence=2, pts=1000), True)

    def test_invalid_frame_does_not_block_or_leave_old_sample_reusable(self):
        self.offer()
        with self.source.lock:
            with self.assertRaises(ValueError):
                associate(self.source, sequence=True)
        self.check(associate(self.source), False, 'invalid_frame_identity_or_time')

    def test_frame_regression_retires_and_new_stream_is_independent(self):
        self.offer()
        self.check(associate(self.source), True)
        self.check(associate(self.source, sequence=1), False, 'source_frame_or_clock_order_reversed')
        new = associator(stream_id='c'*32)
        new.offer(observation(10.))
        self.check(associate(new), True)

    def test_frame_gaps_are_allowed_without_filling_missing_captures(self):
        self.offer()
        self.check(associate(self.source), True)
        result = self.check(associate(self.source, 10.06, sequence=5, pts=1800), True)
        self.assertEqual(result['capture_sequence'], 5)
        self.assertEqual(result['sender_media_pts'], 1800)

    def test_input_and_output_ownership(self):
        value = self.offer()
        baseline = copy.deepcopy(value)
        value['linear_mps'] = 99.
        value['invalid_fields'].append('linear_mps')
        result = self.check(associate(self.source), True)
        self.assertEqual(result['odometry_observation'], baseline)
        result['odometry_observation']['linear_mps'] = -99.
        result['policy']['capacity'] = 999
        next_result = self.check(associate(self.source, 10.06, sequence=2, pts=1000), True)
        self.assertEqual(next_result['odometry_observation'], baseline)
        self.assertEqual(next_result['policy']['capacity'], 4)

    def test_explicit_bounded_policies_required(self):
        for change in (dict(sender_id=None), dict(stream_id=''), dict(capacity=True),
            dict(capacity=1025), dict(max_callback_lag_sec=0), dict(max_capture_wait_sec=float('nan')),
            dict(max_progress_lag_sec=True), dict(motion_frame_id='bad frame')):
            with self.assertRaises(ValueError):
                associator(**change)


class ActualCodecIdentityTests(unittest.TestCase):
    def test_rtp_rebases_first_received_timestamp_including_wrap(self):
        from aiortc.rtcrtpreceiver import TimestampMapper
        first, with_loss = TimestampMapper(), TimestampMapper()
        origin = 2**32-1000
        timestamp = lambda pts:(origin+pts) % 2**32
        self.assertEqual([first.map(timestamp(p)) for p in (0, 3000, 6000)], [0, 3000, 6000])
        self.assertEqual([with_loss.map(timestamp(p)) for p in (3000, 6000)], [0, 3000])
        # Decoded PTS zero alone cannot identify which source capture arrived.

    def test_vp8_round_trip_does_not_carry_arbitrary_frame_identity(self):
        import av
        from aiortc.codecs.vpx import Vp8Encoder, Vp8Decoder, vp8_depayload
        from aiortc.jitterbuffer import JitterFrame
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(image, format='bgr24')
        frame.pts, frame.time_base = 3000, Fraction(1, 90000)
        frame.opaque = dict(stream_id=STREAM, capture_sequence=7)
        payloads, pts = Vp8Encoder().encode(frame)
        decoded = Vp8Decoder().decode(JitterFrame(b''.join(vp8_depayload(p) for p in payloads), pts))
        self.assertEqual(len(decoded), 1)
        self.assertIsNone(decoded[0].opaque)
        self.assertLessEqual(abs(pts-3000), 1)
        self.assertEqual(decoded[0].to_ndarray(format='bgr24').shape, image.shape)


if __name__ == '__main__':
    unittest.main()
