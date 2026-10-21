"""Explicit native angular-KB4 rays and conditional floor/segment geometry.

NumPy only: no ROS, hardware, GPU, OpenCV undistortion or auto configuration.
Coordinates: optical x-right/y-down/z-axis; supplied target x-forward/y-left/z-up.
"""
from dataclasses import dataclass
import math

import numpy as np

from fisheye_floor_geometry import checked_transform


@dataclass(frozen=True)
class AngularCamera:
    K: object
    D: object
    max_theta_rad: float
    image_size: tuple = (1280,720)
    roi_xywh: tuple = (0,0,640,720)

    def __post_init__(self):
        if np.iscomplexobj(self.K) or np.iscomplexobj(self.D):
            raise ValueError('real calibration required')
        K=np.array(self.K,float,copy=True);D=np.array(self.D,float,copy=True)
        if (K.shape!=(3,3) or D.shape!=(4,) or not np.isfinite(K).all() or not np.isfinite(D).all()
            or not np.array_equal(K[2],[0,0,1]) or K[0,1]!=0 or K[1,0]!=0 or min(K[0,0],K[1,1])<=0
            or isinstance(self.max_theta_rad,(bool,np.bool_)) or not math.isfinite(self.max_theta_rad)
            or not 0<self.max_theta_rad<math.pi-1e-5):
            raise ValueError('finite zero-skew K, four coefficients and explicit angular domain required')
        if (self.image_size!=(1280,720) or self.roi_xywh!=(0,0,640,720)
            or not 0<K[0,2]<640 or not 0<K[1,2]<720):
            raise ValueError('native1280x720 front-left coordinate contract required')
        # Exact extrema of g'(theta) on [0,max_theta], not sampled monotonicity.
        polynomial=np.array([9*D[3],7*D[2],5*D[1],3*D[0],1.])
        stationary=np.roots(np.polyder(np.trim_zeros(polynomial,'f')))
        values=[0.,self.max_theta_rad**2]
        values.extend(float(r.real) for r in stationary if abs(r.imag)<1e-10 and 0<r.real<self.max_theta_rad**2)
        if min(np.polyval(polynomial,values))<=0:
            raise ValueError('angular radial map is not strictly monotonic on declared domain')
        K.setflags(write=False);D.setflags(write=False)
        object.__setattr__(self,'K',K);object.__setattr__(self,'D',D)

    def radial(self,theta):
        theta=np.asarray(theta,float)
        return theta+sum(d*theta**(2*i+3) for i,d in enumerate(self.D))


def camera_from_candidate(data):
    if (data.get('schema')!='offline_angular_kb4_diagnostic_v1' or data.get('camera_model')!='kb4_atan2_angular'
        or data.get('selected_lens')!='front_left' or not data.get('checks')
        or not all(data['checks'].values()) or data.get('image_size')!=[1280,720]
        or data.get('roi_native_xywh')!=[0,0,640,720]):
        raise ValueError('screened offline native angular candidate required; no implicit legacy fallback')
    return AngularCamera(data['K'],data['D'],math.radians(data['observed_max_angle_deg']))


def unproject(pixels,camera,*,image_size):
    if not isinstance(camera,AngularCamera) or image_size!=camera.image_size or np.iscomplexobj(pixels):
        raise ValueError('matching native image size, angular camera and real pixels required')
    p=np.asarray(pixels,float)
    if p.shape in ((0,),(0,2)):p=np.empty((0,2))
    if p.ndim!=2 or p.shape[1]!=2 or not np.isfinite(p).all():
        raise ValueError('finite Nx2 native pixels required')
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
    rays[valid,:2]=norm[valid]*scale[:,None]
    rays[valid,2]=np.cos(theta)
    return rays,valid


def project(camera_points,camera):
    if not isinstance(camera,AngularCamera) or np.iscomplexobj(camera_points):
        raise ValueError('real camera points and angular camera required')
    p=np.asarray(camera_points,float)
    if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all():
        raise ValueError('finite Nx3 camera points required')
    rho=np.hypot(p[:,0],p[:,1]);length=np.linalg.norm(p,axis=1)
    theta=np.arctan2(rho,p[:,2])
    valid=(length>1e-12)&(theta<=camera.max_theta_rad)
    scale=np.divide(camera.radial(theta),rho,out=np.zeros_like(rho),where=rho!=0)
    uv=p[:,:2]*scale[:,None]*[camera.K[0,0],camera.K[1,1]]+camera.K[:2,2]
    uv[~valid]=np.nan
    return uv,valid


def floor_from_rays(rays,valid,target_from_optical,*,min_incidence_cos=.03):
    T=checked_transform(target_from_optical)
    rays=np.asarray(rays,float);valid=np.asarray(valid,bool)
    if (rays.ndim!=2 or rays.shape[1]!=3 or valid.shape!=(len(rays),) or T[2,3]<=0
        or not math.isfinite(min_incidence_cos) or not 0<min_incidence_cos<1
        or not np.isfinite(rays[valid]).all()
        or not np.allclose(np.linalg.norm(rays[valid],axis=1),1.,atol=1e-10)):
        raise ValueError('valid unit rays, above-floor transform and incidence in (0,1) required')
    direction=rays@T[:3,:3].T
    accepted=valid&(direction[:,2]<-min_incidence_cos)
    points=np.full_like(rays,np.nan)
    scales=-T[2,3]/direction[accepted,2]
    points[accepted]=T[:3,3]+scales[:,None]*direction[accepted]
    return points,accepted


def segment_from_rays(optical_rays,target_from_optical,*,height_m=.73,tip_forward_offset_m=0.):
    T=checked_transform(target_from_optical)
    p=np.asarray(optical_rays,float)
    if (p.shape!=(2,3) or not np.isfinite(p).all() or not np.allclose(np.linalg.norm(p,axis=1),1.,atol=1e-10)
        or not math.isfinite(height_m) or height_m<=0 or not math.isfinite(tip_forward_offset_m) or tip_forward_offset_m<0):
        raise ValueError('two unit tip/base rays and positive known height required')
    direction=p@T[:3,:3].T
    A=np.column_stack((direction[0],-direction[1]))
    scales,_,rank,singular=np.linalg.lstsq(A,[tip_forward_offset_m,0.,height_m],rcond=None)
    condition=float(singular[0]/singular[-1]) if singular[-1]>0 else float('inf')
    angle=float(np.degrees(np.arccos(np.clip(direction[0]@direction[1],-1,1))))
    residual=float(np.linalg.norm(A@scales-[tip_forward_offset_m,0.,height_m]))
    estimated=rank==2 and condition<=1e6 and angle>=.1 and bool(np.all(scales>0))
    points=direction*scales[:,None]+T[:3,3]
    estimated=estimated and bool(np.all(points[:,0]>0))
    return dict(estimated=estimated,tip_target_m=points[0].tolist() if estimated else None,
        base_target_m=points[1].tolist() if estimated else None,residual_m=residual,condition_number=condition,
        ray_angle_deg=angle,segment_consistent=residual<=.02,physical_endpoint_correspondence_verified=False,usable_for_ffb=False)
