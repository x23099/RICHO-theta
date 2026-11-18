"""Small deterministic virtual-link fixtures, not real timing benchmarks."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
PATH=ROOT/'Experimental_results/2026-11-18/lossless_sender_load_r01/model.py'
SPEC=importlib.util.spec_from_file_location('png_load_model_tests',PATH)
model=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=model;SPEC.loader.exec_module(model)
from test_driver_frame_packet import candidate


class LoadModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=np.full((720,1280,3),93,np.uint8)
        wire=model.packet.encode_packet(source,candidate())
        cls.header,cls.payload=model.packet.unpack_packet(wire)
        large=np.random.default_rng(61).integers(0,8,(720,1280,3),dtype=np.uint8)*32
        cls.large_header,cls.large_payload=model.packet.unpack_packet(model.packet.encode_packet(large,candidate()))

    def simulate(self,**options):
        sender_ms=options.pop('sender_ms',5.)
        receiver_ms=options.pop('receiver_ms',5.)
        template=model.Template('synthetic_not_camera',self.header,self.payload,sender_ms,receiver_ms)
        settings=dict(name='test',hz=10,rate_mbps=15,duration_sec=1.)
        settings.update(options)
        return model.simulate([template],**settings)

    def test_small_fixture_delivers_one_shot_exact_frames(self):
        summary,rows=self.simulate()
        self.assertEqual(summary['counts']['captured'],10)
        self.assertEqual(summary['counts']['consumed'],10)
        self.assertEqual([r['sequence'] for r in rows],list(range(1,11)))
        self.assertTrue(all(r['exact_pixels'] and not r['usable_for_ffb'] for r in rows))

    def test_deterministic_scenario_reproduces_every_counter_and_trace(self):
        self.assertEqual(self.simulate(loss_every=3),self.simulate(loss_every=3))

    def test_dropped_single_fragments_never_form_partial_images(self):
        summary,rows=self.simulate(loss_every=2)
        self.assertEqual(summary['counts']['fragment_drops'],5)
        self.assertEqual(summary['counts']['consumed'],5)
        self.assertEqual([r['sequence'] for r in rows],[1,3,5,7,9])

    def test_delayed_first_arrival_is_not_source_freshness_proof(self):
        summary,rows=self.simulate(transit_delay_sec=.5)
        self.assertEqual(len(rows),10)
        self.assertGreater(summary['oracle_max_capture_to_take_ms'],500)
        self.assertEqual(summary['oracle_over_200ms_consumed'],10)
        self.assertLess(summary['max_receiver_local_first_to_take_ms'],200)
        self.assertFalse(summary['source_freshness_verified'])

    def test_slow_sender_replaces_waiting_input_and_expires_output(self):
        summary,rows=self.simulate(sender_ms=300.)
        self.assertEqual(rows,[])
        self.assertGreater(summary['counts']['raw_pending_replaced'],0)
        self.assertGreater(summary['sender']['expired'],0)
        self.assertEqual(summary['peaks']['raw_slots'],2)

    def test_slow_receiver_queue_is_bounded_and_never_returns_expired_pair(self):
        summary,rows=self.simulate(receiver_ms=180.)
        self.assertGreater(summary['counts']['decode_pending_replaced'],0)
        self.assertGreater(summary['counts']['decode_rejected_or_expired'],0)
        self.assertLessEqual(summary['peaks']['decode_slots'],2)
        self.assertTrue(all(r['receiver_local_first_to_take_ms']<=200.000001 for r in rows))

    def test_stall_model_resumes_with_bounded_channel_queue(self):
        # A flat-color PNG fits several whole frames inside 32KiB and does NOT
        # necessarily cause pressure. Use a larger byte fixture for this test.
        template=model.Template('large_synthetic',self.large_header,self.large_payload,5.,5.)
        summary,rows=model.simulate([template],name='stall',hz=10,rate_mbps=100,
            duration_sec=1.,stall=(.2,.7))
        self.assertLessEqual(summary['peaks']['channel_buffer_bytes'],32768)
        self.assertGreater(summary['sender']['held_for_buffer'],0)
        self.assertTrue(any(r['sequence']>=9 for r in rows))

    def test_fixed_limits_and_explicit_model_costs_required(self):
        for change in (dict(hz=100),dict(rate_mbps=0),dict(duration_sec=1000),dict(receiver_ms=float('nan'))):
            with self.assertRaises(ValueError):self.simulate(**change)


if __name__=='__main__':unittest.main()
