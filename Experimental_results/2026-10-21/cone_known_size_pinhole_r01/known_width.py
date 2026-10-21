"""Fixed known-width pinhole hypothesis, NOT verified base-edge correspondence."""
import math

import cv2
import numpy as np

from ground_contact import _lens_geometry
from fisheye_floor_geometry import checked_transform, legacy_front_diagnostic_geometry

VIRTUAL_K = np.array([[480., 0., 479.5], [0., 480., 479.5], [0., 0., 1.]])
VIRTUAL_SIZE = (960, 960)
BASE_SIDE_M = .375


def empty(reason):
    return dict(estimated=False, reason=reason, width_rectified_px=None, endpoint_v_difference_px=None,
                optical_z_m=None, x_right_m=None, z_forward_m=None, height_above_floor_m=None,
                horizontal_distance_m=None, in_diagnostic_range=False,
                calibrated_intrinsics=False, physical_width_correspondence_verified=False, usable_for_ffb=False)


def pinhole_width_position(endpoints_rectified, K, target_from_optical, width_m=BASE_SIDE_M):
    """Exact only for a known horizontal segment at equal optical Z.

    Optical x-right/y-down/z-forward; target ROS x-forward/y-left/z-up.
    Does not intersect floor or use height to scale depth. Unequal endpoint
    v is recorded, not silently replaced with a 'corrected' contact edge.
    """
    if np.iscomplexobj(endpoints_rectified) or np.iscomplexobj(K):
        raise ValueError("real endpoints and intrinsics required")
    uv, K = np.asarray(endpoints_rectified, float), np.asarray(K, float)
    transform = checked_transform(target_from_optical)
    if (uv.shape != (2, 2) or not np.isfinite(uv).all() or K.shape != (3, 3) or not np.isfinite(K).all()
            or min(K[0, 0], K[1, 1]) <= 0 or not np.allclose(K[2], [0, 0, 1], atol=1e-12, rtol=0)
            or abs(K[0, 1])+abs(K[1, 0]) > 1e-12 or not math.isfinite(width_m) or width_m <= 0):
        raise ValueError("two finite endpoints, zero-skew K and positive known width required")
    width = float(uv[1, 0]-uv[0, 0])
    if width < 4.:
        return empty("reversed_or_too_small_rectified_width")
    z = float(K[0, 0]*width_m/width)
    optical = np.linalg.solve(K, [*uv.mean(axis=0), 1.])*z
    target = transform[:3, :3] @ optical + transform[:3, 3]
    radial = float(np.hypot(target[0], target[1]))
    if not np.isfinite(target).all() or target[0] <= 0:
        return empty("nonfinite_or_nonforward_position")
    return dict(empty("unverified_visible_span_as_known_frontal_width"), estimated=True,
        width_rectified_px=width, endpoint_v_difference_px=float(uv[1, 1]-uv[0, 1]), optical_z_m=z,
        x_right_m=float(-target[1]), z_forward_m=float(target[0]), height_above_floor_m=float(target[2]),
        horizontal_distance_m=radial, in_diagnostic_range=.2 <= radial <= 4.)


def raw_to_rectified(points, parameters, K=VIRTUAL_K, size=VIRTUAL_SIZE):
    p = np.asarray(points)
    if (np.iscomplexobj(p) or p.shape != (2, 2) or not np.isfinite(p).all()
            or np.any(p < 0) or np.any(p[:, 0] >= 1280) or np.any(p[:, 1] >= 720)):
        raise ValueError("two finite full-native1280x720 endpoints required")
    p = p.astype(float)
    cx, cy, radius, _ = _lens_geometry(1280, 720, parameters, "front", "left")
    if not math.isfinite(radius) or radius <= 0 or np.any(np.linalg.norm(p-[cx, cy], axis=1) >= radius):
        return None
    focal = radius/(math.pi/2)
    Kraw = np.array([[focal, 0., cx], [0., focal, cy], [0., 0., 1.]])
    uv = cv2.fisheye.undistortPoints(p.reshape(-1, 1, 2), Kraw, np.zeros(4), P=np.asarray(K)).reshape(-1, 2)
    if (not np.isfinite(uv).all() or np.any(uv < 0) or np.any(uv[:, 0] > size[0]-1)
            or np.any(uv[:, 1] > size[1]-1)):
        return None
    return uv


def estimate_native_span(endpoints, parameters):
    uv = raw_to_rectified(endpoints, parameters)
    if uv is None:
        return empty("outside_native_lens_or_virtual_view")
    _, transform = legacy_front_diagnostic_geometry(parameters)
    return pinhole_width_position(uv, VIRTUAL_K, transform)


def envelope_endpoints(points):
    p = np.asarray(points)
    if (np.iscomplexobj(p) or p.ndim != 2 or p.shape[1] != 2 or len(p) < 8
            or not np.isfinite(p).all() or not np.equal(p, np.rint(p)).all()
            or np.any(np.diff(p[:, 0]) <= 0)):
        raise ValueError("full actual integer lower-envelope columns in X order required")
    return p[[0, -1]].astype(float)
