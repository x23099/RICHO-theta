"""OFFLINE ONLY: rejection-only comparison against an explicit body boundary.

A local native image-space skyline is analyst-reviewed, not auto-segmented or
physical ground truth. Increasing image y is toward the visible body region.
Clearance never verifies floor contact; no image/point modification or metric
inference. Live entry points MUST NOT import this experimental comparator.
"""
import copy
import math
import re

from cone_motion_range import checked_current_support


def checked_reference(reference):
    if (not isinstance(reference, dict)
            or reference.get("schema") != "offline_self_body_boundary_v1"
            or reference.get("image_size") != [1280, 720]
            or reference.get("layout") != "dual_fisheye_front_left_unremapped"
            or not isinstance(reference.get("session"), str)
            or not re.fullmatch("[0-9a-f]{32}", reference["session"])
            or type(reference.get("source_frame")) is not int or reference["source_frame"] < 1
            or not isinstance(reference.get("source_png_sha256"), str)
            or not re.fullmatch("[0-9a-f]{64}", reference["source_png_sha256"])
            or any(reference.get(k) is not False for k in ("independent_physical_measurement",
                "cross_session_mount_verified", "live_authorized", "floor_contact_verified"))):
        raise ValueError("explicit unverified native self-body reference required")
    points = reference.get("boundary_xy")
    if not isinstance(points, list) or not 2 <= len(points) <= 64:
        raise ValueError("2..64 ordered local boundary samples required")
    previous = -1
    for point in points:
        if (not isinstance(point, list) or len(point) != 2
                or any(type(v) is not int for v in point)
                or not previous < point[0] < 640 or not 0 <= point[1] < 720):
            raise ValueError("ordered bounded native integer boundary required")
        previous = point[0]
    return copy.deepcopy(reference)


def _edge_y(points, x):
    for a, b in zip(points, points[1:]):
        if a[0] <= x <= b[0]:
            return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
    raise ValueError("no boundary extrapolation")


def compare_self_body(observation, reference, *, session, margin_px=2., reference_matches=False, compact=False):
    """Return a separate observation; only preserve or revoke, NEVER rescue.

    Caller must check the reference PNG hash before setting reference_matches.
    All support columns must lie strictly ABOVE edge-margin, not just the point.
    Invalid/unknown references fail closed for this OFFLINE proposal only.
    """
    # Compact is only consumed within one fresh comparison call. All rejection
    # edits are top-level; the borrowed nested diagnostics remain read-only.
    if type(compact) is not bool:
        raise ValueError('explicit bool compact mode required')
    if type(margin_px) not in (int, float) or not math.isfinite(margin_px) or not 0 <= margin_px <= 16:
        raise ValueError("finite 0..16 pixel margin required")
    if not isinstance(observation, dict):
        raise ValueError("observation dict required")
    ref = checked_reference(reference)
    result = dict(observation=dict(observation) if compact else copy.deepcopy(observation), revoked=False, reference_usable=False,
        reason="no_observed_point", min_clearance_px=None, point_clearance_px=None,
        affected_columns=0, support_columns=0, margin_px=float(margin_px),
        diagnostic_only=True, live_authorized=False, floor_contact_verified=False,
        physical_metric_verified=False, controlling_distance=False, usable_for_ffb=False)
    if observation.get("point") is None:
        return result  # Preserve every existing unavailable observation verbatim.
    if any(observation.get(k) is not False for k in ("floor_contact_verified",
            "physical_metric_verified", "controlling_distance", "usable_for_ffb")):
        raise ValueError("unverified image observation required")

    def reject(reason):
        result.update(revoked=True, reason=reason)
        result["observation"].update(point=None, support=None, reason=reason,
            live_authorized=False, floor_contact_verified=False, physical_metric_verified=False,
            controlling_distance=False, usable_for_ffb=False)
        return result

    if session != ref["session"]:
        return reject("self_body_reference_session_mismatch")
    if reference_matches is not True:
        return reject("self_body_reference_image_unchecked")
    point, reason = checked_current_support(observation)
    if point is None:
        return reject(reason)
    support = observation["support"]
    result["support_columns"] = len(support)
    points = ref["boundary_xy"]
    if any(not points[0][0] <= p[0] <= points[-1][0] for p in support):
        return reject("self_body_reference_does_not_cover_support")
    clearances = [_edge_y(points, p[0]) - p[1] for p in support]
    result.update(reference_usable=True, min_clearance_px=float(min(clearances)),
        point_clearance_px=float(_edge_y(points, point[0]) - point[1]),
        affected_columns=sum(c <= margin_px for c in clearances))
    if result["affected_columns"]:
        return reject("possible_self_body_occlusion")
    result["reason"] = "clear_of_reviewed_local_body_boundary_NOT_floor_contact"
    return result  # Exact same point/support, with no grant of new authority.
