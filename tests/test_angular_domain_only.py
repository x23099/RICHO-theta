"""Exact domain-only refactor vs original cf747b78 unproject equations."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from angular_fisheye_geometry import AngularCamera,pixels_in_domain,unproject
from cone_distance_core import load_config


def frozen_unproject(pixels,camera):
    # Numeric body from pre-refactor angular_fisheye_geometry.py SHA256
    # cf747b786e3f204a86b347cacd3bfed6864b30b0262a20599d029053bdb4d2b8.
    p=np.asarray(pixels,float)
    if p.shape in ((0,),(0,2)):p=np.empty((0,2))
    norm=(p-camera.K[:2,2])/[camera.K[0,0],camera.K[1,1]]
    radius=np.linalg.norm(norm,axis=1)
    x,y,w,h=camera.roi_xywh
    valid=(p[:,0]>=x)&(p[:,0]<x+w)&(p[:,1]>=y)&(p[:,1]<y+h)&(radius<=camera.radial(camera.max_theta_rad))
    rays=np.full((len(p),3),np.nan)
    lo=np.zeros(np.count_nonzero(valid));hi=np.full_like(lo,camera.max_theta_rad)
    target=radius[valid]
    for _ in range(64):
        mid=(lo+hi)/2
        below=camera.radial(mid)<target
        lo=np.where(below,mid,lo);hi=np.where(below,hi,mid)
    theta=(lo+hi)/2
    scale=np.divide(np.sin(theta),target,out=np.ones_like(theta),where=target!=0)
    rays[valid,:2]=norm[valid]*scale[:,None];rays[valid,2]=np.cos(theta)
    return rays,valid


class AngularDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cameras=[load_config()[1],AngularCamera([[190,0,320],[0,192,311],[0,0,1]],
            [-.04,.035,-.014,.001],np.deg2rad(100.))]

    def exact(self,pixels,camera):
        expected,valid=frozen_unproject(pixels,camera)
        rays,actual=unproject(pixels,camera,image_size=(1280,720))
        domain=pixels_in_domain(pixels,camera,image_size=(1280,720))
        np.testing.assert_array_equal(actual,valid);np.testing.assert_array_equal(domain,valid)
        np.testing.assert_array_equal(rays.view(np.uint64),expected.view(np.uint64))

    def test_random_pixels_bit_exact_for_both_cameras(self):
        pixels=np.random.default_rng(1234).uniform([-200,-200],[1500,900],(4096,2))
        for camera in self.cameras:self.exact(pixels,camera)

    def test_roi_centre_and_subpixel_edges_bit_exact(self):
        for camera in self.cameras:
            self.exact([[camera.K[0,2],camera.K[1,2]],[0,0],[639,719],[640,300],[1280,720],
                [-np.finfo(float).eps,300],[639.999999,719.999999],[300,-1],[300,720]],camera)

    def test_max_radial_domain_and_nextafter_neighbours_bit_exact(self):
        for camera in self.cameras:
            radius=float(camera.radial(camera.max_theta_rad));points=[]
            for value in (np.nextafter(radius,0),radius,np.nextafter(radius,np.inf)):
                for angle in np.linspace(0,2*np.pi,17):
                    points.append(camera.K[:2,2]+[camera.K[0,0]*value*np.cos(angle),camera.K[1,1]*value*np.sin(angle)])
            self.exact(points,camera)

    def test_empty_duplicate_and_integer_arrays_bit_exact(self):
        for pixels in ([],np.empty((0,2)),[[320.25,380.75]]*5,np.array([[0,0],[320,400],[640,400]],np.int32)):
            self.exact(pixels,self.cameras[0])

    def test_invalid_inputs_keep_exception_type_for_both_apis(self):
        for pixels in ([[np.nan,1]],[[np.inf,1]],[[1+1j,2]],[1,2],[[1,2,3]],np.zeros((1,1,2))):
            for operation in (pixels_in_domain,unproject):
                with self.subTest(pixels=repr(pixels)),self.assertRaises(ValueError):
                    operation(pixels,self.cameras[0],image_size=(1280,720))

    def test_wrong_camera_and_image_size_rejected(self):
        for operation in (pixels_in_domain,unproject):
            with self.assertRaises(ValueError):operation([[320,400]],None,image_size=(1280,720))
            with self.assertRaises(ValueError):operation([[320,400]],self.cameras[0],image_size=(640,360))

    def test_domain_only_does_not_run_inverse_solver(self):
        original=AngularCamera.radial
        with patch.object(AngularCamera,'radial',autospec=True,side_effect=original) as radial:
            pixels_in_domain([[320,400]],self.cameras[0],image_size=(1280,720))
            self.assertEqual(radial.call_count,1)
        with patch.object(AngularCamera,'radial',autospec=True,side_effect=original) as radial:
            unproject([[320,400]],self.cameras[0],image_size=(1280,720))
            self.assertEqual(radial.call_count,65)

    def test_no_mutation_or_cross_call_mask_alias(self):
        camera=self.cameras[0];pixels=np.array([[320.,400.],[1000.,300.]])
        before=pixels.copy(),camera.K.copy(),camera.D.copy()
        first=pixels_in_domain(pixels,camera,image_size=(1280,720));expected=first.copy();first[:]=False
        np.testing.assert_array_equal(pixels_in_domain(pixels,camera,image_size=(1280,720)),expected)
        for actual,old in zip((pixels,camera.K,camera.D),before):np.testing.assert_array_equal(actual,old)


if __name__=='__main__':unittest.main()
