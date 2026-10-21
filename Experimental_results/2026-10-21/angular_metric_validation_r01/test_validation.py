import unittest
try:
    import scipy
except ModuleNotFoundError as error:
    raise unittest.SkipTest('Optional offline TF study requires SciPy') from error

import cv2
import numpy as np

from run import fit_floor_rotation,FIT_IDS
from angular_fisheye_geometry import AngularCamera,project


class RotationFitTests(unittest.TestCase):
    def test_fit_recovers_rotation_only_and_fixed_height(self):
        camera=AngularCamera([[190,0,320],[0,192,311],[0,0,1]],[-.04,.035,-.014,.001],np.deg2rad(100))
        nominal=np.eye(4);nominal[:3,:3]=[[0,0,1],[-1,0,0],[0,-1,0]];nominal[2,3]=.59
        true=nominal.copy();true[:3,:3]=cv2.Rodrigues(np.array([.02,-.01,.03]))[0]@nominal[:3,:3]
        world=np.array([[.8,0,0],[1.3,0,0],[2,0,0],[1.3,.4,0],[1.3,-.4,0]])
        uv,valid=project((world-true[:3,3])@true[:3,:3],camera)
        fitted,info=fit_floor_rotation(uv,world,camera,nominal)
        np.testing.assert_allclose(fitted,true,atol=1e-9)
        np.testing.assert_array_equal(fitted[:3,3],nominal[:3,3])
        self.assertEqual(info['numerical_rank'],3)
        self.assertFalse(info['intrinsics_refitted'])

    def test_only_documented_fit_ids(self):
        self.assertEqual(FIT_IDS,('C080','C130','C200','L130','R130'))
        self.assertFalse(set(FIT_IDS)&{'H100','H160','paper_cone_2m'})


if __name__=='__main__':unittest.main()
