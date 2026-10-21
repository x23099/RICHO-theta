import copy
import json
from pathlib import Path
import unittest
import cv2
import numpy as np
import analyze_plumb as study
from plumb_support import bracket_observed_support,rectify,segment_image_line,select_base
from known_width import VIRTUAL_K,raw_to_rectified
from known_height import height_position
from fisheye_floor_geometry import legacy_front_diagnostic_geometry,EquidistantCamera


class PlumbSupportTests(unittest.TestCase):
    def setUp(self):
        self.points=np.array([[x,40] for x in range(10,31)],float)
        self.valid=np.ones(len(self.points),bool)

    def select(self,line,points=None):
        p=self.points if points is None else points
        return bracket_observed_support(p,p.copy(),np.ones(len(p),bool),line)

    def test_only_actual_observed_point_not_interpolated_root(self):
        r=self.select([1,0,-22.3])
        self.assertTrue(r['selected'])
        self.assertEqual(r['point_native'],[22.,40.])
        self.assertAlmostEqual(r['line_distance_px'],.3)
        self.assertFalse(r['physical_endpoint_correspondence_verified'])
        self.assertFalse(r['usable_for_ffb'])

    def test_exact_observed_root_is_single_not_duplicated(self):
        r=self.select([1,0,-22])
        self.assertTrue(r['selected'])
        self.assertEqual(r['root_groups'],1)
        self.assertEqual(r['point_native'],[22.,40.])

    def test_no_extrapolation_outside_support(self):
        self.assertEqual(self.select([1,0,-29])['reason'],'no_bracket_in_observed_support')
        self.assertFalse(self.select([1,0,-100])['selected'])

    def test_missing_columns_cannot_be_bridged(self):
        p=self.points[~np.isin(self.points[:,0],[22,23])]
        self.assertFalse(self.select([1,0,-22.4],p)['selected'])

    def test_two_adjacent_crossings_are_not_merged(self):
        p=self.points.copy()
        p[:,1]=40
        p[p[:,0]==20,1]=42
        r=self.select([0,1,-41],p)
        self.assertEqual(r['reason'],'ambiguous_observed_intersections')
        self.assertEqual(r['root_groups'],2)

    def test_many_crossings_rejected(self):
        p=self.points.copy()
        p[:,1]=40+p[:,0]%2*2
        self.assertEqual(self.select([0,1,-41],p)['reason'],'ambiguous_observed_intersections')

    def test_invalid_virtual_point_cannot_bridge_root(self):
        valid=self.valid.copy()
        valid[self.points[:,0]==22]=False
        r=bracket_observed_support(self.points,self.points,valid,[1,0,-22.3])
        self.assertFalse(r['selected'])

    def test_insufficient_support(self):
        self.assertEqual(self.select([1,0,-12],self.points[:8])['reason'],'insufficient_observed_support')

    def test_invalid_order_or_noninteger_rejected(self):
        for p in (self.points[::-1],self.points+.1):
            with self.assertRaises(ValueError):
                self.select([1,0,-22],p)
        with self.assertRaises(ValueError):
            self.select([float('nan'),0,0])

    def test_no_input_mutation(self):
        p=self.points.copy()
        self.select([1,0,-22])
        np.testing.assert_array_equal(p,self.points)

    def test_actual_perspective_segment_plane_including_pitch_roll(self):
        R0=np.array([[0.,0.,1.],[-1.,0.,0.],[0.,-1.,0.]])
        T=np.eye(4)
        T[:3,:3]=cv2.Rodrigues(np.array([.08,-.06,.12]))[0]@R0
        T[2,3]=.59
        for offset in (0.,.1875):
            base=np.array([1.3,-.5875,0.])
            delta=np.array([offset,0,.73])
            optical=(np.array([base+delta,base])-T[:3,3])@T[:3,:3]
            uv=optical@VIRTUAL_K.T
            uv=uv[:,:2]/uv[:,2,None]
            line=segment_image_line(uv[0],VIRTUAL_K,T,delta)
            self.assertAlmostEqual(float(line@[*uv[1],1.]),0.,places=9)
            self.assertGreater(abs(uv[0,0]-uv[1,0]),1.)
            result=height_position(uv,VIRTUAL_K,T,tip_forward_offset_m=offset)
            self.assertAlmostEqual(result['z_forward_m'],1.3)

    def test_segment_line_is_scale_invariant(self):
        T=np.array([[0.,0.,1.,0.],[-1.,0.,0.,0.],[0.,-1.,0.,.59],[0.,0.,0.,1.]])
        a=segment_image_line([470,400],VIRTUAL_K,T,[.1875,0,.73])
        b=segment_image_line([470,400],VIRTUAL_K,T,[.375,0,1.46])
        np.testing.assert_allclose(a,b,atol=1e-12,rtol=0)

    def test_invalid_line_and_reflection(self):
        T=np.eye(4)
        with self.assertRaises(ValueError):
            segment_image_line([1,2],VIRTUAL_K,T,[0,0,0])
        T[0,0]=-1
        with self.assertRaises(ValueError):
            segment_image_line([1,2],VIRTUAL_K,T,[0,0,.73])

    def test_native_rectification_matches_opencv_and_preserves_invalid(self):
        parameters=study.previous.width.old.load_inputs()[1]['height_only59']
        camera,T=legacy_front_diagnostic_geometry(parameters)
        p=np.array([[310,320],[312,400]])
        uv,valid=rectify(p,camera,VIRTUAL_K)
        self.assertTrue(valid.all())
        np.testing.assert_allclose(uv,raw_to_rectified(p,parameters),atol=1e-10,rtol=0)
        _,valid=rectify([[0,0],[310,320]],camera,VIRTUAL_K)
        np.testing.assert_array_equal(valid,[False,True])
        with self.assertRaises(ValueError):
            rectify(p,camera,VIRTUAL_K.astype(complex))

    def test_bad_height_or_outside_tip_rejected(self):
        camera=EquidistantCamera(1280,720,320,340,275.)
        T=np.eye(4)
        r=select_base([0,0],self.points,camera,VIRTUAL_K,T)
        self.assertEqual(r['reason'],'tip_outside_lens_or_virtual_view')
        with self.assertRaises(ValueError):
            select_base([320,340],self.points,camera,VIRTUAL_K,T,height_m=0)


class SavedPlumbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=Path(__file__).resolve().parent/'results_r02'
        cls.provenance=json.loads((cls.folder/'provenance.json').read_text())
        cls.rows=study.read_csv(cls.folder/'all_frame_estimates.csv')

    def test_all_frames_and_guards_retained(self):
        self.assertEqual(len(self.rows),6876*6)
        self.assertEqual(len({study.key(r) for r in self.rows}),6876)
        self.assertTrue(all(r['usable_for_ffb']=='False' for r in self.rows))

    def test_hashes_unchanged(self):
        for path,digest in self.provenance['source_sha256'].items():
            self.assertEqual(study.sha256(Path(path)),digest,path)
        for name,digest in self.provenance['output_sha256'].items():
            self.assertEqual(study.sha256(self.folder/name),digest,name)

    def test_selected_points_are_actual_supported_columns(self):
        _,_,envelopes,_,_=study.load_inputs()
        for r in self.rows:
            if r['selected']!='True':
                continue
            p=np.asarray(json.loads(r['native_base_json']))
            env=envelopes[study.key(r)]
            self.assertTrue(any(np.array_equal(p,e) for e in env))
            lo,hi=env[0,0],env[-1,0]
            self.assertTrue(lo+.1*(hi-lo)<=p[0]<=hi-.1*(hi-lo))

    def test_no_invented_targets_in_paper_windows(self):
        rows=[r for r in self.rows if r['dataset']=='paper_cone_20261019' and r['condition'] in ('paper_before','paper_after')]
        self.assertEqual(len(rows),631*6)
        self.assertTrue(all(r['estimated']=='False' for r in rows))

    def test_reference_changes_cannot_choose_point_or_depth(self):
        pixels,baseline,envelopes,models,_=study.load_inputs()
        selected=next(r for r in pixels if r['native_colour_pair_json'])
        a=study.replay([selected],baseline,envelopes,{'height_only59':models['height_only59']})
        altered=dict(selected,reference_z_m='100')
        b=study.replay([altered],baseline,envelopes,{'height_only59':models['height_only59']})
        for x,y in zip(a,b):
            for k in ('native_base_json','estimated','z_forward_m','reason'):
                self.assertEqual(x[k],y[k])

    def test_independent_plane_and_all_selected_pair_rectification(self):
        models=self.provenance['models']
        for r in self.rows:
            if r['selected']!='True':
                continue
            _,T=legacy_front_diagnostic_geometry(models[r['model']])
            native=[json.loads(r['native_tip_json']),json.loads(r['native_base_json'])]
            uv=raw_to_rectified(native,models[r['model']])
            np.testing.assert_allclose(uv,json.loads(r['rectified_pair_json']),atol=1e-9,rtol=0)
            line=np.asarray(json.loads(r['projected_line_json']))
            self.assertAlmostEqual(float(line@[*uv[0],1.]),0.,places=8)
            self.assertAlmostEqual(abs(float(line@[*uv[1],1.])),float(r['line_distance_px']),places=8)
            # Separate plane formula: camera optical centre and a displaced
            # point on the tip ray define a segment projection direction.
            ray=np.linalg.solve(VIRTUAL_K,[*uv[0],1.])
            displaced=ray*2-T[:3,:3].T@[float(r['tip_forward_offset_m']),0,.73]
            image=VIRTUAL_K@displaced
            self.assertAlmostEqual(float(line@(image/image[2])),0.,places=8)

    def test_summary_and_old_matched_population_recompute(self):
        rows=copy.deepcopy(self.rows)
        numeric=('reference_z_m','z_forward_m','old_height_z_m','old_width_z_m','base_height_m','residual_m',
                 'old_height_residual_m','old_height_base_height_m','base_shift_x_px','base_shift_y_px','line_distance_px')
        for r in rows:
            for f in numeric:
                r[f]=float(r[f]) if r[f] else None
            for f in ('estimated','quality_accepted','segment_consistent','in_diagnostic_range'):
                r[f]=r[f]=='True'
        fresh=study.summarize(rows)
        saved=study.read_csv(self.folder/'summary.csv')
        self.assertEqual(len(fresh),len(saved))
        for a,b in zip(fresh,saved):
            for k,v in a.items():
                self.assertEqual('' if v is None else str(v),b[k])


if __name__=='__main__':
    unittest.main()
