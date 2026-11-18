"""PNG scheduler boundaries; actual PNG/fragment bytes, no socket or robot."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import driver_lossless_frame_packet as png
import driver_lossless_frame_fragments as flow
from driver_lossless_frame_sender import LosslessLatestSender
from test_driver_frame_packet import candidate,SENDER,STREAM


def sender(**changes):
    values=dict(sender_id=SENDER,stream_id=STREAM,max_buffered_bytes=32768)
    values.update(changes)
    return LosslessLatestSender(**values)


def pump(source,at,amount=0,opened=True):
    return source.next_fragment(now=at,buffered_amount=amount,channel_open=opened)


class LosslessSenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image=np.random.default_rng(31).integers(0,8,(720,1280,3),dtype=np.uint8)*32
        cls.wires={n:png.encode_packet(image,candidate(sequence=n)) for n in (1,2,3,4)}
        cls.times={n:candidate(sequence=n)['captured_at_sec'] for n in cls.wires}

    def test_exact_same_png_fragment_wire_as_existing_generator(self):
        source=sender();at=self.times[1]
        self.assertTrue(source.offer(self.wires[1],now=at))
        self.assertEqual(list(flow.fragments(self.wires[1])),self.drain(source,at))
        self.assertEqual(source.counts['packets_handed_off'],1)
        self.assertEqual(source.retained_bytes,0)

    def drain(self,source,at):
        result=[]
        while True:
            message=pump(source,at)
            if message is None:return result
            result.append(message)

    def test_progressing_packet_not_starved_by_newer_input(self):
        source=sender();source.offer(self.wires[1],now=self.times[1])
        first=pump(source,self.times[1])
        source.offer(self.wires[2],now=self.times[2]);source.offer(self.wires[3],now=self.times[3])
        messages=[first]+self.drain(source,self.times[3])
        sequences=[flow.HEADER.unpack_from(m)[3] for m in messages]
        self.assertEqual(set(sequences),{1,3})
        self.assertEqual(sequences,sorted(sequences))
        self.assertEqual(source.counts['pending_replaced'],1)
        self.assertEqual(source.counts['packets_handed_off'],2)

    def test_two_slot_and_byte_bound_after_many_offers(self):
        source=sender()
        for n,wire in self.wires.items():source.offer(wire,now=self.times[n])
        self.assertEqual(source.peak_slots,2)
        self.assertLessEqual(source.peak_retained_bytes,2*png.MAX_PACKET)
        self.assertEqual(source.pending.sequence,4)
        self.assertEqual(source.active.sequence,1)

    def test_backpressure_never_exceeds_explicit_byte_threshold(self):
        source=sender(max_buffered_bytes=16384);at=self.times[1]
        source.offer(self.wires[1],now=at)
        self.assertIsNone(pump(source,at,1))
        self.assertEqual(source.index,0)
        message=pump(source,at,0)
        self.assertEqual(len(message),16384)
        self.assertEqual(source.index,1)
        self.assertEqual(source.counts['held_for_buffer'],1)

    def test_expire_active_while_channel_is_full(self):
        source=sender();at=self.times[1]
        source.offer(self.wires[1],now=at)
        self.assertIsNone(pump(source,at+.201,32768))
        self.assertIsNone(source.active)
        self.assertEqual(source.retained_bytes,0)
        self.assertEqual(source.counts['expired'],1)

    def test_expire_active_then_send_surviving_latest_pending(self):
        source=sender();source.offer(self.wires[1],now=self.times[1])
        source.offer(self.wires[4],now=self.times[4])
        message=pump(source,self.times[1]+.201)
        self.assertEqual(flow.HEADER.unpack_from(message)[3],4)
        self.assertEqual(source.counts['expired'],1)

    def test_idle_poll_expires_both_slots_without_send(self):
        source=sender();source.offer(self.wires[1],now=self.times[1])
        source.offer(self.wires[2],now=self.times[2]);source.poll(self.times[2]+.201)
        self.assertEqual(source.retained_bytes,0)
        self.assertEqual(source.counts['expired'],2)

    def test_already_stale_new_offer_consumes_identity_and_clears(self):
        source=sender();self.assertFalse(source.offer(self.wires[1],now=self.times[1]+.201))
        self.assertEqual(source.high_sequence,1)
        self.assertEqual(source.retained_bytes,0)
        self.assertFalse(source.offer(self.wires[1],now=self.times[1]+.202))

    def test_no_handoff_over_sender_capture_deadline(self):
        source=sender();at=self.times[1];source.offer(self.wires[1],now=at)
        self.assertIsNotNone(pump(source,at+.199))
        self.assertIsNone(pump(source,at+.201))
        self.assertLessEqual(source.max_handoff_capture_age_sec,.2)

    def test_invalid_offer_clears_pending_and_active(self):
        source=sender();at=self.times[2]
        source.offer(self.wires[1],now=self.times[1]);source.offer(self.wires[2],now=at)
        self.assertFalse(source.offer(b'bad',now=at))
        self.assertEqual(source.retained_bytes,0)
        self.assertIsNone(pump(source,at))

    def test_duplicate_or_reordered_offer_rejected(self):
        for order in ((1,1),(2,1)):
            source=sender()
            self.assertTrue(source.offer(self.wires[order[0]],now=self.times[3]))
            self.assertFalse(source.offer(self.wires[order[1]],now=self.times[3]))
            self.assertEqual(source.retained_bytes,0)

    def test_foreign_scope_rejected(self):
        for changes in (dict(sender_id='c'*32),dict(stream_id='d'*32)):
            source=sender(**changes)
            self.assertFalse(source.offer(self.wires[1],now=self.times[1]))
            self.assertEqual(source.retained_bytes,0)

    def test_future_source_association_rejected(self):
        source=sender();self.assertFalse(source.offer(self.wires[1],now=self.times[1]-.001))
        self.assertEqual(source.retained_bytes,0)

    def test_new_sequence_cannot_repeat_media_pts(self):
        header,payload=png.unpack_packet(self.wires[2])
        header['candidate']['sender_media_pts']=0;header['encoded_pts']=0
        source=sender();source.offer(self.wires[1],now=self.times[1])
        self.assertFalse(source.offer(png._wrap(header,payload),now=self.times[2]))
        self.assertEqual(source.retained_bytes,0)

    def test_channel_closed_clears_without_old_revival(self):
        source=sender();at=self.times[1];source.offer(self.wires[1],now=at)
        self.assertIsNone(pump(source,at,opened=False));self.assertEqual(source.retained_bytes,0)
        self.assertIsNone(pump(source,at,opened=True))
        self.assertTrue(source.offer(self.wires[2],now=self.times[2]))
        self.assertIsNotNone(pump(source,self.times[2]))

    def test_invalid_channel_state_clears(self):
        for amount,opened in ((True,True),(-1,True),(0,1),(float('nan'),True)):
            source=sender();at=self.times[1];source.offer(self.wires[1],now=at)
            self.assertIsNone(pump(source,at,amount,opened))
            self.assertEqual(source.retained_bytes,0)

    def test_clock_reversal_and_nonfinite_time_retire(self):
        for bad in (self.times[1]-.001,float('nan'),float('inf'),True):
            source=sender();source.offer(self.wires[1],now=self.times[1]);source.poll(bad)
            self.assertTrue(source.closed);self.assertEqual(source.retained_bytes,0)
            self.assertIsNone(pump(source,self.times[2]))

    def test_close_cannot_resume(self):
        source=sender();source.offer(self.wires[1],now=self.times[1]);source.close()
        self.assertFalse(source.offer(self.wires[2],now=self.times[2]))
        self.assertIsNone(pump(source,self.times[2]));self.assertEqual(source.retained_bytes,0)

    def test_explicit_scope_and_limits(self):
        for value in (16383,1048577,True,None):
            with self.assertRaises(ValueError):sender(max_buffered_bytes=value)
        with self.assertRaises(ValueError):sender(stream_id='bad')

    def test_handed_off_bytes_are_not_recalled_on_close(self):
        source=sender();at=self.times[1];source.offer(self.wires[1],now=at)
        message=pump(source,at);source.close()
        self.assertIsInstance(message,bytes)
        self.assertEqual(message,list(flow.fragments(self.wires[1]))[0])


if __name__=='__main__':unittest.main()
