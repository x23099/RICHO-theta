import unittest
from unittest.mock import patch

import cv2
import numpy as np

from fisheye_intrinsic_calibration import Board, partition_views, checked_corners, corner_rms
from fisheye_bundle_diagnostic import PixelBundle, checked_views, grid_audit, fit_bundle
from test_fisheye_intrinsic_calibration import synthetic_views


def bundle_synthetic_views():
    board=Board(square_mm=40.)
    K=np.array([[210.,0.,320.],[0.,212.,300.],[0.,0.,1.]])
    D=np.array([.02,-.01,.001,-.0002])
    rng=np.random.default_rng(20261021)
    views=[]
    centre=board.object_points.reshape(-1,3).mean(axis=0)
    for _ in range(2000):
        rvec=rng.uniform([-.6,-.6,-.3],[.6,.6,.3])
        rotation=cv2.Rodrigues(rvec)[0]
        position=rng.uniform([-.7,-.65,.35],[.7,.65,.8])
        tvec=position-rotation@centre
        if np.any((board.object_points.reshape(-1,3)@rotation.T+tvec)[:,2]<=0):continue
        p=cv2.fisheye.projectPoints(board.object_points,rvec,tvec,K,D)[0].reshape(-1,2)
        try:checked_corners(p,board)
        except ValueError:continue
        if grid_audit(p,board)['median_adjacent_spacing_px']<8:continue
        if all(corner_rms(p,old)>=12 for old in views):views.append(p)
        if len(views)==40:break
    if len(views)!=40:raise AssertionError('synthetic complete view count insufficient')
    return board,K,D,views


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)

    def test_analytic_sparse_jacobian_matches_central_difference(self):
        board=Board(square_mm=20)
        objects=board.object_points-board.object_points.mean(axis=1,keepdims=True)
        K=np.array([[210.,0.,320.],[0.,215.,300.],[0.,0.,1.]])
        D=np.array([.02,-.01,.001,-.0001])
        poses=[np.array([.1,-.2,.03,.1,-.05,np.log(.7)]),np.array([-.2,.15,-.04,-.1,.05,np.log(.8)])]
        x=np.concatenate([np.log([210.,215.]),np.array([320.,300.]),D,*poses])
        points=[]
        for p in poses:
            image=cv2.fisheye.projectPoints(objects,p[:3],np.r_[p[3:5],np.exp(p[5])],K,D)[0]
            points.append(image.reshape(-1,2))
        bundle=PixelBundle(points,objects)
        analytic=bundle.jacobian(x).toarray()
        numeric=np.empty_like(analytic)
        for i in range(len(x)):
            delta=1e-6
            plus=x.copy();plus[i]+=delta
            minus=x.copy();minus[i]-=delta
            numeric[:,i]=(bundle.residual(plus)-bundle.residual(minus))/(2*delta)
        np.testing.assert_allclose(analytic,numeric,atol=1e-6,rtol=1e-5)

    def test_folded_grid_is_flagged(self):
        board=Board(square_mm=20)
        grid=np.mgrid[0:9,0:6].T.reshape(-1,2)*20+[100,200]
        self.assertTrue(grid_audit(grid,board)['cell_orientation_consistent'])
        grid=grid.copy();grid[[1,2]]=grid[[2,1]]
        self.assertFalse(grid_audit(grid,board)['cell_orientation_consistent'])

    def test_insufficient_and_duplicate_inputs_do_not_optimize(self):
        board,_,_,views=synthetic_views()
        with patch('fisheye_bundle_diagnostic.least_squares') as solver:
            with self.assertRaises(ValueError):checked_views(views[:19],board)
            with self.assertRaises(ValueError):checked_views([views[0]]*20,board)
        solver.assert_not_called()

    def test_synthetic_recovery_and_validation_does_not_refit_K_D(self):
        board,K,D,views=bundle_synthetic_views()
        result=fit_bundle(views,board,K,max_nfev=150)
        self.assertTrue(result['optimizer']['success'],result['optimizer'])
        np.testing.assert_allclose(result['K'],K,atol=2e-3)
        np.testing.assert_allclose(result['D'],D,atol=2e-3)
        self.assertLess(result['pose_validation_rms_px'],1e-3)
        changed=[p.copy() for p in views]
        for i in partition_views(views)[1]:changed[i]+=[.2,-.2]
        other=fit_bundle(changed,board,K,max_nfev=150)
        np.testing.assert_array_equal(result['K'],other['K'])
        np.testing.assert_array_equal(result['D'],other['D'])
        self.assertFalse(result['pose_validation_refits_intrinsics'])
        self.assertFalse(result['usable_for_ffb'])
        self.assertTrue(result['all_views_retained'])


if __name__=='__main__':
    unittest.main()
