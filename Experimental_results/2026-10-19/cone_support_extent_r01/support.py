"""Image-space lower envelope and observed line support; NO ground projection."""
import math

import cv2
import numpy as np


SETTINGS = dict(trim_fraction=.1, min_columns=8, min_span_px=6., min_coverage=.8,
                max_column_gap_px=2., max_abs_slope=.75, max_perpendicular_p90_px=1.5,
                display_padding_px=1., fit_distance="DIST_HUBER", fit_param=0., fit_reps=.01, fit_aeps=.01)


def lower_envelope(contour_points):
    p = np.asarray(contour_points)
    if (p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.issubdtype(p.dtype, np.number)
            or np.iscomplexobj(p) or not np.isfinite(p).all() or not np.equal(p, np.rint(p)).all()):
        raise ValueError("at least three finite integer xy native contour points required")
    xs = np.unique(p[:, 0])
    return np.asarray([(x, np.max(p[p[:, 0] == x, 1])) for x in xs], dtype=float)


def describe_support(contour_points):
    envelope = lower_envelope(contour_points)
    lo, hi = float(envelope[0, 0]), float(envelope[-1, 0])
    lower, upper = lo + SETTINGS["trim_fraction"]*(hi-lo), hi-SETTINGS["trim_fraction"]*(hi-lo)
    selected = envelope[(envelope[:, 0] >= lower) & (envelope[:, 0] <= upper)]
    result = dict(envelope_available=True, envelope_columns=len(envelope), full_x_lo=lo, full_x_hi=hi,
                  support_columns=len(selected), x_lo=None, x_hi=None, span_px=None, coverage=None,
                  max_gap_px=None, line_fitted=False, line_consistent=False, reason="insufficient_support",
                  slope=None, line_y_lo=None, line_y_hi=None, perpendicular_residual_p90_px=None,
                  perpendicular_residual_max_px=None, display_band_halfwidth_px=None,
                  floor_contact_verified=False, usable_for_ffb=False)
    if len(selected):
        x_lo, x_hi = float(selected[0, 0]), float(selected[-1, 0])
        span = x_hi-x_lo
        result.update(x_lo=x_lo, x_hi=x_hi, span_px=span, coverage=len(selected)/(span+1),
                      max_gap_px=float(np.max(np.diff(selected[:, 0]))) if len(selected)>1 else None)
    if len(selected) < SETTINGS["min_columns"] or result["span_px"] < SETTINGS["min_span_px"]:
        return result, envelope, selected
    if result["coverage"] < SETTINGS["min_coverage"] or result["max_gap_px"] > SETTINGS["max_column_gap_px"]:
        return dict(result, reason="disconnected_support"), envelope, selected
    vx, vy, x0, y0 = map(float, cv2.fitLine(selected.astype(np.float32), cv2.DIST_HUBER, 0, .01, .01).ravel())
    if abs(vx) < 1e-6:
        return dict(result, reason="near_vertical_line"), envelope, selected
    slope = vy/vx
    residuals = np.abs(vy*(selected[:, 0]-x0)-vx*(selected[:, 1]-y0))
    p90 = float(np.percentile(residuals, 90))
    result.update(line_fitted=True, slope=slope, line_y_lo=y0+slope*(x_lo-x0), line_y_hi=y0+slope*(x_hi-x0),
                  perpendicular_residual_p90_px=p90, perpendicular_residual_max_px=float(max(residuals)),
                  display_band_halfwidth_px=p90/abs(vx)+SETTINGS["display_padding_px"])
    if abs(slope) > SETTINGS["max_abs_slope"]:
        result["reason"] = "steep_lower_boundary"
    elif p90 > SETTINGS["max_perpendicular_p90_px"]:
        result["reason"] = "nonlinear_or_multiedge_lower_boundary"
    else:
        result.update(line_consistent=True, reason="consistent_visible_colour_support_NOT_verified_floor_contact")
    return result, envelope, selected


def line_y_at(result, x):
    """Only interpolate INSIDE observed support; no extrapolation across missing base."""
    if (not result["line_fitted"] or not math.isfinite(float(x))
            or not result["x_lo"] <= x <= result["x_hi"]):
        return None
    return result["line_y_lo"] + result["slope"]*(x-result["x_lo"])


def native_contour(image, box, frozen_reader):
    """Reuse frozen segmentation guards; return a contour, never save a processed image."""
    from cone_observation import checked_bbox
    frozen = frozen_reader(image, box)
    legacy = frozen["legacy"]
    if not legacy["colour_candidate"]:
        return None, legacy
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    left, top, right, bottom = math.floor(x1)-4, math.floor(y1)-4, math.ceil(x2)+4, math.ceil(y2)+4
    hsv = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(cv2.inRange(hsv, (0, 80, 30), (10, 255, 255)),
                         cv2.inRange(hsv, (170, 80, 30), (179, 255, 255)))
    mask = cv2.bitwise_or(mask, cv2.inRange(hsv, (15, 80, 30), (40, 255, 255)))
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    contour = max((c for c in contours if cv2.contourArea(c) >= 20), key=cv2.contourArea)
    return contour[:, 0, :]+[left, top], legacy
