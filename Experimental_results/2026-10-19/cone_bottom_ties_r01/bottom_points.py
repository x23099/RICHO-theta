"""Two image-only bottom representatives, never surveyed physical contact."""
import math

import cv2
import numpy as np


def select_bottom(points, mode):
    points = np.asarray(points)
    if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3
            or not np.issubdtype(points.dtype, np.number) or not np.isfinite(points).all()):
        raise ValueError("at least three finite xy contour points required")
    count = min(len(points), max(3, int(math.ceil(.08*len(points)))))
    cutoff_y = float(np.sort(points[:, 1])[-count])
    if mode == "legacy":
        chosen = points[np.lexsort((points[:, 0], -points[:, 1]))][:count]
    elif mode == "tie_inclusive":
        chosen = points[points[:, 1] >= cutoff_y]
    else:
        raise ValueError("explicit legacy or tie_inclusive mode required")
    pixel = np.median(chosen, axis=0)
    all_bottom = points[points[:, 1] >= cutoff_y]
    return dict(pixel_x=float(pixel[0]), pixel_y=float(pixel[1]), contour_points=len(points),
                nominal_bottom_count=count, selected_points=len(chosen), cutoff_y=cutoff_y,
                cutoff_ties=int(sum(points[:, 1] == cutoff_y)),
                excluded_cutoff_ties=int(len(all_bottom)-len(chosen)),
                bottom_span_px=float(np.ptp(all_bottom[:, 0])))


def extract_bottoms(image, box):
    """Identical V30 mask/contour guards; change ONLY tie handling of bottom points."""
    from cone_observation import checked_bbox
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("native1280x720 uint8 BGR required")
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    left, top, right, bottom = math.floor(x1)-4, math.floor(y1)-4, math.ceil(x2)+4, math.ceil(y2)+4
    common = dict(colour_candidate=False, reason="", pixel_x=None, pixel_y=None,
                  floor_contact_verified=False, usable_for_ffb=False)

    def reject(reason):
        return {name: dict(common, reason=reason) for name in ("legacy", "tie_inclusive")}

    if left < 0 or top < 0 or right > 1280 or bottom > 720:
        return reject("expanded_roi_outside_native_image")
    hsv = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(cv2.inRange(hsv, (0, 80, 30), (10, 255, 255)),
                         cv2.inRange(hsv, (170, 80, 30), (179, 255, 255)))
    mask = cv2.bitwise_or(mask, cv2.inRange(hsv, (15, 80, 30), (40, 255, 255)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = sorted((c for c in contours if cv2.contourArea(c) >= 20), key=cv2.contourArea, reverse=True)
    if not contours:
        return reject("no_supported_colour_contour")
    contour = contours[0]
    if len(contours) > 1 and cv2.contourArea(contours[1]) >= .25*cv2.contourArea(contour):
        return reject("ambiguous_competing_colour_contours")
    bx, by, bw, bh = cv2.boundingRect(contour)
    if bx == 0 or by == 0 or bx+bw >= right-left or by+bh >= bottom-top:
        return reject("colour_contour_reaches_roi_edge")
    if bw < 5 or bh < 8:
        return reject("insufficient_colour_extent")
    result = {}
    for mode in ("legacy", "tie_inclusive"):
        selected = select_bottom(contour[:, 0, :], mode)
        selected["pixel_x"] += left
        selected["pixel_y"] += top
        selected["cutoff_y"] += top
        result[mode] = dict(common, **selected)
        result[mode].update(colour_candidate=True, reason="unverified_visible_colour_bottom")
    return result
