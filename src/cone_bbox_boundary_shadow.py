"""OFFLINE ONLY: compare float bbox vs pixel-coordinate boundary conventions.

Never imported by driver/live entry points. Preserve every old observation;
only a late lateral-completion bbox rejection may yield a separate hypothesis.
No bottom extension, point clamp, temporal hold, threshold tuning or control.
"""
import copy
import math

from cone_motion_range import checked_current_support
from cone_observation import checked_bbox
from cone_upper_support_candidate import observe_upper_completion
from theta_rtc_frames import native_frame

POLICIES = ("half_pixel_overlap", "outward_integer_inclusive")
OBS_FLAGS = ("controlling_distance", "physical_metric_verified", "floor_contact_verified", "usable_for_ffb")


def boundary_contains(box, point, policy):
    if policy not in POLICIES:
        raise ValueError("explicit diagnostic boundary policy required")
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    if (not isinstance(point, list) or len(point) != 2
            or any(type(v) is not int for v in point) or not 0 <= point[0] < 640 or not 0 <= point[1] < 720):
        raise ValueError("integer native front observed point required")
    x, y = point
    if policy == "half_pixel_overlap":
        return x+.5 >= x1 and x-.5 <= x2 and y+.5 >= y1 and y-.5 <= y2
    return math.floor(x1) <= x <= math.ceil(x2) and math.floor(y1) <= y <= math.ceil(y2)


def compare_boundary_observations(image, box, camera):
    native_frame(image)
    # This baseline runs the actual existing observer against original pixels.
    baseline = observe_upper_completion(image, box, camera)
    outputs = {policy: dict(observation=copy.deepcopy(baseline), changed=False,
                            diagnostic_reason="baseline_preserved") for policy in POLICIES}
    result = dict(baseline=copy.deepcopy(baseline), comparisons=outputs,
                  diagnostic_only=True, live_authorized=False,
                  physical_metric_verified=False, controlling_distance=False, usable_for_ffb=False)
    if (baseline.get("point") is not None or baseline.get("reason") != "colour_contour_reaches_roi_edge"
            or baseline.get("completion_reason") != "completed_point_outside_original_bbox"):
        return result
    if any(baseline.get(k) is not False for k in OBS_FLAGS):
        raise ValueError("unexpected authority in offline baseline")
    contexts = baseline.get("contexts") or []
    if len(contexts) != 3:
        return result
    original, first, second = contexts
    a, b = first.get("component") or {}, second.get("component") or {}
    closed = dict(left=False, right=False, top=False, bottom=False)
    original_touches = (original.get("component") or {}).get("touches") or {}
    sha = a.get("pixel_sha256")
    if (not (original_touches.get("left") or original_touches.get("right"))
            or original_touches.get("top") or original_touches.get("bottom")
            or a.get("touches") != closed or b.get("touches") != closed
            or not isinstance(sha, str) or len(sha) != 64 or sha != b.get("pixel_sha256")
            or first.get("observation") != second.get("observation")):
        return result
    observation = first.get("observation") or {}
    point, quality_reason = checked_current_support(observation)
    if point is None:
        for item in outputs.values():
            item["diagnostic_reason"] = quality_reason
        return result
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    if x1 <= point[0] <= x2 and y1 <= point[1] <= y2:
        raise ValueError("late float-bbox rejection contradicts observed point")
    for policy, item in outputs.items():
        if not boundary_contains(box, point, policy):
            item["diagnostic_reason"] = "outside_diagnostic_boundary_policy"
            continue
        candidate = copy.deepcopy(baseline)
        candidate.update(copy.deepcopy(observation))
        candidate.update(reason="unverified_bbox_boundary_shadow",
                         bbox_boundary_shadow_policy=policy, bbox_boundary_shadow_granted=True,
                         **{k: False for k in OBS_FLAGS})
        item.update(observation=candidate, changed=True,
                    diagnostic_reason="same_current_closed_component_only_bbox_policy_changed")
    return result
