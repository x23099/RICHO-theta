"""Colour-separated support prototype: SHADOW ONLY, never metric/FFB authority.

Colour is selected from a fixed upper-body seed BEFORE assessing whether its
contour passes. A failed yellow contour never falls back to a red sticker.
Seed settings are exploratory image association assumptions, not validation.
"""
from dataclasses import dataclass
import math

import cv2
import numpy as np

from angular_fisheye_geometry import unproject
from cone_observation import checked_bbox
from theta_rtc_frames import native_frame
from cone_distance_core import support_from_colour_mask


@dataclass(frozen=True)
class ColourSeedSettings:
    central_width_fraction: float = .1
    upper_y_start_fraction: float = .2
    upper_y_end_fraction: float = .4
    min_coloured_pixels: int = 20
    min_dominant_fraction: float = .9

    def __post_init__(self):
        values = (self.central_width_fraction, self.upper_y_start_fraction,
                  self.upper_y_end_fraction, self.min_dominant_fraction)
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                or not 0 < self.central_width_fraction <= 1
                or not 0 <= self.upper_y_start_fraction < self.upper_y_end_fraction <= 1
                or not .5 < self.min_dominant_fraction <= 1
                or type(self.min_coloured_pixels) is not int or self.min_coloured_pixels < 1):
            raise ValueError("finite colour-seed settings required")


def observe_separated_support(image, box, camera, settings=None):
    native_frame(image)
    settings = settings or ColourSeedSettings()
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    result = dict(support=None, point=None, reason="", selected_colour=None,
                  method="upper_body_colour_seed_shadow_v1", seed_xyxy=None,
                  seed_red_pixels=0, seed_yellow_pixels=0, seed_dominant_fraction=None,
                  controlling_distance=False, floor_contact_verified=False, usable_for_ffb=False)
    _, valid = unproject([[x, y] for x in (x1, x2) for y in (y1, y2)], camera, image_size=(1280, 720))
    if not valid.all():
        return dict(result, reason="bbox_crosses_front_angular_domain")
    left, top, right, bottom = math.floor(x1)-4, math.floor(y1)-4, math.ceil(x2)+4, math.ceil(y2)+4
    if left < 0 or top < 0 or right > 1280 or bottom > 720:
        return dict(result, reason="expanded_roi_outside_native_image")
    hsv = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    masks = dict(red=(cv2.inRange(hsv, (0, 80, 30), (10, 255, 255))
                      | cv2.inRange(hsv, (170, 80, 30), (179, 255, 255))),
                 yellow=cv2.inRange(hsv, (15, 80, 30), (40, 255, 255)))
    center = (x1+x2)/2
    half = (x2-x1)*settings.central_width_fraction/2
    a, c = math.floor(center-half), math.ceil(center+half)
    b = math.floor(y1+(y2-y1)*settings.upper_y_start_fraction)
    d = math.ceil(y1+(y2-y1)*settings.upper_y_end_fraction)
    result["seed_xyxy"] = [a, b, c, d]
    counts = {colour: int(np.count_nonzero(mask[b-top:d-top, a-left:c-left]))
              for colour, mask in masks.items()}
    result.update(seed_red_pixels=counts["red"], seed_yellow_pixels=counts["yellow"])
    total = sum(counts.values())
    if total < settings.min_coloured_pixels:
        return dict(result, reason="insufficient_upper_body_colour_evidence")
    dominant = max(counts, key=counts.get)
    fraction = counts[dominant]/total
    result["seed_dominant_fraction"] = fraction
    if fraction < settings.min_dominant_fraction:
        return dict(result, reason="ambiguous_upper_body_colour")
    result["selected_colour"] = dominant
    observation = support_from_colour_mask(masks[dominant], left, top)
    # Ensure the accepted contour corresponds to the seed; an unrelated lower
    # patch of the same hue must not replace the seeded upper cone component.
    if observation["point"] is not None:
        components = cv2.connectedComponents(masks[dominant], connectivity=8)[1]
        px, py = observation["point"]
        label = components[py-top, px-left]
        if label == 0 or not np.any(components[b-top:d-top, a-left:c-left] == label):
            observation = dict(support=None, point=None, reason="support_not_connected_to_body_seed")
    result.update(observation)
    return result
