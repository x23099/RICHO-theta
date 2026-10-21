import copy
import json
from pathlib import Path
import unittest
import cv2
import numpy as np
import analyze_bearing as study
from bearing import (inspect_pixel,elevation_deg,expected_elevation,central_equidistant_pixels,
                     repeated_pixel_bound)
from fisheye_floor_geometry import legacy_front_diagnostic_geometry


class BearingMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models=json.loads((study.HEIGHT/'results_r01/provenance.json').read_text())['models']

    def project(self,world):
        p=self.models['height_only59']
        camera,T=legacy_front_diagnostic_geometry(p)
        optical=T[:3,:3].T@(np.asarray(world)-T[:3,3])
        f=camera.radius/(np.pi/2)
        K=np.array([[f,0,camera.cx],[0,f,camera.cy],[0,0,1.]])
        image,_=cv2.fisheye.projectPoints(optical.reshape(1,1,3),np.zeros(3),np.zeros(3),K,np.zeros(4))
        return image.reshape(2)

    def test_known_floor_inverse_with_independent_opencv_projection(self):
        r=inspect_pixel(self.project([2.,0.,0.]),self.models['height_only59'],reference_z_m=2.)
        self.assertAlmostEqual(r['required_down_rotation_deg'],0.)
        self.assertAlmostEqual(r['model_floor_z_m'],2.)
        self.assertAlmostEqual(r['implied_camera_height_if_floor_m'],.59)
        self.assertFalse(r['usable_for_ffb'])

    def test_tip_inverse_without_floor_constraint(self):
        r=inspect_pixel(self.project([2.1875,0.,.73]),self.models['height_only59'],reference_z_m=2.1875,reference_height_m=.73)
        self.assertAlmostEqual(r['required_down_rotation_deg'],0.)
        self.assertIsNone(r['implied_camera_height_if_floor_m'])
        self.assertIsNone(r['model_floor_z_m'])

    def test_elevation_scale_invariance(self):
        self.assertEqual(elevation_deg([2.,.1,-.59]),elevation_deg([4.,.2,-1.18]))

    def test_common_pitch_changes_absolute_angles_not_separation(self):
        rays=[np.array([2.,.2,-.59]),np.array([2.1875,.2,.14])]
        angle=.1
        Ry=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
        old=[elevation_deg(r) for r in rays]
        new=[elevation_deg(Ry@r) for r in rays]
        self.assertAlmostEqual(old[1]-old[0],new[1]-new[0])
        self.assertAlmostEqual(new[0]-old[0],-np.degrees(angle))

    def test_physical_camera_height_independent_of_model_snapshot_height(self):
        pixel=[313,371]
        a=inspect_pixel(pixel,self.models['height_only59'],reference_z_m=2.)
        b=inspect_pixel(pixel,self.models['recorded58'],reference_z_m=2.)
        self.assertEqual(a['observed_elevation_deg'],b['observed_elevation_deg'])
        self.assertEqual(a['expected_elevation_deg'],b['expected_elevation_deg'])
        self.assertNotEqual(a['model_floor_z_m'],b['model_floor_z_m'])

    def test_nominal_reference_does_not_modify_observed_bearing(self):
        a=inspect_pixel([313,371],self.models['height_only59'],reference_z_m=2.)
        b=inspect_pixel([313,371],self.models['height_only59'],reference_z_m=3.)
        self.assertEqual(a['observed_elevation_deg'],b['observed_elevation_deg'])
        self.assertNotEqual(a['required_down_rotation_deg'],b['required_down_rotation_deg'])

    def test_no_mutation(self):
        p=copy.deepcopy(self.models['height_only59'])
        original=copy.deepcopy(p)
        inspect_pixel([313,371],p,reference_z_m=2.)
        self.assertEqual(p,original)

    def test_invalid_or_backward_input_rejected(self):
        for d in ([0,0,1],[-1,0,0],[1,float('nan'),0],[1+1j,0,0]):
            with self.assertRaises(ValueError):
                elevation_deg(d)
        with self.assertRaises(ValueError):
            expected_elevation(0,0)
        with self.assertRaises(ValueError):
            inspect_pixel([0,0],self.models['height_only59'],reference_z_m=2.)

    def test_repeatability_lower_bound(self):
        r=repeated_pixel_bound([309,378],[313,371])
        self.assertAlmostEqual(r['separation_px'],np.sqrt(65))
        self.assertAlmostEqual(r['single_projection_minimax_residual_lower_bound_px'],np.sqrt(65)/2)
        self.assertFalse(r['physical_reference_verified'])
        self.assertEqual(repeated_pixel_bound([1,2],[1,2])['separation_px'],0.)

    def test_meridian_cy_pitch_ambiguity_is_exact_in_synthetic_model(self):
        elevations=[-36,-25,-17,0,4,10]
        a=central_equidistant_pixels(elevations,focal_px=175.,cy=339.,pitch_deg=1.)
        b=central_equidistant_pixels(elevations,focal_px=175.,cy=339.+175*np.deg2rad(5),pitch_deg=6.)
        np.testing.assert_allclose(a,b,atol=1e-12,rtol=0)


class SavedBearingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=Path(__file__).resolve().parent/'results_r01'
        cls.provenance=json.loads((cls.folder/'provenance.json').read_text())

    def test_all_positions_frames_hypotheses_retained(self):
        self.assertEqual(len(study.read_csv(self.folder/'floor7_bearings.csv')),7*3)
        self.assertEqual(len(study.read_csv(self.folder/'paper19_all_observations.csv')),1733*9)
        self.assertEqual(len(study.read_csv(self.folder/'cone19_paired_bearings.csv')),299*9)
        self.assertEqual(len(study.read_csv(self.folder/'pixel_sensitivity.csv')),3*3*9)
        self.assertFalse(self.provenance['new_calibration_fit'])
        self.assertFalse(self.provenance['physical_output'])

    def test_frozen_sources_outputs(self):
        for p,digest in self.provenance['source_sha256'].items():
            self.assertEqual(study.sha256(Path(p)),digest,p)
        for name,digest in self.provenance['output_sha256'].items():
            self.assertEqual(study.sha256(self.folder/name),digest,name)

    def test_expected_angles_and_observed_gaps_independently(self):
        for r in study.read_csv(self.folder/'cone19_paired_bearings.csv'):
            offset=float(r['offset_m'])
            floor=float(np.degrees(np.arctan2(-.59,2.)))
            tip=float(np.degrees(np.arctan2(.73-.59,2.+offset)))
            self.assertAlmostEqual(float(r['expected_gap_deg']),tip-floor)
            observed=float(r['tip_observed_elevation_deg'])-float(r['floor_observed_elevation_deg'])
            self.assertAlmostEqual(float(r['observed_gap_deg']),observed)
            self.assertAlmostEqual(float(r['gap_difference_deg']),observed-(tip-floor))
            self.assertEqual(r['usable_for_ffb'],'False')
            self.assertEqual(r['paper_anchor_is_before_after_not_simultaneous'],'True')

    def test_primary_paper_before_after_stable_without_hidden_observations(self):
        rows=study.read_csv(self.folder/'paper19_all_observations.csv')
        selected=[r for r in rows if r['model']=='height_only59' and r['threshold']=='170'
                  and r['phase'] in ('paper_before','paper_after') and r['candidate']=='True']
        self.assertEqual(len(selected),631)
        self.assertEqual({(r['pixel_x'],r['pixel_y']) for r in selected},{('313.0','371.0')})
        hidden=[r for r in rows if r['phase']=='cone_static']
        self.assertTrue(all(not r['observed_elevation_deg'] for r in hidden))

    def test_sensitivity_and_summary_recompute_exactly(self):
        seven,paper,tips,anchor,models,_metadata,_hashes=study.load_inputs()
        summary=study.analyze(seven,paper,tips,anchor,models)[3]
        saved=study.read_csv(self.folder/'angle_gap_summary.csv')
        self.assertEqual(len(summary),len(saved))
        for a,b in zip(summary,saved):
            for k,v in a.items():
                self.assertEqual(str(v),b[k])
        fresh=study.sensitivity(tips,anchor,models)
        saved=study.read_csv(self.folder/'pixel_sensitivity.csv')
        for a,b in zip(fresh,saved):
            for k,v in a.items():
                self.assertEqual(str(v),b[k])

    def test_synthetic_rank_not_claimed_as_real_calibration(self):
        r=json.loads((self.folder/'synthetic_identifiability.json').read_text())
        self.assertEqual(r['synthetic_meridian_jacobian_rank'],1)
        self.assertLess(r['max_pixel_difference'],1e-10)
        self.assertTrue(r['real_full_image_rank_not_evaluated'])
        self.assertFalse(r['new_calibration_fit'])


if __name__=='__main__':
    unittest.main()
