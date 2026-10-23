"""Two predeclared native bands; no image remapping or physical output."""
import cv2
import numpy as np

from angular_fisheye_geometry import unproject
from scene_geometry import plane_from_pixels, infer_up, angle_degrees


def extract_band(image, camera, *, band):
    bounds={'upper':(60,300),'lower':(301,430)}
    if band not in bounds:raise ValueError('only predeclared upper/lower bands are allowed')
    if image.shape!=(720,1280,3) or image.dtype!=np.uint8:
        raise ValueError('native uint8 BGR frame required')
    lo,hi=bounds[band]
    gray=cv2.cvtColor(image[:,:640],cv2.COLOR_BGR2GRAY)
    ys,xs=np.nonzero(cv2.Canny(gray,60,120))
    native=np.column_stack((xs,ys)).astype(float)
    roi=(xs>=40)&(xs<=600)&(ys>=lo)&(ys<=hi)
    native=native[roi]
    rays,valid=unproject(native,camera,image_size=(1280,720))
    valid &= rays[:,2]>=np.cos(np.deg2rad(75))
    native,rays=native[valid],rays[valid]
    points=200*rays[:,:2]/rays[:,2,None]
    if not len(points):return []
    candidates=cv2.HoughLinesPointSet(points.astype(np.float32).reshape(-1,1,2),200,40,-1000,1000,1,0,np.pi,np.pi/720)
    rows=[]
    for index,(votes,rho,theta) in enumerate(candidates.reshape(-1,3) if candidates is not None else []):
        distance=abs(points@np.array([np.cos(theta),np.sin(theta)])-rho)
        ids=np.flatnonzero(distance<=1)
        bins=np.floor(native[ids,1]/2).astype(int)
        chosen=[]
        for bin_id in np.unique(bins):
            options=ids[bins==bin_id];chosen.append(options[np.argmin(distance[options])])
        observed=native[chosen]
        pieces=np.split(observed,np.flatnonzero(np.diff(observed[:,1])>6)+1)
        for part,actual in enumerate(pieces):
            if len(actual)<30:continue
            span=np.ptp(actual,axis=0)
            if span[1]<60 or span[1]<1.5*span[0]:continue
            plane=plane_from_pixels(actual,camera)
            rows.append(dict(line_index=index,part=part,hough_votes=float(votes),rho=float(rho),theta=float(theta),
                native_y_span=float(span[1]),actual_edge_pixels_json=actual.tolist(),**plane))
    kept=[]
    for row in sorted((r for r in rows if r['accepted']),key=lambda r:-r['native_y_span']):
        n=np.array(row['normal'])
        if any(np.degrees(np.arccos(np.clip(abs(n@np.array(r['normal'])),-1,1)))<2 for r in kept):
            row.update(accepted=False,reason='duplicate_ray_plane')
        else:kept.append(row)
    return rows


def fuse_planes(upper, lower):
    """Upper rows preserve priority and order; close lower normals get no vote."""
    for rows,band in ((upper,'upper'),(lower,'lower')):
        for r in rows:
            n=np.asarray(r['normal'],float)
            if r['band']!=band or n.shape!=(3,) or not np.isfinite(n).all() or not np.isclose(np.linalg.norm(n),1):
                raise ValueError('unit normal and explicit source band required')
    kept=list(upper);rejected=[]
    for row in lower:
        n=np.array(row['normal'])
        angles=[float(np.degrees(np.arccos(np.clip(abs(n@np.array(r['normal'])),-1,1)))) for r in kept]
        matches=[i for i,a in enumerate(angles) if a<2]
        if matches:
            i=min(matches,key=lambda j:(angles[j],j))
            rejected.append(dict(band=row['band'],line_index=row['line_index'],part=row['part'],
                duplicate_of_band=kept[i]['band'],duplicate_of_line_index=kept[i]['line_index'],
                duplicate_of_part=kept[i]['part'],angle_deg=angles[i]))
        else:kept.append(row)
    return kept,rejected


def independent_agreement(upper, lower):
    if not upper['accepted'] or not lower['accepted']:
        return dict(accepted=False,up=None,inliers=0,inlier_indices=[],
                    reason='both_independent_band_poses_required',band_direction_difference_deg=None)
    delta=angle_degrees(upper['up'],lower['up'])
    if delta>2:
        return dict(accepted=False,up=None,inliers=0,inlier_indices=[],
                    reason='independent_band_directions_disagree',band_direction_difference_deg=delta)
    return dict(accepted=True,up=list(upper['up']),inliers=upper['inliers'],inlier_indices=upper['inlier_indices'],
                reason='two_independent_bands_agree_upper_retained',band_direction_difference_deg=delta)
