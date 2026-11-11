"""Saved-image benchmark tests. Synthetic predictor only; no CUDA/camera/ROS."""
import argparse
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_replay_r01'))
import cuda_replay as replay

BOX=dict(x1=301.,y1=305.,x2=339.,y2=399.6,confidence=.95,class_id=0)


class SavedCudaReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        settings,camera,_,_=replay.load_config()
        profile,sha=replay.load_motion_profile(ROOT/('Experimental_results/2026-11-09/'
            'cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'),settings)
        image=np.zeros((720,1280,3),np.uint8)
        cv2.fillPoly(image,[np.array([[320,310],[295,400],[345,400]],np.int32)],(0,0,255))
        image.flags.writeable=False
        png=cv2.imencode('.png',image)[1].tobytes()
        self.job=dict(image=image,session='a'*32,frame=7,
            pixel_sha256=replay.digest_bytes(image.tobytes()),png_sha256=replay.digest_bytes(png),
            historical_measurement=dict(selected_detector_boxes=['DO NOT REUSE']))
        reference=dict(schema='offline_self_body_boundary_v1',image_size=[1280,720],
            layout='dual_fisheye_front_left_unremapped',session='a'*32,source_frame=7,
            source_png_sha256=self.job['png_sha256'],boundary_xy=[[280,458],[360,458]],
            independent_physical_measurement=False,cross_session_mount_verified=False,
            live_authorized=False,floor_contact_verified=False)
        self.data=dict(settings=settings,camera=camera,profile=profile,profile_sha=sha,
            jobs=[self.job,dict(self.job,frame=8)],reference=reference,input_sha256={})

    def engine(self):
        return replay.MotionRangeEngine(self.data['settings'],self.data['camera'],
            self.data['profile'],self.data['profile_sha'],acknowledged=True,
            target_roi=[270,0,350,720],observer=replay.observe_upper_completion)

    def args(self,**kwargs):
        parser=argparse.ArgumentParser();replay.options(parser)
        values=parser.parse_args(['--input-dir',str(self.directory/'source'),
            '--evidence-dir',str(self.directory/'evidence'),'--output-dir',str(self.directory/'output'),
            '--experimental-rigid-mount','--validate-only'])
        for key,value in kwargs.items():setattr(values,key,value)
        return values

    def test_measure_calls_predictor_with_exact_native_pixels(self):
        seen=[]
        def predictor(frame):
            seen.append(frame)
            return [dict(BOX)]
        frame,result=replay.measure(self.engine(),predictor,self.job,'b'*32,1,'synthetic_test')
        self.assertIs(frame.image,self.job['image'])
        self.assertEqual(len(seen),1)
        self.assertEqual(result['raw_detector_boxes'],[BOX])
        self.assertEqual(result['original_frame'],7)
        self.assertEqual(result['inference_source'],'synthetic_test_NOT_CUDA')
        self.assertTrue(all(result[k] is False for k in replay.FLAGS))

    def test_new_empty_detection_is_not_replaced_with_historical_detection(self):
        _,result=replay.measure(self.engine(),lambda frame:[],self.job,'b'*32,1,'actual_cuda')
        self.assertEqual(result['raw_detector_boxes'],[])
        self.assertEqual(result['reason'],'no_candidate')
        self.assertFalse(result['distance_available'])

    def test_processing_age_gate_preserved(self):
        with patch.object(replay.time,'monotonic',side_effect=[10.,11.,11.1]):
            _,result=replay.measure(self.engine(),lambda frame:[BOX],self.job,'b'*32,1,'synthetic_test')
        self.assertEqual(result['reason'],'frame_processing_too_old')
        self.assertIsNone(result['horizontal_camera_foot_range_m'])

    def test_budget_rejects_overflow_without_partial_write(self):
        stream=io.StringIO();budget=replay.Budget(5)
        with self.assertRaises(ValueError):budget.write(stream,dict(test=1))
        self.assertEqual(stream.getvalue(),'')
        self.assertEqual(budget.used,0)

    def test_signatures_order_independent_and_nonfinite_rejected(self):
        self.assertEqual(replay.signature(dict(a=1,b=2)),replay.signature(dict(b=2,a=1)))
        with self.assertRaises(ValueError):replay.signature(float('nan'))

    def test_pairing_omits_only_replay_image_provenance_not_detection_fields(self):
        a=dict(BOX,image='session_a:1',prediction_index=0)
        b=dict(BOX,image='session_b:2',prediction_index=0)
        self.assertEqual(replay.detector_values([a]),replay.detector_values([b]))
        _,first=replay.measure(self.engine(),lambda frame:[a],self.job,'b'*32,1,'synthetic_test')
        _,second=replay.measure(self.engine(),lambda frame:[b],self.job,'c'*32,1,'synthetic_test')
        self.assertEqual(replay.primary_signature(first),replay.primary_signature(second))
        second['selected_detector_boxes'][0]['confidence']=.99
        self.assertNotEqual(replay.primary_signature(first),replay.primary_signature(second))
        self.assertEqual(first['raw_detector_boxes'][0]['image'],'session_a:1')

    def test_wait_reports_worker_error(self):
        worker=argparse.Namespace(error='synthetic writer error')
        with self.assertRaisesRegex(RuntimeError,'synthetic writer error'):
            replay.wait_for(lambda:True,worker,time.monotonic()+1)

    def test_wait_is_bounded(self):
        with self.assertRaises(TimeoutError):
            replay.wait_for(lambda:False,argparse.Namespace(error=None),time.monotonic()-1)

    def test_benchmark_option_limits(self):
        for kwargs in (dict(cycles=0),dict(cycles=True),dict(warmup=65),dict(fps=float('nan')),
                       dict(fps=61),dict(max_duration=601),dict(execution_kind='cached')):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                replay.benchmark(self.data,lambda frame:[BOX],self.directory,**kwargs)

    def test_real_thread_abba_synthetic_predictor_and_immutable_pixels(self):
        calls=[]
        def predictor(frame):
            calls.append(frame)
            return [dict(BOX,image=f'{frame.session}:{frame.sequence}',prediction_index=0)]
        before=self.job['image'].tobytes()
        summary=replay.benchmark(self.data,predictor,self.directory,cycles=1,warmup=1,fps=60)
        self.assertEqual(summary['state'],'complete')
        self.assertFalse(summary['actual_cuda_inference'])
        self.assertEqual(len(calls),1+4*(1+2))  # warmup + four setup + eight measured
        self.assertEqual(summary['paired_samples'],4)
        self.assertEqual(summary['primary_changed_pairs'],0)
        self.assertEqual(summary['detector_changed_pairs'],0)
        self.assertEqual(summary['warmup_excluded_calls'],1)
        self.assertEqual(summary['groups']['on']['measured_frames'],4)
        self.assertEqual(summary['groups']['off']['predict_ms']['count'],4)
        self.assertEqual(summary['groups']['on']['start_interval_ms']['count'],2)
        self.assertEqual(self.job['image'].tobytes(),before)
        self.assertFalse(self.job['image'].flags.writeable)
        for block in summary['blocks']:
            if not block['comparison_enabled']:continue
            self.assertTrue(block['comparison_shutdown']['shutdown_complete'])
            self.assertEqual(block['comparison_final_status']['snapshots_saved'],1)
            self.assertGreaterEqual(block['comparison_reference_rows'],1)
            self.assertGreaterEqual(block['comparison_numeric_rows'],1)
            path=self.directory/f"block_{block['id']:02d}_on/comparison/reference.json"
            ref=json.loads(path.read_text())
            self.assertTrue(ref['offline_replay_binding_NOT_live_mount_evidence'])
            self.assertNotEqual(ref['session'],self.data['reference']['session'])
            self.assertFalse(ref['live_authorized'])

    def test_predictor_mutating_source_is_rejected(self):
        calls=0
        def predictor(frame):
            nonlocal calls
            calls+=1
            if calls==3:
                frame.image.flags.writeable=True
                frame.image[0,0,0]=1
                frame.image.flags.writeable=False
            return []
        with self.assertRaisesRegex(ValueError,'modified source pixels'):
            replay.benchmark(self.data,predictor,self.directory,cycles=1,warmup=1,fps=60)

    def test_worker_setup_error_does_not_get_success_summary(self):
        with patch.object(replay,'issue',side_effect=RuntimeError('synthetic request failure')):
            with self.assertRaisesRegex(RuntimeError,'synthetic request failure'):
                replay.benchmark(self.data,lambda frame:[],self.directory,cycles=1,warmup=1,fps=60)
        status=json.loads((self.directory/'block_01_on/comparison/comparison_status.json').read_text())
        self.assertTrue(status['shutdown_complete'])

    @staticmethod
    def blocks():
        result=[]
        for n,enabled in enumerate([False,True,True,False]):
            row=dict(original_frame=7,cycle=0,primary_signature='p',detector_signature='d',
                range_m=1.,predict_ms=2.,primary_ms=3.,comparison_tap_ms=0.,primary_log_and_tap_ms=4.,
                start_interval_ms=None,distance_available=True,period_overrun=False,reason='example')
            result.append(dict(id=n,comparison_enabled=enabled,records=[row]))
        return result

    def test_summary_separates_detection_variation_from_primary(self):
        blocks=self.blocks();blocks[1]['records'][0]['detector_signature']='different'
        summary=replay.summarize(blocks,[dict(predict_ms=1000)],30,'synthetic_test')
        self.assertEqual(summary['primary_changed_pairs'],0)
        self.assertEqual(summary['detector_changed_pairs'],1)
        self.assertEqual(summary['groups']['on']['predict_ms']['max'],2.)
        self.assertEqual(summary['warmup_predict_ms']['max'],1000)

    def test_primary_difference_reported_without_claiming_cause(self):
        blocks=self.blocks();blocks[2]['records'][0].update(primary_signature='new',range_m=1.2)
        summary=replay.summarize(blocks,[],30,'synthetic_test')
        self.assertEqual(summary['primary_changed_pairs'],1)
        self.assertEqual(summary['primary_reproducibility'],'differences_observed_NOT_causally_attributed')
        self.assertAlmostEqual(summary['pairs'][1]['range_abs_delta_m'],.2)
        self.assertFalse(summary['live_latency_verified'])

    def test_unpaired_summary_rejected(self):
        for mode in ('count','identity','length','order'):
            blocks=self.blocks()
            if mode=='count':blocks.pop()
            if mode=='identity':blocks[1]['records'][0]['original_frame']=8
            if mode=='length':blocks[1]['records']=[]
            if mode=='order':blocks[0]['comparison_enabled']=True
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                replay.summarize(blocks,[],30,'synthetic_test')

    def test_validate_only_never_constructs_yolo(self):
        args=self.args()
        with patch.object(replay,'comparison_path',return_value=args.output_dir),\
             patch.object(replay,'load_inputs',return_value=self.data),\
             patch.object(replay,'YoloConePredictor',side_effect=AssertionError('CUDA must not start')):
            result=replay.run(args)
        self.assertEqual(result['state'],'validated_inputs_only')
        self.assertFalse(result['cuda_started'])

    def test_wrong_checkpoint_rejected_before_constructor_and_output(self):
        weights=self.directory/'wrong.pt';weights.write_bytes(b'wrong')
        args=self.args(validate_only=False,weights=weights)
        with patch.object(replay,'comparison_path',return_value=args.output_dir),\
             patch.object(replay,'load_inputs',return_value=self.data),\
             patch.object(replay,'YoloConePredictor',side_effect=AssertionError('must not load')):
            with self.assertRaisesRegex(ValueError,'checkpoint SHA mismatch'):replay.run(args)
        self.assertFalse(args.output_dir.exists())

    def test_missing_weights_rejected(self):
        args=self.args(validate_only=False)
        with patch.object(replay,'comparison_path',return_value=args.output_dir),\
             patch.object(replay,'load_inputs',return_value=self.data):
            with self.assertRaisesRegex(ValueError,'explicit local --weights'):replay.run(args)

    def test_model_init_failure_saved_without_cpu_fallback(self):
        weights=self.directory/'model.pt';weights.write_bytes(b'synthetic')
        data=copy.deepcopy(self.data);data['settings']['weights_sha256']=replay.digest_bytes(b'synthetic')
        args=self.args(validate_only=False,weights=weights)
        with patch.object(replay,'comparison_path',return_value=args.output_dir),\
             patch.object(replay,'load_inputs',return_value=data),\
             patch.object(replay,'YoloConePredictor',side_effect=RuntimeError('CUDA unavailable')) as model:
            with self.assertRaisesRegex(RuntimeError,'CUDA unavailable'):replay.run(args)
        self.assertEqual(model.call_count,1)
        summary=json.loads((args.output_dir/'summary.json').read_text())
        self.assertEqual(summary['state'],'failed')
        self.assertTrue(summary['cuda_model_initialization_attempted'])
        self.assertFalse(summary['actual_cuda_inference'])

    def test_output_cannot_overlap_original(self):
        args=self.args(input_dir=self.directory)
        with patch.object(replay,'comparison_path',return_value=args.output_dir),\
             patch.object(replay,'load_inputs',side_effect=AssertionError('do not load')):
            with self.assertRaisesRegex(ValueError,'outside original'):replay.run(args)

    def test_cli_requires_explicit_mount_acknowledgement(self):
        parser=argparse.ArgumentParser();replay.options(parser)
        with patch('sys.stderr',io.StringIO()),self.assertRaises(SystemExit):
            parser.parse_args(['--input-dir','source','--evidence-dir','evidence','--output-dir','output'])

    def test_invalid_cli_bounds_rejected_before_loading(self):
        for values in (dict(fps=float('inf')),dict(device=-1),dict(cycles=0),dict(warmup=65)):
            with self.subTest(values=values),patch.object(replay,'load_inputs',side_effect=AssertionError('no load')):
                with self.assertRaises(ValueError):replay.run(self.args(**values))


if __name__=='__main__':unittest.main()
