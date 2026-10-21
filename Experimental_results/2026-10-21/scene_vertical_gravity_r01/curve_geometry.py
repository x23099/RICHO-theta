"""Hough on back-projected edge coordinates, not a remapped camera image."""
import cv2
import numpy as np
from angular_fisheye_geometry import unproject
from scene_geometry import plane_from_pixels


def extract_curve_planes(image,camera):
    if image.shape!=(720,1280,3) or image.dtype!=np.uint8:raise ValueError('native uint8 BGR frame required')
    gray=cv2.cvtColor(image[:,:640],cv2.COLOR_BGR2GRAY)
    ys,xs=np.nonzero(cv2.Canny(gray,60,120))
    native=np.column_stack((xs,ys)).astype(float)
    roi=(xs>=40)&(xs<=600)&(ys>=60)&(ys<=300)
    native=native[roi]
    rays,valid=unproject(native,camera,image_size=(1280,720))
    valid &= rays[:,2]>=np.cos(np.deg2rad(75))
    native=native[valid];rays=rays[valid]
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
