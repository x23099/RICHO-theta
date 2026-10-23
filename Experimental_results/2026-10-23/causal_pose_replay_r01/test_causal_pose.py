"""Causal initialization, bounded proofs, real-prefix replay, and output holds."""
import copy
import json
from pathlib import Path
import unittest

import numpy as np

from replay_saved import HERE,ROOT,UNIFORM,CONTRACT,key,flag,replay_session
from causal_pose import PastOnlyPose,MODES
from angular_fisheye_geometry import camera_from_candidate
from cone_dataset import read_csv,sha256


def ready():
    p=PastOnlyPose()
    for i in range(1,5):p.ingest(i,float(i),True,[0.,0.,1.])
    return p


class StateTests(unittest.TestCase):
    def test_no_output_before_four_distinct_images(self):
        p=PastOnlyPose()
        for i in range(1,5):
            p.ingest(i,float(i),True,[0.,0.,1.])
            self.assertEqual(p.query(i,float(i),'sample_only')['pose_available'],i==4)

    def test_two_training_and_two_later_validation_not_reused(self):
        r=ready().query(4,4.,'sample_only')
        self.assertEqual(r['training_frames'],[1,2]);self.assertEqual(r['validation_frames'],[3,4])

    def test_invalid_images_do_not_count_as_validation(self):
        p=PastOnlyPose()
        for i in (1,2):p.ingest(i,float(i),True,[0.,0.,1.])
        p.ingest(3,3.,False)
        p.ingest(4,4.,True,[0.,0.,1.])
        self.assertFalse(p.query(4,4.,'sample_only')['pose_available'])
        p.ingest(5,5.,True,[0.,0.,1.]);self.assertTrue(p.query(5,5.,'sample_only')['pose_available'])

    def test_one_second_exact_boundary_included_beyond_refused(self):
        p=ready()
        self.assertTrue(p.query(5,5.,'bounded_between_samples_1s')['pose_available'])
        self.assertFalse(p.query(6,float(np.nextafter(5.,6.)),'bounded_between_samples_1s')['pose_available'])

    def test_sample_only_never_uses_pose_from_previous_frame(self):
        p=ready();self.assertFalse(p.query(5,4.01,'sample_only')['pose_available'])
        self.assertTrue(p.query(5,4.01,'bounded_between_samples_1s')['pose_available'])

    def test_rejected_scene_blocks_even_within_ttl(self):
        p=ready();p.ingest(5,4.1,False)
        result=p.query(6,4.2,'bounded_between_samples_1s')
        self.assertFalse(result['pose_available']);self.assertEqual(result['pose_reason'],'latest_scene_image_rejected')

    def test_reconfirmation_can_resume_but_does_not_reissue_old_distance(self):
        p=ready();p.ingest(5,5.,False);p.ingest(6,6.,True,[0.,0.,1.])
        r=p.query(6,6.,'sample_only');self.assertTrue(r['pose_available'])
        self.assertEqual(r['latest_scene_frame'],6);self.assertNotIn('distance',r)

    def test_valid_but_disagreeing_direction_restarts(self):
        p=ready();a=np.radians(5.)
        p.ingest(5,5.,True,[0.,np.sin(a),np.cos(a)])
        r=p.query(5,5.,'sample_only');self.assertFalse(r['pose_available'])
        self.assertEqual(r['training_frames'],[5]);self.assertEqual(r['validation_frames'],[]);self.assertEqual(r['restarts'],1)

    def test_training_disagreement_restarts_before_validation(self):
        p=PastOnlyPose();p.ingest(1,1.,True,[0.,0.,1.]);a=np.radians(10.)
        p.ingest(2,2.,True,[0.,np.sin(a),np.cos(a)])
        self.assertIsNone(p.candidate);self.assertEqual(p.query(2,2.,'sample_only')['training_frames'],[2])

    def test_candidate_not_updated_by_future_reconfirmation(self):
        p=ready();first=p.candidate.copy();a=np.radians(1.)
        p.ingest(5,5.,True,[0.,np.sin(a),np.cos(a)])
        np.testing.assert_array_equal(p.candidate,first)

    def test_input_vectors_are_copied(self):
        v=np.array([0.,0.,1.]);p=PastOnlyPose();p.ingest(1,1.,True,v);v[:]=[1.,0.,0.]
        np.testing.assert_array_equal(p.train[0][1],[0.,0.,1.])

    def test_unknown_mode_and_nonunit_direction_refused(self):
        with self.assertRaises(ValueError):ready().query(4,4.,'auto')
        for v in ([0,0,2],[0,0,0],[0,np.nan,1],[1,2]):
            with self.assertRaises(ValueError):PastOnlyPose().ingest(1,1.,True,v)

    def test_duplicate_or_reversed_features_refused(self):
        for frame,time in ((4,5.),(3,5.),(5,4.),(5,np.nan)):
            with self.subTest(frame=frame,time=time),self.assertRaises(ValueError):ready().ingest(frame,time,True,[0,0,1])

    def test_rejected_direction_and_implicit_flags_refused(self):
        with self.assertRaises(ValueError):PastOnlyPose().ingest(1,1.,False,[0,0,1])
        for v in ('False',0,1,None):
            with self.assertRaises(ValueError):PastOnlyPose().ingest(1,1.,v)

    def test_query_cannot_precede_observation(self):
        for frame,time in ((3,4.),(4,3.),(4,np.nan)):
            with self.assertRaises(ValueError):ready().query(frame,time,'sample_only')

    def test_rejected_frames_keep_past_initialization_evidence_not_live_output(self):
        p=ready();p.ingest(5,5.,False)
        r=p.query(5,5.,'sample_only');self.assertTrue(r['initialized']);self.assertFalse(r['pose_available'])
        self.assertEqual(r['training_frames'],[1,2])

    def test_recordings_do_not_share_state(self):
        a=ready();b=PastOnlyPose()
        self.assertTrue(a.query(4,4.,'sample_only')['pose_available'])
        self.assertFalse(b.query(4,4.,'sample_only')['pose_available'])

    def test_synthetic_ready_is_not_physical_or_ffb_approval(self):
        r=ready().query(4,4.,'sample_only')
        self.assertFalse(r['physical_transform_verified']);self.assertFalse(r['usable_for_ffb'])


class RecordedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r01';cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.rows=read_csv(cls.output/'frame_metrics.csv');cls.events=read_csv(cls.output/'scene_events.csv')
        cls.session='floor_cone_same_pose_r01_20261015_160621_378'
        cls.samples=[r for r in read_csv(UNIFORM/'scene_results_r01/image_diagnostics.csv') if r['session']==cls.session]
        all_obs=read_csv(ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv')
        cls.obs=[r for r in all_obs if r['session']==cls.session]
        cls.q={int(r['frame']):r for r in read_csv(UNIFORM/'quality_results_r01/all_frame_quality.csv') if r['session']==cls.session}
        cls.camera=camera_from_candidate(json.loads((ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json').read_text()))
        cls.T=np.array(json.loads((ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json').read_text())['transform_target_from_source'])
        cls.full,cls.full_events=replay_session(cls.samples,cls.obs,cls.q,cls.camera,cls.T)

    def test_source_and_output_hashes(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)

    def test_all_frames_and_scene_observations_retained(self):
        self.assertEqual(len(self.rows),13752);self.assertEqual(len(self.events),492)
        self.assertEqual(len({(r['session'],r['frame'],r['mode']) for r in self.rows}),13752)
        for mode in MODES:self.assertEqual(sum(r['mode']==mode for r in self.rows),6876)

    def test_single_frame_feature_replay_matches_frozen_result(self):
        self.assertEqual(self.summary['single_frame_scene_replay_mismatches'],0)
        self.assertEqual(self.summary['initialized_recordings'],1)

    def test_first_readiness_uses_first_two_plus_next_two_images(self):
        event=next(r for r in self.events if flag(r['initialization_event']))
        self.assertEqual(event['frame'],'302')
        self.assertEqual(json.loads(event['training_frames_json']),[62,152])
        self.assertEqual(json.loads(event['validation_frames_json']),[272,302])
        self.assertAlmostEqual(float(event['time_sec']),10.057164)

    def test_nothing_before_initialization_retroactively_emitted(self):
        for r in self.rows:
            if r['session']==self.session and int(r['frame'])<302:self.assertEqual(r['diagnostic_z_m'],'')

    def test_every_used_proof_is_at_or_before_current_frame(self):
        for r in self.rows:
            frame=int(r['frame']);self.assertLessEqual(int(r['latest_scene_frame']),frame)
            for k in ('training_frames_json','validation_frames_json'):
                self.assertTrue(all(f<=frame for f in json.loads(r[k])))

    def test_prefix_replay_unchanged_by_truncating_future(self):
        for cutoff in (250,302,1135,1139):
            obs=[r for r in self.obs if int(r['frame'])<=cutoff]
            samples=[r for r in self.samples if int(r['frame'])<=cutoff]
            prefix,events=replay_session(samples,obs,self.q,self.camera,self.T)
            self.assertEqual(prefix,[r for r in self.full if r['frame']<=cutoff])
            self.assertEqual(events,[r for r in self.full_events if r['frame']<=cutoff])

    def test_future_direction_poison_does_not_affect_current_prefix(self):
        samples=copy.deepcopy(self.samples);obs=[r for r in self.obs if int(r['frame'])<=302]
        for r in samples:
            if int(r['frame'])>302:r['accepted']='True';r['up_optical_json']='[null, null, null]'
        prefix,_=replay_session(samples,obs,self.q,self.camera,self.T)
        self.assertEqual(prefix,[r for r in self.full if r['frame']<=302])

    def test_split_roles_and_distance_labels_never_enter_state_machine(self):
        samples=copy.deepcopy(self.samples);obs=copy.deepcopy(self.obs[:350])
        for r in samples:r['role']='poisoned_future_split'
        for r in obs:r['reference_z_m']='999';r['condition']='poisoned_reference'
        prefix,_=replay_session(samples,obs,self.q,self.camera,self.T)
        self.assertEqual(prefix,[r for r in self.full if r['frame']<=int(obs[-1]['frame'])])

    def test_no_distance_when_scene_not_available_even_with_colour(self):
        for r in self.rows:
            if not flag(r['pose_available']):
                self.assertEqual(r['raw_floor_z_m'],'');self.assertEqual(r['diagnostic_z_m'],'')

    def test_current_quality_rejection_cannot_be_bypassed(self):
        for r in self.rows:
            if not flag(r['quality_accepted']):self.assertEqual(r['diagnostic_z_m'],'')

    def test_pose_proof_age_and_same_frame_modes(self):
        for r in self.rows:
            if flag(r['pose_available']):
                self.assertLessEqual(float(r['latest_scene_age_sec']),1.)
                if r['mode']=='sample_only':self.assertEqual(r['frame'],r['latest_scene_frame'])

    def test_known_occlusion_held_and_current_observation_recovers(self):
        for r in self.rows:
            if r['session']==self.session and r['frame'] in ('1133','1134','1135'):self.assertEqual(r['diagnostic_z_m'],'')
        recovery=next(r for r in self.rows if r['session']==self.session and r['frame']=='1139' and r['mode']=='bounded_between_samples_1s')
        self.assertEqual(recovery['diagnostic_available'],'True')
        self.assertEqual(recovery['diagnostic_z_m'],recovery['raw_floor_z_m'])
        self.assertEqual(recovery['latest_scene_frame'],'1138')

    def test_recordings_without_initialization_remain_withheld(self):
        for r in self.rows:
            if r['session']!=self.session:self.assertEqual(r['diagnostic_z_m'],'')

    def test_static_conditional_coverage_not_30fps_claim(self):
        self.assertEqual(self.summary['diagnostic_frames_by_mode'],{'sample_only':12,'bounded_between_samples_1s':377})
        self.assertFalse(self.summary['processing_latency_simulated'])
        self.assertFalse(self.summary['physical_output'])

    def test_physical_flags_and_no_imputation(self):
        for r in self.rows:
            for k in ('physical_metric_verified','distance_imputed','usable_for_ffb'):self.assertEqual(r[k],'False')


if __name__=='__main__':unittest.main()
