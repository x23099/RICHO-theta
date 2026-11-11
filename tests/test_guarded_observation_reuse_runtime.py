"""Per-call reuse integration; no model, network, ROS, camera or control."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import test_cone_guarded_stream_comparison as fixtures
from cone_upper_support_candidate import observe_upper_completion


class RuntimeReuseTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.StreamComparisonTests('test_explicit_opt_in_required');self.fx.setUp()

    def test_stream_extracts_once_and_preserves_engine_sequence_state(self):
        self.fx.activate()
        frame=self.fx.frame(2,10.03);self.fx.admit(frame)
        original=self.fx.main_result(frame)
        with patch('cone_bbox_boundary_shadow.observe_upper_completion',wraps=observe_upper_completion) as observed,\
             patch.object(self.fx.stream._engine,'observer',side_effect=AssertionError('duplicate extraction')):
            result=self.fx.stream.compare(frame,[fixtures.BOX],original)
        self.assertTrue(result['comparison_distance_available'])
        self.assertEqual(observed.call_count,1)
        self.assertEqual(self.fx.stream._engine.last_frame,2)
        duplicate=self.fx.stream.compare(frame,[fixtures.BOX],original)
        self.assertEqual(duplicate['reason'],'comparison_failed')

    def test_does_not_trust_modified_main_observation(self):
        self.fx.activate();frame=self.fx.frame(2,10.03);self.fx.admit(frame)
        original=self.fx.main_result(frame)
        original['support_observation']['reason']='forged'
        result=self.fx.stream.compare(frame,[fixtures.BOX],original)
        self.assertEqual(result['reason'],'comparison_failed')
        self.assertFalse(result['comparison_distance_available'])

    def test_selected_box_mismatch_cannot_reuse_another_observation(self):
        self.fx.activate();frame=self.fx.frame(2,10.03);self.fx.admit(frame)
        original=copy.deepcopy(self.fx.main_result(frame))
        original['selected_detector_boxes'][0]['x1']-=1.
        result=self.fx.stream.compare(frame,[fixtures.BOX],original)
        self.assertEqual(result['reason'],'comparison_failed')

    def test_per_call_override_does_not_replace_default_observer(self):
        engine=self.fx.stream._engine
        default=engine.observer
        frame=self.fx.frame()
        result=engine.measure(frame,[fixtures.BOX],10.005,observer=observe_upper_completion)
        self.assertIs(engine.observer,default)
        with patch.object(engine,'observer',wraps=default) as observed:
            engine.measure(self.fx.frame(2,10.03),[fixtures.BOX],10.035)
        self.assertEqual(observed.call_count,1)
        self.assertFalse(result['distance_available'])

    def test_invalid_observer_rejected_without_consuming_sequence(self):
        engine=self.fx.stream._engine
        with self.assertRaises(ValueError):engine.measure(self.fx.frame(),[fixtures.BOX],10.005,observer={})
        self.assertEqual(engine.last_frame,0)


if __name__=='__main__':unittest.main()
