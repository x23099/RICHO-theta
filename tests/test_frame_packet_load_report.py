"""Offline benchmark accounting; no live hardware, timing target or network."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
BENCH=ROOT/'Experimental_results/2026-11-18/frame_packet_load_r01'
sys.path.insert(0,str(BENCH))
from bench import describe,packet_due,FakeSink
from report import equal,same_stats,event_counts
from driver_frame_packet_flow import fragment_plan
from test_driver_frame_packet import image,candidate
from driver_frame_packet import encode_packet


class LoadReportTests(unittest.TestCase):
    def event(self,event,sequence=1,at=100.,admitted=100.):
        return dict(event=event,sequence=sequence,local_time_sec=at,
                    admitted_at_sec=admitted,in_measurement_window=True)

    def test_30hz_tick_selects_exact_explicit_rates(self):
        for rate in (0,5,10,30):
            self.assertEqual(sum(packet_due(tick,rate) for tick in range(90)),rate*3)

    def test_invalid_tick_or_implicit_rate_rejected(self):
        for tick,rate in ((-1,5),(True,5),(0,True),(0,20),(1.,10)):
            with self.assertRaises(ValueError):
                packet_due(tick,rate)

    def test_empty_stats_stays_missing_not_zero(self):
        self.assertEqual(describe([]),dict(count=0,minimum=None,median=None,p95=None,maximum=None))

    def test_statistics_and_mismatch(self):
        stats=describe([1.,2.,3.])
        self.assertEqual(stats['median'],2.)
        same_stats(stats,[1.,2.,3.])
        with self.assertRaises(ValueError):
            same_stats(stats,[1.,2.,4.])

    def test_none_is_not_zero(self):
        self.assertFalse(equal(None,0))
        self.assertTrue(equal(None,None))

    def test_completed_and_missing_source_are_distinct(self):
        offered,done=event_counts([self.event('offered'),self.event('offered',sequence=2),
                                  self.event('send_complete',at=100.03)])
        self.assertEqual(set(offered)-set(done),{2})
        self.assertAlmostEqual(done[1][0]-done[1][1],.03)

    def test_duplicate_and_unoffered_completion_rejected(self):
        for events in ([self.event('offered')]*2,[self.event('send_complete')]):
            with self.assertRaises(ValueError):
                event_counts(events)

    def test_expiry_changed_admission_and_reversed_event_rejected(self):
        for done in (self.event('send_complete',at=100.3),
                     self.event('send_complete',at=100.03,admitted=100.01),
                     self.event('send_complete',at=99.)):
            with self.assertRaises(ValueError):
                event_counts([self.event('offered'),done])

    def test_nonfinite_event_and_bad_sequence_rejected(self):
        for value in (self.event('offered',at=float('nan')),self.event('offered',sequence=0)):
            with self.assertRaises(ValueError):
                event_counts([value])

    def test_warmup_events_not_counted_as_measurement(self):
        warmup=self.event('offered')
        warmup['in_measurement_window']='False'
        self.assertEqual(event_counts([warmup]),({},{}))

    def test_fake_sink_does_not_keep_payload_or_create_transport(self):
        plan=fragment_plan(encode_packet(image(),candidate()),message_bytes=16384)
        sink=FakeSink()
        for index in range(plan.count):
            sink.send(plan.fragment(index))
        self.assertEqual(sink.bufferedAmount,0)
        self.assertEqual(len(sink.records),1)
        self.assertEqual(sink.message_bytes,len(plan.wire)+plan.count*88)
        self.assertEqual(sink.messages,plan.count)
        self.assertIsNone(sink.current)

    def test_installed_streaming_codec_one_tick_rounding_is_diagnostic_only(self):
        import av
        from fractions import Fraction
        from aiortc.codecs.vpx import Vp8Encoder
        encoder=Vp8Encoder()
        for sequence in range(5):
            frame=av.VideoFrame.from_ndarray(image(),format='bgr24')
            frame.pts,frame.time_base=sequence*3000,Fraction(1,90000)
            _,pts=encoder.encode(frame)
            self.assertLessEqual(abs(pts-sequence*3000),1)


if __name__=='__main__':
    unittest.main()
