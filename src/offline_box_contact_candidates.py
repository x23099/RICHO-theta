"""Exploratory blue-box segmentation/contact candidates, OFFLINE ONLY.

No temporal target ROI, ground-truth labels, ROS, device or runtime integration.
Opening separates narrow connections; a surviving bright seed is required in
each dark-blue connected component. This does NOT prove semantic box identity.
"""
from dataclasses import dataclass
import math

import cv2
import numpy as np

from ground_contact import (_lens_geometry, blue_hsv_mask,
                            dual_fisheye_pixels_to_vehicle_rays,
                            estimate_ground_contact)


@dataclass(frozen=True)
class BoxCandidateSettings:
    weak_v_min: int = 10
    opening_size: int = 5
    minimum_seed_pixels: int = 100
    minimum_seed_fraction: float = .10
    bottom_central_fraction: float = .80
    body_s_min: int = 130

    def __post_init__(self):
        if not 0 <= self.weak_v_min <= 255:
            raise ValueError("weak_v_min must be in [0, 255]")
        if not 0 <= self.body_s_min <= 255:
            raise ValueError("body_s_min must be in [0, 255]")
        if self.opening_size < 1 or self.opening_size % 2 != 1:
            raise ValueError("opening_size must be positive and odd")
        if self.minimum_seed_pixels < 1:
            raise ValueError("minimum_seed_pixels must be positive")
        if not math.isfinite(self.minimum_seed_fraction) or not 0 < self.minimum_seed_fraction <= 1:
            raise ValueError("minimum_seed_fraction must be in (0, 1]")
        if not math.isfinite(self.bottom_central_fraction) or not 0 < self.bottom_central_fraction <= 1:
            raise ValueError("bottom_central_fraction must be in (0, 1]")


def seeded_components(frame, parameters, settings):
    """Return weak components containing enough strict-mask pixels after opening.

    The strict threshold is recorded/configured, not a learned target colour.
    There is no closing, so gaps in the mask are never synthetically filled.
    Both masks use the same recorded geometry and colour preprocessing.
    """
    strict_v = int(parameters.get("blue_ground_contact_hsv_v_min", 30))
    if settings.weak_v_min > strict_v:
        raise ValueError("weak value threshold must not exceed strict threshold")
    kernel = np.ones((settings.opening_size, settings.opening_size), np.uint8)
    strict = cv2.morphologyEx(blue_hsv_mask(frame, parameters), cv2.MORPH_OPEN, kernel)
    weak = cv2.morphologyEx(blue_hsv_mask(frame, dict(parameters, blue_ground_contact_hsv_v_min=settings.weak_v_min)),
                            cv2.MORPH_OPEN, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(weak, connectivity=8)
    seed_counts = np.bincount(labels[strict != 0], minlength=count)
    minimum = float(parameters.get("blue_ground_contact_min_area", 300))
    components = []
    for label in range(1, count):
        pixel_count = int(stats[label, cv2.CC_STAT_AREA])
        if pixel_count < minimum or seed_counts[label] < settings.minimum_seed_pixels:
            continue
        seed_fraction = float(seed_counts[label]) / pixel_count
        if seed_fraction < settings.minimum_seed_fraction:
            continue
        x, y, w, h = (int(v) for v in stats[label, :4])
        mask = (labels[y:y + h, x:x + w] == label).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        contour = max(contours, key=cv2.contourArea)
        contour = contour + np.array([[[x, y]]], np.int32)
        components.append({"contour": contour, "mask": mask, "origin": (x, y),
                           "pixel_count": pixel_count, "seed_fraction": seed_fraction})
    return components


def select_component(components, frame_shape, parameters):
    """Retain production area/front-ROI/aspect rules, then select largest area."""
    cx, cy, radius, _ = _lens_geometry(frame_shape[1], frame_shape[0], parameters, "front")
    configured = parameters.get("blue_ground_contact_max_aspect_ratio")
    aspect = math.inf if configured is None else float(configured)
    if configured is not None and (not math.isfinite(aspect) or aspect <= 0):
        raise ValueError("aspect limit must be positive and finite")
    candidates = []
    for component in components:
        contour = component["contour"]
        area = cv2.contourArea(contour)
        x, y, w, h = cv2.boundingRect(contour)
        if (area < float(parameters.get("blue_ground_contact_min_area", 300)) or w / h > aspect
                or y + h / 2 < cy - .04 * radius
                or math.hypot(x + w / 2 - cx, y + h / 2 - cy) > .90 * radius):
            continue
        candidates.append(component)
    return max(candidates, key=lambda c: cv2.contourArea(c["contour"])) if candidates else None


def supported_bottom_contact(component, frame_shape, parameters, central_fraction=.8):
    """Project actual bottommost mask pixels in central columns; median metric X/Z.

    Unlike the existing nearest-contour estimator, a narrow lower protrusion
    cannot dominate the median across the target's width. Bottom colour loss
    and wide reflections can still give a stable but incorrect contact.
    """
    if not math.isfinite(central_fraction) or not 0 < central_fraction <= 1:
        raise ValueError("central_fraction must be in (0, 1]")
    mask = component["mask"]
    origin_x, origin_y = component["origin"]
    width = mask.shape[1]
    margin = int(math.floor(width * (1 - central_fraction) / 2))
    points = []
    for x in range(margin, width - margin):
        ys = np.flatnonzero(mask[:, x])
        if len(ys):
            points.append((origin_x + x, origin_y + int(ys[-1])))
    if len(points) < 3:
        return None
    pixels, rays = dual_fisheye_pixels_to_vehicle_rays(np.asarray(points), frame_shape[1], frame_shape[0], parameters)
    downward = rays[:, 1] < -.03
    pixels, rays = pixels[downward], rays[downward]
    if len(rays) < 3:
        return None
    scale = -float(parameters["camera_height"]) / rays[:, 1]
    ground = np.column_stack((scale * rays[:, 0], scale * rays[:, 2]))
    distances = np.linalg.norm(ground, axis=1)
    valid = (scale > 0) & (ground[:, 1] > 0) & (distances >= .2) & (distances <= 4)
    pixels, ground = pixels[valid], ground[valid]
    # At least half the originally sampled columns must project validly.
    if len(ground) < max(3, math.ceil(len(points) / 2)):
        return None
    contact = np.median(ground, axis=0)
    pixel = np.median(pixels, axis=0)
    return {"x_m": float(contact[0]), "z_m": float(contact[1]),
            "distance_m": float(np.linalg.norm(contact)),
            "pixel_x": float(pixel[0]), "pixel_y": float(pixel[1]),
            "contact_samples": len(ground)}


def component_contact(component, frame_shape, parameters, settings, *, bottom=False):
    if component is None:
        return None
    contact = (supported_bottom_contact(component, frame_shape, parameters, settings.bottom_central_fraction)
               if bottom else estimate_ground_contact(component["contour"], frame_shape, parameters,
                                                       contact_fraction=parameters.get("blue_ground_contact_fraction", .08)))
    if contact is not None:
        contact.update(area_px=float(cv2.contourArea(component["contour"])), contour=component["contour"],
                       seed_fraction=component["seed_fraction"])
    return contact
