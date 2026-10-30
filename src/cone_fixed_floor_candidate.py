"""Explicit session-scoped floor model: OFFLINE/DIAGNOSTIC ONLY.

No background scene pose, ROS/TF publication, hardware or FFB access. The
caller must supply (a) a unit floor normal in front-optical coordinates,
(b) an explicit camera-to-floor height, and (c) a heading-reference transform
from another explicitly named model. Radial range is invariant to yaw about
the floor normal; forward/lateral are labelled with the preserved heading
reference, NOT measured base_link axes.

This module is intentionally not imported by cone_distance_core, the worker,
or the live receiver. It cannot release the existing WITHHELD state.
"""
import math

import numpy as np

from angular_fisheye_geometry import floor_from_rays, unproject
from cone_scene_diagnostic import align_up_preserving_heading_reference
from fisheye_floor_geometry import checked_transform

SCHEMA = "explicit_floor_model_v1"
COORDINATE_FRAME = "paper7_heading_carryover_camera_foot"
FALSE_FLAGS = ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb")


def _unit(values):
    array = np.asarray(values, float)
    if (array.shape != (3,) or not np.isfinite(array).all()
            or not np.isclose(np.linalg.norm(array), 1., rtol=0, atol=1e-10)):
        raise ValueError("finite unit floor normal required")
    return array


def checked_explicit_floor_model(model):
    """Validate the explicit contract; never infer a missing field."""
    if not isinstance(model, dict):
        raise ValueError("explicit floor model mapping required")
    if model.get("schema") != SCHEMA:
        raise ValueError("explicit floor model schema required")
    name, session = model.get("name"), model.get("session")
    if type(name) is not str or not name or type(session) is not str or not session:
        raise ValueError("non-empty model name and session required")
    normal = _unit(model.get("normal_optical"))
    height = model.get("camera_to_floor_m")
    if (isinstance(height, bool) or not isinstance(height, (int, float))
            or not math.isfinite(height) or not 0 < height < 5):
        raise ValueError("finite camera-to-floor height in (0,5) m required")
    if model.get("coordinate_frame") != COORDINATE_FRAME:
        raise ValueError("explicit heading-carryover coordinate frame required")
    for key in ("evidence", "assumptions", "invalidation_conditions"):
        values = model.get(key)
        if (not isinstance(values, list) or not values
                or any(type(value) is not str or not value for value in values)):
            raise ValueError("non-empty string list required: " + key)
    if any(model.get(key) is not False for key in FALSE_FLAGS):
        raise ValueError("diagnostic model must not claim physical approval")
    heading = model.get("heading_reference")
    if (not isinstance(heading, dict) or type(heading.get("path")) is not str
            or type(heading.get("sha256")) is not str or len(heading["sha256"]) != 64):
        raise ValueError("explicit hashed heading reference required")
    return dict(model, normal_optical=normal.tolist())


def build_explicit_floor_transform(model, heading_reference_transform):
    """Replace heading-reference height and up; keep its heading convention."""
    model = checked_explicit_floor_model(model)
    transform = checked_transform(heading_reference_transform)
    if transform[2, 3] <= 0:
        raise ValueError("heading reference must place the camera above the floor")
    # The explicit model defines its origin as the camera's vertical floor
    # projection. The heading reference supplies orientation only; never carry
    # an unrelated translation into this frame.
    base = transform.copy()
    base[:3, 3] = [0., 0., float(model["camera_to_floor_m"])]
    output = align_up_preserving_heading_reference(base, model["normal_optical"])
    up = output[:3, :3].T @ np.array([0., 0., 1.])
    if not np.allclose(up, model["normal_optical"], rtol=0, atol=1e-9):
        raise ValueError("explicit model normal not reproduced by transform")
    if not math.isclose(float(output[2, 3]), float(model["camera_to_floor_m"]),
                        rel_tol=0, abs_tol=1e-12):
        raise ValueError("explicit floor height not preserved")
    return output


def _up_change_deg(normal, heading_reference_transform):
    reference = checked_transform(heading_reference_transform)
    old = reference[:3, :3].T @ np.array([0., 0., 1.])
    return float(np.degrees(np.arccos(np.clip(float(_unit(normal) @ old), -1., 1.))))


def measure_support(support_xy, model, camera, heading_reference_transform, *,
                    session, diagnostic_range_m=(0.2, 4.0)):
    """Conditional range for one observed support pixel; never a contact proof.

    The support pixel is whatever the caller observed (baseline or shadow).
    This function does not decide that it is a cone base or floor contact.
    """
    model = checked_explicit_floor_model(model)
    if type(session) is not str or not session or session != model["session"]:
        raise ValueError("floor model is scoped to one explicit session")
    support = np.asarray(support_xy, float)
    if (support.shape != (2,) or not np.isfinite(support).all()
            or not np.equal(support, np.rint(support)).all()):
        raise ValueError("finite integer support pixel required")
    lo, hi = diagnostic_range_m
    if (not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) for v in (lo, hi)) or not 0 < lo < hi):
        raise ValueError("finite positive diagnostic range required")
    transform = build_explicit_floor_transform(model, heading_reference_transform)
    result = dict(
        status="WITHHELD", reason="", range_available=False,
        model_name=model["name"], model_session=model["session"],
        camera_to_floor_m=float(model["camera_to_floor_m"]),
        normal_optical=model["normal_optical"],
        diagnostic_range_m=[lo, hi],
        coordinate_frame=COORDINATE_FRAME,
        heading_reference_path=model["heading_reference"]["path"],
        heading_reference_sha256=model["heading_reference"]["sha256"],
        heading_reference_up_change_deg=_up_change_deg(
            model["normal_optical"], heading_reference_transform),
        horizontal_camera_foot_range_m=None, forward_heading_reference_m=None,
        lateral_right_heading_reference_m=None, lens_slant_range_m=None,
        incidence_cos=None, floor_point_heading_reference_m=None,
        camera_position_heading_reference_m=None,
        support_pixel=None, yaw_measured=False, controlling_distance=False,
        target_association_physically_verified=False, physical_metric_verified=False,
        floor_contact_verified=False, usable_for_ffb=False)
    rays, valid = unproject([support], camera, image_size=(1280, 720))
    if not valid[0]:
        return dict(result, reason="support_outside_front_angular_domain")
    xyz, accepted = floor_from_rays(rays, valid, transform)
    if not accepted[0] or not np.isfinite(xyz[0]).all():
        return dict(result, reason="explicit_floor_intersection_unavailable")
    point = np.asarray(xyz[0], float)
    radial = float(np.hypot(point[0], point[1]))
    camera_position = np.array([0., 0., float(model["camera_to_floor_m"])])
    slant = float(np.linalg.norm(point - camera_position))
    incidence = float(-np.asarray(model["normal_optical"]) @ rays[0])
    result.update(
        support_pixel=[int(support[0]), int(support[1])],
        floor_point_heading_reference_m=point.tolist(),
        camera_position_heading_reference_m=camera_position.tolist(),
        horizontal_camera_foot_range_m=radial,
        forward_heading_reference_m=float(point[0]),
        lateral_right_heading_reference_m=float(-point[1]),
        lens_slant_range_m=slant, incidence_cos=incidence)
    if point[0] <= 0:
        return dict(result, reason="support_behind_heading_reference")
    if not lo <= radial <= hi:
        return dict(result, reason="outside_diagnostic_range")
    return dict(result, status="CONDITIONAL_FIXED_FLOOR_RANGE_ONLY",
                range_available=True,
                reason="EXPLICIT_FLOOR_MODEL_NOT_PHYSICALLY_VERIFIED")
