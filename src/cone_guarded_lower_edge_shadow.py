"""OFFLINE ONLY: combine the fixed local body veto and lower-edge overlap.

Never imported by live entry points. No bbox/point clamp, rounding fallback,
image modification, history, fitted contact, or change to metric equations.
All old observations stay separately available for comparison.
"""
import copy

from cone_bbox_boundary_shadow import compare_boundary_observations
from cone_observation import checked_bbox
from cone_self_body_shadow import compare_self_body


def lower_half_pixel_only(box, point):
    """Fixed diagnostic rule: only original y2 may fall short by <=.5px."""
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    if (not isinstance(point, list) or len(point) != 2
            or any(type(v) is not int for v in point)
            or not 0 <= point[0] < 640 or not 0 <= point[1] < 720):
        raise ValueError("integer observed native front point required")
    x, y = point
    return x1 <= x <= x2 and y1 <= y and y2 < y <= y2 + .5


def compare_guarded_lower_edge(image, box, camera, reference, *, session,
                               reference_matches=False, margin_px=2., compact=False):
    """compact: owned per-call graph, read-only until consumed by an engine.

    Values/guards are unchanged; independent deep diagnostic copies remain the
    default API. No compact graph is stored between frames or returned by IPC.
    """
    if type(compact) is not bool:
        raise ValueError('explicit bool compact mode required')
    # Existing comparator enforces seeded, closed, identical components and
    # spatial support before it can propose any half-pixel observation.
    comparison = compare_boundary_observations(image, box, camera, compact=compact)
    baseline = comparison["baseline"]
    baseline_review = compare_self_body(baseline, reference, session=session,
        reference_matches=reference_matches, margin_px=margin_px, compact=compact)
    half = comparison["comparisons"]["half_pixel_overlap"]
    candidate = half["observation"]
    eligible = (baseline.get("point") is None and half["changed"] is True
                and candidate.get("point") is not None and lower_half_pixel_only(box, candidate["point"]))
    proposal_review = (compare_self_body(candidate, reference, session=session,
        reference_matches=reference_matches, margin_px=margin_px, compact=compact) if eligible else baseline_review)
    proposal = dict(proposal_review['observation']) if compact else copy.deepcopy(proposal_review["observation"])
    if (proposal.get("point") is not None and baseline.get("point") is None
            and not eligible):
        raise ValueError("candidate bypassed lower-edge-only rule")
    return dict(baseline=baseline if compact else copy.deepcopy(baseline),
        baseline_body_review=baseline_review if compact else copy.deepcopy(baseline_review),
        proposed_observation=proposal, proposed_body_review=proposal_review if compact else copy.deepcopy(proposal_review),
        lower_half_pixel_eligible=bool(eligible),
        new_point_proposed=baseline.get("point") is None and proposal.get("point") is not None,
        baseline_point_revoked=baseline.get("point") is not None and proposal.get("point") is None,
        original_half_pixel_changed=half["changed"],
        method="offline_body_veto_and_lower_half_pixel_only_v1", diagnostic_only=True,
        live_authorized=False, floor_contact_verified=False, physical_metric_verified=False,
        controlling_distance=False, usable_for_ffb=False)
