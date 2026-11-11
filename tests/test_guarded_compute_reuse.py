"""Offline per-frame compute sharing; no CUDA, stream, camera or control."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_compute_reuse_r01'))
import compute as candidate
from cone_distance_core import load_config
from cone_motion_range import MotionRangeEngine,load_motion_profile
from cone_upper_support_candidate import observe_upper_completion
from theta_rtc_frames import NativeFrame

BOX=dict(x1=301.,y1=305.,x2=339.,y2=399.6,confidence=.95,class_id=0)


class CurrentFrameReuseTests(unittest.TestCase):
    def setUp(self):
        settings,camera,_,_=load_config()
        profile,sha=load_motion_profile(ROOT/('Experimental_results/2026-11-09/'
            'cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'),settings)
        self.data=dict(settings=settings,camera=camera,profile=profile,profile_sha=sha)
        self.image=np.zeros((720,1280,3),np.uint8)
        cv2.fillPoly(self.image,[np.array([[320,310],[295,400],[345,400]],np.int32)],(0,0,255))
        self.image.flags.writeable=False
        self.frame=NativeFrame('a'*32,2,.1,10.,self.image)
        self.ref=dict(schema='offline_self_body_boundary_v1',image_size=[1280,720],
            layout='dual_fisheye_front_left_unremapped',session='a'*32,source_frame=1,
            source_png_sha256='b'*64,boundary_xy=[[280,458],[360,458]],
            independent_physical_measurement=False,cross_session_mount_verified=False,
            live_authorized=False,floor_contact_verified=False)

    def original(self,boxes):
        return MotionRangeEngine(self.data['settings'],self.data['camera'],self.data['profile'],
            self.data['profile_sha'],acknowledged=True,target_roi=[270,0,350,720],
            observer=observe_upper_completion).measure(self.frame,boxes,10.005)

    def run_case(self,boxes=None,original=None,shared=True,frame=None,**kwargs):
        boxes=[dict(BOX)] if boxes is None else boxes
        original=self.original(boxes) if original is None else original
        return candidate.evaluate_offline_frame(frame or self.frame,boxes,original,self.data,self.ref,
            completed_at=10.01,shared=shared,offline_only=True,**kwargs)

    def test_same_complete_results_for_legacy_and_shared(self):
        boxes=[dict(BOX)];original=self.original(boxes)
        self.assertEqual(self.run_case(boxes,original,shared=False),self.run_case(boxes,original,shared=True))

    def test_observation_runs_twice_versus_once_from_current_pixels(self):
        boxes=[dict(BOX)];original=self.original(boxes)
        for shared,expected in ((False,2),(True,1)):
            with patch('cone_bbox_boundary_shadow.observe_upper_completion',wraps=observe_upper_completion) as boundary,\
                 patch.object(candidate,'observe_upper_completion',wraps=observe_upper_completion) as metric:
                self.run_case(boxes,original,shared=shared)
            self.assertEqual(boundary.call_count+metric.call_count,expected)
            self.assertIs(boundary.call_args.args[0],self.image)

    def test_original_pixels_boxes_and_results_unchanged(self):
        boxes=[dict(BOX)];original=self.original(boxes)
        before=(copy.deepcopy(boxes),copy.deepcopy(original),self.image.tobytes())
        output=self.run_case(boxes,original)
        self.assertEqual(boxes,before[0]);self.assertEqual(original,before[1])
        output['baseline']['support_observation']['reason']='changed baseline output'
        output['proposal']['support_observation']['reason']='changed output'
        self.assertEqual(original,before[1])
        self.assertEqual(self.image.tobytes(),before[2])
        self.assertFalse(self.image.flags.writeable)

    def test_main_log_observation_forgery_is_not_reused(self):
        boxes=[dict(BOX)];original=self.original(boxes)
        original['support_observation']['reason']='forged cached observation'
        with self.assertRaisesRegex(ValueError,'cannot reproduce original'):
            self.run_case(boxes,original)

    def test_selected_box_forgery_rejected_independently_of_raw_boxes(self):
        boxes=[dict(BOX)];original=self.original(boxes)
        original['selected_detector_boxes']=[]
        with self.assertRaisesRegex(ValueError,'cannot reproduce original'):
            self.run_case(boxes,original)

    def test_input_flags_profile_and_identity_rejected(self):
        for change in (dict(profile_sha256='f'*64),dict(published_to_ros=True),dict(session='b'*32),
                       dict(frame=1),dict(completed_time_sec=11.)):
            boxes=[dict(BOX)];original=self.original(boxes);original.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.run_case(boxes,original)

    def test_geometry_forgery_rejected(self):
        for change in (dict(horizontal_camera_foot_range_m=2.),dict(reason='invented'),dict(distance_available=True)):
            boxes=[dict(BOX)];original=self.original(boxes);original.update(change)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'cannot reproduce original'):
                self.run_case(boxes,original)

    def test_no_candidate_or_ambiguous_never_inherits_previous_number(self):
        self.assertTrue(self.run_case()['proposal']['distance_available'])
        for boxes in ([],[dict(BOX),dict(BOX,confidence=.94)]):
            for shared in (False,True):
                result=self.run_case(boxes,shared=shared)
                self.assertFalse(result['proposal']['distance_available'])
                self.assertIsNone(result['proposal']['horizontal_camera_foot_range_m'])

    def test_body_veto_preserved(self):
        self.ref['boundary_xy']=[[280,400],[360,400]]
        self.assertEqual(self.run_case(shared=False),self.run_case(shared=True))
        self.assertFalse(self.run_case()['proposal']['distance_available'])
        self.assertEqual(self.run_case()['body_review_reason'],'possible_self_body_occlusion')

    def test_baseline_existing_point_preserved_when_clear(self):
        boxes=[dict(BOX,x1=280.,y1=300.,x2=360.,y2=420.)]
        legacy=self.run_case(boxes,shared=False);shared=self.run_case(boxes)
        self.assertEqual(legacy,shared)
        self.assertTrue(shared['baseline']['distance_available'])
        self.assertEqual(shared['baseline']['support_pixel'],shared['proposal']['support_pixel'])

    def test_each_call_reextracts_no_cross_frame_cache(self):
        boxes=[dict(BOX)];original=self.original(boxes)
        with patch('cone_bbox_boundary_shadow.observe_upper_completion',wraps=observe_upper_completion) as observed:
            self.run_case(boxes,original);self.run_case(boxes,original)
        self.assertEqual(observed.call_count,2)

    def test_comparator_failure_does_not_return_a_past_result(self):
        self.assertTrue(self.run_case()['proposal']['distance_available'])
        with patch.object(candidate,'compare_guarded_lower_edge',side_effect=RuntimeError('failed current extraction')):
            with self.assertRaises(RuntimeError):self.run_case()

    def test_reference_mismatch_cannot_grant_a_number(self):
        self.ref['session']='b'*32
        self.assertFalse(self.run_case()['proposal']['distance_available'])

    def test_explicit_offline_only_ack_required(self):
        boxes=[dict(BOX)];original=self.original(boxes)
        with self.assertRaises(ValueError):
            candidate.evaluate_offline_frame(self.frame,boxes,original,self.data,self.ref,completed_at=10.01)
        result=self.run_case()
        self.assertFalse(result['reference_lifecycle_verified'])
        self.assertFalse(result['live_authorized'])
        self.assertTrue(all(result[k] is False for k in candidate.FLAGS))


if __name__=='__main__':unittest.main()
