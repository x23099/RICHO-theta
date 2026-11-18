"""Lossless candidate experiments only; no GPU, hardware or image outputs."""
import copy
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import zlib

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('pixel_preservation_test',ROOT/
    'Experimental_results/2026-11-18/frame_packet_preservation_r01/compare.py')
experiment=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(experiment)
probe=experiment.probe


class PreservationTests(unittest.TestCase):
    def setUp(self):
        # Deterministic native BGR pattern, exact byte comparisons rather than PSNR.
        self.image=np.empty((720,1280,3),np.uint8)
        self.image[:,:,0]=np.arange(1280,dtype=np.uint16)[None,:]%256
        self.image[:,:,1]=np.arange(720,dtype=np.uint16)[:,None]%256
        self.image[:,:,2]=127
        self.image.flags.writeable=False

    def test_three_lossless_payloads_reproduce_all_native_pixels(self):
        before=probe.sha_bytes(self.image.tobytes())
        for kind in experiment.KINDS[1:]:
            with self.subTest(kind=kind):
                wire=experiment.encode_lossless(self.image,kind)
                image=experiment.decode_lossless(wire,kind)
                self.assertEqual(image.shape,(720,1280,3))
                self.assertEqual(probe.sha_bytes(image.tobytes()),before)
                self.assertFalse(image.flags.writeable)
        self.assertEqual(probe.sha_bytes(self.image.tobytes()),before)
        self.assertFalse(self.image.flags.writeable)

    def test_PNG_dimensions_rejected_before_codec_decode(self):
        wire=bytearray(experiment.encode_lossless(self.image,'png_default'))
        wire[16:20]=struct.pack('!I',2**30)
        with self.assertRaisesRegex(ValueError,'IHDR'):
            experiment.decode_lossless(bytes(wire),'png_default')

    def test_PNG_wrong_bit_depth_channel_or_header_rejected(self):
        wire=experiment.encode_lossless(self.image,'png_default')
        for index,value in ((0,0),(24,16),(25,6)):
            changed=bytearray(wire);changed[index]=value
            with self.subTest(index=index),self.assertRaisesRegex(ValueError,'IHDR'):
                experiment.decode_lossless(bytes(changed),'png_default')

    def test_zlib_truncated_or_trailing_stream_rejected(self):
        wire=experiment.encode_lossless(self.image,'zlib_level1')
        for value in (wire[:-1],wire+b'junk',wire+wire):
            with self.assertRaises(ValueError):experiment.decode_lossless(value,'zlib_level1')

    def test_zlib_wrong_output_lengths_rejected_without_unbounded_flush(self):
        for size in (experiment.RAW_BYTES-1,experiment.RAW_BYTES+100):
            wire=zlib.compress(b'\0'*size,1)
            with self.assertRaisesRegex(ValueError,'bounded native'):
                experiment.decode_lossless(wire,'zlib_level1')

    def test_unknown_codec_and_payload_limits_rejected(self):
        with self.assertRaises(ValueError):experiment.encode_lossless(self.image,'unknown')
        for payload in (b'',bytearray(b'x'),b'x'*(experiment.CAP+1)):
            with self.assertRaises(ValueError):experiment.decode_lossless(payload,'zlib_level1')
        with patch.object(experiment,'CAP',10),self.assertRaisesRegex(ValueError,'no cap expansion'):
            experiment.encode_lossless(self.image,'png_default')

    def fixture(self):
        settings,camera,_,_=probe.load_config()
        profile,sha=probe.load_motion_profile(probe.PROFILE,settings)
        engine=probe.MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,
            target_roi=[270,0,350,720],observer=probe.observe_upper_completion)
        image=self.image
        value=engine.measure(probe.NativeFrame('c'*32,1,0.,1.,image),[],1.)
        old=dict(sequence=1,measurement=value,raw_detector_boxes=[],
                 inference_pixel_sha256=probe.sha_bytes(image.tobytes()))
        case=dict(job=dict(path='fixture.png',image=image,pixel_sha256=probe.sha_bytes(image.tobytes()),png_sha256='a'*64),
                  records=dict(original=old,packet=copy.deepcopy(old)),roi=[270,0,350,720])
        return case,settings,camera,profile,sha

    def test_decision_reproduced_without_claiming_new_inference_or_runtime_compatibility(self):
        case,*args=self.fixture()
        row=experiment.trial(case,'png_default',0,*args)
        self.assertTrue(row['decision_identical_to_original'])
        self.assertTrue(row['pixels_identical_to_original'])
        self.assertFalse(row['new_YOLO_inference_performed'])
        self.assertFalse(row['live_packet_format_compatible'])
        self.assertFalse(row['usable_for_ffb'])
        self.assertEqual(row['reason'],'no_candidate')

    def test_saved_bbox_cannot_be_reused_on_different_inference_pixels(self):
        case,*args=self.fixture()
        case['records']['original']['inference_pixel_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'exact image'):
            experiment.trial(case,'png_default',0,*args)

    def test_changed_historical_geometry_not_silently_reproduced(self):
        case,*args=self.fixture()
        case['records']['original']['measurement']['reason']='invented'
        with self.assertRaisesRegex(ValueError,'does not reproduce'):
            experiment.trial(case,'zlib_level1',0,*args)

    def test_summary_keeps_rate_scope_and_changes_separate(self):
        case,*args=self.fixture()
        row=experiment.trial(case,'png_default',0,*args)
        summary=experiment.summarize([row])
        self.assertEqual(summary['png_default']['trials'],1)
        self.assertEqual(summary['png_default']['decisions_preserved_trials'],1)
        self.assertEqual(summary['png_default']['withheld_to_numeric'],0)
        self.assertEqual(summary['vp8_current']['trials'],0)
        self.assertAlmostEqual(row['payload_or_packet_Mbps_at_10Hz'],row['bytes']*80/1e6)
        self.assertAlmostEqual(row['ideal_serialization_ms_at_15Mbps'],row['bytes']*8/15000)

    def test_decision_comparison_allows_roundoff_not_metric_or_pixel_changes(self):
        a=dict(distance_available=True,reason='example',support_pixel=[232,409],
               horizontal_camera_foot_range_m=1.189269304864688)
        b=dict(a,horizontal_camera_foot_range_m=1.1892693048646885)
        self.assertTrue(experiment.decisions_equal(b,a))
        self.assertFalse(experiment.decisions_equal(dict(b,horizontal_camera_foot_range_m=1.159),a))
        self.assertFalse(experiment.decisions_equal(dict(b,support_pixel=[232,411]),a))
        self.assertFalse(experiment.decisions_equal(dict(b,reason='changed'),a))
        self.assertTrue(experiment.decisions_equal(dict(b,support_observation={'diagnostic':'different'}),a))


if __name__=='__main__':unittest.main()
