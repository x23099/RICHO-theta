"""下側探索のオフライン反証実験。liveへ接続せず、接地を認定しない。"""
import copy
import hashlib
import math

import cv2
import numpy as np

from angular_fisheye_geometry import unproject
from cone_distance_core import support_from_colour_mask
from cone_motion_range import checked_current_support
from cone_observation import checked_bbox
from cone_upper_support_candidate import _lower_support, observe_upper_completion
from theta_rtc_frames import native_frame


def bottom_context(image, box, camera, colour, seed, padding):
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    left, right = math.floor(x1)-4, math.ceil(x2)+4
    top, bottom = math.floor(y1)-4, math.ceil(y2)+padding
    info = dict(crop_xyxy=[left, top, right, bottom], bottom_padding_px=padding,
                top_padding_px=4, lateral_padding_px=4, component=None)
    if left < 0 or top < 0 or right > 1280 or bottom > 720:
        return dict(info, reason="context_outside_native_image"), None
    _, valid = unproject([[x, y] for x in (left, right-1) for y in (top, bottom-1)],
                         camera, image_size=(1280, 720))
    if not valid.all():
        return dict(info, reason="context_outside_front_angular_domain"), None
    a, b, c, d = seed
    if not (left <= a < c <= right and top <= b < d <= bottom):
        return dict(info, reason="original_seed_outside_context"), None
    hsv = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    if colour == "red":
        mask = cv2.inRange(hsv, (0, 80, 30), (10, 255, 255)) | cv2.inRange(hsv, (170, 80, 30), (179, 255, 255))
    elif colour == "yellow":
        mask = cv2.inRange(hsv, (15, 80, 30), (40, 255, 255))
    else:
        raise ValueError("original seed-selected red/yellow only")
    observation = support_from_colour_mask(mask, left, top)
    info["observation"] = observation
    labels = cv2.connectedComponents(mask, connectivity=8)[1]
    present = np.unique(labels[b-top:d-top, a-left:c-left])
    present = present[present != 0]
    if len(present) != 1:
        return dict(info, reason="seed_not_one_colour_component"), None
    label = int(present[0])
    contours = sorted((p for p in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
                       if cv2.contourArea(p) >= 20), key=cv2.contourArea, reverse=True)
    if not contours or labels[contours[0][0, 0, 1], contours[0][0, 0, 0]] != label:
        return dict(info, reason="largest_colour_component_not_seeded"), None
    yy, xx = np.nonzero(labels == label)
    pixels = np.column_stack((xx+left, yy+top)).astype("<i4")
    touches = dict(left=bool(np.any(xx == 0)), right=bool(np.any(xx == right-left-1)),
                   top=bool(np.any(yy == 0)), bottom=bool(np.any(yy == bottom-top-1)))
    info["component"] = dict(pixel_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
        pixel_count=len(pixels), touches=touches, observed_lower_support=_lower_support(pixels))
    if observation["point"] is not None:
        px, py = observation["point"]
        if labels[py-top, px-left] != label:
            return dict(info, reason="support_not_connected_to_original_seed"), None
    return dict(info, reason=observation["reason"]), pixels


def probe_bottom_extension(image, box, camera):
    native_frame(image)
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    baseline = observe_upper_completion(image, box, camera)
    result = dict(baseline=copy.deepcopy(baseline), guarded_observation=copy.deepcopy(baseline),
        contexts=[], diagnostic_only=True, live_authorized=False, guarded_candidate=False,
        closure_only_point_NOT_safe=None, reason="baseline_preserved", physical_metric_verified=False,
        floor_contact_verified=False, controlling_distance=False, usable_for_ffb=False)
    if (baseline.get("point") is not None or baseline.get("reason") != "colour_contour_reaches_roi_edge"
            or baseline.get("selected_colour") not in ("red", "yellow")):
        return result
    original, old_pixels = bottom_context(image, box, camera, baseline["selected_colour"], baseline["seed_xyxy"], 4)
    result["contexts"].append(original)
    if old_pixels is None:
        return dict(result, reason=original["reason"])
    touches = original["component"]["touches"]
    if not touches["bottom"] or any(touches[k] for k in ("left", "right", "top")):
        return dict(result, reason="not_bottom_only_contact")
    padding = min(16, max(8, math.ceil(.2*(y2-y1))))
    expanded = []
    for pad in (padding, 2*padding):
        ctx, pixels = bottom_context(image, box, camera, baseline["selected_colour"], baseline["seed_xyxy"], pad)
        result["contexts"].append(ctx)
        if pixels is None or ctx["observation"]["point"] is None:
            return dict(result, reason="context_rejected:"+ctx["reason"])
        if any(ctx["component"]["touches"].values()):
            return dict(result, reason="expanded_component_not_closed")
        expanded.append((ctx, pixels))
    (first, pixels), (second, _) = expanded
    if (first["component"]["pixel_sha256"] != second["component"]["pixel_sha256"]
            or first["observation"] != second["observation"]):
        return dict(result, reason="component_or_support_changes_across_contexts")
    point, quality_reason = checked_current_support(first["observation"])
    if point is None:
        return dict(result, reason=quality_reason)
    result["closure_only_point_NOT_safe"] = point
    if not {tuple(p) for p in old_pixels} <= {tuple(p) for p in pixels}:
        return dict(result, reason="original_seeded_pixels_not_preserved")
    if original["component"]["observed_lower_support"] != first["observation"]["support"]:
        return dict(result, reason="original_lower_support_changed")
    if point not in original["component"]["observed_lower_support"]:
        return dict(result, reason="point_not_in_original_observed_support")
    if not x1 <= point[0] <= x2 or not y1 <= point[1] <= y2:
        return dict(result, reason="point_outside_original_float_bbox")
    candidate = copy.deepcopy(baseline)
    candidate.update(copy.deepcopy(first["observation"]))
    candidate.update(reason="unverified_bottom_preserved_support_probe",
                     physical_metric_verified=False, floor_contact_verified=False,
                     controlling_distance=False, usable_for_ffb=False)
    return dict(result, guarded_observation=candidate, guarded_candidate=True,
                reason="same_closed_pair_original_lower_support_and_point_preserved")
