from collections import Counter,defaultdict
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from run import HERE,ROOT,PREVIOUS,OLD,MODES
from band_geometry import extract_band,fuse_planes,independent_agreement
from cone_dataset import read_csv,sha256
from angular_fisheye_geometry import camera_from_candidate


def plane(band,index,angle):
    a=np.deg2rad(angle)
    return dict(band=band,line_index=index,part=0,normal=[np.cos(a),0,np.sin(a)])


class FusionTests(unittest.TestCase):
    def test_upper_order_and_values_are_never_replaced(self):
        upper=[plane('upper',1,30),plane('upper',0,0)]
        lower=[plane('lower',2,31),plane('lower',3,60)]
        fused,rejected=fuse_planes(upper,lower)
        self.assertEqual(fused[:len(upper)],upper)
        self.assertEqual(fused[-1],lower[-1]);self.assertEqual(len(rejected),1)
    def test_same_line_in_both_bands_is_not_a_second_vote(self):
        fused,rejected=fuse_planes([plane('upper',0,0)],[plane('lower',1,0)])
        self.assertEqual(len(fused),1);self.assertEqual(rejected[0]['duplicate_of_band'],'upper')
    def test_opposite_normal_sign_is_the_same_direction(self):
        lower=plane('lower',1,0);lower['normal']=[-1,0,0]
        fused,rejected=fuse_planes([plane('upper',0,0)],[lower])
        self.assertEqual(len(fused),1);self.assertEqual(len(rejected),1)
    def test_lower_duplicates_are_also_removed(self):
        fused,rejected=fuse_planes([],[plane('lower',0,0),plane('lower',1,.5)])
        self.assertEqual(len(fused),1);self.assertEqual(rejected[0]['duplicate_of_band'],'lower')
    def test_distinct_plane_can_add_one_vote(self):
        fused,rejected=fuse_planes([plane('upper',0,0)],[plane('lower',1,20)])
        self.assertEqual(len(fused),2);self.assertEqual(rejected,[])
    def test_invalid_normals_and_source_band_are_refused(self):
        bad=plane('upper',0,0);bad['normal']=[0,0,0]
        with self.assertRaises(ValueError):fuse_planes([bad],[])
        with self.assertRaises(ValueError):fuse_planes([plane('lower',0,0)],[])
    def test_caller_inputs_are_not_mutated(self):
        upper=[plane('upper',0,0)];lower=[plane('lower',1,1)]
        original=json.dumps([upper,lower]);fuse_planes(upper,lower)
        self.assertEqual(json.dumps([upper,lower]),original)


class AgreementTests(unittest.TestCase):
    def pose(self,angle=0,accepted=True):
        a=np.deg2rad(angle)
        return dict(accepted=accepted,up=[0,-np.cos(a),np.sin(a)] if accepted else None,
                    inliers=6,inlier_indices=list(range(6)))
    def test_either_missing_side_is_refused(self):
        for a,b in ((False,True),(True,False),(False,False)):
            r=independent_agreement(self.pose(accepted=a),self.pose(accepted=b))
            self.assertFalse(r['accepted']);self.assertIsNone(r['up'])
    def test_disagreeing_directions_are_not_averaged(self):
        r=independent_agreement(self.pose(),self.pose(3))
        self.assertFalse(r['accepted']);self.assertIsNone(r['up'])
    def test_agreement_retains_upper_direction_exactly(self):
        upper=self.pose(.25);r=independent_agreement(upper,self.pose(.5))
        self.assertTrue(r['accepted']);self.assertEqual(r['up'],upper['up'])


class SavedBandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r01';cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.frames=read_csv(cls.output/'image_diagnostics.csv');cls.planes=read_csv(cls.output/'fused_plane_ledger.csv')
        candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
        cls.camera=camera_from_candidate(json.loads(candidate.read_text()))
    def test_frozen_source_and_output_hashes(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
    def test_all_492_frames_are_retained_in_each_of_four_modes(self):
        self.assertEqual(len(self.frames),1968)
        counts=Counter((r['session'],r['frame']) for r in self.frames)
        self.assertEqual(len(counts),492);self.assertEqual(set(counts.values()),{4})
        self.assertEqual({r['mode'] for r in self.frames},set(MODES))
    def test_upper_reproduces_every_original_decision(self):
        old=read_csv(PREVIOUS/'scene_results_r01/image_diagnostics.csv')
        current=[r for r in self.frames if r['mode']=='upper']
        self.assertEqual([(r['session'],r['frame'],r['accepted'],r['reason'],r['inliers'],r['up_optical_json']) for r in current],
                         [(r['session'],r['frame'],r['accepted'],r['reason'],r['inliers'],r['up_optical_json'] or 'null') for r in old])
        self.assertEqual(self.summary['baseline_equivalence_representatives'],18)
    def test_upper_plane_prefix_is_exactly_preserved_for_every_frame(self):
        before=defaultdict(list);after=defaultdict(list)
        for r in read_csv(PREVIOUS/'scene_results_r01/line_candidates.csv'):
            if r['accepted']=='True':before[r['session'],r['frame']].append(r)
        for r in self.planes:after[r['session'],r['frame']].append(r)
        for key,rows in before.items():
            fused=after[key]
            self.assertTrue(all(r['band']=='upper' for r in fused[:len(rows)]))
            self.assertEqual([(r['line_index'],r['part'],r['normal_json']) for r in rows],
                             [(r['line_index'],r['part'],r['normal_json']) for r in fused[:len(rows)]])
    def test_kept_normals_are_not_duplicate_votes(self):
        groups=defaultdict(list)
        for r in self.planes:groups[r['session'],r['frame']].append(r)
        for rows in groups.values():
            n=np.array([json.loads(r['normal_json']) for r in rows])
            for i in range(len(n)):
                if i:self.assertTrue((np.degrees(np.arccos(np.clip(abs(n[:i]@n[i]),-1,1)))>=2-1e-10).all())
    def test_duplicate_reference_is_a_retained_vote(self):
        kept={(r['session'],r['frame'],r['band'],r['line_index'],r['part']) for r in self.planes}
        for r in read_csv(self.output/'cross_band_duplicates.csv'):
            self.assertIn((r['session'],r['frame'],r['duplicate_of_band'],r['duplicate_of_line_index'],r['duplicate_of_part']),kept)
            self.assertLess(float(r['angle_deg']),2)
    def test_lower_endpoints_only_use_lower_native_band(self):
        for r in read_csv(self.output/'lower_line_candidates.csv'):
            for field in ('first_native_json','last_native_json'):
                x,y=json.loads(r[field]);self.assertTrue(40<=x<=600 and 301<=y<=430)
    def test_modes_do_not_export_transform_or_claim_metric_eligibility(self):
        rows=read_csv(self.output/'session_hypotheses.csv')
        self.assertEqual(len(rows),36)
        self.assertTrue(all('conditional_transform' not in r and 'metric_eligible' not in r for r in rows))
        self.assertTrue(all(r['usable_for_ffb']=='False' for r in rows))
    def test_no_physical_or_production_changes(self):
        for field in ('metric_labels_used','physical_vertical_verified','source_images_edited','production_settings_changed','physical_output','usable_for_ffb'):
            self.assertFalse(self.summary[field])
        self.assertEqual(self.summary['work_date'],'2026-10-23')
    def test_completed_checkpoints_cover_nine_sessions(self):
        paths=list((self.output/'sessions').glob('*/complete.json'));self.assertEqual(len(paths),9)
        for p in paths:
            r=json.loads(p.read_text());self.assertEqual(r['run_spec_sha256'],sha256(self.output/'run_spec.json'))
            self.assertEqual(r['data_sha256'],sha256(p.parent/'data.json'))
    def test_empty_image_makes_no_candidate_in_either_band(self):
        image=np.zeros((720,1280,3),np.uint8)
        for band in ('upper','lower'):self.assertEqual(extract_band(image,self.camera,band=band),[])
    def test_only_predeclared_bands_and_native_images_are_allowed(self):
        with self.assertRaises(ValueError):extract_band(np.zeros((720,1280,3),np.uint8),self.camera,band='third')
        with self.assertRaises(ValueError):extract_band(np.zeros((360,640,3),np.uint8),self.camera,band='upper')


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'report_r01';cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.assets=HERE.parent/'report_assets'
    def test_report_source_output_and_assets_integrity(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
        self.assertEqual(sha256(self.assets/'manifest.json'),self.summary['asset_manifest_sha256'])
        manifest=json.loads((self.assets/'manifest.json').read_text())
        self.assertEqual(len(manifest['assets']),4)
        for r in manifest['assets']:self.assertEqual(sha256(self.assets/r['file']),sha256(Path(r['source'])))
    def test_all_original_acceptances_are_preserved_but_failures_remain(self):
        self.assertEqual(self.summary['old_accepted_images'],27)
        self.assertEqual(self.summary['old_accepted_images_lost'],0)
        self.assertEqual(self.summary['newly_accepted_images'],26)
        pairs=read_csv(self.output/'paired_images.csv');self.assertEqual(len(pairs),492)
        self.assertEqual(sum(r['fusion_accepted']!='True' for r in pairs),439)
    def test_new_acceptances_have_only_one_lower_inlier(self):
        rows=read_csv(self.output/'paired_images.csv')
        for r in rows:
            if r['upper_accepted']!='True' and r['fusion_accepted']=='True':
                self.assertEqual(r['fusion_inliers_upper'],'5');self.assertEqual(r['fusion_inliers_lower'],'1')
    def test_report_native_frame_is_not_edited_and_capture_date_is_not_relabelled(self):
        manifest=json.loads((self.assets/'manifest.json').read_text())
        r=next(x for x in manifest['assets'] if x['kind']=='native_camera')
        self.assertEqual(manifest['work_date'],'2026-10-23');self.assertEqual(r['capture_date'],'2026-10-15')
        self.assertFalse(r['image_edited']);self.assertEqual(cv2.imread(str(self.assets/r['file'])).shape,(720,1280,3))


if __name__=='__main__':unittest.main()
