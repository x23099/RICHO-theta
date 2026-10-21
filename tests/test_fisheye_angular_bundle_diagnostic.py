import unittest

import cv2
import numpy as np

try:
    import scipy
except ModuleNotFoundError as error:
    if error.name != 'scipy':
        raise
    raise unittest.SkipTest('Optional offline angular fisheye diagnostic requires SciPy') from error

from fisheye_intrinsic_calibration import Board,partition_views
from fisheye_bundle_diagnostic import PixelBundle
from fisheye_angular_bundle_diagnostic import angular_project,AngularBundle,pose_projection,fit_angular_bundle
from test_fisheye_bundle_diagnostic import bundle_synthetic_views


class AngularTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cv2.setNumThreads(1)

    def test_matches_opencv_on_positive_Z(self):
        points=np.array([[.1,.2,1.],[-.5,.4,.01],[0.,0.,1.]])
        K=np.array([[190.,0.,320.],[0.,192.,310.],[0.,0.,1.]])
        D=np.array([.01,-.003,.001,-.0001])
        own=angular_project(points,K,D)[0]
        reference=cv2.fisheye.projectPoints(points.reshape(1,-1,3),np.zeros(3),np.zeros(3),K,D)[0]
        np.testing.assert_allclose(own,reference.reshape(-1,2),atol=1e-10)

    def test_continuous_across_Z_zero_and_derivative_matches(self):
        K=np.array([[190.,0.,320.],[0.,192.,310.],[0.,0.,1.]])
        D=np.array([.01,-.003,.001,-.0001])
        p=np.array([[.5,.05,1e-8],[.5,.05,0.],[.5,.05,-1e-8],[0.,0.,1.]])
        uv,J,_,theta=angular_project(p,K,D)
        self.assertLess(np.linalg.norm(uv[0]-uv[2]),1e-4)
        self.assertGreater(theta[2],np.pi/2)
        for k in range(3):
            plus=p.copy();plus[:,k]+=1e-6
            minus=p.copy();minus[:,k]-=1e-6
            numerical=(angular_project(plus,K,D)[0]-angular_project(minus,K,D)[0])/(2e-6)
            np.testing.assert_allclose(J[:,:,k],numerical,atol=1e-5,rtol=1e-5)
        with self.assertRaises(ValueError):angular_project([[0,0,-1]],K,D)

    def test_full_joint_jacobian_for_wide_angle_pose(self):
        board=Board(square_mm=40)
        objects=board.object_points-board.object_points.mean(axis=1,keepdims=True)
        pose=np.array([0.,1.1,0.,.5,0.,np.log(.08)])
        K=np.array([[180.,0.,320.],[0.,182.,310.],[0.,0.,1.]])
        D=np.array([.01,-.003,.001,-.0001])
        uv,_,_,theta,_,_=pose_projection(objects,pose,K,D)
        self.assertGreater(theta.max(),np.pi/2)
        x=np.concatenate([np.log([180.,182.]),[320.,310.],D,pose])
        bundle=AngularBundle([uv],objects)
        analytic=bundle.jacobian(x).toarray()
        for k in range(len(x)):
            plus=x.copy();plus[k]+=1e-6
            minus=x.copy();minus[k]-=1e-6
            numerical=(bundle.residual(plus)-bundle.residual(minus))/(2e-6)
            np.testing.assert_allclose(analytic[:,k],numerical,atol=1e-5,rtol=1e-5)

    def test_synthetic_recovery_and_no_validation_K_D_leak(self):
        board,K,D,views=bundle_synthetic_views()
        a=fit_angular_bundle(views,board,K,max_nfev=150)
        np.testing.assert_allclose(a['K'],K,atol=2e-3)
        np.testing.assert_allclose(a['D'],D,atol=2e-3)
        self.assertTrue(a['checks']['stationarity'])
        self.assertLess(a['pose_validation_rms_px'],1e-3)
        changed=[p.copy() for p in views]
        for i in partition_views(views)[1]:changed[i]+=[.2,-.2]
        b=fit_angular_bundle(changed,board,K,max_nfev=150)
        np.testing.assert_array_equal(a['K'],b['K'])
        np.testing.assert_array_equal(a['D'],b['D'])
        self.assertFalse(a['usable_for_ffb'])
        self.assertFalse(a['direct_opencv_full_fov_undistort_compatible'])


if __name__=='__main__':unittest.main()
