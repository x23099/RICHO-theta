import copy
import sys
from pathlib import Path
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/"src"))
from geometry_models import (BOUNDS, CHECK_IDS, FIT_IDS, FAMILIES, arrays,
    fit_model, partition, project_floor_to_pixels, project_pixels_to_floor)

P = dict(camera_height=.59,pitch_deg=1.,roll_deg=2.,yaw_deg=0.,radius_scale=.86,
         front_cx_offset=-80.,front_cy_offset=-21.,back_cx_offset=82.,back_cy_offset=-18.)
POINTS = dict(C080=(0,.8),C130=(0,1.3),C200=(0,2.),L130=(-.4,1.3),R130=(.4,1.3),H100=(0,1.),H160=(0,1.6))


def synthetic(p):
    pixels = project_floor_to_pixels(list(POINTS.values()),p)
    return [dict(point_id=key,reference_x_m=x,reference_z_m=z,pixel_x=u,pixel_y=v,
                 role="diagnostic" if key in FIT_IDS else "held_out_from_future_fit")
            for (key,(x,z)),(u,v) in zip(POINTS.items(),pixels)]


class GeometryCandidateTests(unittest.TestCase):
    def test_forward_inverse_round_trip(self):
        for parameters in (P,dict(P,front_cx_offset=-95,front_cy_offset=-28,yaw_deg=3,pitch_deg=-2,roll_deg=5)):
            world = np.array(list(POINTS.values()))
            pixels = project_floor_to_pixels(world,parameters)
            np.testing.assert_allclose(project_pixels_to_floor(pixels,parameters),world,atol=1e-12,rtol=0)

    def test_forward_zero_rotation_analytic(self):
        p=dict(P,yaw_deg=0,pitch_deg=0,roll_deg=0)
        pixel=project_floor_to_pixels([[0,1.3]],p)[0]
        np.testing.assert_allclose(pixel,[320,339+275.2*np.arctan(.59/1.3)/(np.pi/2)],atol=1e-12,rtol=0)

    def test_right_positive_x(self):
        p=dict(P,yaw_deg=0,pitch_deg=0,roll_deg=0)
        a=project_floor_to_pixels([[-.4,1.3],[0,1.3],[.4,1.3]],p)
        self.assertTrue(a[0,0]<a[1,0]<a[2,0])

    def test_invalid_native_pixels_rejected_not_dropped(self):
        for pixels in ([[320,200]],[[0,0]],[[1280,450]],[[320,720]],[[float('nan'),440]],[],[[318,440],[0,0]]):
            with self.subTest(pixels=pixels),self.assertRaises(ValueError):
                project_pixels_to_floor(pixels,P)

    def test_invalid_forward_geometry(self):
        for points in ([],[[0,0]],[[float('inf'),1]],[[0]],[[0,-1]]):
            with self.subTest(points=points),self.assertRaises(ValueError):
                project_floor_to_pixels(points,P)
        for changes in (dict(camera_height=0),dict(radius_scale=-1),dict(pitch_deg=float('nan'))):
            with self.assertRaises(ValueError):project_floor_to_pixels([[0,1]],dict(P,**changes))

    def test_recover_synthetic_centre_only(self):
        true=dict(P,front_cx_offset=-92.,front_cy_offset=-26.)
        train,_=partition(synthetic(true))
        result=fit_model(train,P,"centre2")
        self.assertAlmostEqual(result['parameters']['front_cx_offset'],-92.,places=7)
        self.assertAlmostEqual(result['parameters']['front_cy_offset'],-26.,places=7)
        self.assertEqual(result['normalized_jacobian_rank'],2)
        self.assertLess(result['pixel_sse'],1e-16)

    def test_holdouts_do_not_change_fit(self):
        all_rows=synthetic(dict(P,front_cx_offset=-92.,front_cy_offset=-26.))
        train,_=partition(all_rows)
        first=fit_model(train,P,"centre2")
        for row in all_rows:
            if row['point_id'] in CHECK_IDS:
                row.update(pixel_x=-10000,reference_z_m=999999)
        other,_=partition(all_rows)
        second=fit_model(other,P,"centre2")
        self.assertEqual(first['parameters'],second['parameters'])
        self.assertEqual(first['pixel_sse'],second['pixel_sse'])

    def test_holdout_and_duplicate_never_fit(self):
        rows=synthetic(P)
        with self.assertRaises(ValueError):fit_model(rows,P,"centre2")
        train,_=partition(rows)
        with self.assertRaises(ValueError):fit_model(train+[train[0]],P,"centre2")
        train[0]['role']='held_out_from_future_fit'
        with self.assertRaises(ValueError):fit_model(train,P,"centre2")

    def test_role_mapping_is_fixed(self):
        rows=synthetic(P)
        rows[-1]['role']='diagnostic'
        with self.assertRaises(ValueError):partition(rows)
        with self.assertRaises(ValueError):partition(rows[:-1])

    def test_height_fixed_and_inputs_immutable(self):
        train,_=partition(synthetic(P))
        before=copy.deepcopy((train,P))
        result=fit_model(train,P,"centre2")
        self.assertEqual((train,P),before)
        self.assertEqual(result['parameters']['camera_height'],.59)
        self.assertTrue(result['offline_only'])
        self.assertFalse(result['physical_output_authorized'])
        self.assertFalse(result['usable_for_ffb'])
        with self.assertRaises(ValueError):fit_model(train,dict(P,camera_height=.58),"centre2")

    def test_family_and_bounds_guards(self):
        train,_=partition(synthetic(P))
        with self.assertRaises(ValueError):fit_model(train,P,"unknown")
        with self.assertRaises(ValueError):fit_model(train,dict(P,front_cx_offset=-200),"centre2")
        for family,names in FAMILIES.items():
            self.assertNotIn('camera_height',names)
            self.assertTrue(all(name in BOUNDS for name in names))

    def test_recover_radius_synthetic_without_new_distortion_terms(self):
        true=dict(P,front_cx_offset=-90.,front_cy_offset=-23.,radius_scale=.88)
        train,_=partition(synthetic(true))
        result=fit_model(train,P,"centre_radius3")
        self.assertAlmostEqual(result['parameters']['radius_scale'],.88,places=7)
        self.assertLess(result['pixel_sse'],1e-14)


if __name__=='__main__':unittest.main()
