"""Offline-first fisheye rays + explicit rigid transform + floor plane.

No ROS/TF buffer, Qt, detector, empirical range correction or actuator access.
Optical axes are x-right/y-down/z-forward; target axes are supplied by caller.
The camera is IDEAL EQUIDISTANT, not a measured OpenCV distortion calibration.
Nothing returned by this module grants physical-output permission.
"""
from dataclasses import dataclass
import math
from collections.abc import Mapping

import numpy as np


@dataclass(frozen=True)
class EquidistantCamera:
    width: int
    height: int
    cx: float
    cy: float
    radius: float  # pixel radius corresponding to pi/2 off optical axis

    def __post_init__(self):
        if (type(self.width) is not int or type(self.height) is not int or min(self.width, self.height) < 2
                or any(isinstance(v, (bool, np.bool_)) or not math.isfinite(v) for v in (self.cx, self.cy, self.radius))
                or self.radius <= 0 or not (0 <= self.cx < self.width and 0 <= self.cy < self.height)):
            raise ValueError("finite ideal-equidistant camera and image dimensions required")


def checked_transform(transform):
    """Copy T_target_from_source; points use R*p+t, vectors use R*v only."""
    if np.iscomplexobj(transform):
        raise ValueError("real proper rigid transform required")
    t = np.array(transform, dtype=np.float64, copy=True)
    if (t.shape != (4, 4) or not np.isfinite(t).all()
            or not np.allclose(t[3], (0, 0, 0, 1), rtol=0, atol=1e-12)
            or not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), rtol=0, atol=1e-10)
            or not math.isclose(float(np.linalg.det(t[:3, :3])), 1., abs_tol=1e-10)):
        raise ValueError("finite proper rigid transform required; no reflections/scaling")
    return t


def optical_rays(pixels, camera):
    """Return (Nx3 unit rays, N validity flags), preserving order and duplicates.

    Invalid rays are NaN, not discarded. Subpixel coordinates are retained.
    At the optical centre the limiting ray is [0,0,1]. This deliberate generic
    limit differs from the legacy diagnostic centre exclusion.
    """
    if not isinstance(camera, EquidistantCamera) or np.iscomplexobj(pixels):
        raise ValueError("ideal-equidistant camera and real native pixels required")
    p = np.asarray(pixels, dtype=np.float64)
    if p.shape in ((0,), (0, 2)):
        p = np.empty((0, 2))
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        raise ValueError("finite Nx2 native pixel coordinates required")
    delta = p - [camera.cx, camera.cy]
    rho = np.linalg.norm(delta, axis=1)
    valid = ((p[:, 0] >= 0) & (p[:, 0] < camera.width) & (p[:, 1] >= 0)
             & (p[:, 1] < camera.height) & (rho < camera.radius))
    rays = np.full((len(p), 3), np.nan)
    r = rho[valid]
    theta = r/camera.radius*(np.pi/2)
    scale = np.divide(np.sin(theta), r, out=np.full_like(r, np.pi/(2*camera.radius)), where=r != 0)
    rays[valid, :2] = delta[valid]*scale[:, None]
    rays[valid, 2] = np.cos(theta)
    return rays, valid


def intersect_floor(pixels, camera, target_from_optical, *, image_size,
                    plane_normal=(0., 0., 1.), plane_offset_m=0., min_incidence_cos=.03):
    """Intersect rays with n.dot(point)+offset=0 in the target frame.

    n must be UNIT length and point from floor toward the camera. Offset is in
    metres. Actual decoded image_size=(width,height) must match the model;
    resizing pixel coordinates without updating calibration is never implicit.
    No runtime range limits or front-only policy are imposed by this math core.
    """
    if image_size != (camera.width, camera.height):
        raise ValueError("actual native image size must match camera model")
    t = checked_transform(target_from_optical)
    if np.iscomplexobj(plane_normal):
        raise ValueError("real unit plane normal required")
    n = np.asarray(plane_normal, dtype=np.float64)
    if (n.shape != (3,) or not np.isfinite(n).all() or not np.isclose(np.linalg.norm(n), 1., rtol=0, atol=1e-10)
            or not math.isfinite(plane_offset_m) or not math.isfinite(min_incidence_cos)
            or not 0 < min_incidence_cos < 1):
        raise ValueError("unit floor normal, finite metre offset and incidence in (0,1) required")
    origin = t[:3, 3]
    height = float(n @ origin + plane_offset_m)
    if height <= 0:
        raise ValueError("camera must be on positive side of supplied floor plane")
    optical, valid = optical_rays(pixels, camera)
    directions = optical @ t[:3, :3].T
    records = []
    for i, direction in enumerate(directions):
        point = None
        distance = None
        if not valid[i]:
            reason = "outside_native_image_or_lens"
        else:
            incidence = float(n @ direction)
            if incidence >= -min_incidence_cos:
                reason = "not_downward_or_grazing_floor_ray"
            else:
                distance = -height/incidence
                point = tuple(map(float, origin + distance*direction))
                reason = "conditional_floor_intersection"
        records.append(dict(input_index=i, reason=reason, point_target_m=point,
                            ray_distance_m=distance, floor_contact_verified=False, usable_for_ffb=False))
    return records


def legacy_front_diagnostic_geometry(parameters: Mapping[str, float]):
    """Frozen1280x720 front-left compatibility, NOT measured base_link extrinsics.

    Returns camera, T_camera_ground_reference_from_front_optical. Target axes
    are ROS x-forward/y-left/z-up, origin at camera's vertical floor projection.
    car_offset_* are display controls and deliberately NOT used as extrinsics.
    Existing pitch/roll/yaw are private convention, NOT ROS RPY arguments.
    """
    from ground_contact import _lens_geometry
    keys = ("camera_height", "pitch_deg", "roll_deg", "yaw_deg", "radius_scale", "front_cx_offset", "front_cy_offset")
    if (any(k not in parameters or isinstance(parameters[k], (bool, np.bool_))
            or not math.isfinite(parameters[k]) for k in keys)
            or parameters["camera_height"] <= 0 or parameters["radius_scale"] <= 0):
        raise ValueError("complete finite legacy front geometry required")
    cx, cy, radius, _ = _lens_geometry(1280, 720, parameters, "front", "left")
    camera = EquidistantCamera(1280, 720, cx, cy, radius)
    yaw, pitch, roll = np.deg2rad([parameters[k] for k in ("yaw_deg", "pitch_deg", "roll_deg")])
    ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rp = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    rr = np.array([[math.cos(roll), -math.sin(roll), 0], [math.sin(roll), math.cos(roll), 0], [0, 0, 1]])
    old_world_to_ros = np.array([[0., 0., 1.], [-1., 0., 0.], [0., 1., 0.]])
    optical_to_old_camera = np.diag([1., -1., 1.])
    t = np.eye(4)
    t[:3, :3] = old_world_to_ros @ (rr @ rp @ ry).T @ optical_to_old_camera
    t[2, 3] = parameters["camera_height"]
    return camera, checked_transform(t)
