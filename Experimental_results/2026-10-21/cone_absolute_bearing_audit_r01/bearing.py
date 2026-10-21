"""Absolute bearing consistency diagnostics. Never return a calibration model."""
import math
import numpy as np
from fisheye_floor_geometry import legacy_front_diagnostic_geometry, optical_rays

CAMERA_HEIGHT_M=.59
CONE_HEIGHT_M=.73


def elevation_deg(direction):
    if np.iscomplexobj(direction):
        raise ValueError('real forward direction required')
    d=np.asarray(direction,float)
    if d.shape!=(3,) or not np.isfinite(d).all() or d[0]<=0:
        raise ValueError('finite positive-forward direction required')
    return float(np.degrees(np.arctan2(d[2],d[0])))


def expected_elevation(z_forward_m,height_m,*,camera_height_m=CAMERA_HEIGHT_M):
    if (not all(math.isfinite(v) for v in (z_forward_m,height_m,camera_height_m))
            or z_forward_m<=0 or camera_height_m<=0):
        raise ValueError('finite height and positive depth/camera height required')
    return float(np.degrees(np.arctan2(height_m-camera_height_m,z_forward_m)))


def inspect_pixel(pixel,parameters,*,reference_z_m,reference_height_m=0.):
    camera,T=legacy_front_diagnostic_geometry(parameters)
    rays,valid=optical_rays([pixel],camera)
    if not valid[0]:
        raise ValueError('pixel outside native lens')
    d=T[:3,:3]@rays[0]
    observed=elevation_deg(d)
    required=expected_elevation(reference_z_m,reference_height_m)
    floor_z=-T[2,3]*d[0]/d[2] if d[2]<0 else None
    # Height demanded by the current bearing for this point to be on floor
    # at nominal Z. NOT a new measurement or an adopted camera-height fit.
    implied_h=-reference_z_m*d[2]/d[0] if reference_height_m==0 else None
    return dict(pixel_x=float(pixel[0]),pixel_y=float(pixel[1]),observed_elevation_deg=observed,
                expected_elevation_deg=required,required_down_rotation_deg=observed-required,
                model_floor_z_m=float(floor_z) if floor_z is not None else None,
                implied_camera_height_if_floor_m=float(implied_h) if implied_h is not None else None,
                physical_reference_verified=False,calibrated_intrinsics=False,usable_for_ffb=False)


def central_equidistant_pixels(elevations_deg,*,focal_px,cy,pitch_deg):
    """Synthetic central meridian only; private runtime pitch convention NOT used.

    p_y=cy-f*(world_elevation+pitch). cy+=f*delta and pitch+=delta
    exactly cancel for this 1D ideal model. This is NOT full-image calibration.
    """
    if np.iscomplexobj(elevations_deg):
        raise ValueError('real elevations required')
    a=np.asarray(elevations_deg,float)
    if not np.isfinite(a).all() or not all(math.isfinite(x) for x in (focal_px,cy,pitch_deg)) or focal_px<=0:
        raise ValueError('finite synthetic model required')
    return cy-focal_px*np.deg2rad(a+pitch_deg)


def repeated_pixel_bound(a,b):
    """Any SINGLE deterministic projection of the SAME 3D point has this bound."""
    if np.iscomplexobj(a) or np.iscomplexobj(b):
        raise ValueError('real pixels required')
    a,b=np.asarray(a,float),np.asarray(b,float)
    if a.shape!=(2,) or b.shape!=(2,) or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('two finite pixels required')
    return dict(delta_x_px=float(b[0]-a[0]),delta_y_px=float(b[1]-a[1]),
        separation_px=float(np.linalg.norm(b-a)),single_projection_minimax_residual_lower_bound_px=float(np.linalg.norm(b-a)/2),
        conditional_on_same_physical_point_and_mapping=True,physical_reference_verified=False,usable_for_ffb=False)
