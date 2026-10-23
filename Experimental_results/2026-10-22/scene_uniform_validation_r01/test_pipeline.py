from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256
from prepare import time_grid
from analyze_scenes import summarize_directions
from pool_planes import stable_planes
from quality_replay import replay


class SamplingTests(unittest.TestCase):
    def rows(self,times):return [dict(frame=i+1,time_sec=t) for i,t in enumerate(times)]

    def test_irregular_times_choose_first_at_or_after_target(self):
        selected,duplicates=time_grid(self.rows([.1,.2,1.2,2.4,2.41,3.8]))
        self.assertEqual([r['frame'] for r in selected],[1,3,4,6]);self.assertEqual(duplicates,0)
        self.assertTrue(all(r['time_sec']>=r['target_time_sec'] for r in selected))

    def test_large_gap_not_counted_as_multiple_images(self):
        selected,duplicates=time_grid(self.rows([.1,4.8]))
        self.assertEqual([r['frame'] for r in selected],[1,2]);self.assertEqual(duplicates,3)

    def test_estimate_and_holdout_use_time_not_capture_label(self):
        selected,_=time_grid(self.rows([.1,.2,1.2,2.4,2.41,3.8]))
        self.assertEqual([r['role'] for r in selected],['estimate','estimate','heldout','heldout'])

    def test_invalid_times_and_frame_sequences_rejected(self):
        for rows in ([],self.rows([0,0]),self.rows([1,0]),self.rows([0,np.nan]),[dict(frame=2,time_sec=0)]):
            with self.assertRaises(ValueError):time_grid(rows)
        with self.assertRaises(ValueError):time_grid(self.rows([0,1]),0)

    def test_sampling_does_not_read_metric_labels(self):
        a=self.rows([0,.5,1.1,1.9,2.2]);b=[dict(r,reference_z_m=999,quality_accepted=False) for r in a]
        self.assertEqual(time_grid(a),time_grid(b))


class DirectionValidationTests(unittest.TestCase):
    def setUp(self):
        self.T=np.eye(4);self.T[:3,:3]=[[0,0,1],[-1,0,0],[0,-1,0]];self.T[2,3]=.59
    def row(self,role,angle=0,accepted=True):
        return dict(role=role,accepted=accepted,up_optical=[0,-np.cos(angle),np.sin(angle)])
    def test_training_and_heldout_both_needed(self):
        rows=[self.row('estimate')]*2+[self.row('heldout')]*2
        r=summarize_directions(rows,self.T)
        self.assertTrue(r['metric_eligible']);self.assertEqual(r['temporal_validation'],'PASS')
    def test_one_training_image_refused(self):
        r=summarize_directions([self.row('estimate')]+[self.row('heldout')]*5,self.T)
        self.assertFalse(r['metric_eligible']);self.assertIsNone(r['up_optical'])
    def test_one_heldout_image_is_not_a_temporal_pass(self):
        r=summarize_directions([self.row('estimate')]*2+[self.row('heldout')],self.T)
        self.assertTrue(r['training_accepted']);self.assertFalse(r['metric_eligible']);self.assertEqual(r['temporal_validation'],'INSUFFICIENT')
    def test_divergent_heldout_directions_refused(self):
        r=summarize_directions([self.row('estimate')]*2+[self.row('heldout',.05)]*2,self.T)
        self.assertFalse(r['metric_eligible']);self.assertEqual(r['temporal_validation'],'FAIL')
    def test_heldout_never_updates_training_up(self):
        a=[self.row('estimate',.01),self.row('estimate',.015)]
        first=summarize_directions(a+[self.row('heldout')]*2,self.T)
        second=summarize_directions(a+[self.row('heldout',.02)]*2,self.T)
        np.testing.assert_array_equal(first['up_optical'],second['up_optical'])
        np.testing.assert_array_equal(first['conditional_transform'],second['conditional_transform'])
    def test_unstable_training_does_not_get_averaged_into_pass(self):
        r=summarize_directions([self.row('estimate',-.1),self.row('estimate',.1)]+[self.row('heldout')]*2,self.T)
        self.assertFalse(r['training_accepted']);self.assertFalse(r['metric_eligible'])


class PoolingTests(unittest.TestCase):
    def rows(self,frames):
        return [dict(frame=f,line_index=i,part=0,plane_rms_deg=.05,normal_json='[1,0,0]') for i,f in enumerate(frames)]
    def test_repeated_frames_are_one_plane_not_independent_votes(self):
        r=stable_planes(self.rows(range(1,10)))
        self.assertEqual(len(r),1);self.assertEqual(r[0]['different_frames'],9);self.assertTrue(r[0]['accepted'])
    def test_duplicate_edges_in_one_frame_are_one_observation(self):
        r=stable_planes(self.rows([1,1,1,1]))
        self.assertEqual(r[0]['different_frames'],1);self.assertFalse(r[0]['accepted'])
    def test_three_distinct_frames_required(self):
        self.assertFalse(stable_planes(self.rows([1,2]))[0]['accepted'])
        self.assertTrue(stable_planes(self.rows([1,2,3]))[0]['accepted'])
    def test_frame_order_does_not_change_result(self):
        rows=self.rows([1,2,3,4]);self.assertEqual(stable_planes(rows),stable_planes(rows[::-1]))


class CausalReplayTests(unittest.TestCase):
    def records(self):
        support=[[x,400] for x in range(100,121)]
        return [dict(dataset='test',session='same',frame=i+1,time_sec=i/30,condition='test',
            candidates=[dict(support=support)] if i<3 or i>=5 else []) for i in range(9)]
    def test_missing_observation_never_returns_anchor_as_current(self):
        rows=replay(self.records());self.assertTrue(rows[2]['quality_accepted'])
        for r in rows[3:5]:
            self.assertFalse(r['quality_accepted']);self.assertEqual(r['observed_support_json'],'')
            self.assertFalse(r['current_frame_observation_only']);self.assertFalse(r['rows_imputed'])
    def test_future_changes_do_not_change_prefix(self):
        records=self.records();self.assertEqual(replay(records)[:5],replay(records[:5]))
    def test_metric_label_does_not_enter_gate(self):
        records=self.records();altered=[dict(r,reference_z_m=999,height_m=999) for r in records]
        self.assertEqual(replay(records),replay(altered))
    def test_nonconsecutive_frames_refused(self):
        records=self.records();records[2]['frame']=4
        with self.assertRaises(ValueError):replay(records)


class SavedPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifests=[HERE/folder/'summary.json' for folder in ('intake_r01','scene_results_r01','pooled_results_r01','quality_results_r01','metric_results_r01')]
        cls.digest=staticmethod(lru_cache(maxsize=None)(sha256))
    def test_frozen_sources_and_all_outputs(self):
        for manifest in self.manifests:
            data=json.loads(manifest.read_text())
            for p,h in data['source_sha256'].items():self.assertEqual(self.digest(Path(p)),h,p)
            for name,h in data['output_sha256'].items():self.assertEqual(self.digest(manifest.parent/name),h,name)
            self.assertEqual(data['work_date'],'2026-10-22');self.assertFalse(data['usable_for_ffb']);self.assertFalse(data['physical_output'])
    def test_every_selected_native_image_has_original_dimensions_and_hash(self):
        rows=read_csv(HERE/'intake_r01/native_sample_manifest.csv')
        self.assertEqual(len(rows),492)
        for r in rows:
            path=Path(r['source_native_png']);self.assertEqual(self.digest(path),r['png_sha256'])
            image=cv2.imread(str(path));self.assertEqual(image.shape,(720,1280,3))
            self.assertEqual(r['image_edited'],'False')
    def test_sampler_plan_is_exactly_followed(self):
        plan=json.loads((HERE/'intake_r01/sampling_plan.json').read_text())
        rows=read_csv(HERE/'intake_r01/native_sample_manifest.csv')
        expected={(s['session'],int(r['frame']),r['role']) for s in plan['sessions'] for r in s['selected']}
        self.assertEqual(expected,{(r['session'],int(r['frame']),r['role']) for r in rows})
    def test_session_checkpoints_match_run_spec(self):
        output=HERE/'scene_results_r01';h=self.digest(output/'run_spec.json')
        for p in (output/'sessions').glob('*/complete.json'):
            data=json.loads(p.read_text());self.assertEqual(data['run_spec_sha256'],h)
            for name,value in data['output_sha256'].items():self.assertEqual(self.digest(p.parent/name),value)
    def test_historical_quality_and_real_prefix_consistency(self):
        d=json.loads((HERE/'quality_results_r01/summary.json').read_text())
        self.assertEqual(d['frames'],6876);self.assertEqual(d['historical_decision_or_reason_mismatches'],0)
        self.assertTrue(d['prefix_invariance_verified']);self.assertTrue(d['current_frame_support_membership_verified'])
    def test_metrics_keep_every_frame_per_model(self):
        rows=read_csv(HERE/'metric_results_r01/all_frame_metrics.csv')
        self.assertEqual(len(rows),13752)
        counts=Counter((r['session'],r['frame']) for r in rows)
        self.assertEqual(len(counts),6876);self.assertEqual(set(counts.values()),{2})
    def test_no_pose_no_quality_no_emitted_distance(self):
        for r in read_csv(HERE/'metric_results_r01/all_frame_metrics.csv'):
            allowed=all(r[k]=='True' for k in ('pose_temporally_checked','quality_accepted','geometry_estimated'))
            self.assertEqual(r['measurement_emitted']=='True',allowed)
            if not allowed:self.assertEqual(r['emitted_floor_z_m'],'')
            else:self.assertEqual(r['emitted_floor_z_m'],r['raw_floor_z_m'])
            self.assertEqual(r['distance_imputed'],'False');self.assertEqual(r['usable_for_ffb'],'False')
    def test_known_occlusion_is_withheld_and_original_bad_distances_retained(self):
        rows=read_csv(HERE/'metric_results_r01/all_frame_metrics.csv')
        selected=[r for r in rows if r['dataset']=='sequence' and int(r['frame']) in (1133,1134,1135)]
        self.assertEqual(len(selected),6)
        for r in selected:
            self.assertTrue(float(r['raw_floor_z_m'])>3)
            self.assertEqual(r['measurement_emitted'],'False');self.assertEqual(r['emitted_floor_z_m'],'')
    def test_paper_no_fallback_from_another_recording(self):
        models={name:{r['session'] for r in read_csv(HERE/folder/'session_hypotheses.csv') if r['metric_eligible']=='True'}
            for name,folder in [('uniform_images','scene_results_r01'),('pooled_planes','pooled_results_r01')]}
        for r in read_csv(HERE/'metric_results_r01/paper_reference_results.csv'):
            if r['session'] not in models[r['model']]:self.assertEqual(r['estimated'],'False')
    def test_empirical_pose_range_not_called_confidence_interval(self):
        rows=read_csv(HERE/'metric_results_r01/empirical_pose_sensitivity.csv')
        self.assertEqual(len(rows),16)
        self.assertTrue(all(r['uncertainty_confidence_interval']=='False' for r in rows))


if __name__=='__main__':unittest.main()
