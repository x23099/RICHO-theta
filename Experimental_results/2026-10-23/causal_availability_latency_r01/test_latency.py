"""Completion availability, no freshness renewal, and conservative pending hold."""
from collections import Counter,defaultdict
import copy
import inspect
import json
from pathlib import Path
import unittest

import numpy as np

from replay_completion import HERE,ROOT,CAUSAL,UNIFORM,SCENARIOS,replay,key,flag
from finish_aware import schedule,FinishAwarePose
from pending_hold_control import hold_for_newer_input
from cone_dataset import read_csv,sha256
from angular_fisheye_geometry import camera_from_candidate


def samples(n=5):
    return [dict(frame=str(i),time_sec=str(float(i)),accepted='True',up_optical_json='[0,0,1]') for i in range(1,n+1)]


class SchedulingTests(unittest.TestCase):
    def test_fifo_wait_and_finish(self):
        jobs=schedule(samples(3),{1:1.5,2:1.5,3:1.5})
        self.assertEqual([j['finish_sec'] for j in jobs],[2.5,4.,5.5])
        self.assertEqual([j['queue_wait_sec'] for j in jobs],[0.,.5,1.])

    def test_no_application_before_completion(self):
        worker=FinishAwarePose(schedule(samples(1),{1:.2}))
        self.assertEqual(worker.query(1,1.)['latest_scene_frame'],0)
        self.assertEqual(worker.query(2,1.2)['latest_scene_frame'],1)

    def test_all_four_proofs_must_finish_before_readiness(self):
        worker=FinishAwarePose(schedule(samples(4),{i:.1 for i in range(1,5)}))
        for i in range(1,5):
            self.assertFalse(worker.query(i,float(i))['pose_available'])
        self.assertTrue(worker.query(5,4.1)['pose_available'])

    def test_freshness_uses_original_input_time_not_finish_time(self):
        worker=FinishAwarePose(schedule(samples(4),{i:1.5 for i in range(1,5)}))
        r=worker.query(10,7.)
        self.assertTrue(r['initialized']);self.assertFalse(r['pose_available'])
        self.assertEqual(r['latest_scene_age_sec'],3.)

    def test_refusal_not_known_before_finish_and_applied_after(self):
        s=samples(5);s[-1].update(accepted='False',up_optical_json='')
        worker=FinishAwarePose(schedule(s,{1:0.,2:0.,3:0.,4:0.,5:.4}))
        self.assertTrue(worker.query(4,4.)['pose_available'])
        self.assertEqual(worker.query(5,5.)['latest_scene_frame'],4)
        r=worker.query(6,5.4);self.assertEqual(r['latest_scene_frame'],5);self.assertFalse(r['pose_available'])

    def test_duplicate_release_and_invalid_costs_rejected(self):
        for cost in (-1.,float('nan'),float('inf'),True,'0.1'):
            with self.assertRaises(ValueError):schedule(samples(1),{1:cost})
        s=samples(2);s[1]['time_sec']='1.0'
        with self.assertRaises(ValueError):schedule(s,{1:0.,2:0.})

    def test_decision_clock_strict_and_no_future_frame(self):
        w=FinishAwarePose(schedule(samples(1),{1:0.}));w.query(1,1.)
        with self.assertRaises(ValueError):w.query(1,2.)
        with self.assertRaises(ValueError):w.query(2,1.)
        with self.assertRaises(ValueError):FinishAwarePose(schedule(samples(2),{1:0.,2:0.})).query(1,3.)

    def test_future_poisoned_direction_not_read_before_finish(self):
        s=samples(2);s[1]['up_optical_json']='[null,null,null]'
        w=FinishAwarePose(schedule(s,{1:0.,2:10.}))
        self.assertEqual(w.query(2,2.)['latest_scene_frame'],1)

    def test_pending_hold_has_no_future_acceptance_input(self):
        self.assertEqual(list(inspect.signature(hold_for_newer_input).parameters),['latest_released_frame','latest_completed_frame'])
        self.assertTrue(hold_for_newer_input(5,4));self.assertFalse(hold_for_newer_input(5,5))

    def test_pending_counters_are_strict(self):
        for a,b in ((-1,0),(3,4),(True,0),('5',4),(5,None)):
            with self.assertRaises(ValueError):hold_for_newer_input(a,b)


class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark=HERE/'benchmark_r01';cls.result=HERE/'results_r01';cls.control=HERE/'pending_control_r01'
        cls.b=json.loads((cls.benchmark/'summary.json').read_text());cls.s=json.loads((cls.result/'summary.json').read_text())
        cls.rows=read_csv(cls.result/'completion_frame_metrics.csv');cls.jobs=read_csv(cls.result/'scene_job_schedule.csv')
        cls.control_rows=read_csv(cls.control/'pending_control_frame_metrics.csv')
        cls.session=cls.s['replay_session']
        cls.features=[r for r in read_csv(UNIFORM/'scene_results_r01/image_diagnostics.csv') if r['session']==cls.session]
        cls.obs=[r for r in read_csv(ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv') if r['session']==cls.session]
        cls.quality={int(r['frame']):r for r in read_csv(UNIFORM/'quality_results_r01/all_frame_quality.csv') if r['session']==cls.session}
        cls.camera=camera_from_candidate(json.loads((ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json').read_text()))
        cls.T=np.array(json.loads((ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json').read_text())['transform_target_from_source'])
        times=defaultdict(list)
        for r in read_csv(cls.benchmark/'scene_stage_measurements.csv'):times[int(r['frame'])].append(float(r['scene_service_ms'])/1000.)
        cls.service={f:float(np.median(v)) for f,v in times.items()}
        cls.full,_,_=replay(cls.features,cls.obs,cls.quality,cls.service,cls.camera,cls.T)

    def test_all_manifests_and_frozen_sources_match(self):
        for folder in (self.benchmark,self.result,self.control):
            d=json.loads((folder/'summary.json').read_text())
            for p,h in d['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
            for name,h in d['output_sha256'].items():self.assertEqual(sha256(folder/name),h,name)

    def test_saved_timing_rows_are_complete_not_new_scene_timing(self):
        rs=read_csv(self.benchmark/'recorded_timing_rows.csv');summary=read_csv(self.benchmark/'recorded_timing_summary.csv')
        self.assertEqual(len(rs),14526);self.assertEqual(len(summary),9)
        self.assertEqual(sum(int(r['valid_timing_frames']) for r in summary),14526)
        self.assertTrue(all(r['new_scene_stage_included']=='False' for r in summary))
        self.assertTrue(all(r['exact_capture_or_completion_timestamp_available']=='False' for r in summary))

    def test_benchmark_has_three_runs_per_fixed_image(self):
        rs=read_csv(self.benchmark/'scene_stage_measurements.csv')
        self.assertEqual(len(rs),156);self.assertEqual(set(Counter(r['frame'] for r in rs).values()),{3})
        self.assertTrue(all(r['original_single_frame_result_matches']=='True' for r in rs))
        self.assertFalse(self.b['end_to_end_latency_measured']);self.assertEqual(self.b['environment']['opencv_threads'],1)

    def test_cost_statistics_reproduce_saved_measurements(self):
        values=[float(r['scene_service_ms']) for r in read_csv(self.benchmark/'scene_stage_measurements.csv')]
        self.assertAlmostEqual(float(np.median(values)),self.b['scene_service_median_ms'])
        self.assertAlmostEqual(float(np.percentile(values,95)),self.b['scene_service_p95_ms'])

    def test_loss_partition_does_not_overlap_or_change_population(self):
        rows=read_csv(self.result/'historical_loss_partition.csv')
        for mode in ('sample_only','bounded_between_samples_1s'):
            selected=[r for r in rows if r['mode']==mode]
            self.assertEqual(sum(int(r['frames']) for r in selected),1107)
            self.assertTrue(all(r['mutually_exclusive']=='True' for r in selected))
        bounded={r['reason']:int(r['frames']) for r in rows if r['mode']=='bounded_between_samples_1s'}
        self.assertEqual(bounded,{'retained':377,'latest_scene_image_rejected':730})

    def test_three_scenarios_retain_every_frame(self):
        self.assertEqual(len(self.rows),4641);self.assertEqual(len(self.jobs),156)
        self.assertEqual(Counter(r['scenario'] for r in self.rows),{s:1547 for s in SCENARIOS})

    def test_zero_cost_reproduces_causal_reference_exactly(self):
        prior={r['frame']:r for r in read_csv(CAUSAL/'results_r01/frame_metrics.csv') if r['session']==self.session and r['mode']=='bounded_between_samples_1s'}
        for r in self.rows:
            if r['scenario']=='zero_service_reference':
                self.assertEqual(r['pose_available'],prior[r['frame']]['pose_available'])
                self.assertEqual(r['diagnostic_z_m'],prior[r['frame']]['diagnostic_z_m'])

    def test_only_completed_events_are_used_and_source_age_not_renewed(self):
        jobs={(r['scenario'],int(r['frame'])):r for r in self.jobs}
        for r in self.rows:
            latest=int(r['latest_completed_scene_frame'])
            if latest:
                j=jobs[r['scenario'],latest]
                self.assertLessEqual(float(j['finish_sec']),float(r['time_sec']))
                self.assertAlmostEqual(float(r['source_age_sec']),float(r['time_sec'])-float(j['release_sec']))
            if r['pose_available']=='True':self.assertLessEqual(float(r['source_age_sec']),1.)

    def test_actual_prefix_and_future_direction_poison(self):
        for cutoff in (302,1135):
            obs=[r for r in self.obs if int(r['frame'])<=cutoff]
            features=copy.deepcopy(self.features)
            for r in features:
                if int(r['frame'])>cutoff:r['accepted']='True';r['up_optical_json']='[null,null,null]'
            prefix,_,_=replay(features,obs,self.quality,self.service,self.camera,self.T)
            self.assertEqual(prefix,[r for r in self.full if r['frame']<=cutoff])

    def test_additional_outputs_disclose_pending_rejection(self):
        reference={r['frame']:r for r in self.rows if r['scenario']=='zero_service_reference'}
        for scenario in SCENARIOS[1:]:
            extra=[r for r in self.rows if r['scenario']==scenario and r['diagnostic_available']=='True' and reference[r['frame']]['diagnostic_available']=='False']
            self.assertEqual(len(extra),3)
            self.assertTrue(all(r['newer_unfinished_rejection_posthoc']=='True' for r in extra))

    def test_pending_control_is_availability_only_no_new_values(self):
        originals={(r['scenario'],r['frame']):r for r in self.rows}
        self.assertEqual(len(self.control_rows),4641)
        for r in self.control_rows:
            old=originals[r['scenario'],r['frame']]
            self.assertEqual(r['raw_floor_z_m'],old['raw_floor_z_m'])
            self.assertEqual(r['before_control_diagnostic_z_m'],old['diagnostic_z_m'])
            if r['diagnostic_available']=='True':self.assertEqual(r['diagnostic_z_m'],old['diagnostic_z_m'])
            if r['newer_scene_input_pending']=='True':self.assertEqual(r['diagnostic_z_m'],'')

    def test_pending_control_removes_unfinished_rejection_outputs(self):
        summary=read_csv(self.control/'pending_control_summary.csv')
        self.assertTrue(all(r['outputs_with_newer_unfinished_rejection']=='0' for r in summary))
        self.assertEqual({r['scenario']:int(r['after_control_diagnostic_frames']) for r in summary},
            {'zero_service_reference':377,'local_three_pass_median':265,'local_three_pass_observed_max':258})

    def test_pending_counter_is_latest_released_only_not_future(self):
        for r in self.control_rows:
            released=[j for j in self.jobs if j['scenario']==r['scenario'] and float(j['release_sec'])<=float(r['time_sec'])]
            latest=max([int(j['frame']) for j in released],default=0)
            self.assertEqual(int(r['latest_released_scene_frame']),latest)
            self.assertEqual(flag(r['newer_scene_input_pending']),latest>int(r['latest_completed_scene_frame']))

    def test_physical_and_hardware_flags_unchanged(self):
        for r in self.rows+self.control_rows:
            self.assertEqual(r['distance_imputed'],'False');self.assertEqual(r['physical_metric_verified'],'False')
            self.assertEqual(r['usable_for_ffb'],'False')
        self.assertFalse(self.s['original_capture_and_delivery_latency_reproduced'])
        self.assertFalse(self.s['recorded_blue_time_used_as_scene_service'])


if __name__=='__main__':unittest.main()
