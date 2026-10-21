import inspect
import json
from pathlib import Path
import sys
import unittest

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from contact_geometry import choose_observed_root,central_support,floor_implied_tip_heights
from angular_fisheye_geometry import segment_from_rays
from cone_dataset import read_csv,sha256


class ContactGeometryTests(unittest.TestCase):
    def setUp(self):
        self.T=np.eye(4);self.T[:3,:3]=[[0,0,1],[-1,0,0],[0,-1,0]];self.T[2,3]=.59
        self.points=np.array([[x,40.] for x in range(10,31)])

    def ray(self,world):
        r=(np.asarray(world)-self.T[:3,3])@self.T[:3,:3]
        return r/np.linalg.norm(r,axis=-1,keepdims=True)

    def choose(self,signs,points=None,valid=None):
        # With nominal pose and tip=(0,0,1), vertical plane has normal=(1,0,0).
        p=self.points if points is None else points
        rays=np.column_stack((signs,np.full(len(p),.3),np.ones(len(p))))
        rays/=np.linalg.norm(rays,axis=1)[:,None]
        v=np.ones(len(p),bool) if valid is None else valid
        return choose_observed_root(p,rays,v,[0,0,1],self.T)

    def test_actual_observed_point_only(self):
        r=self.choose((self.points[:,0]-22.3)/100.)
        self.assertTrue(r['selected']);self.assertEqual(r['index'],12)
        self.assertFalse(r['usable_for_ffb']);self.assertFalse(r['physical_contact_verified'])

    def test_exact_zero_not_double_counted(self):
        r=self.choose((self.points[:,0]-22.)/100.)
        self.assertEqual(r['root_groups'],1);self.assertEqual(r['index'],12)

    def test_adjacent_distinct_roots_not_merged(self):
        signs=np.ones(21);signs[10]=-1
        r=self.choose(signs/100.)
        self.assertFalse(r['selected']);self.assertEqual(r['root_groups'],2)

    def test_no_bridging_missing_columns(self):
        p=self.points[~np.isin(self.points[:,0],[22,23])]
        r=self.choose((p[:,0]-22.4)/100.,p)
        self.assertFalse(r['selected'])

    def test_no_bridging_invalid_ray(self):
        valid=np.ones(21,bool);valid[12]=False
        r=self.choose((self.points[:,0]-22.3)/100.,valid=valid)
        self.assertFalse(r['selected'])

    def test_no_extrapolation_or_insufficient_support(self):
        self.assertFalse(self.choose((self.points[:,0]-29)/100.)['selected'])
        p=self.points[:8]
        self.assertEqual(self.choose((p[:,0]-13)/100.,p)['reason'],'insufficient_observed_support')

    def test_invalid_order_subpixel_and_delta_refused(self):
        for p in (self.points[::-1],self.points+.1):
            with self.assertRaises(ValueError):central_support(p)
        with self.assertRaises(ValueError):
            choose_observed_root(self.points,np.ones((21,3)),np.ones(21,bool),[0,0,1],self.T)

    def test_floor_height_consistency_restores_true_tip_for_both_offsets(self):
        for offset in (0.,.1875):
            base=np.array([2.,-.3,0]);tip=base+[offset,0,.73]
            rays=self.ray([tip,base])
            r=floor_implied_tip_heights(rays[0],rays[1:],np.ones(1,bool),self.T,offset_m=offset)
            self.assertTrue(r['accepted'][0]);self.assertGreater(r['tip_elevation_deg'],0)
            self.assertAlmostEqual(r['tip_heights'][0],.73)
            self.assertLess(r['horizontal_residuals'][0],1e-12)
            height=segment_from_rays(rays,self.T,tip_forward_offset_m=offset)
            self.assertAlmostEqual(height['base_target_m'][2],0)

    def test_downward_tip_cannot_be_taller_than_camera_for_any_bottom(self):
        tip=self.ray([2.,0,.50])
        bases=self.ray([[.8,0,0],[1.3,0,0],[2.,0,0],[3.,0,0]])
        r=floor_implied_tip_heights(tip,bases,np.ones(4,bool),self.T)
        self.assertLess(r['tip_elevation_deg'],0)
        self.assertTrue(np.all(r['tip_heights']<.59))

    def test_no_height_or_reference_distance_fit_in_implied_height_api(self):
        params=inspect.signature(floor_implied_tip_heights).parameters
        self.assertNotIn('height_m',params);self.assertNotIn('reference_z_m',params)
        self.assertNotIn('reference_z_m',inspect.signature(choose_observed_root).parameters)

    def test_floor_rejects_upward_bottom(self):
        r=floor_implied_tip_heights(self.ray([2,0,.73]),[self.ray([2,0,1.])],np.ones(1,bool),self.T)
        self.assertFalse(r['accepted'][0]);self.assertTrue(np.isnan(r['tip_heights'][0]))

    def test_no_input_mutation(self):
        p=self.points.copy();self.choose((p[:,0]-22.3)/100.,p)
        np.testing.assert_array_equal(p,self.points)

    def test_plane_is_rotation_and_segment_scale_invariant(self):
        angle=.13
        rotation=np.array([[1,0,0],[0,np.cos(angle),-np.sin(angle)],[0,np.sin(angle),np.cos(angle)]])
        self.T[:3,:3]=rotation@self.T[:3,:3]
        for offset in (0.,.1875):
            tip=self.ray([2+offset,0,.73])
            rays=self.ray([[2,(x-20)*.02,0] for x in self.points[:,0]])
            a=choose_observed_root(self.points,rays,np.ones(21,bool),tip,self.T,offset_m=offset)
            b=choose_observed_root(self.points,rays,np.ones(21,bool),tip,self.T,offset_m=2*offset,height_m=1.46)
            self.assertEqual(a['index'],10);self.assertEqual(a['index'],b['index'])

    def test_ray_plane_agrees_with_pinhole_signed_zero(self):
        tip=self.ray([2,0,.73]);delta_optical=self.T[:3,:3].T@np.array([0,0,.73])
        rays=self.ray([[2,(x-20)*.02,0] for x in self.points[:,0]])
        line=np.cross(tip,delta_optical)
        normalized=rays/rays[:,2,None]
        np.testing.assert_array_equal(np.sign(rays@line),np.sign(normalized@line))
        self.assertEqual(choose_observed_root(self.points,rays,np.ones(21,bool),tip,self.T)['index'],10)


class SavedContactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=HERE/'results_r01'
        if not cls.folder.exists():raise unittest.SkipTest('Run frozen study before saved-result checks')
        cls.data=json.loads((cls.folder/'summary.json').read_text())

    def test_frozen_sources_and_outputs(self):
        for p,digest in self.data['source_sha256'].items():self.assertEqual(sha256(Path(p)),digest,p)
        for name,digest in self.data['output_sha256'].items():self.assertEqual(sha256(self.folder/name),digest,name)

    def test_all_rows_missing_and_observed_selection_retained(self):
        from collections import Counter
        rows=read_csv(self.folder/'all_frame_results.csv')
        counts=Counter((r['dataset'],r['session'],r['frame']) for r in rows)
        self.assertEqual(len(counts),6876);self.assertEqual(set(counts.values()),{4})
        self.assertEqual(len(rows),27504)
        for r in rows:
            self.assertEqual(r['physical_contact_verified'],'False');self.assertEqual(r['usable_for_ffb'],'False')
            if r['estimated']=='True':
                point=np.array(json.loads(r['selected_native_json']))
                np.testing.assert_array_equal(point,np.rint(point))
            else:self.assertEqual(r['selected_height_z_m'],'')

    def test_no_refit_or_physical_output(self):
        for key in ('geometry_refitted','physical_output','new_yolo_inference','original_images_edited','usable_for_ffb'):
            self.assertFalse(self.data[key])

    def test_selected_native_pixels_are_exactly_in_original_envelopes(self):
        from collections import defaultdict
        actual=defaultdict(set)
        for path in self.data['source_sha256']:
            if path.endswith('/lower_envelopes.csv') or path.endswith('/additional_full_envelopes.csv'):
                for r in read_csv(path):actual[r['dataset'],r['session'],r['frame']].add((float(r['x']),float(r['y'])))
        for r in read_csv(self.folder/'all_frame_results.csv'):
            if r['selected_native_json']:
                self.assertIn(tuple(json.loads(r['selected_native_json'])),actual[r['dataset'],r['session'],r['frame']])


if __name__=='__main__':unittest.main()
