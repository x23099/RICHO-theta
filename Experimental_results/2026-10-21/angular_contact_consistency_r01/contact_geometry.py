"""Observed angular-ray support selection and floor/height consistency only."""
import numpy as np
from fisheye_floor_geometry import checked_transform
from angular_fisheye_geometry import floor_from_rays


def central_support(points):
    p=np.asarray(points,float)
    if (p.ndim!=2 or p.shape[1]!=2 or not len(p) or not np.isfinite(p).all()
        or not np.equal(p,np.rint(p)).all() or np.any(np.diff(p[:,0])<=0)):
        raise ValueError('ordered actual integer native support required')
    lo,hi=p[0,0],p[-1,0]
    return (p[:,0]>=lo+.1*(hi-lo))&(p[:,0]<=hi-.1*(hi-lo))


def choose_observed_root(points,rays,valid,tip_ray,T,*,offset_m=0.,height_m=.73):
    p=np.asarray(points,float);r=np.asarray(rays,float);v=np.asarray(valid,bool)
    tip=np.asarray(tip_ray,float);T=checked_transform(T)
    inside=central_support(p)
    if (r.shape!=(len(p),3) or v.shape!=(len(p),) or tip.shape!=(3,) or not np.isfinite(tip).all()
        or not np.isfinite(r[v]).all() or not np.allclose(np.linalg.norm(r[v],axis=1),1,atol=1e-10)
        or not np.isclose(np.linalg.norm(tip),1,atol=1e-10)
        or not np.isfinite(offset_m) or offset_m<0 or not np.isfinite(height_m) or height_m<=0):
        raise ValueError('unit rays, finite positive height and nonnegative offset required')
    result=dict(selected=False,reason='insufficient_observed_support',index=None,root_groups=0,
        support_columns=int(inside.sum()),plane_angle_deg=None,physical_contact_verified=False,usable_for_ffb=False)
    if inside.sum()<8 or np.ptp(p[inside,0])<6:return result
    normal=np.cross(tip,T[:3,:3].T@np.array([offset_m,0.,height_m]))
    norm=np.linalg.norm(normal)
    if norm<1e-12:return dict(result,reason='degenerate_segment_plane')
    signed=r@(normal/norm)
    roots=[]
    for i in range(len(p)):
        if inside[i] and v[i] and abs(signed[i])<=1e-10:roots.append({i})
        if (i and inside[i] and inside[i-1] and v[i] and v[i-1]
            and p[i,0]-p[i-1,0]<=2 and signed[i]*signed[i-1]<0):roots.append({i-1,i})
    merged=[]
    for root in roots:
        if merged and any(abs(signed[i])<=1e-10 for i in root&merged[-1]):merged[-1]|=root
        else:merged.append(root.copy())
    result['root_groups']=len(merged)
    if len(merged)!=1:
        return dict(result,reason='no_bracket' if not merged else 'ambiguous_intersections')
    i=min(merged[0],key=lambda j:(abs(signed[j]),p[j,0]))
    return dict(result,selected=True,reason='actual_observed_bracket_point',index=int(i),
        plane_angle_deg=float(np.degrees(np.arcsin(np.clip(abs(signed[i]),0,1)))))


def floor_implied_tip_heights(tip_ray,base_rays,valid,T,*,offset_m=0.):
    """Solve tip range from horizontal correspondence, NOT from known height."""
    T=checked_transform(T)
    tip=np.asarray(tip_ray,float)
    if tip.shape!=(3,) or not np.isfinite(tip).all() or not np.isclose(np.linalg.norm(tip),1,atol=1e-10):
        raise ValueError('finite unit tip ray required')
    if not np.isfinite(offset_m) or offset_m<0:raise ValueError('finite nonnegative offset required')
    bases,accepted=floor_from_rays(base_rays,valid,T)
    d=T[:3,:3]@tip
    denominator=d[:2]@d[:2]
    heights=np.full(len(bases),np.nan);residual=np.full(len(bases),np.nan)
    scales=np.full(len(bases),np.nan)
    if denominator>1e-12:
        displacement=bases[:,:2]-T[:2,3]+[offset_m,0.]
        scales=displacement@d[:2]/denominator
        accepted &= scales>0
        heights[accepted]=T[2,3]+scales[accepted]*d[2]
        residual[accepted]=np.linalg.norm(scales[accepted,None]*d[:2]-displacement[accepted],axis=1)
    else:accepted[:]=False
    return dict(points=bases,accepted=accepted,tip_heights=heights,horizontal_residuals=residual,
        tip_up_component=float(d[2]),tip_elevation_deg=float(np.degrees(np.arctan2(d[2],np.linalg.norm(d[:2])))))
