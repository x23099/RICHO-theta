"""Virtual pinhole geometry with an explicit proper ROS-axis rigid transform.

Offline only: no CameraInfo publisher, TF broadcaster, inference or hardware.
"""
from dataclasses import dataclass
import math

import cv2
import numpy as np

from ground_contact import _lens_geometry


@dataclass(frozen=True)
class VirtualView:
    width: int = 960
    height: int = 960
    horizontal_fov_deg: float = 90.

    def __post_init__(self):
        if (type(self.width) is not int or type(self.height) is not int or min(self.width, self.height) < 2
                or not math.isfinite(self.horizontal_fov_deg) or not 0 < self.horizontal_fov_deg < 180):
            raise ValueError("positive image extents and finite FOV in (0,180) required")

    @property
    def K(self):
        f = self.width/(2*math.tan(math.radians(self.horizontal_fov_deg)/2))
        return np.array([[f, 0., (self.width-1)/2], [0., f, (self.height-1)/2], [0., 0., 1.]])


def check_parameters(p):
    keys = ("camera_height", "pitch_deg", "roll_deg", "yaw_deg", "radius_scale", "front_cx_offset",
            "front_cy_offset", "back_cx_offset", "back_cy_offset")
    if any(k not in p or not math.isfinite(float(p[k])) for k in keys):
        raise ValueError("complete finite native camera geometry required")
    if p["camera_height"] <= 0 or p["radius_scale"] <= 0:
        raise ValueError("positive camera height and lens radius required")


def equidistant_K(p):
    """Existing assumed equidistant model expressed as OpenCV fisheye K,D=0."""
    check_parameters(p)
    cx, cy, radius, _ = _lens_geometry(1280, 720, p, "front", "left")
    if not (0 <= cx-radius and cx+radius <= 1280 and 0 <= cy-radius and cy+radius <= 720):
        raise ValueError("front lens circle must fit native frame")
    f = radius/(math.pi/2)
    return np.array([[f, 0., cx], [0., f, cy], [0., 0., 1.]]), radius


def validate_transform(transform):
    t = np.asarray(transform, dtype=float)
    if (t.shape != (4, 4) or not np.isfinite(t).all() or not np.allclose(t[3], [0, 0, 0, 1], atol=1e-12, rtol=0)
            or not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-12, rtol=0)
            or not math.isclose(np.linalg.det(t[:3, :3]), 1., abs_tol=1e-12)
            or t[2, 3] <= 0):
        raise ValueError("proper finite rigid transform with camera above floor required")
    return t


def optical_to_ground_transform(p):
    """Optical x-right/y-down/z-front -> ground x-front/y-left/z-up.

    Existing private axes are not a ROS TF frame. Both axis conversions are
    necessary; publishing the single y-flip as a rotation would be improper.
    """
    check_parameters(p)
    yaw, pitch, roll = np.deg2rad([p[k] for k in ("yaw_deg", "pitch_deg", "roll_deg")])
    ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rp = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    rr = np.array([[math.cos(roll), -math.sin(roll), 0], [math.sin(roll), math.cos(roll), 0], [0, 0, 1]])
    private_to_ros_ground = np.array([[0., 0., 1.], [-1., 0., 0.], [0., 1., 0.]])
    optical_to_private_camera = np.diag([1., -1., 1.])
    t = np.eye(4)
    t[:3, :3] = private_to_ros_ground @ (rr @ rp @ ry).T @ optical_to_private_camera
    t[2, 3] = float(p["camera_height"])
    return validate_transform(t)


def floor_intersections(pixels, K, transform):
    """Known rectified pixels -> rays -> rigid transform -> plane ground_z=0."""
    pixels = np.asarray(pixels, dtype=float)
    if pixels.shape in ((0,), (0, 2)):
        pixels = np.empty((0, 2))
    if pixels.ndim != 2 or pixels.shape[1] != 2 or not np.isfinite(pixels).all():
        raise ValueError("finite virtual pixels required")
    K = np.asarray(K, dtype=float)
    if (K.shape != (3, 3) or not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0
            or not np.allclose(K[2], [0, 0, 1], rtol=0, atol=1e-12) or abs(np.linalg.det(K)) < 1e-15):
        raise ValueError("valid pinhole intrinsic matrix required")
    t = validate_transform(transform)
    optical = np.column_stack((pixels, np.ones(len(pixels)))) @ np.linalg.inv(K).T
    optical /= np.linalg.norm(optical, axis=1)[:, None]
    rays = optical @ t[:3, :3].T
    result = []
    for ray in rays:
        x, z, radial, floor_x, floor_y, floor_z = (None,)*6
        if ray[2] >= -.03:
            reason = "not_downward_floor_ray"
        else:
            scale = -t[2, 3]/ray[2]
            point = t[:3, 3] + scale*ray
            floor_x, floor_y, floor_z = map(float, point)
            x, z = -floor_y, floor_x  # comparison only, same axes as existing CSV
            radial = math.hypot(floor_x, floor_y)
            if not np.isfinite(point).all() or z <= 0:
                reason = "invalid_or_nonforward_floor_intersection"
            elif not .2 <= radial <= 4.:
                reason = "outside_radial_diagnostic_range"
            else:
                reason = "valid"
        result.append(dict(x_m=x, z_m=z, radial_m=radial, reason=reason,
                           ground_x_m=floor_x, ground_y_m=floor_y, ground_z_m=floor_z,
                           floor_contact_verified=False, usable_for_ffb=False))
    return result


def project_columns(columns, p, view=VirtualView(), *, quantized=False):
    points = np.asarray(columns, dtype=float)
    Kraw, radius = equidistant_K(p)
    transform = optical_to_ground_transform(p)
    if points.shape in ((0,), (0, 2)):
        return []
    if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
            or np.any(points < 0) or np.any(points[:, 0] >= 1280) or np.any(points[:, 1] >= 720)):
        raise ValueError("finite native1280x720 pixels required")
    rho = np.linalg.norm(points-Kraw[:2, 2], axis=1)
    native_valid = (rho > 1e-9) & (rho < radius)  # retain existing optical-centre exclusion
    uv = np.full_like(points, np.nan)
    if native_valid.any():
        uv[native_valid] = cv2.fisheye.undistortPoints(points[native_valid].reshape(-1, 1, 2), Kraw,
                                                       np.zeros(4), P=view.K).reshape(-1, 2)
    in_view = (native_valid & np.isfinite(uv).all(axis=1)
               & (uv[:, 0] >= 0) & (uv[:, 0] <= view.width-1)
               & (uv[:, 1] >= 0) & (uv[:, 1] <= view.height-1))
    used = np.rint(uv) if quantized else uv
    intersections = floor_intersections(used[in_view], view.K, transform)
    intersection_index = iter(intersections)
    result = []
    for i, pixel in enumerate(points):
        if in_view[i]:
            record = next(intersection_index)
        else:
            reason = "outside_virtual_view" if native_valid[i] else "outside_front_lens_or_optical_centre"
            record = dict(x_m=None, z_m=None, radial_m=None, ground_x_m=None, ground_y_m=None, ground_z_m=None,
                          reason=reason, floor_contact_verified=False, usable_for_ffb=False)
        record.update(pixel_x=float(pixel[0]), pixel_y=float(pixel[1]),
                      virtual_u=float(uv[i, 0]) if np.isfinite(uv[i, 0]) else None,
                      virtual_v=float(uv[i, 1]) if np.isfinite(uv[i, 1]) else None,
                      used_u=float(used[i, 0]) if in_view[i] else None,
                      used_v=float(used[i, 1]) if in_view[i] else None,
                      quantized=quantized, in_virtual_view=bool(in_view[i]))
        result.append(record)
    return result


def inverse_maps(p, view=VirtualView()):
    Kraw, radius = equidistant_K(p)
    mx, my = cv2.fisheye.initUndistortRectifyMap(Kraw, np.zeros(4), np.eye(3), view.K,
                                               (view.width, view.height), cv2.CV_32FC1)
    valid = ((mx >= 0) & (mx < 1280) & (my >= 0) & (my < 720)
             & (np.hypot(mx-Kraw[0, 2], my-Kraw[1, 2]) < radius))
    return mx, my, valid


def rectify_in_memory(image, maps):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("native1280x720 uint8 BGR image required")
    mx, my, valid = maps
    if mx.shape != my.shape or mx.shape != valid.shape:
        raise ValueError("map dimensions must match")
    rectified = cv2.remap(image, mx, my, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    rectified[~valid] = 0
    return rectified
