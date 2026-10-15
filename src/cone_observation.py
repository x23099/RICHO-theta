"""Offline cone bbox-to-ground *hypotheses*, not validated obstacle positions.

Only camera geometry is shared with the blue-box pipeline. A bounding box
cannot prove that a cone stands on the floor or that its base is visible.
Every result is therefore explicitly ineligible for physical FFB. This module
does not load a model, open a camera, import ROS, or send commands.
"""

from __future__ import annotations

import math

import numpy as np

from ground_contact import _lens_geometry, dual_fisheye_pixels_to_vehicle_rays


CAMERA_KEYS = (
    "camera_height", "pitch_deg", "roll_deg", "yaw_deg", "radius_scale",
    "front_cx_offset", "front_cy_offset", "back_cx_offset", "back_cy_offset",
)


def checked_bbox(row, width, height):
    """Require original-image xyxy coordinates, not normalized/model coordinates."""
    try:
        box = tuple(float(row[key]) for key in ("x1", "y1", "x2", "y2"))
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("finite original-image xyxy bbox required") from error
    x1, y1, x2, y2 = box
    if not all(math.isfinite(value) for value in box) or not (
        0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
    ):
        raise ValueError("finite nondegenerate in-image xyxy bbox required")
    return box


class ConeGroundProjector:
    """Project the bbox bottom centre under an UNVERIFIED floor assumption.

    Width/height describe the calibration's native image, not arbitrary resized
    inference inputs. Pixel offsets must not silently be used at another size.
    Left/right here are image sides; the caller explicitly selects the front.
    """

    def __init__(self, parameters, *, width, height, front_lens,
                 confidence_threshold=0.25, min_distance_m=0.20,
                 max_distance_m=4.0):
        if (type(width) is not int or type(height) is not int
                or min(width, height) < 1):
            raise ValueError("positive integer native calibration dimensions required")
        if front_lens not in ("left", "right"):
            raise ValueError("explicit front_lens left/right required")
        if any(key not in parameters for key in CAMERA_KEYS):
            raise ValueError("explicit complete camera geometry required")
        self.parameters = {key: float(parameters[key]) for key in CAMERA_KEYS}
        if not all(math.isfinite(value) for value in self.parameters.values()):
            raise ValueError("finite camera geometry required")
        if self.parameters["camera_height"] <= 0 or self.parameters["radius_scale"] <= 0:
            raise ValueError("positive camera height and lens radius required")
        self.width, self.height, self.front_lens = width, height, front_lens
        self.confidence_threshold = float(confidence_threshold)
        self.min_distance_m, self.max_distance_m = map(float, (min_distance_m, max_distance_m))
        if (not math.isfinite(self.confidence_threshold)
                or not 0 < self.confidence_threshold <= 1
                or not all(math.isfinite(v) for v in (self.min_distance_m, self.max_distance_m))
                or not 0 < self.min_distance_m < self.max_distance_m):
            raise ValueError("finite confidence in (0,1] and 0 < min range < max range required")
        self.cx, self.cy, self.radius, _ = _lens_geometry(
            width, height, self.parameters, "front", front_lens)
        if not (0 <= self.cx-self.radius < self.cx+self.radius <= width
                and 0 <= self.cy-self.radius < self.cy+self.radius <= height):
            raise ValueError("front lens circle must fit native image")

    def _in_circle(self, x, y):
        return math.hypot(x-self.cx, y-self.cy) < self.radius

    def centre_in_front_lens(self, row):
        """Geometric evaluation scope only; NOT human front/visibility annotation."""
        x1, y1, x2, y2 = checked_bbox(row, self.width, self.height)
        return self._in_circle((x1+x2)/2, (y1+y2)/2)

    def project(self, row, *, frame_width, frame_height):
        result = dict(projection_candidate=False, reason="", pixel_x=None, pixel_y=None,
                      x_m=None, z_m=None, distance_m=None,
                      floor_contact_verified=False, usable_for_ffb=False)

        def reject(reason):
            return dict(result, reason=reason)

        if (frame_width, frame_height) != (self.width, self.height):
            return reject("calibration_resolution_mismatch")
        try:
            box = checked_bbox(row, self.width, self.height)
            score, class_id = float(row["confidence"]), float(row["class_id"])
        except (KeyError, TypeError, ValueError):
            return reject("invalid_detection")
        if not (math.isfinite(score) and 0 <= score <= 1
                and math.isfinite(class_id) and class_id == 0):
            return reject("invalid_score_or_cone_class")
        if score < self.confidence_threshold:
            return reject("below_confidence")
        x1, y1, x2, y2 = box
        if not self.centre_in_front_lens(row):
            return reject("outside_front_lens")
        if x1 <= 0 or y1 <= 0 or x2 >= self.width or y2 >= self.height:
            return reject("image_edge_truncation")
        if not all(self._in_circle(x, y) for x in (x1, x2) for y in (y1, y2)):
            return reject("bbox_crosses_front_lens_boundary")
        pixel = ((x1+x2)/2, y2)
        _, rays = dual_fisheye_pixels_to_vehicle_rays(
            np.asarray([pixel]), self.width, self.height, self.parameters,
            lens="front", front_lens=self.front_lens)
        if len(rays) != 1 or rays[0, 1] >= -0.03:
            return reject("no_downward_floor_ray")
        scale = -self.parameters["camera_height"] / rays[0, 1]
        x_m, z_m = float(scale*rays[0, 0]), float(scale*rays[0, 2])
        distance = math.hypot(x_m, z_m)
        if (not all(math.isfinite(v) for v in (x_m, z_m, distance))
                or scale <= 0 or z_m <= 0):
            return reject("nonforward_or_nonfinite_intersection")
        if not self.min_distance_m <= distance <= self.max_distance_m:
            return reject("outside_diagnostic_range")
        return dict(result, projection_candidate=True,
                    reason="unverified_bbox_bottom_floor_assumption",
                    pixel_x=pixel[0], pixel_y=pixel[1],
                    x_m=x_m, z_m=z_m, distance_m=distance)
