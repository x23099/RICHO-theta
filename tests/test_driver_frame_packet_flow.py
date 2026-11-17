"""Bounded synthetic fragments, real packet bytes, no RTC/ROS/socket/FFB."""
import hashlib
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_frame_packet import encode_packet, unpack_packet, _wrap, FramePacketReceiver
from driver_frame_packet_flow import (HEADER, MAGIC, MAX_PACKET, fragment_plan,
    PacketReassembler, LatestPacketSender)
from test_driver_frame_packet import candidate, SENDER, STREAM


def receiver(**options):
    args = dict(sender_id=SENDER, stream_id=STREAM, message_bytes=1024, timeout_sec=.2)
    args.update(options)
    return PacketReassembler(**args)


def sender(**options):
    args = dict(sender_id=SENDER, stream_id=STREAM, message_bytes=1024,
                max_capture_age_sec=.2, max_buffered_bytes=2048)
    args.update(options)
    return LatestPacketSender(**args)


def alter(chunk, **changes):
    values = list(HEADER.unpack_from(chunk))
    keys = ['magic', 'sender', 'stream', 'seq', 'total', 'index', 'count', 'digest']
    for key, value in changes.items():
        values[keys.index(key)] = value
    return HEADER.pack(*values)+chunk[HEADER.size:]


class PacketFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        yy, xx = np.indices((720, 1280))
        pixels = np.stack((xx%256, yy%256, (xx+yy)%256), axis=-1).astype(np.uint8)
        wire = encode_packet(pixels, candidate())
        cls.header, cls.payload = unpack_packet(wire)

    @classmethod
    def packet(cls, seq=1, *, stream=STREAM, received_motion=True):
        value = candidate(sequence=seq, stream=stream, withheld=not received_motion)
        head = dict(cls.header, candidate=value, encoded_pts=value['sender_media_pts'])
        return _wrap(head, cls.payload)

    def plan(self, seq=1, **options):
        return fragment_plan(self.packet(seq, **options), message_bytes=1024)

    def deliver(self, rec, plan, at=100., order=None):
        result = False
        for index in range(plan.count) if order is None else order:
            result = rec.accept(plan.fragment(index), received_at_sec=at)
        return result

    def test_fragment_caps_and_byte_exact_roundtrip(self):
        plan, rec = self.plan(), receiver()
        self.assertGreater(plan.count, 1)
        self.assertTrue(self.deliver(rec, plan))
        value = rec.take(100.)
        self.assertEqual(value.wire, plan.wire)
        self.assertIsNone(rec.take(100.))
        self.assertTrue(all(len(plan.fragment(i)) <= 1024 for i in range(plan.count)))
        self.assertLessEqual(rec.peak_retained_bytes, MAX_PACKET)

    def test_real_reassembly_to_independent_codec(self):
        plan, rec = self.plan(), receiver()
        self.deliver(rec, plan, order=reversed(range(plan.count)))
        done = rec.take(100.)
        decoded = FramePacketReceiver(sender_id=SENDER, stream_id=STREAM,
            max_receive_age_sec=.2).accept(done.wire, received_at_sec=done.first_received_at_sec)
        self.assertEqual(decoded.candidate['capture_sequence'], 1)
        self.assertEqual(decoded.image.shape, (720, 1280, 3))

    def test_first_frame_and_middle_frame_loss_do_not_relabel_later_packet(self):
        rec = receiver()
        self.deliver(rec, self.plan(2))
        self.assertEqual(rec.take(100.).sequence, 2)
        self.deliver(rec, self.plan(4), at=100.01)
        self.assertEqual(rec.take(100.01).sequence, 4)

    def test_missing_fragment_times_out_and_same_sequence_cannot_revive(self):
        rec, plan = receiver(), self.plan()
        self.deliver(rec, plan, order=range(1, plan.count))
        self.assertIsNone(rec.take(100.201))
        self.assertEqual(rec.retained_bytes, 0)
        self.assertFalse(rec.accept(plan.fragment(0), received_at_sec=100.202))
        self.assertIsNone(rec.take(100.202))
        self.assertEqual(rec.counts['expired'], 1)

    def test_duplicate_does_not_extend_initial_deadline(self):
        rec, plan = receiver(), self.plan()
        rec.accept(plan.fragment(0), received_at_sec=100.)
        rec.accept(plan.fragment(0), received_at_sec=100.19)
        self.assertEqual(rec.counts['duplicates'], 1)
        self.assertIsNone(rec.take(100.201))

    def test_complete_packet_uses_initial_not_completion_deadline(self):
        rec, plan = receiver(), self.plan()
        rec.accept(plan.fragment(0), received_at_sec=100.)
        self.deliver(rec, plan, at=100.19, order=range(1, plan.count))
        self.assertIsNone(rec.take(100.201))

    def test_newer_packet_supersedes_old_incomplete_and_old_chunks_do_not_mix(self):
        rec, old, new = receiver(), self.plan(), self.plan(2)
        rec.accept(old.fragment(0), received_at_sec=100.)
        rec.accept(new.fragment(0), received_at_sec=100.01)
        self.deliver(rec, old, at=100.02)
        self.assertIsNone(rec.complete)
        self.deliver(rec, new, at=100.03, order=range(1, new.count))
        self.assertEqual(rec.take(100.03).sequence, 2)
        self.assertEqual(rec.counts['replaced'], 1)

    def test_new_packet_invalidates_old_completed_pair(self):
        rec = receiver()
        self.deliver(rec, self.plan())
        rec.accept(self.plan(2).fragment(0), received_at_sec=100.01)
        self.assertIsNone(rec.take(100.01))

    def test_conflicting_duplicate_retires_that_sequence(self):
        rec, plan = receiver(), self.plan()
        chunk = plan.fragment(0)
        rec.accept(chunk, received_at_sec=100.)
        changed = chunk[:-1]+bytes([chunk[-1]^1])
        self.assertFalse(rec.accept(changed, received_at_sec=100.01))
        self.assertEqual(rec.retained_bytes, 0)
        self.deliver(rec, plan, at=100.02)
        self.assertIsNone(rec.take(100.02))
        self.assertEqual(rec.counts['conflicts'], 1)

    def test_inconsistent_packet_identity_rejected(self):
        rec, plan = receiver(), self.plan()
        rec.accept(plan.fragment(0), received_at_sec=100.)
        rec.accept(alter(plan.fragment(1), digest=bytes(32)), received_at_sec=100.01)
        self.assertEqual(rec.retained_bytes, 0)
        self.assertEqual(rec.counts['conflicts'], 1)

    def test_full_digest_failure_rejected(self):
        rec, plan = receiver(), self.plan()
        chunks = [plan.fragment(i) for i in range(plan.count)]
        chunks[-1] = chunks[-1][:-1]+bytes([chunks[-1][-1]^1])
        for chunk in chunks:
            rec.accept(chunk, received_at_sec=100.)
        self.assertIsNone(rec.take(100.))
        self.assertEqual(rec.counts['invalid'], 1)

    def test_wrapper_sequence_must_match_inner_source(self):
        rec, plan = receiver(), self.plan()
        for i in range(plan.count):
            rec.accept(alter(plan.fragment(i), seq=2), received_at_sec=100.)
        self.assertIsNone(rec.take(100.))
        self.assertEqual(rec.counts['invalid'], 1)

    def test_foreign_scope_ignored_and_new_receiver_rejects_old_stream(self):
        rec, old, new = receiver(stream_id='c'*32), self.plan(), self.plan(stream='c'*32)
        rec.accept(new.fragment(0), received_at_sec=100.)
        self.deliver(rec, old, at=100.01)
        self.deliver(rec, new, at=100.02, order=range(1, new.count))
        self.assertEqual(rec.take(100.02).wire, new.wire)
        self.assertEqual(rec.counts['foreign'], old.count)

    def test_malformed_sizes_indexes_and_body_lengths_allocate_nothing(self):
        plan = self.plan()
        values = [b'', 'notbytes', plan.fragment(0)[:-1], plan.fragment(0)+b'x',
            alter(plan.fragment(0), total=MAX_PACKET+1), alter(plan.fragment(0), index=65535),
            alter(plan.fragment(0), count=65535), alter(plan.fragment(0), magic=bytes(8)),
            alter(plan.fragment(0), seq=2**63)]
        for value in values:
            rec = receiver()
            self.assertFalse(rec.accept(value, received_at_sec=100.))
            self.assertEqual(rec.retained_bytes, 0)
            self.assertIsNone(rec.take(100.))

    def test_receiver_clock_reversal_and_close_prevent_revival(self):
        for closed in (False, True):
            rec, plan = receiver(), self.plan()
            rec.accept(plan.fragment(0), received_at_sec=100.)
            if closed:
                rec.close()
            else:
                rec.take(99.)
            self.assertTrue(rec.closed)
            self.deliver(rec, plan, at=101.)
            self.assertIsNone(rec.take(101.))
            self.assertEqual(rec.retained_bytes, 0)

    def test_source_sender_one_active_and_one_latest_pending(self):
        tx = sender()
        self.assertTrue(tx.offer(self.packet(), now=10.05))
        first = tx.next_fragment(now=10.05, buffered_amount=0, channel_open=True)
        self.assertEqual(HEADER.unpack_from(first)[3], 1)
        tx.offer(self.packet(2), now=10.1)
        tx.offer(self.packet(3), now=10.15)
        self.assertEqual((tx.active.sequence, tx.pending.sequence), (1, 3))
        self.assertEqual(tx.counts['pending_replaced'], 1)
        self.assertLessEqual(tx.retained_bytes, 2*MAX_PACKET)

    def test_pending_does_not_interrupt_progressing_packet(self):
        tx = sender(max_capture_age_sec=.5)
        tx.offer(self.packet(), now=10.05)
        tx.next_fragment(now=10.05, buffered_amount=0, channel_open=True)
        tx.offer(self.packet(2), now=10.1)
        sequences = []
        while True:
            chunk = tx.next_fragment(now=10.1, buffered_amount=0, channel_open=True)
            if chunk is None:
                break
            sequences.append(HEADER.unpack_from(chunk)[3])
        self.assertEqual(sequences, [1]*(self.plan().count-1)+[2]*self.plan(2).count)

    def test_new_offer_replaces_pending_after_active_handoff_without_reordering(self):
        tx = sender(max_capture_age_sec=.5)
        tx.offer(self.packet(), now=10.05)
        tx.offer(self.packet(2), now=10.1)
        for _ in range(self.plan().count):
            tx.next_fragment(now=10.1, buffered_amount=0, channel_open=True)
        self.assertIsNone(tx.active)
        self.assertIsNotNone(tx.pending)
        tx.offer(self.packet(3), now=10.15)
        self.assertIsNone(tx.pending)
        chunk = tx.next_fragment(now=10.15, buffered_amount=0, channel_open=True)
        self.assertEqual(HEADER.unpack_from(chunk)[3], 3)

    def test_backpressure_leaves_fragment_index_and_queue_bounded(self):
        tx = sender()
        tx.offer(self.packet(), now=10.05)
        for _ in range(100):
            self.assertIsNone(tx.next_fragment(now=10.06, buffered_amount=2048, channel_open=True))
        self.assertEqual(tx.index, 0)
        self.assertEqual(tx.counts['held_for_buffer'], 100)
        self.assertIsNotNone(tx.next_fragment(now=10.06, buffered_amount=1024, channel_open=True))

    def test_stalled_active_expires_then_latest_pending_is_sent(self):
        tx = sender()
        tx.offer(self.packet(), now=10.05)
        tx.next_fragment(now=10.05, buffered_amount=0, channel_open=True)
        tx.offer(self.packet(4), now=10.2)
        chunk = tx.next_fragment(now=10.251, buffered_amount=0, channel_open=True)
        self.assertEqual(HEADER.unpack_from(chunk)[3], 4)
        self.assertEqual(tx.counts['expired'], 1)

    def test_expired_offer_does_not_rescue_old_pending(self):
        tx = sender()
        tx.offer(self.packet(), now=10.05)
        self.assertFalse(tx.offer(self.packet(2), now=10.4))
        self.assertEqual(tx.retained_bytes, 0)
        self.assertIsNone(tx.next_fragment(now=10.4, buffered_amount=0, channel_open=True))

    def test_bad_new_offer_clears_previous_data(self):
        for wire in (b'bad', self.packet(stream='c'*32), self.packet()):
            tx = sender()
            tx.offer(self.packet(), now=10.05)
            self.assertFalse(tx.offer(wire, now=10.06))
            self.assertEqual(tx.retained_bytes, 0)

    def test_sender_clock_reverse_wrong_time_or_send_failure_closes(self):
        for mode in ('reverse', 'close', 'nan'):
            tx = sender()
            tx.offer(self.packet(), now=10.05)
            if mode == 'close':
                tx.close()  # Contract for a failed actual channel.send.
            now = 10.04 if mode == 'reverse' else float('nan') if mode == 'nan' else 10.06
            self.assertIsNone(tx.next_fragment(now=now, buffered_amount=0, channel_open=True))
            self.assertTrue(tx.closed)
            self.assertEqual(tx.retained_bytes, 0)

    def test_channel_unavailable_discards_unsent_data(self):
        tx = sender()
        tx.offer(self.packet(), now=10.05)
        self.assertIsNone(tx.next_fragment(now=10.06, buffered_amount=0, channel_open=False))
        self.assertEqual(tx.retained_bytes, 0)
        self.assertIsNone(tx.next_fragment(now=10.07, buffered_amount=0, channel_open=True))

    def test_invalid_buffer_metadata_clears_data(self):
        for buffered, opened in ((True, True), (-1, True), (0, 1)):
            tx = sender()
            tx.offer(self.packet(), now=10.05)
            self.assertIsNone(tx.next_fragment(now=10.06, buffered_amount=buffered, channel_open=opened))
            self.assertEqual(tx.retained_bytes, 0)

    def test_explicit_limits_and_fragment_indices(self):
        for change in (dict(message_bytes=True), dict(message_bytes=16385), dict(timeout_sec=0),
                       dict(timeout_sec=float('inf')), dict(sender_id='wrong')):
            with self.assertRaises(ValueError):
                receiver(**change)
        for change in (dict(max_buffered_bytes=1023), dict(max_buffered_bytes=True),
                       dict(max_capture_age_sec=False)):
            with self.assertRaises(ValueError):
                sender(**change)
        plan = self.plan()
        for index in (-1, True, plan.count):
            with self.assertRaises(ValueError):
                plan.fragment(index)

    def test_receiver_clock_origin_does_not_have_to_match_sender(self):
        plan, rec = self.plan(), receiver()
        self.deliver(rec, plan, at=700000.)
        self.assertEqual(rec.take(700000.).wire, plan.wire)


if __name__ == '__main__':
    unittest.main()
