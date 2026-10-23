from collections import Counter
import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from support_audit import HERE,ROOT,PREVIOUS,normal_angle,nearest,near_seam,leave_one_out
from cone_dataset import read_csv,sha256
from scene_geometry import infer_up


class HelperTests(unittest.TestCase):
    def test_normal_sign_is_not_a_new_direction(self):
        self.assertEqual(normal_angle([1,0,0],[-1,0,0]),0)
    def test_normal_contract(self):
        with self.assertRaises(ValueError):normal_angle([0,0,0],[1,0,0])
    def test_no_upper_reference_is_not_invented(self):
        self.assertEqual(nearest([1,0,0],[]),(None,None))
    def test_seam_continuity_uses_observed_boundaries(self):
        self.assertTrue(near_seam([[240,229],[235,300]],[[235,301],[236,362]]))
        self.assertFalse(near_seam([[240,229],[220,300]],[[235,301],[236,362]]))
        self.assertFalse(near_seam([[240,229],[235,280]],[[235,301],[236,362]]))
    def test_leave_one_out_does_not_modify_original_members(self):
        angles=np.deg2rad(np.arange(6)*20.)
        members=[dict(band='upper',line_index=i,part=0,normal_json=json.dumps([float(np.cos(a)),0.,float(np.sin(a))])) for i,a in enumerate(angles)]
        original=json.dumps(members);n=np.array([json.loads(r['normal_json']) for r in members]);pose=infer_up(n,[0,-1,0])
        rows=leave_one_out(members,pose,[0,-1,0])
        self.assertEqual(json.dumps(members),original);self.assertEqual(len(rows),6)
        self.assertTrue(all(not r['remaining_accepted'] for r in rows))


class SavedSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r01';cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.refs=read_csv(cls.output/'all_lower_references.csv');cls.support=read_csv(cls.output/'lower_inlier_support.csv')
    def test_source_and_output_hashes(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
    def test_all_492_counterfactual_images_are_retained(self):
        rows=read_csv(self.output/'counterfactual_images.csv');self.assertEqual(len(rows),492)
        self.assertEqual(len({(r['session'],r['frame']) for r in rows}),492)
        self.assertEqual(sum(r['accepted']=='True' for r in rows),36)
    def test_new_angular_reference_count_is_not_hidden(self):
        selected=[r for r in self.refs if r['newly_accepted_image']=='True' and r['is_inlier']=='True']
        self.assertEqual(len(selected),26)
        close=[r for r in selected if r['counterfactual_veto']=='True'];self.assertEqual(len(close),17)
        self.assertTrue(all(r['closest_upper_reason']=='duplicate_ray_plane' for r in close))
    def test_seam_and_angular_flags_are_independent_columns(self):
        lookup={(r['session'],r['frame'],r['fusion_index']):r for r in self.refs}
        counts=Counter((lookup[r['session'],r['frame'],r['fusion_index']]['counterfactual_veto'],r['seam_continuation_possible'])
            for r in self.support if r['newly_accepted_image']=='True')
        self.assertEqual(counts,{('True','True'):17,('False','False'):9})
    def test_actual_lower_pixels_match_old_saved_support(self):
        old={(r['session'],r['frame'],r['line_index'],r['part']):r for r in read_csv(PREVIOUS/'results_r01/lower_line_candidates.csv')}
        for r in read_csv(self.output/'actual_lower_support.csv'):
            points=np.array(json.loads(r['actual_edge_pixels_json']))
            self.assertTrue(((points[:,1]>=301)&(points[:,1]<=430)).all())
            digest=hashlib.sha256(points.astype('<i4').tobytes()).hexdigest()
            self.assertEqual(digest,r['native_points_sha256'])
            self.assertEqual(digest,old[r['session'],r['frame'],r['line_index'],r['part']]['native_points_sha256'])
    def test_native_images_are_unchanged(self):
        rows=read_csv(self.output/'verified_native_images.csv');self.assertEqual(len(rows),29)
        for r in rows:
            self.assertEqual(sha256(Path(r['source_native_png'])),r['png_sha256'])
            self.assertEqual(cv2.imread(r['source_native_png']).shape,(720,1280,3))
    def test_all_321_inlier_removals_are_retained(self):
        rows=read_csv(self.output/'leave_one_plane_out.csv');self.assertEqual(len(rows),321)
        selected=[r for r in rows if r['newly_accepted_image']=='True' and r['removed_band']=='lower']
        self.assertEqual(len(selected),26)
        self.assertEqual(sum(r['remaining_accepted']=='False' for r in selected),22)
        self.assertEqual(sum(r['remaining_accepted']=='True' for r in selected),4)
    def test_counterfactual_has_only_two_temporal_passes(self):
        rows=read_csv(self.output/'counterfactual_sessions.csv');self.assertEqual(len(rows),9)
        self.assertEqual(sum(r['temporal_candidate_eligible']=='True' for r in rows),2)
        self.assertTrue(all('conditional_transform' not in r and 'metric_eligible' not in r for r in rows))
    def test_flags_do_not_assert_physical_identity_or_output(self):
        self.assertFalse(self.summary['metric_labels_used']);self.assertFalse(self.summary['physical_output'])
        self.assertFalse(self.summary['source_images_edited']);self.assertFalse(self.summary['usable_for_ffb'])
        self.assertTrue(all(r['physical_same_edge_verified']=='False' for r in self.refs))


class ReportTests(unittest.TestCase):
    def test_report_hashes_and_native_context_images(self):
        folder=HERE/'report_r01';data=json.loads((folder/'summary.json').read_text())
        for p,h in data['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in data['output_sha256'].items():self.assertEqual(sha256(folder/name),h,name)
        for r in data['native_assets']:
            self.assertEqual(sha256(folder/r['file']),sha256(Path(r['source'])))
            self.assertEqual(cv2.imread(str(folder/r['file'])).shape,(720,1280,3));self.assertFalse(r['image_edited'])


if __name__=='__main__':unittest.main()
