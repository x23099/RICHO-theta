"""Conditional floor projection of actual image columns, NOT a contact estimator."""
from collections import Counter
import math

import numpy as np

from ground_contact import dual_fisheye_pixels_to_vehicle_rays

PARAMETERS = ("camera_height", "pitch_deg", "roll_deg", "yaw_deg", "radius_scale",
              "front_cx_offset", "front_cy_offset", "back_cx_offset", "back_cy_offset")
RANGE_FIELDS = ("x_min_m", "x_max_m", "x_span_m", "x_median_m",
                "z_min_m", "z_max_m", "z_span_m", "z_median_m",
                "radial_min_m", "radial_max_m")


def project_columns(columns, parameters):
    """Return one output per supplied column; invalid rays are never discarded."""
    for name in PARAMETERS:
        if name not in parameters or not math.isfinite(float(parameters[name])):
            raise ValueError("complete finite camera parameters required")
    if parameters["camera_height"] <= 0 or parameters["radius_scale"] <= 0:
        raise ValueError("positive camera height and radius required")
    points = np.asarray(columns, dtype=float)
    if points.shape in ((0,), (0, 2)):
        return []
    if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
            or not np.array_equal(points, np.round(points))
            or np.any(points < 0) or np.any(points[:, 0] >= 1280) or np.any(points[:, 1] >= 720)
            or np.any(np.diff(points[:, 0]) <= 0)):
        raise ValueError("sorted unique integer native1280x720 columns required")
    selected, rays = dual_fisheye_pixels_to_vehicle_rays(points, 1280, 720, parameters,
                                                        lens="front", front_lens="left")
    by_pixel = {tuple(pixel): ray for pixel, ray in zip(selected, rays)}
    result = []
    for pixel in points:
        ray = by_pixel.get(tuple(pixel))
        x, z, radial = None, None, None
        if ray is None:
            reason = "outside_front_lens_or_optical_centre"
        elif ray[1] >= -.03:
            reason = "not_downward_floor_ray"
        else:
            scale = -float(parameters["camera_height"])/ray[1]
            x, z = float(scale*ray[0]), float(scale*ray[2])
            radial = math.hypot(x, z)
            if not all(math.isfinite(v) for v in (x, z, radial)) or z <= 0:
                reason = "invalid_or_nonforward_floor_intersection"
            elif not .2 <= radial <= 4.:
                reason = "outside_radial_diagnostic_range"
            else:
                reason = "valid"
        result.append(dict(pixel_x=int(pixel[0]), pixel_y=int(pixel[1]),
                           x_m=x, z_m=z, radial_m=radial, reason=reason,
                           floor_contact_verified=False, usable_for_ffb=False))
    return result


def bounds(points):
    """All-or-withhold; never report a truncated valid subset as the full range."""
    bad = Counter(p["reason"] for p in points if p["reason"] != "valid")
    complete = bool(points) and not bad
    result = dict(input_columns=len(points), valid_columns=len(points)-sum(bad.values()),
                  invalid_columns=sum(bad.values()), invalid_reasons=dict(sorted(bad.items())),
                  projection_complete=complete,
                  projection_reason="complete" if complete else ("no_observed_curve" if not points else "incomplete_projection"),
                  **dict.fromkeys(RANGE_FIELDS))
    if complete:
        x, z, radial = (np.array([p[k] for p in points]) for k in ("x_m", "z_m", "radial_m"))
        result.update(x_min_m=float(x.min()), x_max_m=float(x.max()), x_span_m=float(np.ptp(x)),
                      x_median_m=float(np.median(x)), z_min_m=float(z.min()), z_max_m=float(z.max()),
                      z_span_m=float(np.ptp(z)), z_median_m=float(np.median(z)),
                      radial_min_m=float(radial.min()), radial_max_m=float(radial.max()))
    return result


def compare_columns(first, second):
    """Difference second-first at exactly matching observed pixels, not extents."""
    a = [(p["pixel_x"], p["pixel_y"]) for p in first]
    b = [(p["pixel_x"], p["pixel_y"]) for p in second]
    if a != b:
        raise ValueError("identical observed pixel columns required for model comparison")
    complete = bool(first) and all(p["reason"] == "valid" for p in first+second)
    result = dict(comparison_complete=complete, compared_columns=len(first) if complete else 0,
                  dx_median_m=None, dz_median_m=None, dx_abs_max_m=None, dz_abs_max_m=None,
                  floor_contact_verified=False, usable_for_ffb=False)
    if complete:
        dx = np.array([q["x_m"]-p["x_m"] for p, q in zip(first, second)])
        dz = np.array([q["z_m"]-p["z_m"] for p, q in zip(first, second)])
        result.update(dx_median_m=float(np.median(dx)), dz_median_m=float(np.median(dz)),
                      dx_abs_max_m=float(max(abs(dx))), dz_abs_max_m=float(max(abs(dz))))
    return result
