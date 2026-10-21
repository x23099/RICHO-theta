"""Offline known upright segment using two rays, NOT a calibrated cone detector."""
import math
import numpy as np
from fisheye_floor_geometry import checked_transform

HEIGHT_M = .73  # user measured floor-to-tip including base, 2026-10-21
BASE_HALF_M = .375/2


def empty(reason):
    return dict(estimated=False, reason=reason, z_forward_m=None, x_right_m=None,
                base_height_m=None, tip_z_m=None, tip_height_m=None, residual_m=None,
                condition_number=None, ray_angle_deg=None, in_diagnostic_range=False,
                segment_consistent=False, calibrated_intrinsics=False,
                physical_endpoint_correspondence_verified=False, usable_for_ffb=False)


def height_position(uv, K, transform, *, height_m=HEIGHT_M, tip_forward_offset_m=0.):
    """uv order: tip, base. Target axes forward/left/up. No floor constraint.

    Solve lambda_top R K^-1 p_top - lambda_base R K^-1 p_base =
    (tip_forward_offset_m, 0, height_m). With correct corresponding physical
    points and rotation this handles unequal optical depths and pitch/roll.
    Offset is an explicit physical assumption, never fitted from reference Z.
    """
    if any(np.iscomplexobj(x) for x in (uv, K)):
        raise ValueError('real endpoints/intrinsics required')
    uv, K = np.asarray(uv, float), np.asarray(K, float)
    T = checked_transform(transform)
    if (uv.shape != (2,2) or not np.isfinite(uv).all() or K.shape != (3,3)
            or not np.isfinite(K).all() or not np.allclose(K[2], [0,0,1], atol=1e-12, rtol=0)
            or abs(K[0,1])+abs(K[1,0]) > 1e-12 or min(K[0,0],K[1,1]) <= 0
            or not math.isfinite(height_m) or height_m <= 0
            or not math.isfinite(tip_forward_offset_m) or tip_forward_offset_m < 0):
        raise ValueError('finite tip/base, positive height, zero-skew K and nonnegative offset required')
    directions = np.linalg.solve(K, np.column_stack((uv, np.ones(2))).T).T @ T[:3,:3].T
    units = directions/np.linalg.norm(directions, axis=1)[:,None]
    angle = float(np.degrees(np.arccos(np.clip(units[0]@units[1], -1, 1))))
    if angle < .1:
        return dict(empty('coincident_or_insufficient_ray_angle'), ray_angle_deg=angle)
    A = np.column_stack((directions[0], -directions[1]))
    delta = np.array([tip_forward_offset_m, 0., height_m])
    scales, _, rank, singular = np.linalg.lstsq(A, delta, rcond=None)
    condition = float(singular[0]/singular[-1]) if singular[-1] > 0 else float('inf')
    residual = float(np.linalg.norm(A@scales-delta))
    details = dict(ray_angle_deg=angle, residual_m=residual, condition_number=condition)
    if rank < 2 or condition > 1e6 or np.any(scales <= 0):
        return dict(empty('nonpositive_or_degenerate_depth'), **details)
    positions = directions*scales[:,None]+T[:3,3]
    if not np.isfinite(positions).all() or np.any(positions[:,0] <= 0):
        return dict(empty('nonfinite_or_nonforward_position'), **details)
    tip, base = positions
    return dict(empty('unverified_tip_base_known_height_correspondence'), **details,
                estimated=True, z_forward_m=float(base[0]), x_right_m=float(-base[1]),
                base_height_m=float(base[2]), tip_z_m=float(tip[0]), tip_height_m=float(tip[2]),
                in_diagnostic_range=.2 <= np.hypot(*base[:2]) <= 4., segment_consistent=residual <= .02)


def contour_pair(contour):
    """Measured top-row median X and nearest actual lower-envelope column.

    Does not extrapolate a hidden base centre, fit a line, or use nominal Z.
    """
    p = np.asarray(contour)
    if (p.ndim != 2 or p.shape[1] != 2 or len(p) < 8 or np.iscomplexobj(p)
            or not np.isfinite(p).all() or not np.equal(p,np.rint(p)).all()):
        raise ValueError('actual finite integer native contour required')
    top_y = float(p[:,1].min())
    top_x = float(np.median(p[p[:,1] == top_y,0]))
    xs = np.unique(p[:,0])
    bottom_x = min(xs, key=lambda x:(abs(x-top_x), x))
    bottom_y = float(max(p[p[:,0] == bottom_x,1]))
    if bottom_y-top_y < 4:
        return None
    return np.array([[top_x,top_y],[float(bottom_x),bottom_y]])
