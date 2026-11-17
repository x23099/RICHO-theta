"""Atomic frame/motion envelopes, actual VP8, no network/camera/ROS/G923."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_frame_packet import (checked_candidate, encode_packet, unpack_packet, _wrap,
    FramePacketReceiver, PREFIX, MAGIC, MAX_HEADER, MAX_PAYLOAD)
from driver_frame_motion import FLAGS
from test_driver_frame_motion import associator, observation, associate, SENDER, STREAM


def candidate(sequence=1, *, v=0., w=0., stream=STREAM, withheld=False):
    source = associator(stream_id=stream)
    now = 10.+sequence*.05
    if not withheld:
        source.offer(observation(now-.01, sec=1000+sequence, v=v, w=w))
    return associate(source, now, sequence=sequence, pts=(sequence-1)*3000)


def image(value=80):
    return np.full((720, 1280, 3), value, np.uint8)


def receiver(stream=STREAM):
    return FramePacketReceiver(sender_id=SENDER, stream_id=stream, max_receive_age_sec=.2)


class FramePacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = image()
        cls.meta = candidate()
        cls.wire = encode_packet(cls.source, cls.meta)

    def test_real_codec_roundtrip_preserves_candidate_and_native_shape(self):
        decoded = receiver().accept(self.wire, received_at_sec=5000.)
        self.assertEqual(decoded.candidate, self.meta)
        self.assertEqual(decoded.image.shape, (720, 1280, 3))
        self.assertEqual(decoded.image.dtype, np.uint8)
        self.assertFalse(decoded.image.flags.writeable)
        self.assertEqual(decoded.packet_sha256, hashlib.sha256(self.wire).hexdigest())
        self.assertLess(abs(float(decoded.image.mean())-80.), 5.)
        for flag in FLAGS:
            self.assertIs(decoded.candidate[flag], False)

    def test_source_pixels_and_metadata_are_not_modified_by_encode(self):
        pixels, value = image(), candidate()
        before = hashlib.sha256(pixels.tobytes()).hexdigest()
        original = copy.deepcopy(value)
        encode_packet(pixels, value)
        self.assertEqual(value, original)
        self.assertEqual(hashlib.sha256(pixels.tobytes()).hexdigest(), before)

    def test_first_capture_loss_does_not_relabel_second_as_first(self):
        wire = encode_packet(image(130), candidate(sequence=2, v=-.2, w=.1))
        decoded = receiver().accept(wire, received_at_sec=9000.)
        self.assertEqual(decoded.candidate['capture_sequence'], 2)
        self.assertEqual(decoded.candidate['sender_media_pts'], 3000)
        self.assertEqual(decoded.candidate['odometry_observation']['linear_mps'], -.2)
        self.assertGreater(decoded.image.mean(), 120.)

    def test_middle_loss_needs_no_prior_codec_reference(self):
        rec = receiver()
        rec.accept(self.wire, received_at_sec=100.)
        third = encode_packet(image(180), candidate(sequence=3, v=.2, w=-.1))
        decoded = rec.accept(third, received_at_sec=100.05)
        self.assertEqual(decoded.candidate['capture_sequence'], 3)
        self.assertEqual(decoded.candidate['odometry_observation']['angular_radps'], -.1)
        self.assertGreater(decoded.image.mean(), 170.)

    def test_withheld_motion_can_have_an_image_but_no_old_velocity(self):
        rec = receiver()
        rec.accept(self.wire, received_at_sec=100.)
        wire = encode_packet(image(), candidate(sequence=2, withheld=True))
        decoded = rec.accept(wire, received_at_sec=100.01)
        self.assertFalse(decoded.candidate['local_pair_available'])
        self.assertIsNone(decoded.candidate['odometry_observation'])

    def test_mismatched_metadata_or_payload_cannot_use_original_digest(self):
        head, payload = unpack_packet(self.wire)
        newer = encode_packet(image(140), candidate(sequence=2))
        head2, payload2 = unpack_packet(newer)
        h1, h2 = (json.dumps(h, allow_nan=False, separators=(',', ':')).encode() for h in (head, head2))
        for header, body in ((h2, payload), (h1, payload2)):
            _, _, _, original_digest = PREFIX.unpack_from(self.wire)
            wire = PREFIX.pack(MAGIC, len(header), len(body), original_digest)+header+body
            with self.assertRaisesRegex(ValueError, 'integrity'):
                unpack_packet(wire)

    def test_truncation_extra_bytes_and_corruption_rejected(self):
        for wire in (b'', self.wire[:-1], self.wire+b'x', self.wire[:PREFIX.size],
                     self.wire[:-1]+bytes([self.wire[-1]^1]), 'not bytes'):
            with self.assertRaises(ValueError):
                unpack_packet(wire)

    def test_declared_sizes_are_bounded_before_decode(self):
        for h, p in ((0, 10), (MAX_HEADER+1, 10), (1, MAX_PAYLOAD+1)):
            wire = PREFIX.pack(MAGIC, h, p, bytes(32))+bytes(10)
            with self.assertRaises(ValueError):
                unpack_packet(wire)

    def test_duplicate_and_nonfinite_json_rejected_even_with_valid_digest(self):
        _, payload = unpack_packet(self.wire)
        for data in (b'{"schema":1,"schema":2}', b'{"value":NaN}', b'{"value":Infinity}', b'\xff'):
            wire = PREFIX.pack(MAGIC, len(data), len(payload), hashlib.sha256(data+payload).digest())+data+payload
            with self.assertRaises(ValueError):
                unpack_packet(wire)

    def test_header_identity_types_and_authority_are_strict(self):
        head, payload = unpack_packet(self.wire)
        for key, value in (('width', True), ('height', 1080), ('clock_rate', 1),
            ('encoded_pts', True), ('encoded_pts', 3000), ('usable_for_ffb', True),
            ('schema', 'future'), ('extra', 'unexpected')):
            changed = copy.deepcopy(head)
            changed[key] = value
            with self.assertRaises(ValueError):
                unpack_packet(_wrap(changed, payload))

    def test_keyframe_dimensions_visibility_and_reference_rejected_before_codec(self):
        head, payload = unpack_packet(self.wire)
        changes = []
        for index, xor in ((0, 1), (0, 16), (3, 1), (6, 1), (9, 0x80)):
            changed = bytearray(payload)
            changed[index] ^= xor
            changes.append(bytes(changed))
        for changed in changes:
            with patch('av.CodecContext') as codec:
                codec.create.side_effect = AssertionError('must reject before decode')
                with self.assertRaises(ValueError):
                    receiver().accept(_wrap(head, changed), received_at_sec=100.)
                codec.create.assert_not_called()

    def test_replay_and_reordered_packets_clear_old_pair(self):
        rec = receiver()
        rec.accept(self.wire, received_at_sec=100.)
        for at in (100.01, 100.02):
            with self.assertRaises(ValueError):
                rec.accept(self.wire, received_at_sec=at)
            self.assertIsNone(rec.snapshot(at))
        second = encode_packet(image(), candidate(sequence=2))
        rec.accept(second, received_at_sec=100.03)
        with self.assertRaises(ValueError):
            rec.accept(self.wire, received_at_sec=100.04)
        self.assertIsNone(rec.snapshot(100.04))

    def test_reconnect_requires_new_receiver_scope(self):
        new_wire = encode_packet(image(), candidate(stream='c'*32))
        old = receiver()
        old.accept(self.wire, received_at_sec=100.)
        with self.assertRaises(ValueError):
            old.accept(new_wire, received_at_sec=100.01)
        self.assertIsNone(old.snapshot(100.01))
        new = receiver('c'*32)
        self.assertEqual(new.accept(new_wire, received_at_sec=500.).candidate['stream_id'], 'c'*32)
        with self.assertRaises(ValueError):
            new.accept(self.wire, received_at_sec=500.01)

    def test_bad_update_clears_cache_and_only_a_new_valid_sequence_recovers(self):
        rec = receiver()
        rec.accept(self.wire, received_at_sec=100.)
        with self.assertRaises(ValueError):
            rec.accept(self.wire[:-2], received_at_sec=100.01)
        self.assertIsNone(rec.snapshot(100.02))
        wire = encode_packet(image(), candidate(sequence=2))
        self.assertEqual(rec.accept(wire, received_at_sec=100.03).candidate['capture_sequence'], 2)

    def test_receiver_age_expiration_does_not_measure_cross_pc_delay(self):
        rec = receiver()
        rec.accept(self.wire, received_at_sec=1.)  # Source time is ~10s, intentionally unrelated.
        self.assertIsNotNone(rec.snapshot(1.1))
        self.assertIsNone(rec.snapshot(1.201))

    def test_receiver_clock_reversal_retires_instance(self):
        rec = receiver()
        rec.accept(self.wire, received_at_sec=100.)
        self.assertIsNone(rec.snapshot(99.))
        self.assertTrue(rec.closed)
        with self.assertRaises(ValueError):
            rec.accept(encode_packet(image(), candidate(sequence=2)), received_at_sec=101.)

    def test_close_prevents_revival(self):
        rec = receiver()
        rec.accept(self.wire, received_at_sec=100.)
        rec.close()
        self.assertIsNone(rec.snapshot(101.))
        with self.assertRaises(ValueError):
            rec.accept(encode_packet(image(), candidate(sequence=2)), received_at_sec=101.)

    def test_snapshot_does_not_expose_mutable_internal_state(self):
        rec = receiver()
        decoded = rec.accept(self.wire, received_at_sec=100.)
        decoded.candidate['odometry_observation']['linear_mps'] = 99.
        decoded.image.flags.writeable = True
        decoded.image[:] = 0
        current = rec.snapshot(100.01)
        self.assertEqual(current.candidate['odometry_observation']['linear_mps'], 0.)
        self.assertGreater(current.image.mean(), 70.)

    def test_candidate_validator_roundtrip_and_no_authority_promotion(self):
        original = candidate()
        self.assertEqual(checked_candidate(json.loads(json.dumps(original))), original)
        for key, value in (('local_pair_available', 1), ('receiver_media_pts', 0),
                           ('receiver_frame_identity_verified', True), ('extra', 1)):
            with self.assertRaises(ValueError):
                checked_candidate(dict(original, **{key:value}))

    def test_candidate_temporal_and_motion_values_must_reproduce(self):
        for key, value in (('callback_to_capture_sec', 0.), ('progress_to_capture_sec', 0.),
            ('captured_at_sec', 9.), ('sender_media_pts', True), ('capture_sequence', True),
            ('sender_monotonic_clock_id', 'receiver-process/unknown')):
            changed = copy.deepcopy(self.meta)
            changed[key] = value
            with self.assertRaises(ValueError):
                checked_candidate(changed)

    def test_withheld_candidate_cannot_carry_old_motion_or_unknown_reason(self):
        value = candidate(withheld=True)
        self.assertEqual(checked_candidate(value), value)
        for key, wrong in (('odometry_observation', self.meta['odometry_observation']),
            ('reason', 'future_unknown'), ('callback_to_capture_sec', 0.), ('capture_wait_sec', False)):
            with self.assertRaises(ValueError):
                checked_candidate(dict(value, **{key:wrong}))

    def test_native_shape_and_media_span_limits(self):
        for pixels in (np.zeros((10, 10, 3), np.uint8), np.zeros((720, 1280, 3), np.float32)):
            with self.assertRaises(ValueError):
                encode_packet(pixels, self.meta)
        value = copy.deepcopy(self.meta)
        value['sender_media_pts'] = 2**32
        with self.assertRaises(ValueError):
            encode_packet(image(), value)

    def test_no_wall_clock_or_clock_binding_read(self):
        with patch('time.time', side_effect=AssertionError('not needed')):
            wire = encode_packet(image(), self.meta)
            self.assertIsNotNone(receiver().accept(wire, received_at_sec=1.))


if __name__ == '__main__':
    unittest.main()
