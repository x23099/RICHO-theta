"""Offline architectural-line hypotheses, without metric object labels."""
import cv2
import numpy as np
from angular_fisheye_geometry import unproject
from fisheye_floor_geometry import checked_transform


def angle_degrees(a,b):
    return float(np.degrees(np.arccos(np.clip(np.dot(a,b),-1,1))))


def unit(v):
    v=np.asarray(v,float)
    if v.shape!=(3,) or not np.isfinite(v).all() or np.linalg.norm(v)<1e-12:
        raise ValueError('finite nonzero vector required')
    return v/np.linalg.norm(v)


def plane_from_pixels(pixels,camera):
    p=np.asarray(pixels,float)
    if (p.ndim!=2 or p.shape[1]!=2 or len(p)<30 or not np.isfinite(p).all()
        or not np.equal(p,np.rint(p)).all()):raise ValueError('30 actual native edge pixels required')
    rays,valid=unproject(p,camera,image_size=(1280,720))
    if not valid.all():return dict(accepted=False,reason='outside_angular_domain')
    if np.max(np.degrees(np.arccos(np.clip(rays[:,2],-1,1))))>75:
        return dict(accepted=False,reason='outside_75degree_scene_domain')
    span=angle_degrees(rays[0],rays[-1])
    if span<12:return dict(accepted=False,reason='insufficient_ray_span',ray_span_deg=span)
    _,singular,vt=np.linalg.svd(rays,full_matrices=False)
    normal=vt[-1]
    if normal[0]<0:normal=-normal
    errors=np.degrees(np.arcsin(np.clip(abs(rays@normal),0,1)))
    rms=float(np.sqrt(np.mean(errors**2)));maximum=float(errors.max())
    accepted=rms<=.15 and maximum<=.4
    return dict(accepted=accepted,reason='accepted_plane' if accepted else 'not_one_ray_plane',
        normal=normal.tolist() if accepted else None,plane_rms_deg=rms,plane_max_deg=maximum,
        ray_span_deg=span,edge_points=len(p))


def extract_planes(image,camera):
    if image.shape!=(720,1280,3) or image.dtype!=np.uint8:raise ValueError('native uint8 BGR frame required')
    gray=cv2.cvtColor(image[:,:640],cv2.COLOR_BGR2GRAY)
    lines=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD,1.0).detect(gray)[0]
    canny=cv2.Canny(gray,60,120)
    ys,xs=np.nonzero(canny)
    edge=np.column_stack((xs,ys)).astype(float)
    rows=[]
    for index,line in enumerate(lines.reshape(-1,4) if lines is not None else []):
        a,b=line.reshape(2,2).astype(float);delta=b-a
        if not (np.all([a[0]>=40,b[0]>=40,a[0]<=600,b[0]<=600,a[1]>=60,b[1]>=60,a[1]<=300,b[1]<=300])
            and abs(delta[1])>=60 and abs(delta[1])>=1.5*abs(delta[0])):continue
        length=float(np.linalg.norm(delta));direction=delta/length
        box=(edge[:,0]>=min(a[0],b[0])-3)&(edge[:,0]<=max(a[0],b[0])+3)&(edge[:,1]>=min(a[1],b[1])-3)&(edge[:,1]<=max(a[1],b[1])+3)
        points=edge[box];displacement=points-a
        along=displacement@direction
        distance=abs(displacement[:,0]*direction[1]-displacement[:,1]*direction[0])
        use=(along>=0)&(along<=length)&(distance<=2.5)
        points,along,distance=points[use],along[use],distance[use]
        chosen=[]
        bins=np.floor(along/2).astype(int)
        for bin_id in np.unique(bins):
            indices=np.flatnonzero(bins==bin_id)
            chosen.append(indices[np.argmin(distance[indices])])
        actual=points[chosen]
        row=dict(line_index=index,lsd_endpoints_json=line.tolist(),length_px=length,edge_points=len(actual),
            edge_pixels_json=actual.tolist(),accepted=False,reason='insufficient_observed_edge_points')
        if len(actual)>=30:row.update(plane_from_pixels(actual,camera))
        rows.append(row)
    # Opposite gradient borders / split segments in the same ray plane get one vote.
    kept=[]
    for row in sorted((r for r in rows if r['accepted']),key=lambda r:-r['length_px']):
        normal=np.array(row['normal'])
        if any(np.degrees(np.arccos(np.clip(abs(normal@np.array(r['normal'])),-1,1)))<2 for r in kept):
            row.update(accepted=False,reason='duplicate_ray_plane')
        else:kept.append(row)
    return rows


def infer_up(normals,prior_up):
    n=np.asarray(normals,float)
    prior=unit(prior_up)
    if n.shape==(0,):n=np.empty((0,3))
    if n.ndim!=2 or n.shape[1]!=3 or not np.isfinite(n).all() or not np.allclose(np.linalg.norm(n,axis=1),1):
        raise ValueError('unit plane normals required')
    result=dict(accepted=False,reason='fewer_than_six_distinct_planes',up=None,planes=len(n),inliers=0,
        inlier_indices=[],median_residual_deg=None,normal_span_deg=None,rank_gap_ratio=None,
        architectural_vertical_independently_verified=False,usable_for_ffb=False)
    if len(n)<6:return result
    best=None
    for i in range(len(n)):
        for j in range(i):
            spread=np.degrees(np.arccos(np.clip(abs(n[i]@n[j]),-1,1)))
            if spread<8:continue
            g=unit(np.cross(n[i],n[j]));g=g if g@prior>=0 else -g
            if angle_degrees(g,prior)>20:continue
            residual=np.degrees(np.arcsin(np.clip(abs(n@g),0,1)));inside=residual<=1
            score=(int(inside.sum()),-float(np.median(residual[inside])))
            if best is None or score>best[0]:best=(score,g,inside)
    if best is None:return dict(result,reason='no_diverse_plane_pair_within_prior')
    _,g,inside=best
    for _ in range(2):
        if inside.sum()<6:return dict(result,reason='insufficient_consensus',inliers=int(inside.sum()))
        _,singular,vt=np.linalg.svd(n[inside],full_matrices=False)
        g=vt[-1];g=g if g@prior>=0 else -g
        residual=np.degrees(np.arcsin(np.clip(abs(n@g),0,1)));inside=residual<=1
    if inside.sum()<6:return dict(result,reason='insufficient_final_consensus',inliers=int(inside.sum()))
    # Quality refers to the final fixed inlier set.
    _,singular,_=np.linalg.svd(n[inside],full_matrices=False)
    span=float(np.max(np.degrees(np.arccos(np.clip(abs(n[inside]@n[inside].T),-1,1)))))
    gap=float(singular[1]/max(singular[-1],1e-15))
    accepted=angle_degrees(g,prior)<=20 and span>=15 and gap>=10
    return dict(result,accepted=accepted,reason='conditional_architectural_up' if accepted else 'poor_geometry_or_prior',
        up=g.tolist() if accepted else None,inliers=int(inside.sum()),inlier_indices=np.flatnonzero(inside).tolist(),
        median_residual_deg=float(np.median(residual[inside])),normal_span_deg=span,rank_gap_ratio=gap)


def align_up_preserving_heading_reference(T,up_optical):
    """Minimal rotation only; not a measured yaw or complete floor TF."""
    T=checked_transform(T);g=unit(up_optical);target=T[:3,:3].T@np.array([0.,0.,1.])
    v=np.cross(g,target);cosine=float(g@target)
    if cosine<-.999999:raise ValueError('antiparallel up needs an explicit rotation axis')
    skew=np.array([[0,-v[2],v[1]],[v[2],0,-v[0]],[-v[1],v[0],0]])
    Q=np.eye(3)+skew+skew@skew/(1+cosine)
    output=T.copy();output[:3,:3]=T[:3,:3]@Q
    return checked_transform(output)
