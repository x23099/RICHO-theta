"""Offline conditional geometry, NOT vehicle position or a risk/FFB input.

The floor normal fixes two rotational degrees of freedom, not vehicle heading.
No live caller imports this module. Callers must preserve display vetoes and
source identity; a geometric intersection does not verify physical contact.
"""
import math

import numpy as np


def camera_floor_offset(ray, *, up_optical, height_m):
    """Camera-foot-to-support horizontal vector, expressed in OPTICAL axes.

    With camera origin O, unit floor-up u and assumed height h, its plumb
    foot is -h*u. Ray intersection p = h*r/(-u.r), so q = p+h*u lies in
    the assumed floor plane. q is NOT a vector expressed in vehicle axes.
    Return None for grazing/upward rays; never normalize bad inputs silently.
    """
    for value in (ray, up_optical):
        array = np.asarray(value)
        if (array.shape != (3,) or array.dtype.kind not in 'iuf'
                or any(isinstance(v, (bool, np.bool_)) for v in value)
                or not np.isfinite(array).all()
                or not np.isclose(np.linalg.norm(array), 1., atol=1e-12, rtol=0)):
            raise ValueError('finite real unit ray and floor-up required')
    if type(height_m) not in (int, float) or not math.isfinite(height_m) or not 0 < height_m < 3:
        raise ValueError('explicit assumed height in (0,3) metres required')
    r, u = np.asarray(ray, float), np.asarray(up_optical, float)
    incidence = -float(u @ r)
    if incidence < .03:
        return None
    offset = height_m*r/incidence + height_m*u
    return dict(schema='offline_conditional_camera_floor_offset_v1',
        offset_optical_m=offset.tolist(), horizontal_range_m=float(np.linalg.norm(offset)),
        coordinate_basis='optical_x_right_y_down_z_axis_NOT_vehicle',
        origin='assumed_camera_plumb_foot',
        plane_residual_m=float(u @ offset), assumed_height_m=height_m,
        vehicle_xy_m=None, target_association_verified=False, replay_only=True,
        physical_metric_verified=False, floor_contact_verified=False,
        controlling_distance=False, usable_for_ffb=False, published_to_ros=False)
