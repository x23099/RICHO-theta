from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import unittest

import numpy as np

from contour_join import HERE,ROOT,OBJECT,BANDS,UNIFORM,MODES,near_seam,choose_links,build_join_votes,dedup_votes,recover_owners
from cone_dataset import read_csv,sha256


def row(band,index,angle=0):
    a=np.deg2rad(angle)
    return dict(band=band,line_index=index,part=0,normal=[float(np.cos(a)),0.,float(np.sin(a))])


def link(upper=(1,0),lower=(2,0),owner=(1,0),rms=.05):
    return dict(upper_key=upper,lower_key=lower,owner_key=owner,combined_accepted=True,
        combined_rms_deg=rms,combined_max_deg=.2,combined_points=80,combined_normal=[1.,0.,0.])


class JoinUnitTests(unittest.TestCase):
    def test_actual_seam_gate_and_nonfinite_inputs(self):
        self.assertTrue(near_seam([[235,290],[235,300]],[[235,301],[236,362]]))
        self.assertFalse(near_seam([[235,290],[235,300]],[[250,301],[251,362]]))
        with self.assertRaises(ValueError):near_seam([[np.nan,300]],[[235,301]])
    def test_one_owner_one_lower_is_selected(self):
        r=link();chosen,status=choose_links([r])
        self.assertIs(chosen[(2,0)],r);self.assertEqual(status[(2,0)],'one_observed_group_join')
    def test_two_upper_groups_do_not_get_arbitrarily_selected(self):
        chosen,status=choose_links([link(),link(upper=(3,0),owner=(3,0))])
        self.assertEqual(chosen,{});self.assertEqual(status[(2,0)],'multiple_upper_owner_groups')
    def test_competing_lower_candidates_for_owner_are_both_withheld(self):
        chosen,status=choose_links([link(),link(lower=(4,0))])
        self.assertEqual(chosen,{});self.assertEqual(set(status.values()),{'multiple_lower_candidates_for_owner'})
    def test_same_group_tie_break_does_not_use_metric_labels(self):
        a=link(upper=(5,0),rms=.1);b=link(upper=(6,0),rms=.05)
        a['reference_z_m']=1;b['reference_z_m']=999
        chosen,_=choose_links([a,b]);self.assertIs(chosen[(2,0)],b)
    def test_rejected_fit_is_not_a_link(self):
        chosen,status=choose_links([dict(link(),combined_accepted=False)])
        self.assertEqual(chosen,{});self.assertEqual(status,{})
    def test_joined_lower_never_adds_a_second_vote(self):
        upper=[row('upper',1)];lower=[row('lower',2,3)];r=link()
        votes,removed=build_join_votes(upper,lower,upper,{(2,0):r},{(2,0):'one_observed_group_join'},refit=True)
        self.assertEqual(len(votes),1);self.assertEqual(votes[0]['joined_lower_key'],(2,0))
    def test_count_only_keeps_original_upper_normal(self):
        upper=[row('upper',1,10)];lower=[row('lower',2,20)]
        votes,_=build_join_votes(upper,lower,upper,{(2,0):link()},{(2,0):'one_observed_group_join'},refit=False)
        self.assertEqual(votes[0]['normal'],upper[0]['normal']);self.assertEqual(len(votes),1)
    def test_ambiguous_lower_never_gets_an_extra_vote(self):
        upper=[row('upper',1)];lower=[row('lower',2,20)]
        votes,_=build_join_votes(upper,lower,upper,{}, {(2,0):'multiple_upper_owner_groups'},refit=True)
        self.assertEqual(len(votes),1)
    def test_refit_direction_duplicates_are_removed(self):
        votes,removed=dedup_votes([row('upper',1),row('upper',2,1)])
        self.assertEqual(len(votes),1);self.assertEqual(len(removed),1)
    def test_frozen_owner_order_is_recovered(self):
        a=dict(row('upper',1),accepted=True,reason='accepted_plane',native_y_span=100)
        b=dict(row('upper',2,1),accepted=False,reason='duplicate_ray_plane',native_y_span=90)
        self.assertEqual(recover_owners([b,a]),{(1,0):(1,0),(2,0):(1,0)})


class SavedJoinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r01';cls.summary=json.loads((cls.output/'summary.json').read_text())
    def test_sources_and_outputs_are_frozen(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
    def test_all_images_and_modes_are_retained(self):
        rows=read_csv(self.output/'image_diagnostics.csv');self.assertEqual(len(rows),1476)
        self.assertEqual(Counter(r['mode'] for r in rows),{m:492 for m in MODES})
    def test_previous_object_reference_control_reproduces(self):
        old={(r['session'],r['frame']):r for r in read_csv(OBJECT/'results_r01/image_diagnostics.csv') if r['mode']=='object_and_reference'}
        for r in read_csv(self.output/'image_diagnostics.csv'):
            if r['mode']=='object_reference':
                expected=old[r['session'],r['frame']]
                for k in ('accepted','reason','inliers','up_optical_json'):self.assertEqual(r[k],expected[k])
    def test_unsupported_streams_are_still_withheld(self):
        rows=[r for r in read_csv(self.output/'image_diagnostics.csv') if r['bbox_stream_available']=='False']
        self.assertEqual(len(rows),948)
        self.assertTrue(all(r['accepted']=='False' and r['reason']=='saved_bbox_stream_unavailable' for r in rows))
    def test_merged_support_is_native_observation_without_inserted_seam_pixels(self):
        for r in read_csv(self.output/'merged_observed_support.csv'):
            p=np.array(json.loads(r['combined_pixels_json']))
            self.assertTrue(np.equal(p,np.rint(p)).all())
            self.assertEqual(hashlib.sha256(p.astype('<i4').tobytes()).hexdigest(),r['combined_points_sha256'])
            self.assertTrue((np.diff(p[:,1])>=0).all())
            self.assertTrue((p[:,1]<=300).any() and (p[:,1]>=301).any())
    def test_no_lower_or_owner_is_merged_twice(self):
        rows=read_csv(self.output/'merged_observed_support.csv')
        for field in ('owner_key_json','lower_key_json'):
            keys=[(r['session'],r['frame'],r[field]) for r in rows]
            self.assertEqual(len(keys),len(set(keys)))
    def test_consumed_and_ambiguous_lower_ids_do_not_appear_as_votes(self):
        blocked={(r['session'],r['frame'],r['lower_key_json']) for r in read_csv(self.output/'lower_decisions.csv')
                 if r['decision']!='no_accepted_continuation'}
        for r in read_csv(self.output/'vote_ledger.csv'):
            if r['mode']!='object_reference' and r['band']=='lower':
                self.assertNotIn((r['session'],r['frame'],r['key_json']),blocked)
    def test_kept_vote_normals_remain_distinct(self):
        groups=defaultdict(list)
        for r in read_csv(self.output/'vote_ledger.csv'):groups[r['session'],r['frame'],r['mode']].append(json.loads(r['normal_json']))
        for key,rows in groups.items():
            if key[2]=='object_reference':continue
            n=np.array(rows)
            for i in range(1,len(n)):
                self.assertTrue((np.degrees(np.arccos(np.clip(abs(n[:i]@n[i]),-1,1)))>=2-1e-10).all())
    def test_no_tf_or_metric_eligibility_export(self):
        for r in read_csv(self.output/'session_hypotheses.csv'):
            self.assertNotIn('conditional_transform',r);self.assertNotIn('metric_eligible',r)
            self.assertEqual(r['usable_for_ffb'],'False')
    def test_no_model_inference_or_physical_changes(self):
        for key in ('metric_labels_used','new_model_inference','source_images_edited','physical_output','production_settings_changed','usable_for_ffb'):
            self.assertFalse(self.summary[key])


class ReportTests(unittest.TestCase):
    def test_sources_and_outputs(self):
        folder=HERE/'report_r01';d=json.loads((folder/'summary.json').read_text())
        for p,h in d['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in d['output_sha256'].items():self.assertEqual(sha256(folder/name),h,name)
    def test_all_regressions_are_preserved_not_silently_replaced(self):
        rows=read_csv(HERE/'report_r01/lost_original_acceptances.csv')
        self.assertEqual(len(rows),4);self.assertTrue(all(r['mode']=='join_refit' for r in rows))
        modes={r['mode']:r for r in read_csv(HERE/'report_r01/mode_comparison.csv')}
        self.assertEqual(modes['join_count_only']['old_27_retained'],'27')
        self.assertEqual(modes['join_refit']['old_27_retained'],'23')
    def test_each_temporal_mode_has_only_one_qualified_capture(self):
        rows=read_csv(HERE/'report_r01/mode_comparison.csv')
        self.assertEqual(len(rows),3);self.assertTrue(all(r['temporal_sessions']=='1' for r in rows))


if __name__=='__main__':unittest.main()
