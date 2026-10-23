from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from audit import HERE, ROOT, PREVIOUS, OLD, select_representatives, trace_consensus, trace_extraction
from cone_dataset import read_csv, sha256
from angular_fisheye_geometry import camera_from_candidate
from scene_geometry import infer_up
from roi_geometry import extract_with_roi


class ConsensusTraceTests(unittest.TestCase):
    def planes(self, count=8):
        a=np.deg2rad(np.arange(count)*15.)
        return np.column_stack((np.cos(a),np.zeros(count),np.sin(a)))
    def test_valid_consensus_matches_original(self):
        n=self.planes();official,trace=trace_consensus(n,[0,-1,0])
        self.assertEqual(official,infer_up(n,[0,-1,0]))
        self.assertTrue(official['accepted']);self.assertEqual(trace['refinement_2_inliers'],8)
    def test_five_planes_are_not_relaxed_into_a_pose(self):
        official,trace=trace_consensus(self.planes(5),[0,-1,0])
        self.assertFalse(official['accepted']);self.assertIsNone(official['up'])
        self.assertEqual(trace['diagnostic_residuals_deg_json'],'')
        self.assertEqual(trace['terminal_reason'],'fewer_than_six_distinct_planes')
    def test_empty_input_preserves_original_behavior(self):
        official,trace=trace_consensus(np.empty((0,3)),[0,-1,0])
        self.assertFalse(official['accepted']);self.assertEqual(trace['pairs'],0)
    def test_duplicate_planes_do_not_get_a_diverse_pair(self):
        official,trace=trace_consensus(np.tile([1.,0,0],(8,1)),[0,-1,0])
        self.assertEqual(official['reason'],'no_diverse_plane_pair_within_prior')
        self.assertEqual(trace['diverse_pairs'],0)
    def test_invalid_normals_are_rejected_by_original_contract(self):
        for n in (np.zeros((6,3)),np.full((6,3),np.nan),np.ones((4,2))):
            with self.assertRaises(ValueError):trace_consensus(n,[0,-1,0])
    def test_random_normal_inputs_trace_identically(self):
        rng=np.random.default_rng(221022)
        for size in (6,7,10,15):
            for _ in range(5):
                n=rng.normal(size=(size,3));n/=np.linalg.norm(n,axis=1)[:,None]
                original,trace=trace_consensus(n,[0,-1,0])
                self.assertEqual(original,infer_up(n,[0,-1,0]))
                self.assertEqual(trace['terminal_reason'],original['reason'])


class RepresentativeTests(unittest.TestCase):
    def samples(self):
        return [dict(session=s,role=role,frame=str(f),irrelevant_distance=999)
                for s in ('b','a') for role in ('heldout','estimate') for f in (1,3,5,7)]
    def test_fixed_median_per_session_role(self):
        self.assertTrue(all(r['frame']=='5' for r in select_representatives(self.samples())))
        self.assertEqual(len(select_representatives(self.samples())),4)
    def test_input_order_cannot_select_another_image(self):
        rows=self.samples();self.assertEqual(select_representatives(rows),select_representatives(rows[::-1]))
    def test_metric_labels_do_not_select_images(self):
        rows=self.samples();a=select_representatives(rows)
        b=select_representatives([{**r,'irrelevant_distance':-1} for r in rows])
        self.assertEqual([(r['session'],r['role'],r['frame']) for r in a],
                         [(r['session'],r['role'],r['frame']) for r in b])


class SavedAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r02'
        cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.frames=read_csv(cls.output/'all_frame_consensus.csv')
        cls.pieces=read_csv(cls.output/'representative_all_pieces.csv')
        candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
        cls.camera=camera_from_candidate(json.loads(candidate.read_text()))
    def test_source_and_output_hashes(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
    def test_all_original_frames_and_reasons_preserved(self):
        before=read_csv(PREVIOUS/'scene_results_r01/image_diagnostics.csv')
        self.assertEqual(len(self.frames),492)
        self.assertEqual([(r['session'],r['frame'],r['terminal_reason']) for r in self.frames],
                         [(r['session'],r['frame'],r['reason']) for r in before])
    def test_formal_output_is_complete_and_draft_is_not(self):
        self.assertTrue((self.output/'summary.json').exists())
        self.assertFalse((HERE/'results_r01/summary.json').exists())
    def test_final_counts_are_exhaustive(self):
        self.assertEqual(Counter(r['terminal_reason'] for r in self.frames),
            {'insufficient_consensus':319,'fewer_than_six_distinct_planes':146,'conditional_architectural_up':27})
        self.assertEqual(sum(self.summary['terminal_reasons'].values()),492)
    def test_insufficient_consensus_happens_before_svd(self):
        for r in self.frames:
            if r['terminal_reason']=='insufficient_consensus':
                self.assertLess(int(r['seed_inliers']),6)
                self.assertEqual(r['refinement_1_inliers'],'');self.assertEqual(r['refinement_2_inliers'],'')
    def test_prior_alone_did_not_block_these_images(self):
        for r in self.frames:
            if int(r['plane_count'])>=6:self.assertGreater(int(r['prior_compatible_pairs']),0)
    def test_piece_counts_and_funnel_reconcile(self):
        by_frame=defaultdict(list)
        for r in self.pieces:by_frame[r['session'],r['frame']].append(r)
        for r in read_csv(self.output/'representative_stage_counts.csv'):
            rows=by_frame[r['session'],r['frame']]
            self.assertEqual(len(rows),int(r['pieces']))
            for key,column in [('passed_shape','passes_shape'),('passed_plane','passes_plane'),('distinct_planes','accepted')]:
                self.assertEqual(sum(x[column]=='True' for x in rows),int(r[key]))
    def test_all_traced_pixels_are_native_integer_roi_and_hash_matches(self):
        for r in self.pieces:
            pixels=np.array(json.loads(r['actual_edge_pixels_json']))
            if not len(pixels):continue
            self.assertTrue(np.equal(pixels,np.rint(pixels)).all())
            self.assertTrue(((pixels[:,0]>=40)&(pixels[:,0]<=600)&(pixels[:,1]>=60)&(pixels[:,1]<=300)).all())
            self.assertEqual(hashlib.sha256(pixels.astype('<i4').tobytes()).hexdigest(),r['native_points_sha256'])
    def test_duplicate_votes_reference_a_kept_plane(self):
        index={(r['session'],r['frame'],r['line_index'],r['part']):r for r in self.pieces}
        for r in self.pieces:
            if r['reason']=='duplicate_ray_plane':
                other=index[r['session'],r['frame'],r['duplicate_of_line_index'],r['duplicate_of_part']]
                self.assertEqual(other['accepted'],'True')
    def test_no_threshold_adoption_or_hardware_output(self):
        for key in ('metric_labels_used','source_images_edited','production_settings_changed','physical_output','usable_for_ffb'):
            self.assertFalse(self.summary[key])
    def test_empty_image_trace_has_no_invented_line(self):
        rows,counts=trace_extraction(np.zeros((720,1280,3),np.uint8),self.camera)
        self.assertEqual(rows,[]);self.assertEqual(counts['distinct_planes'],0)
    def test_only_fixed_roi_probe_values_allowed(self):
        image=np.zeros((720,1280,3),np.uint8)
        self.assertEqual(extract_with_roi(image,self.camera,y_max=300),[])
        self.assertEqual(extract_with_roi(image,self.camera,y_max=430),[])
        with self.assertRaises(ValueError):extract_with_roi(image,self.camera,y_max=440)
    def test_images_must_stay_native(self):
        with self.assertRaises(ValueError):trace_extraction(np.zeros((360,640,3),np.uint8),self.camera)


class SavedRoiProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'roi_probe_results_r01'
        cls.summary=json.loads((cls.output/'summary.json').read_text())
    def test_source_and_output_hashes(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
    def test_all_492_frames_paired_not_only_successes(self):
        original=read_csv(PREVIOUS/'scene_results_r01/image_diagnostics.csv')
        paired=read_csv(self.output/'paired_comparison.csv')
        self.assertEqual(len(paired),492)
        self.assertEqual({(r['session'],r['frame']) for r in original},{(r['session'],r['frame']) for r in paired})
        self.assertEqual(self.summary['baseline_equivalence_images'],18)
    def test_no_distance_or_transform_export(self):
        sessions=read_csv(self.output/'session_hypotheses.csv')
        self.assertEqual(len(sessions),9)
        self.assertTrue(all('conditional_transform' not in r for r in sessions))
        self.assertFalse(self.summary['metric_labels_used']);self.assertFalse(self.summary['physical_output'])
        self.assertFalse(self.summary['usable_for_ffb'])
    def test_new_pixels_are_only_predeclared_roi(self):
        for r in read_csv(self.output/'line_candidates.csv'):
            for field in ('first_native_json','last_native_json'):
                x,y=json.loads(r[field]);self.assertTrue(40<=x<=600 and 60<=y<=430)
    def test_completed_session_checkpoints_match_frozen_spec(self):
        count=0
        for path in (self.output/'sessions').glob('*/complete.json'):
            done=json.loads(path.read_text());count+=1
            self.assertEqual(done['run_spec_sha256'],sha256(self.output/'run_spec.json'))
            self.assertEqual(done['data_sha256'],sha256(path.parent/'data.json'))
        self.assertEqual(count,9)


class ReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'report_results_r01'
        cls.summary=json.loads((cls.output/'summary.json').read_text())
    def test_report_source_and_output_hashes(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
    def test_context_images_are_byte_identical_native_frames(self):
        self.assertEqual(len(self.summary['native_assets']),2)
        for r in self.summary['native_assets']:
            self.assertEqual(sha256(Path(r['source'])),sha256(self.output/r['file']))
            self.assertEqual(cv2.imread(str(self.output/r['file'])).shape,(720,1280,3))
            self.assertFalse(r['image_edited'])
    def test_roi_regression_is_kept_not_selected_away(self):
        rows=read_csv(self.output/'session_comparison.csv')
        self.assertEqual(len(rows),9)
        self.assertEqual(sum(r['baseline_temporal_pass']=='True' for r in rows),1)
        self.assertEqual(sum(r['probe_temporal_pass']=='True' for r in rows),5)
        series=next(r for r in rows if r['session'].startswith('floor_cone_same_pose'))
        self.assertEqual(series['baseline_temporal_pass'],'True')
        self.assertEqual(series['probe_temporal_pass'],'False')
    def test_nearby_plane_direction_is_not_physical_correspondence(self):
        self.assertFalse(self.summary['plane_direction_matches_are_physical_correspondences'])
        rows=read_csv(self.output/'plane_direction_retention.csv')
        self.assertEqual(len(rows),len(read_csv(HERE/'results_r02/all_frame_plane_residuals.csv')))
        self.assertTrue(all(r['same_physical_line_verified']=='False' and r['usable_for_ffb']=='False' for r in rows))
    def test_retention_cannot_count_more_missing_than_observed(self):
        for r in read_csv(self.output/'session_comparison.csv'):
            self.assertLessEqual(int(r['baseline_directions_missing_pre_dedup']),int(r['baseline_kept_plane_observations']))
            self.assertLessEqual(int(r['accepted_inlier_directions_missing_pre_dedup']),int(r['baseline_accepted_inlier_observations']))


if __name__=='__main__':unittest.main()
