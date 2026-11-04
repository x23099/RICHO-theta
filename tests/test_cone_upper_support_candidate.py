"""Synthetic OFFLINE comparison tests. No live camera, model or FFB output."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cone_distance_core import ConeDistanceEngine, load_config
from cone_support_completion_candidate import observe_lateral_completion
from cone_support_quality import ConeSupportQualityGate
from cone_upper_support_candidate import _upper_context, observe_upper_completion
from theta_rtc_frames import NativeFrame

BOX=dict(x1=290.,y1=305.,x2=350.,y2=405.,class_id=0,confidence=.95)


def cone(colour=(0,0,255),tip_y=300):
    image=np.zeros((720,1280,3),np.uint8)
    cv2.fillPoly(image,[np.array([[320,tip_y],[295,400],[345,400]],np.int32)],colour)
    return image


class UpperSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera=load_config()[1]

    def test_top_only_red_component_closes_without_changing_lower_support(self):
        image=cone()
        self.assertIsNone(observe_lateral_completion(image,BOX,self.camera)["point"])
        r=observe_upper_completion(image,BOX,self.camera)
        self.assertTrue(r["upper_completion_granted"])
        self.assertEqual(r["point"],[320,400])
        self.assertEqual(r["reason"],"unverified_upper_completed_colour_support")
        original,first,second=r["upper_contexts"]
        self.assertEqual([x["top_padding_px"] for x in r["upper_contexts"]],[4,16,32])
        self.assertEqual(first["component"]["pixel_sha256"],second["component"]["pixel_sha256"])
        self.assertEqual(first["observation"],second["observation"])
        self.assertEqual(original["component"]["observed_lower_support"],r["support"])
        self.assertIn(r["point"],original["component"]["observed_lower_support"])
        self.assertTrue(all(x["lateral_padding_px"]==x["bottom_padding_px"]==4 for x in r["upper_contexts"]))

    def test_yellow_top_completion_keeps_original_colour(self):
        r=observe_upper_completion(cone((0,255,255)),BOX,self.camera)
        self.assertTrue(r["upper_completion_granted"])
        self.assertEqual(r["selected_colour"],"yellow")

    def test_existing_nonclipped_observations_preserved(self):
        box=dict(BOX,y1=295.)
        for colour in ((0,0,255),(0,255,255)):
            old=observe_lateral_completion(cone(colour),box,self.camera)
            r=observe_upper_completion(cone(colour),box,self.camera)
            self.assertEqual(r["original_comparison"],old)
            for key in ("point","support","reason","selected_colour"):
                self.assertEqual(r[key],old[key])
            self.assertFalse(r["upper_completion_attempted"])
            self.assertEqual(r["upper_contexts"],[])

    def test_existing_lateral_completion_is_preserved(self):
        image=cone(tip_y=310)
        box=dict(BOX,x1=301.,x2=339.)
        old=observe_lateral_completion(image,box,self.camera)
        self.assertTrue(old["completion_granted"])
        r=observe_upper_completion(image,box,self.camera)
        self.assertEqual(r["original_comparison"],old)
        self.assertEqual(r["point"],old["point"])
        self.assertFalse(r["upper_completion_granted"])

    def test_bottom_contact_is_not_rescued(self):
        image=cone()
        cv2.rectangle(image,(280,395),(360,430),(0,0,255),-1)
        r=observe_upper_completion(image,BOX,self.camera)
        self.assertIsNone(r["point"])
        self.assertFalse(r["upper_completion_attempted"])
        self.assertEqual(r["upper_completion_reason"],"not_top_only_contact")

    def test_top_and_side_contact_not_jointly_rescued(self):
        r=observe_upper_completion(cone(),dict(BOX,x1=301.,x2=339.),self.camera)
        self.assertIsNone(r["point"])
        self.assertEqual(r["upper_completion_reason"],"not_top_only_contact")

    def test_completed_point_must_stay_in_original_float_bbox(self):
        r=observe_upper_completion(cone(),dict(BOX,y2=398.),self.camera)
        self.assertIsNone(r["point"])
        self.assertTrue(r["upper_completion_attempted"])
        self.assertEqual(r["upper_completion_reason"],"upper_point_outside_original_bbox")

    def test_component_still_open_within_bound_is_not_extended_further(self):
        r=observe_upper_completion(cone(tip_y=250),BOX,self.camera)
        self.assertIsNone(r["point"])
        self.assertFalse(r["upper_completion_granted"])
        self.assertTrue(all(c["top_padding_px"]<=32 for c in r["upper_contexts"]))

    def test_outer_competing_contour_not_ignored(self):
        image=cone()
        cv2.rectangle(image,(288,275),(352,288),(0,0,255),-1)
        r=observe_upper_completion(image,BOX,self.camera)
        self.assertIsNone(r["point"])
        self.assertIn("ambiguous_competing_colour_contours",r["upper_completion_reason"])

    def test_change_in_observed_lower_columns_is_rejected(self):
        image=cone()
        cv2.rectangle(image,(288,290),(352,300),(0,0,255),-1)
        r=observe_upper_completion(image,BOX,self.camera)
        self.assertIsNone(r["point"])
        self.assertEqual(r["upper_completion_reason"],"original_observed_lower_support_changed")

    def test_absent_seed_is_not_invented(self):
        r=observe_upper_completion(np.zeros((720,1280,3),np.uint8),BOX,self.camera)
        self.assertIsNone(r["point"])
        self.assertFalse(r["upper_completion_attempted"])

    def test_mixed_seed_does_not_fall_back_to_successful_colour(self):
        image=cone()
        cv2.rectangle(image,(320,325),(324,345),(0,255,255),-1)
        r=observe_upper_completion(image,BOX,self.camera)
        self.assertIsNone(r["point"])
        self.assertEqual(r["reason"],"ambiguous_upper_body_colour")

    def test_yellow_bottom_contamination_does_not_fall_back_to_red(self):
        image=cone((0,255,255))
        cv2.rectangle(image,(280,395),(360,430),(0,255,255),-1)
        cv2.rectangle(image,(316,370),(324,380),(0,0,255),-1)
        r=observe_upper_completion(image,BOX,self.camera)
        self.assertEqual(r["selected_colour"],"yellow")
        self.assertIsNone(r["point"])

    def test_bounds_are_not_clamped_and_rear_is_not_remapped(self):
        context,pixels=_upper_context(cone(),BOX,self.camera,"red",[315,325,325,345],512)
        self.assertEqual(context["reason"],"context_outside_native_image")
        self.assertIsNone(pixels)
        r=observe_upper_completion(cone(),dict(BOX,x1=930.,x2=990.),self.camera)
        self.assertIsNone(r["point"])
        self.assertEqual(r["reason"],"bbox_crosses_front_angular_domain")

    def test_original_input_pixels_and_cached_legacy_result_unchanged(self):
        image=cone()
        before=image.copy()
        old=observe_lateral_completion(image,dict(BOX,y1=295.),self.camera)
        cached=copy.deepcopy(old)
        with patch("cone_upper_support_candidate.observe_lateral_completion",return_value=cached):
            r=observe_upper_completion(image,dict(BOX,y1=295.),self.camera)
        self.assertEqual(cached,old)
        r["original_comparison"]["support"].clear()
        self.assertEqual(cached,old)
        np.testing.assert_array_equal(image,before)

    def test_wrong_resolution_and_nonfinite_bbox_rejected(self):
        with self.assertRaises(ValueError):
            observe_upper_completion(np.zeros((360,640,3),np.uint8),BOX,self.camera)
        with self.assertRaises(ValueError):
            observe_upper_completion(cone(),dict(BOX,y1=float("nan")),self.camera)

    def test_new_candidate_does_not_skip_temporal_confirmation(self):
        r=observe_upper_completion(cone(),BOX,self.camera)
        gate=ConeSupportQualityGate()
        q=[gate.update(1+n/30,[dict(support=r["support"])]) for n in range(3)]
        self.assertEqual([x["quality_accepted"] for x in q],[False,False,True])
        for flag in ("controlling_distance","physical_metric_verified","floor_contact_verified","usable_for_ffb"):
            self.assertIs(r[flag],False)

    def test_live_engine_does_not_call_new_offline_comparator(self):
        engine=ConeDistanceEngine(support_completion_shadow=True)
        engine.reset("synthetic_offline_only")
        with patch("cone_upper_support_candidate.observe_upper_completion",side_effect=AssertionError("must not be called")):
            r=engine.measure(NativeFrame("synthetic_offline_only",1,1.,1.,cone()),[BOX],1.01)
        self.assertNotIn("upper_support_shadow",r)
        self.assertFalse(r["usable_for_ffb"])


if __name__=="__main__":
    unittest.main()
