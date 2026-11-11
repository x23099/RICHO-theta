"""Per-call compact graph equivalence/ownership, synthetic pixels only."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cone_bbox_boundary_shadow import compare_boundary_observations,boundary_contains
from cone_distance_core import load_config
from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge
from cone_self_body_shadow import compare_self_body
import test_cone_guarded_stream_comparison as stream_fixtures
import test_cone_guarded_lower_edge_shadow as fixtures


class CompactComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.camera=load_config()[1]

    def compare(self,compact,*,image=None,box=None,reference=None,session=fixtures.SESSION,verified=True,margin=2.):
        return compare_guarded_lower_edge(fixtures.pixels() if image is None else image,
            dict(fixtures.BOX) if box is None else box,self.camera,
            fixtures.reference() if reference is None else reference,session=session,
            reference_matches=verified,margin_px=margin,compact=compact)

    def test_all_guarded_values_equal_across_late_bbox_boundaries(self):
        for y2 in (399.,399.49,399.5,399.6,400.,405.,420.):
            with self.subTest(y2=y2):
                box=dict(fixtures.BOX,y2=y2)
                self.assertEqual(self.compare(False,box=box),self.compare(True,box=box))

    def test_red_yellow_blank_and_open_component_equal(self):
        opened=fixtures.pixels().copy();cv2.rectangle(opened,(280,395),(360,430),(0,0,255),-1)
        for image in (fixtures.pixels(),fixtures.pixels((0,255,255)),np.zeros((720,1280,3),np.uint8),opened):
            image.flags.writeable=False
            self.assertEqual(self.compare(False,image=image),self.compare(True,image=image))

    def test_veto_margin_and_reference_scope_equal(self):
        partial=fixtures.reference();partial['boundary_xy']=[[319,458],[321,458]]
        options=[dict(reference=fixtures.reference(400)),dict(reference=partial),
            dict(session='c'*32),dict(verified=False),dict(margin=0.),dict(margin=16.)]
        for kwargs in options:
            with self.subTest(kwargs=kwargs):self.assertEqual(self.compare(False,**kwargs),self.compare(True,**kwargs))

    def test_compact_only_constructs_consumed_policy(self):
        image=fixtures.pixels();box=dict(fixtures.BOX)
        with patch('cone_bbox_boundary_shadow.boundary_contains',wraps=boundary_contains) as contains:
            compact=compare_boundary_observations(image,box,self.camera,compact=True)
        self.assertEqual(list(compact['comparisons']),['half_pixel_overlap'])
        self.assertEqual(contains.call_count,1)
        full=compare_boundary_observations(image,box,self.camera)
        self.assertEqual(compact['baseline'],full['baseline'])
        self.assertEqual(compact['comparisons']['half_pixel_overlap'],full['comparisons']['half_pixel_overlap'])
        self.assertIn('outward_integer_inclusive',full['comparisons'])

    def test_default_diagnostic_views_remain_independently_owned(self):
        result=self.compare(False)
        old=copy.deepcopy(result['baseline_body_review'])
        result['baseline']['contexts'].clear()
        self.assertEqual(result['baseline_body_review'],old)
        old=copy.deepcopy(result['proposed_body_review'])
        result['proposed_observation']['support'].clear()
        self.assertEqual(result['proposed_body_review'],old)

    def test_compact_uses_fresh_graph_each_call(self):
        first=self.compare(True);second=self.compare(True)
        first['baseline']['contexts'].clear()
        self.assertNotEqual(first['baseline'],second['baseline'])
        first['proposed_observation']['support'].clear()
        self.assertTrue(second['proposed_observation']['support'])

    def test_compact_does_not_mutate_pixels_box_or_reference(self):
        image=fixtures.pixels();box=dict(fixtures.BOX);ref=fixtures.reference()
        before=image.tobytes(),copy.deepcopy(box),copy.deepcopy(ref)
        self.compare(True,image=image,box=box,reference=ref)
        self.assertEqual((image.tobytes(),box,ref),before)
        self.assertFalse(image.flags.writeable)

    def test_compact_body_rejection_changes_only_its_own_top_level(self):
        observation=self.compare(False,box=dict(fixtures.BOX,y2=405.))['baseline']
        original=copy.deepcopy(observation)
        review=compare_self_body(observation,fixtures.reference(400),session=fixtures.SESSION,
            reference_matches=True,compact=True)
        self.assertTrue(review['revoked']);self.assertIsNone(review['observation']['point'])
        self.assertEqual(observation,original)
        self.assertIsNot(review['observation'],observation)

    def test_default_body_review_nested_input_isolation_preserved(self):
        observation=self.compare(False,box=dict(fixtures.BOX,y2=405.))['baseline']
        original=copy.deepcopy(observation)
        result=compare_self_body(observation,fixtures.reference(),session=fixtures.SESSION,reference_matches=True)
        result['observation']['support'].clear()
        self.assertEqual(observation,original)

    def test_compact_mode_rejects_non_bool_at_all_layers(self):
        obs=self.compare(False)['baseline']
        for value in (1,None,'yes'):
            for operation in (
                lambda:self.compare(value),
                lambda:compare_boundary_observations(fixtures.pixels(),fixtures.BOX,self.camera,compact=value),
                lambda:compare_self_body(obs,fixtures.reference(),session=fixtures.SESSION,compact=value)):
                with self.subTest(value=value),self.assertRaises(ValueError):operation()

    def test_bad_reference_and_margin_checks_still_apply(self):
        for options in (dict(reference=dict(fixtures.reference(),live_authorized=True)),dict(margin=True),dict(margin=float('nan'))):
            with self.subTest(options=options),self.assertRaises(ValueError):self.compare(True,**options)

    def test_no_physical_or_control_authority(self):
        result=self.compare(True)
        for key in ('live_authorized','floor_contact_verified','physical_metric_verified','controlling_distance','usable_for_ffb'):
            self.assertIs(result[key],False)
            if key!='live_authorized':self.assertIs(result['proposed_observation'][key],False)

    def test_runtime_only_uses_compact_after_reference_activation(self):
        fx=stream_fixtures.StreamComparisonTests('test_explicit_opt_in_required');fx.setUp()
        with patch('cone_guarded_stream_comparison.compare_guarded_lower_edge',wraps=compare_guarded_lower_edge) as compared:
            fx.next_result()
            self.assertEqual(compared.call_count,0)
            fx.stream=fx.new_stream();fx.activate();row=fx.next_result()
            self.assertTrue(compared.call_args.kwargs['compact'])
        self.assertTrue(row['comparison_distance_available'])
        row['comparison_support_pixel'][0]=-1
        self.assertEqual(fx.stream.poll(fixtures.SESSION)['comparison_support_pixel'],[320,400])

    def test_engine_result_owns_copy_after_compact_graph_is_discarded(self):
        fx=stream_fixtures.StreamComparisonTests('test_explicit_opt_in_required');fx.setUp()
        graph=self.compare(True)
        frame=fx.frame()
        row=fx.stream._engine.measure(frame,[fixtures.BOX],10.005,
            observer=lambda *args:graph['proposed_observation'])
        before=copy.deepcopy(row['support_observation'])
        graph['proposed_observation']['support'].clear()
        graph['baseline']['contexts'].clear()
        self.assertEqual(row['support_observation'],before)


if __name__=='__main__':unittest.main()
