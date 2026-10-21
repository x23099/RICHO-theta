"""Project known segment plane onto actual observed native support. Offline only."""
import numpy as np
from fisheye_floor_geometry import checked_transform, optical_rays

TRIM_FRACTION=.1
MIN_COLUMNS=8
MIN_SPAN_PX=6.
MAX_COLUMN_GAP=2.
MAX_LINE_DISTANCE_PX=2.


def rectify(points,camera,K,*,size=(960,960)):
    """Ideal-equidistant rays -> virtual pinhole. Preserve invalid point slots."""
    if np.iscomplexobj(K):
        raise ValueError('real pinhole intrinsics required')
    K=np.asarray(K,float)
    if (K.shape!=(3,3) or not np.isfinite(K).all() or min(K[0,0],K[1,1])<=0
            or not np.allclose(K[2],[0,0,1],atol=1e-12,rtol=0)):
        raise ValueError('finite pinhole intrinsics required')
    rays,valid=optical_rays(points,camera)
    projected=rays@K.T
    uv=projected[:,:2]/projected[:,2,None]
    valid &= np.isfinite(uv).all(axis=1)&(rays[:,2]>0)&(uv>=0).all(axis=1)&(uv[:,0]<=size[0]-1)&(uv[:,1]<=size[1]-1)
    return uv,valid


def segment_image_line(tip_uv,K,T,delta):
    if any(np.iscomplexobj(v) for v in (tip_uv,K,delta)):
        raise ValueError('real inputs required')
    tip,K,delta=np.asarray(tip_uv,float),np.asarray(K,float),np.asarray(delta,float)
    T=checked_transform(T)
    if (tip.shape!=(2,) or K.shape!=(3,3) or delta.shape!=(3,) or not np.isfinite(tip).all()
            or not np.isfinite(K).all() or not np.isfinite(delta).all() or delta[2]<=0
            or min(K[0,0],K[1,1])<=0 or not np.allclose(K[2],[0,0,1],atol=1e-12,rtol=0)):
        raise ValueError('finite tip/K and positive vertical segment required')
    ray=np.linalg.solve(K,[*tip,1.])
    normal=np.cross(ray,T[:3,:3].T@delta)
    line=np.linalg.solve(K.T,normal)
    scale=np.linalg.norm(line[:2])
    if not np.isfinite(scale) or scale<1e-12:
        return None
    return line/scale


def bracket_observed_support(points,uv,valid,line):
    """Only nearest actual point bracketing ONE root inside observed central80%."""
    if any(np.iscomplexobj(v) for v in (points,uv,line)):
        raise ValueError('real support required')
    p,uv,line=np.asarray(points,float),np.asarray(uv,float),np.asarray(line,float)
    valid=np.asarray(valid,bool)
    if (p.ndim!=2 or p.shape[1]!=2 or len(p)<1 or uv.shape!=p.shape or valid.shape!=(len(p),)
            or line.shape!=(3,) or not np.isfinite(p).all() or not np.equal(p,np.rint(p)).all()
            or np.any(np.diff(p[:,0])<=0) or not np.isfinite(line).all()
            or not np.isclose(np.linalg.norm(line[:2]),1.,atol=1e-10,rtol=0)
            or not np.isfinite(uv[valid]).all()):
        raise ValueError('actual ordered integer envelope and normalized line required')
    lo,hi=p[0,0],p[-1,0]
    inside=(p[:,0]>=lo+TRIM_FRACTION*(hi-lo))&(p[:,0]<=hi-TRIM_FRACTION*(hi-lo))
    result=dict(selected=False,reason='insufficient_observed_support',index=None,point_native=None,
                point_rectified=None,line_distance_px=None,root_groups=0,support_columns=int(inside.sum()),
                support_x_lo=float(p[inside,0].min()) if inside.any() else None,
                support_x_hi=float(p[inside,0].max()) if inside.any() else None,
                pixel_consistent=False,physical_endpoint_correspondence_verified=False,usable_for_ffb=False)
    if inside.sum()<MIN_COLUMNS or np.ptp(p[inside,0])<MIN_SPAN_PX:
        return result
    signed=np.column_stack((uv,np.ones(len(uv))))@line
    roots=[]
    for i in range(len(p)):
        if inside[i] and valid[i] and abs(signed[i])<=1e-8:
            roots.append({i})
        if (i>0 and inside[i] and inside[i-1] and valid[i] and valid[i-1]
                and p[i,0]-p[i-1,0]<=MAX_COLUMN_GAP and signed[i]*signed[i-1]<0):
            roots.append({i-1,i})
    merged=[]
    for root in roots:
        # Adjacent sign-change intervals can be TWO different crossings of
        # a jagged envelope. Merge only a shared exact-zero observed point.
        if merged and any(abs(signed[i])<=1e-8 for i in root&merged[-1]):
            merged[-1]|=root
        else:
            merged.append(root.copy())
    result['root_groups']=len(merged)
    if len(merged)!=1:
        return dict(result,reason='no_bracket_in_observed_support' if not merged else 'ambiguous_observed_intersections')
    chosen=min(merged[0],key=lambda i:(abs(signed[i]),p[i,0]))
    distance=float(abs(signed[chosen]))
    return dict(result,selected=True,reason='actual_observed_point_nearest_bracketed_segment_projection',
                index=int(chosen),point_native=p[chosen].tolist(),point_rectified=uv[chosen].tolist(),
                line_distance_px=distance,pixel_consistent=distance<=MAX_LINE_DISTANCE_PX)


def select_base(tip_native,envelope,camera,K,T,*,height_m=.73,offset_m=0.):
    if not np.isfinite(height_m) or height_m<=0 or not np.isfinite(offset_m) or offset_m<0:
        raise ValueError('positive height and nonnegative offset required')
    tip,tip_valid=rectify([tip_native],camera,K)
    if not tip_valid[0]:
        return dict(selected=False,reason='tip_outside_lens_or_virtual_view')
    line=segment_image_line(tip[0],K,T,[offset_m,0.,height_m])
    if line is None:
        return dict(selected=False,reason='degenerate_segment_projection')
    uv,valid=rectify(envelope,camera,K)
    result=bracket_observed_support(envelope,uv,valid,line)
    result.update(projected_line_json=line.tolist(),tip_rectified=tip[0].tolist())
    return result
