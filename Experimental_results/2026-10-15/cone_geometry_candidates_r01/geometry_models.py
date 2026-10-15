"""Exploratory fixed-height fits to unverified V-apex candidates, OFFLINE ONLY.

No ROS, camera/model access, runtime imports/writes, or physical-FFB eligibility.
Forward equations match existing bird_eye.py/ground_contact.py geometry.
"""
from copy import deepcopy
import math

import numpy as np
from scipy.optimize import least_squares

from ground_contact import _lens_geometry, dual_fisheye_pixels_to_vehicle_rays

FIT_IDS = ("C080", "C130", "C200", "L130", "R130")
CHECK_IDS = ("H100", "H160")
FAMILIES = {
    "centre2": ("front_cx_offset", "front_cy_offset"),
    "pose3": ("yaw_deg", "pitch_deg", "roll_deg"),
    "centre_radius3": ("front_cx_offset", "front_cy_offset", "radius_scale"),
    "centre_pose5": ("front_cx_offset", "front_cy_offset", "yaw_deg", "pitch_deg", "roll_deg"),
}
BOUNDS = dict(front_cx_offset=(-105.,-55.), front_cy_offset=(-46.,4.),
              radius_scale=(.80,.92), yaw_deg=(-8.,8.), pitch_deg=(-7.,9.), roll_deg=(-6.,10.))
PRIMARY = "centre2"


def project_floor_to_pixels(points, p):
    """World (X,Z) floor points -> left/front native1280x720 raw pixel."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not len(points) or not np.isfinite(points).all():
        raise ValueError("nonempty finite Nx2 floor points required")
    if np.any(points[:,1] <= 0):
        raise ValueError("positive forward Z required")
    for key in ("camera_height","radius_scale","yaw_deg","pitch_deg","roll_deg","front_cx_offset","front_cy_offset"):
        if key not in p or not math.isfinite(float(p[key])):
            raise ValueError("finite complete front geometry required")
    if p["camera_height"] <= 0 or p["radius_scale"] <= 0:
        raise ValueError("positive height and radius required")
    x,z = points.T
    y = np.full_like(x,-p["camera_height"])
    yaw,pitch,roll = np.deg2rad([p[k] for k in ("yaw_deg","pitch_deg","roll_deg")])
    x1,z1 = x*np.cos(yaw)+z*np.sin(yaw), -x*np.sin(yaw)+z*np.cos(yaw)
    y2,z2 = y*np.cos(pitch)-z1*np.sin(pitch), y*np.sin(pitch)+z1*np.cos(pitch)
    camera = np.column_stack((x1*np.cos(roll)-y2*np.sin(roll),x1*np.sin(roll)+y2*np.cos(roll),z2))
    camera /= np.linalg.norm(camera,axis=1)[:,None]
    if np.any(camera[:,2] <= 0):
        raise ValueError("world point outside front hemisphere")
    cx,cy,radius,_ = _lens_geometry(1280,720,p,"front","left")
    theta = np.arccos(np.clip(camera[:,2],-1,1))
    radial = radius*theta/(np.pi/2)
    sin = np.sin(theta)
    ratio = np.divide(radial,sin,out=np.zeros_like(radial),where=sin>1e-12)
    return np.column_stack((cx+ratio*camera[:,0],cy-ratio*camera[:,1]))


def project_pixels_to_floor(pixels,p):
    """All-or-error diagnostic projection, retaining existing floor/range rules."""
    pixels = np.asarray(pixels,dtype=float)
    if pixels.ndim != 2 or pixels.shape[1] != 2 or not len(pixels) or not np.isfinite(pixels).all():
        raise ValueError("nonempty finite Nx2 native pixels required")
    if np.any(pixels < 0) or np.any(pixels[:,0] >= 1280) or np.any(pixels[:,1] >= 720):
        raise ValueError("native pixels outside image")
    if not math.isfinite(float(p["camera_height"])) or p["camera_height"] <= 0:
        raise ValueError("positive height required")
    selected,rays = dual_fisheye_pixels_to_vehicle_rays(pixels,1280,720,p,lens="front",front_lens="left")
    if len(selected) != len(pixels) or not np.array_equal(selected,pixels) or np.any(rays[:,1] >= -.03):
        raise ValueError("one or more input rays are not valid front-floor rays")
    scale = -p["camera_height"]/rays[:,1]
    ground = rays[:,[0,2]]*scale[:,None]
    distances = np.linalg.norm(ground,axis=1)
    if not np.isfinite(ground).all() or np.any(ground[:,1]<=0) or np.any((distances<.2)|(distances>4)):
        raise ValueError("floor intersection outside diagnostic range")
    return ground


def partition(rows):
    """Fixed IDs/roles; holdout content is deliberately not passed to fit_model."""
    identities = [row["point_id"] for row in rows]
    if len(identities) != 7 or set(identities) != set(FIT_IDS+CHECK_IDS):
        raise ValueError("seven fixed unique floor IDs required")
    train,check = [],[]
    for row in rows:
        target = train if row["point_id"] in FIT_IDS else check
        expected_role = "diagnostic" if target is train else "held_out_from_future_fit"
        if row["role"] != expected_role:
            raise ValueError("floor role mismatch; cannot promote a holdout")
        target.append(deepcopy(row))
    return train,check


def arrays(rows):
    points = np.array([[float(r[k]) for k in ("reference_x_m","reference_z_m")] for r in rows])
    pixels = np.array([[float(r[k]) for k in ("pixel_x","pixel_y")] for r in rows])
    if not np.isfinite(points).all() or not np.isfinite(pixels).all():
        raise ValueError("finite measured coordinates and candidate pixels required")
    return points,pixels


def fit_model(rows,base,family):
    """Fit only supplied diagnostic IDs; holdouts/duplicates/unknown IDs rejected."""
    if family not in FAMILIES:
        raise ValueError("unknown model family")
    ids = [r["point_id"] for r in rows]
    if len(ids) < 3 or len(ids) != len(set(ids)) or any(i not in FIT_IDS for i in ids):
        raise ValueError("only at least three unique diagnostic IDs may be fitted")
    if any(r.get("role") != "diagnostic" for r in rows):
        raise ValueError("only diagnostic roles may be fitted")
    if not math.isclose(float(base["camera_height"]),.59,rel_tol=0,abs_tol=1e-12):
        raise ValueError("measured lens-centre height .59m must be fixed, not fitted")
    world,pixels = arrays(rows)
    names = FAMILIES[family]
    lower,upper = np.array([BOUNDS[k] for k in names]).T
    scales = (upper-lower)/2
    initial = np.array([base[k] for k in names],dtype=float)
    if np.any(initial<=lower) or np.any(initial>=upper):
        raise ValueError("baseline must be strictly inside declared search bounds")
    def parameters(values):
        return dict(base,**dict(zip(names,map(float,values))))
    def residual(values):
        return (project_floor_to_pixels(world,parameters(values))-pixels).ravel()
    direction = np.array([1 if i%2==0 else -1 for i in range(len(names))])
    starts = [initial, initial+.1*scales*direction, initial-.1*scales*direction]
    solutions = [least_squares(residual,start,bounds=(lower,upper),method="trf",loss="linear",
        jac="3-point",x_scale=scales,ftol=1e-11,xtol=1e-11,gtol=1e-11,max_nfev=500) for start in starts]
    successful = [r for r in solutions if r.success and np.isfinite(r.fun).all()]
    if not successful:
        raise ValueError("no successful fit; do not fabricate a candidate")
    result = min(successful,key=lambda r:float(r.fun@r.fun))
    singular = np.linalg.svd(result.jac*scales,compute_uv=False)
    threshold = singular[0]*max(result.jac.shape)*np.finfo(float).eps
    rank = int(np.sum(singular>threshold))
    condition = float(singular[0]/singular[-1]) if singular[-1]>threshold else None
    p = parameters(result.x)
    cx,cy,radius,_ = _lens_geometry(1280,720,p,"front","left")
    circle_fits = 0<=cx-radius and cx+radius<=1280 and 0<=cy-radius and cy+radius<=720
    if not circle_fits:
        raise ValueError("candidate lens circle outside native image")
    return dict(family=family,parameters=p,fit_ids=ids,free_parameters=list(names),
        pixel_sse=float(result.fun@result.fun),pixel_point_rmse=float(np.sqrt(np.mean(np.sum(result.fun.reshape(-1,2)**2,axis=1)))),
        solver_success=bool(result.success),active_bounds={key:int(mask) for key,mask in zip(names,result.active_mask)},
        search_bounds={key:list(BOUNDS[key]) for key in names},
        normalized_jacobian_singular_values=singular.tolist(),normalized_jacobian_rank=rank,
        normalized_jacobian_condition=condition,starts=len(starts),
        offline_only=True,physical_output_authorized=False,usable_for_ffb=False,
        interpretation="provisional model for unverified assistant pixel candidates; not measured physical intrinsics/pose")
