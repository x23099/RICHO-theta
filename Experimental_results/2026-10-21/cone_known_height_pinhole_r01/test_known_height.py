import copy
import json
from pathlib import Path
import unittest
import cv2
import numpy as np
import analyze_height as study
from known_height import HEIGHT_M, BASE_HALF_M, contour_pair, height_position
from known_width import VIRTUAL_K
from fisheye_floor_geometry import optical_rays, legacy_front_diagnostic_geometry


class HeightMathTests(unittest.TestCase):
    def setUp(self):
        self.T=np.array([[0.,0.,1.,0.],[-1.,0.,0.,0.],[0.,-1.,0.,.59],[0.,0.,0.,1.]])
        self.base=np.array([2.,0.,0.])

    def project(self,base=None,offset=0.,T=None):
        base=self.base if base is None else base
        T=self.T if T is None else T
        target=np.array([base+[offset,0,HEIGHT_M],base])
        optical=(target-T[:3,3])@T[:3,:3]
        p=optical@VIRTUAL_K.T
        return p[:,:2]/p[:,2,None]

    def test_exact_upright_height(self):
        r=height_position(self.project(),VIRTUAL_K,self.T)
        self.assertAlmostEqual(r['z_forward_m'],2.)
        self.assertAlmostEqual(r['base_height_m'],0.)
        self.assertAlmostEqual(r['tip_height_m'],HEIGHT_M)
        self.assertLess(r['residual_m'],1e-12)
        self.assertFalse(r['usable_for_ffb'])

    def test_rotation_and_lateral_offset(self):
        T=self.T.copy()
        T[:3,:3]=cv2.Rodrigues(np.array([.07,-.04,.09]))[0]@T[:3,:3]
        for x in (-.5875,0.,.5875):
            base=np.array([1.3,-x,0.])
            r=height_position(self.project(base=base,T=T),VIRTUAL_K,T)
            self.assertAlmostEqual(r['z_forward_m'],1.3)
            self.assertAlmostEqual(r['x_right_m'],x)

    def test_known_forward_offset_recovers_near_edge(self):
        r=height_position(self.project(offset=BASE_HALF_M),VIRTUAL_K,self.T,tip_forward_offset_m=BASE_HALF_M)
        self.assertAlmostEqual(r['z_forward_m'],2.)
        self.assertAlmostEqual(r['tip_z_m'],2.+BASE_HALF_M)

    def test_wrong_correspondence_not_automatically_corrected_by_height(self):
        r=height_position(self.project(offset=BASE_HALF_M),VIRTUAL_K,self.T)
        self.assertGreater(abs(r['z_forward_m']-2.),.02)
        self.assertGreater(abs(r['base_height_m']),.005)

    def test_height_translation_does_not_scale_depth(self):
        uv=self.project()
        T=self.T.copy()
        T[2,3]+=1.
        a,b=height_position(uv,VIRTUAL_K,self.T),height_position(uv,VIRTUAL_K,T)
        self.assertEqual(a['z_forward_m'],b['z_forward_m'])
        self.assertAlmostEqual(b['base_height_m']-a['base_height_m'],1.)

    def test_virtual_K_resolution_invariance(self):
        uv=self.project()
        K=VIRTUAL_K.copy()
        K[:2]*=2.
        a,b=height_position(uv,VIRTUAL_K,self.T),height_position(uv*2,K,self.T)
        self.assertAlmostEqual(a['z_forward_m'],b['z_forward_m'])

    def test_measured_height_scales_depth(self):
        r=height_position(self.project(),VIRTUAL_K,self.T,height_m=HEIGHT_M*1.2)
        self.assertAlmostEqual(r['z_forward_m'],2.4)

    def test_truncated_tip_overestimates_depth(self):
        uv=self.project()
        uv[0]=(uv[0]+uv[1])/2
        r=height_position(uv,VIRTUAL_K,self.T)
        self.assertAlmostEqual(r['z_forward_m'],4.)
        self.assertFalse(r['physical_endpoint_correspondence_verified'])

    def test_out_of_range_retained(self):
        r=height_position(self.project(base=np.array([8.,0.,0.])),VIRTUAL_K,self.T)
        self.assertTrue(r['estimated'])
        self.assertAlmostEqual(r['z_forward_m'],8.)
        self.assertFalse(r['in_diagnostic_range'])

    def test_degenerate_and_reversed_rays(self):
        uv=self.project()
        self.assertFalse(height_position(np.array([uv[0],uv[0]]),VIRTUAL_K,self.T)['estimated'])
        self.assertFalse(height_position(uv[::-1],VIRTUAL_K,self.T)['estimated'])

    def test_invalid_inputs(self):
        for kwargs in ({'height_m':0.},{'height_m':float('nan')},{'tip_forward_offset_m':-.1}):
            with self.assertRaises(ValueError):
                height_position(self.project(),VIRTUAL_K,self.T,**kwargs)
        for uv in (np.full((2,2),np.nan),self.project().astype(complex)):
            with self.assertRaises(ValueError):
                height_position(uv,VIRTUAL_K,self.T)
        T=self.T.copy()
        T[:3,0]*=-1
        with self.assertRaises(ValueError):
            height_position(self.project(),VIRTUAL_K,T)

    def test_lateral_inconsistency_is_retained_as_residual(self):
        uv=self.project()
        uv[0,0]+=50
        r=height_position(uv,VIRTUAL_K,self.T)
        self.assertTrue(r['estimated'])
        self.assertGreater(r['residual_m'],.02)
        self.assertFalse(r['segment_consistent'])

    def test_no_mutation(self):
        uv,K,T=self.project(),VIRTUAL_K.copy(),self.T.copy()
        expected=[x.copy() for x in (uv,K,T)]
        height_position(uv,K,T)
        for a,b in zip((uv,K,T),expected):
            np.testing.assert_array_equal(a,b)

    def test_contour_uses_measured_column_not_hidden_centre(self):
        c=np.array([[10,10],[11,10],[12,11],[13,13],[13,18],[12,20],[11,20],[10,20],[9,18]])
        uv=contour_pair(c)
        np.testing.assert_array_equal(uv,[[10.5,10.],[10.,20.]])
        with self.assertRaises(ValueError):
            contour_pair(c+.1)

    def test_subpixel_tip_sensitivity_not_silently_quantized(self):
        uv=self.project()
        a=height_position(uv,VIRTUAL_K,self.T)
        uv[0,1]+=.5
        b=height_position(uv,VIRTUAL_K,self.T)
        self.assertNotEqual(a['z_forward_m'],b['z_forward_m'])

    def test_nominal_reference_has_no_effect(self):
        p=study.width.old.load_inputs()[1]['height_only59']
        source=dict(dataset='test',session='test',frame=1,native_colour_pair_json='[[315,320],[315,390]]',
                    native_bbox_pair_json='',reference_z_m=2.)
        a=study.replay([source],{'test':p})
        source['reference_z_m']=99.
        b=study.replay([source],{'test':p})
        self.assertEqual([r['z_forward_m'] for r in a],[r['z_forward_m'] for r in b])


class SavedHeightStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=Path(__file__).resolve().parent/'results_r01'
        cls.provenance=json.loads((cls.folder/'provenance.json').read_text())
        cls.rows=study.read_csv(cls.folder/'all_frame_estimates.csv')

    def test_complete_frames_and_methods(self):
        self.assertEqual(len(self.rows),6876*9)
        self.assertEqual(len({study.key(r) for r in self.rows}),6876)
        self.assertTrue(all(r['usable_for_ffb']=='False' for r in self.rows))
        self.assertTrue(all(r['physical_endpoint_correspondence_verified']=='False' for r in self.rows))

    def test_frozen_sources_and_outputs(self):
        for path,digest in self.provenance['source_sha256'].items():
            self.assertEqual(study.sha256(Path(path)),digest,path)
        for name,digest in self.provenance['output_sha256'].items():
            self.assertEqual(study.sha256(self.folder/name),digest,name)

    def test_no_invented_paper_only_targets(self):
        rows=[r for r in self.rows if r['dataset']=='paper_cone_20261019' and r['condition'] in ('paper_before','paper_after')]
        self.assertEqual(len(rows),(391+240)*9)
        self.assertTrue(all(r['estimated']=='False' for r in rows))

    def test_width_comparison_really_matched_per_frame(self):
        old={study.key(r):r for r in study.read_csv(study.WIDTH/'results_r01/all_frame_estimates.csv')
             if r['model']=='height_only59' and r['method']=='visible_full_span'}
        for r in self.rows:
            self.assertEqual(r['previous_width_z_m'],old[study.key(r)]['z_forward_m'])

    def test_all_estimated_positions_independent_native_rays(self):
        # Analytic 2x2 normal equations, not production lstsq or undistortPoints.
        for model,parameters in self.provenance['models'].items():
            camera,T=legacy_front_diagnostic_geometry(parameters)
            selected=[r for r in self.rows if r['model']==model and r['estimated']=='True']
            native=np.array([json.loads(r['native_bbox_pair_json'] if r['method']=='bbox_vertical_control' else r['native_colour_pair_json']) for r in selected])
            optical,valid=optical_rays(native.reshape(-1,2),camera)
            self.assertTrue(valid.all())
            directions=(optical/optical[:,2,None]@T[:3,:3].T).reshape(-1,2,3)
            a,b=directions[:,0],-directions[:,1]
            delta=np.array([[float(r['tip_forward_offset_m']),0.,HEIGHT_M] for r in selected])
            aa=np.einsum('ij,ij->i',a,a)
            bb=np.einsum('ij,ij->i',b,b)
            ab=np.einsum('ij,ij->i',a,b)
            ad=np.einsum('ij,ij->i',a,delta)
            bd=np.einsum('ij,ij->i',b,delta)
            s=(aa*bd-ab*ad)/(aa*bb-ab*ab)
            base=-b*s[:,None]+T[:3,3]
            saved=np.array([[float(r['z_forward_m']),-float(r['x_right_m']),float(r['base_height_m'])] for r in selected])
            np.testing.assert_allclose(base,saved,atol=1e-9,rtol=0)

    def test_summary_exact_recompute(self):
        rows=copy.deepcopy(self.rows)
        for r in rows:
            for field in ('reference_z_m','previous_width_z_m','z_forward_m','base_height_m','residual_m'):
                r[field]=float(r[field]) if r[field] else None
            for field in ('estimated','quality_accepted','segment_consistent','in_diagnostic_range'):
                r[field]=r[field]=='True'
        fresh=study.summarize(rows)
        saved=study.read_csv(self.folder/'summary.csv')
        self.assertEqual(len(fresh),len(saved))
        for a,b in zip(fresh,saved):
            for field,value in a.items():
                self.assertEqual('' if value is None else str(value),b[field])


if __name__=='__main__':
    unittest.main()
