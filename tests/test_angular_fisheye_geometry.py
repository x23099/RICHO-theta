import unittest

import numpy as np

from angular_fisheye_geometry import AngularCamera,camera_from_candidate,unproject,project,floor_from_rays,segment_from_rays


class AngularGeometryTests(unittest.TestCase):
    def setUp(self):
        self.camera=AngularCamera([[190,0,320],[0,192,311],[0,0,1]],[-.04,.035,-.014,.001],np.deg2rad(100.))
        self.T=np.eye(4)
        self.T[:3,:3]=[[0,0,1],[-1,0,0],[0,-1,0]]
        self.T[2,3]=.59

    def test_roundtrip_across_90_degrees_preserves_order(self):
        angles=np.deg2rad([0,10,70,89,90,95,99])
        rays=np.column_stack((np.sin(angles),np.zeros(len(angles)),np.cos(angles)))
        pixels,valid=project(rays,self.camera)
        self.assertTrue(valid.all())
        recovered,valid=unproject(pixels,self.camera,image_size=(1280,720))
        self.assertTrue(valid.all())
        np.testing.assert_allclose(recovered,rays,atol=1e-12)
        np.testing.assert_allclose(np.linalg.norm(recovered,axis=1),1,atol=1e-12)

    def test_optical_centre_limit(self):
        ray,ok=unproject([[320,311]],self.camera,image_size=(1280,720))
        self.assertTrue(ok[0]);np.testing.assert_array_equal(ray,[[0,0,1]])

    def test_invalid_roi_domain_and_image_size(self):
        rays,valid=unproject([[1000,300],[639,710],[-1,300]],self.camera,image_size=(1280,720))
        self.assertFalse(valid.any());self.assertTrue(np.isnan(rays).all())
        with self.assertRaises(ValueError):unproject([[320,311]],self.camera,image_size=(640,360))
        with self.assertRaises(ValueError):unproject([[np.nan,300]],self.camera,image_size=(1280,720))

    def test_nonmonotonic_and_invalid_camera_refused(self):
        with self.assertRaises(ValueError):AngularCamera(self.camera.K,[-1,0,0,0],1.)
        with self.assertRaises(ValueError):AngularCamera(self.camera.K,[0,0,0,0],np.pi)
        zero=AngularCamera(self.camera.K,[0,0,0,0],1.)
        self.assertEqual(zero.radial(.5),.5)

    def test_input_calibration_copied_and_readonly(self):
        K=self.camera.K.copy();D=self.camera.D.copy()
        c=AngularCamera(K,D,self.camera.max_theta_rad)
        K[0,0]=1.;D[0]=2.
        self.assertEqual(c.K[0,0],190.)
        with self.assertRaises(ValueError):c.K[0,0]=1.

    def test_synthetic_floor_coordinates_restore_with_subpixel_precision(self):
        world=np.array([[.8,0,0],[1.3,.4,0],[2.,-.4,0]])
        optical=(world-self.T[:3,3])@self.T[:3,:3]
        pixels,ok=project(optical,self.camera)
        rays,valid=unproject(pixels,self.camera,image_size=(1280,720))
        recovered,valid=floor_from_rays(rays,valid,self.T)
        self.assertTrue(valid.all());np.testing.assert_allclose(recovered,world,atol=1e-12)

    def test_grazing_or_upward_rays_not_forced_to_floor(self):
        rays=np.array([[0,0,1],[0,-1,0],[0,1,0]])
        points,valid=floor_from_rays(rays,np.ones(3,bool),self.T)
        np.testing.assert_array_equal(valid,[False,False,True])
        self.assertTrue(np.isnan(points[:2]).all())

    def test_known_segment_recovers_positive_depth_and_base_height(self):
        world=np.array([[2.,0,.73],[2.,0,0.]])
        optical=(world-self.T[:3,3])@self.T[:3,:3]
        optical/=np.linalg.norm(optical,axis=1)[:,None]
        result=segment_from_rays(optical,self.T)
        self.assertTrue(result['estimated'])
        np.testing.assert_allclose(result['base_target_m'],world[1],atol=1e-12)
        self.assertLess(result['residual_m'],1e-12)
        self.assertFalse(result['usable_for_ffb'])

    def test_known_offset_is_not_implicitly_subtracted_from_reference(self):
        world=np.array([[2.1875,0,.73],[2.,0,0.]])
        optical=(world-self.T[:3,3])@self.T[:3,:3]
        optical/=np.linalg.norm(optical,axis=1)[:,None]
        result=segment_from_rays(optical,self.T,tip_forward_offset_m=.1875)
        np.testing.assert_allclose(result['base_target_m'],world[1],atol=1e-12)

    def test_candidate_schema_must_be_explicit(self):
        with self.assertRaises(ValueError):camera_from_candidate({'camera_model':'opencv_fisheye_4coef'})

    def test_empty_and_duplicate_pixels(self):
        rays,valid=unproject([],self.camera,image_size=(1280,720))
        self.assertEqual(rays.shape,(0,3))
        rays,valid=unproject([[320.25,380.75]]*2,self.camera,image_size=(1280,720))
        np.testing.assert_array_equal(rays[0],rays[1])


if __name__=='__main__':unittest.main()
