"""Bounded lateral colour-component completion: OFFLINE/SHADOW ONLY.

Never called by the live distance engine. Preserve existing colour-shadow
acceptances verbatim; only analyse lateral-only crop contacts. Neither a
closed colour component nor this observation verifies physical floor contact.
"""
import hashlib
import math

import cv2
import numpy as np

from angular_fisheye_geometry import unproject
from cone_colour_support_candidate import observe_separated_support
from cone_distance_core import support_from_colour_mask
from cone_observation import checked_bbox
from theta_rtc_frames import native_frame


def _context(image, box, camera, colour, seed, lateral_padding):
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    left, right = math.floor(x1)-lateral_padding, math.ceil(x2)+lateral_padding
    top, bottom = math.floor(y1)-4, math.ceil(y2)+4
    info = dict(crop_xyxy=[left, top, right, bottom], lateral_padding_px=lateral_padding,
                vertical_padding_px=4, reason="", component=None)
    if left < 0 or top < 0 or right > 1280 or bottom > 720:
        return dict(info, reason="context_outside_native_image"), None, None
    _, valid = unproject([[x, y] for x in (left, right-1) for y in (top, bottom-1)],
                         camera, image_size=(1280, 720))
    if not valid.all():
        return dict(info, reason="context_outside_front_angular_domain"), None, None
    hsv = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    # Frozen HSV ranges copied from v1 for this isolated comparator. Do not
    # retune by context closure or fall back from yellow to red components.
    if colour == "red":
        mask = cv2.inRange(hsv, (0, 80, 30), (10, 255, 255)) | cv2.inRange(hsv, (170, 80, 30), (179, 255, 255))
    elif colour == "yellow":
        mask = cv2.inRange(hsv, (15, 80, 30), (40, 255, 255))
    else:
        raise ValueError("original seed-selected red or yellow required")
    observation = support_from_colour_mask(mask, left, top)
    labels = cv2.connectedComponents(mask, connectivity=8)[1]
    a, b, c, d = seed
    present = np.unique(labels[b-top:d-top, a-left:c-left])
    present = present[present != 0]
    if len(present) != 1:
        return dict(info, reason="seed_not_one_colour_component", observation=observation), None, None
    label = int(present[0])
    contours = sorted((contour for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
                       if cv2.contourArea(contour) >= 20), key=cv2.contourArea, reverse=True)
    if not contours or labels[contours[0][0, 0, 1], contours[0][0, 0, 0]] != label:
        return dict(info, reason="largest_colour_component_not_seeded", observation=observation), None, None
    yy, xx = np.nonzero(labels == label)
    pixels = np.column_stack((xx+left, yy+top)).astype("<i4")
    touches = dict(left=bool(np.any(xx == 0)), right=bool(np.any(xx == right-left-1)),
                   top=bool(np.any(yy == 0)), bottom=bool(np.any(yy == bottom-top-1)))
    component = dict(pixel_count=len(pixels), pixel_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
        bounds_xyxy=[int(xx.min()+left), int(yy.min()+top), int(xx.max()+left), int(yy.max()+top)],
        touches=touches)
    if observation["point"] is not None:
        px, py = observation["point"]
        if labels[py-top, px-left] != label:
            return dict(info, reason="support_not_connected_to_original_seed", component=component, observation=observation), None, None
    return dict(info, component=component, observation=observation, reason=observation["reason"]), pixels, label


def observe_lateral_completion(image, box, camera):
    """Diagnostic candidate only. Never changes the old accepted point.

    Only original 4px lateral-only contacts enter the two-context experiment.
    Both crops must close, retain the seeded component exactly, preserve all
    original seeded pixels, and give identical support with its chosen point
    inside the original detector bbox. Pads: p=clip(ceil(.2*width),8,16), 2p.
    """
    native_frame(image)
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    baseline = observe_separated_support(image, box, camera)
    result = dict(baseline, method="bounded_lateral_completion_shadow_v1",
        original_shadow_reason=baseline["reason"], original_shadow_point=baseline["point"],
        completion_attempted=False, completion_granted=False, completion_reason="not_eligible",
        contexts=[], controlling_distance=False, physical_metric_verified=False,
        floor_contact_verified=False, usable_for_ffb=False)
    if baseline["point"] is not None:
        return dict(result, completion_reason="existing_shadow_point_preserved")
    if baseline["reason"] != "colour_contour_reaches_roi_edge" or baseline["selected_colour"] not in ("red", "yellow"):
        return result
    seed = baseline["seed_xyxy"]
    original, old_pixels, _ = _context(image, box, camera, baseline["selected_colour"], seed, 4)
    result["contexts"].append(original)
    if old_pixels is None:
        return dict(result, completion_reason=original["reason"])
    touches = original["component"]["touches"]
    if touches["top"] or touches["bottom"] or not (touches["left"] or touches["right"]):
        return dict(result, completion_reason="not_lateral_only_contact")
    result["completion_attempted"] = True
    padding = min(16, max(8, math.ceil(.2*(x2-x1))))
    all_pixels = []
    for pad in (padding, 2*padding):
        context, pixels, _ = _context(image, box, camera, baseline["selected_colour"], seed, pad)
        result["contexts"].append(context)
        if pixels is None or context["observation"]["point"] is None:
            return dict(result, completion_reason="context_rejected:"+context["reason"])
        if any(context["component"]["touches"].values()):
            return dict(result, completion_reason="context_component_not_closed")
        # Existing point/ambiguity/envelope guards are applied unchanged to
        # each context by support_from_colour_mask, not bypassed by closure.
        all_pixels.append(pixels)
    first, second = result["contexts"][-2:]
    if (first["component"]["pixel_sha256"] != second["component"]["pixel_sha256"]
            or first["observation"] != second["observation"]):
        return dict(result, completion_reason="component_or_support_changes_across_contexts")
    old_set = {tuple(p) for p in old_pixels}
    new_set = {tuple(p) for p in all_pixels[0]}
    if not old_set <= new_set:
        return dict(result, completion_reason="original_seeded_pixels_not_preserved")
    point = first["observation"]["point"]
    if not (x1 <= point[0] <= x2 and y1 <= point[1] <= y2):
        return dict(result, completion_reason="completed_point_outside_original_bbox")
    result.update(first["observation"])
    result.update(reason="unverified_lateral_completed_colour_support", completion_granted=True,
        completion_reason="same_closed_seeded_component_and_support_in_two_contexts")
    return result
