"""Offline angular KB4 diagnostic, continuous across camera Z=0.

For Z>0 this uses the same four angular coefficients as OpenCV fisheye. For
Z<=0 it does NOT use X/Z or OpenCV's hemisphere-clipped undistortion. The
projection domain is explicit and this schema is never auto-applied live.
"""
import math

import cv2
import numpy as np
import scipy
from scipy.optimize import least_squares
from scipy.sparse import coo_matrix

from fisheye_intrinsic_calibration import Board, FRONT_ROI, IMAGE_SIZE, SCREEN
from fisheye_bundle_diagnostic import PixelBundle, checked_views, initial_parameters


def angular_project(camera_points, K, D):
    """Return pixels, d(pixel)/d(camera_xyz), and d(pixel)/d(shared log-f/K/D).

    theta=atan2(sqrt(X^2+Y^2),Z); radial=theta+k1*theta^3+...+k4*theta^9.
    Optical-axis forward limit is explicit; the backward antipode is undefined.
    """
    p=np.asarray(camera_points,float).reshape(-1,3)
    K=np.asarray(K,float);D=np.asarray(D,float).reshape(4)
    if not np.isfinite(p).all() or not np.isfinite(K).all() or not np.isfinite(D).all():
        raise ValueError('finite camera model and points required')
    X,Y,Z=p.T
    rho=np.hypot(X,Y);norm2=np.sum(p*p,axis=1)
    axis=rho<1e-10
    if np.any(norm2<1e-20) or np.any(axis & (Z<=0)):
        raise ValueError('camera centre or backward antipode is not projectable')
    safe=np.maximum(rho,1e-10)
    theta=np.arctan2(rho,Z)
    powers=theta[:,None]**np.array([3,5,7,9])
    radial=theta+powers@D
    slope=1+sum((2*i+1)*D[i-1]*theta**(2*i) for i in range(1,5))
    nx=X/safe;ny=Y/safe
    fx,fy=K[0,0],K[1,1]
    uv=np.column_stack([fx*radial*nx+K[0,2],fy*radial*ny+K[1,2]])
    dtheta=np.column_stack([Z*X/(safe*norm2),Z*Y/(safe*norm2),-rho/norm2])
    dnx=np.column_stack([Y*Y/safe**3,-X*Y/safe**3,np.zeros(len(p))])
    dny=np.column_stack([-X*Y/safe**3,X*X/safe**3,np.zeros(len(p))])
    Jxyz=np.stack([fx*(nx[:,None]*slope[:,None]*dtheta+radial[:,None]*dnx),
                   fy*(ny[:,None]*slope[:,None]*dtheta+radial[:,None]*dny)],axis=1)
    Jxyz[axis]=0.
    Jxyz[axis,0,0]=fx/Z[axis]
    Jxyz[axis,1,1]=fy/Z[axis]
    shared=np.zeros((len(p),2,8))
    shared[:,0,0]=fx*radial*nx;shared[:,1,1]=fy*radial*ny
    shared[:,0,2]=1.;shared[:,1,3]=1.
    shared[:,0,4:8]=fx*nx[:,None]*powers
    shared[:,1,4:8]=fy*ny[:,None]*powers
    return uv,Jxyz,shared,theta


def pose_projection(objects, pose, K, D):
    rvec=pose[:3].reshape(3,1)
    tvec=np.r_[pose[3:5],np.exp(pose[5])]
    R,dR=cv2.Rodrigues(rvec)
    objects=np.asarray(objects).reshape(-1,3)
    camera=objects@R.T+tvec
    uv,Jxyz,shared,theta=angular_project(camera,K,D)
    dC=np.zeros((len(objects),3,6))
    for i in range(3):dC[:,:,i]=objects@dR[i].reshape(3,3).T
    dC[:,0,3]=1.;dC[:,1,4]=1.;dC[:,2,5]=tvec[2]
    Jpose=np.einsum('nij,njk->nik',Jxyz,dC)
    return uv,shared,Jpose,theta,camera,R


class AngularBundle(PixelBundle):
    def evaluate(self,x):
        if self.last_x is not None and np.array_equal(x,self.last_x):return
        K,D=self.camera(x)
        residuals,rr,cc,vv=[],[],[],[]
        width=2*self.count
        for i,points in enumerate(self.points):
            uv,shared,pose,_,_,_=pose_projection(self.objects,x[8+6*i:14+6*i],K,D)
            residuals.append((uv-points).ravel())
            block=np.hstack([shared.reshape(width,8),pose.reshape(width,6)])
            cols=np.r_[np.arange(8),np.arange(8+6*i,14+6*i)]
            rr.append(np.repeat(np.arange(width)+width*i,14))
            cc.append(np.tile(cols,width));vv.append(block.ravel())
        self.last_residual=np.concatenate(residuals)
        if not np.isfinite(self.last_residual).all() or not np.isfinite(np.concatenate(vv)).all():
            raise ValueError('nonfinite angular projection')
        self.last_jacobian=coo_matrix((np.concatenate(vv),(np.concatenate(rr),np.concatenate(cc))),
            shape=(width*len(self.points),self.n)).tocsr()
        self.last_x=np.asarray(x).copy()
        self.trace.append(dict(evaluation=len(self.trace),pixel_rms=float(np.sqrt(np.mean(self.last_residual.reshape(-1,2)**2)*2))))


def scaled_gradient(J,residual):
    if hasattr(J,'toarray'):J=J.toarray()
    norms=np.linalg.norm(J,axis=0)
    return float(np.max(abs(J.T@residual)/np.maximum(norms,1e-12)))


def bounds_for(x):
    lower=np.full_like(x,-np.inf);upper=np.full_like(x,np.inf)
    lower[:4]=[0.,0.,0.,0.];upper[:4]=[math.log(10000.),math.log(10000.),640.,720.]
    lower[13::6]=math.log(1e-6);upper[13::6]=math.log(1000.)
    return lower,upper


def fit_angular_bundle(views,board,initial_K,*,max_nfev=300):
    checked,train,validation,distribution=checked_views(views,board)
    x0,objects,initial_rms=initial_parameters([checked[i] for i in train],board,initial_K)
    bundle=AngularBundle([checked[i] for i in train],objects)
    options=dict(method='trf',x_scale='jac',loss='linear',max_nfev=max_nfev,ftol=1e-9,xtol=1e-9,gtol=1e-9)
    result=least_squares(bundle.residual,x0,jac=bundle.jacobian,bounds=bounds_for(x0),tr_solver='lsmr',
        tr_options=dict(regularize=True,atol=1e-12,btol=1e-12,maxiter=2000),**options)
    K,D=bundle.camera(result.x)
    # Re-evaluate at final x (last trial evaluation need not be the accepted x).
    residual=bundle.residual(result.x)
    J=bundle.jacobian(result.x)
    stationarity=scaled_gradient(J,residual)
    per_view,normals,residual_vectors,poses=[],[],[],[]
    all_angles=[]
    reduced=[]
    width=2*board.count
    for local,i in enumerate(train):
        pose=result.x[8+6*local:14+6*local]
        uv,shared,Jpose,theta,camera,R=pose_projection(objects,pose,K,D)
        error=uv-checked[i]
        Jp=Jpose.reshape(width,6)
        singular=np.linalg.svd(Jp,compute_uv=False)
        condition=float(singular[0]/singular[-1])
        per_view.append(dict(view_index=i,split='train',rms_px=float(np.sqrt(np.mean(np.sum(error**2,axis=1)))),
            minimum_camera_z_m=float(camera[:,2].min()),points_beyond_90=int(np.count_nonzero(theta>math.pi/2)),
            maximum_angle_deg=float(np.degrees(theta.max())),pose_jacobian_condition=condition,pose_stationarity=None))
        q=np.linalg.qr(Jp,mode='reduced')[0]
        shared=shared.reshape(width,8)
        reduced.append(shared-q@(q.T@shared))
        residual_vectors.append(dict(view_index=i,residual_px=error.tolist()))
        normals.append(R[:,2]);all_angles.append(theta)
        poses.append(dict(view_index=i,centred_pose=pose.tolist()))
    validation_success=[]
    for i in validation:
        # Initial pose only: initial K,D=0, not refitting final K,D to validation.
        normalized=cv2.fisheye.undistortPoints(checked[i].reshape(1,-1,2),np.asarray(initial_K,float),np.zeros((4,1)))
        ok,r,t=cv2.solvePnP(objects.reshape(-1,3),normalized.reshape(-1,2),np.eye(3),None,flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok or t[2,0]<=0:raise ValueError('held-out initial pose not solvable')
        p0=np.r_[r.ravel(),t[:2].ravel(),math.log(t[2,0])]
        def fun(p):return (pose_projection(objects,p,K,D)[0]-checked[i]).ravel()
        def jac(p):return pose_projection(objects,p,K,D)[2].reshape(width,6)
        lo=np.full(6,-np.inf);hi=np.full(6,np.inf);lo[5]=math.log(1e-6);hi[5]=math.log(1000.)
        fitted=least_squares(fun,p0,jac=jac,bounds=(lo,hi),**options)
        uv,_,Jp,theta,camera,_=pose_projection(objects,fitted.x,K,D)
        error=uv-checked[i]
        grad=scaled_gradient(Jp.reshape(width,6),error.ravel())
        validation_success.append(bool(fitted.success) and grad<1e-4)
        per_view.append(dict(view_index=i,split='pose_validation_only',rms_px=float(np.sqrt(np.mean(np.sum(error**2,axis=1)))),
            minimum_camera_z_m=float(camera[:,2].min()),points_beyond_90=int(np.count_nonzero(theta>math.pi/2)),
            maximum_angle_deg=float(np.degrees(theta.max())),pose_jacobian_condition=None,pose_stationarity=grad))
        residual_vectors.append(dict(view_index=i,residual_px=error.tolist()))
        poses.append(dict(view_index=i,centred_pose=fitted.x.tolist()))
        all_angles.append(theta)
    train_rms=float(np.sqrt(np.mean([r['rms_px']**2 for r in per_view if r['split']=='train'])))
    val_rms=float(np.sqrt(np.mean([r['rms_px']**2 for r in per_view if r['split']=='pose_validation_only'])))
    spread=max(math.degrees(math.acos(float(np.clip(abs(a@b),0.,1.)))) for a in normals for b in normals)
    theta_max=float(max(a.max() for a in all_angles))
    theta=np.linspace(0.,theta_max,1000)
    derivative=1+sum((2*i+1)*D.ravel()[i-1]*theta**(2*i) for i in range(1,5))
    profile=np.concatenate(reduced)
    profile=profile/np.maximum(np.linalg.norm(profile,axis=0),1e-12)
    profile_singular=np.linalg.svd(profile,compute_uv=False)
    checks=dict(train_rms=train_rms<=SCREEN['train_rms_px'],validation_rms=val_rms<=SCREEN['pose_validation_rms_px'],
        normal_diversity=spread>=SCREEN['normal_spread_deg'],centre_in_selected_lens=0<K[0,2]<640 and 0<K[1,2]<720,
        focal_ratio=.5<=K[0,0]/K[1,1]<=2.,monotonic_in_observed_angle=bool(np.all(derivative>0)),
        optimizer_converged=bool(result.success),stationarity=stationarity<1e-4,
        validation_poses_converged=all(validation_success),angular_domain_no_antipode=theta_max<math.pi-1e-5,
        train_pose_condition_below_1e6=max(r['pose_jacobian_condition'] for r in per_view if r['split']=='train')<1e6,
        intrinsic_profile_full_rank=bool(profile_singular[-1]>1e-8*profile_singular[0]))
    checks={k:bool(v) for k,v in checks.items()}
    return dict(schema='offline_angular_kb4_diagnostic_v1',camera_model='kb4_atan2_angular',
        image_size=list(IMAGE_SIZE),roi_native_xywh=list(FRONT_ROI),selected_lens='front_left',board=vars(board),
        K=K.tolist(),D=D.ravel().tolist(),initial_K=np.asarray(initial_K).tolist(),initial_D=[0.]*4,
        train_indices=train,validation_indices=validation,coverage=distribution,initial_train_rms_px=initial_rms,
        calibration_rms_px=train_rms,pose_validation_rms_px=val_rms,normal_spread_deg=spread,
        observed_max_angle_deg=float(np.degrees(theta_max)),points_beyond_90=sum(r['points_beyond_90'] for r in per_view),
        stationarity_scaled_gradient=stationarity,intrinsic_profile_singular_values=profile_singular.tolist(),
        intrinsic_profile_condition=float(profile_singular[0]/profile_singular[-1]),checks=checks,screen=SCREEN,
        per_view=per_view,per_view_residuals=residual_vectors,centred_poses=poses,
        object_origin_shift_m=board.object_points.reshape(-1,3).mean(axis=0).tolist(),trace=bundle.trace,
        optimizer=dict(method='scipy_trf_joint_angular',loss='linear',status=int(result.status),success=bool(result.success),
            message=str(result.message),nfev=int(result.nfev),njev=int(result.njev),optimality=float(result.optimality),max_nfev=max_nfev),
        all_views_retained=True,robust_loss_used=False,pose_validation_refits_intrinsics=False,
        scipy_version=scipy.__version__,opencv_version=cv2.__version__,
        decision='ANGULAR_DIAGNOSTIC_CANDIDATE_ONLY' if all(checks.values()) else 'REJECTED_ANGULAR_DIAGNOSTIC',
        direct_opencv_full_fov_undistort_compatible=False,physical_lens_fov_independently_measured=False,
        usable_for_ffb=False,physical_floor_distance_verified=False,camera_to_floor_extrinsics_measured=False)
