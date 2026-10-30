"""Opt-in session-bound fixed-floor comparison log. Never distance authority.

No source images, GPU, network, ROS, or FFB access. All configured models are
kept; a convenient range is never selected as the winner.
"""
import copy
import hashlib
import json
from pathlib import Path

from cone_fixed_floor_candidate import COORDINATE_FRAME, checked_explicit_floor_model, measure_support
from cone_support_quality import ConeSupportQualityGate

SOURCES = ("baseline", "colour_support_shadow", "support_completion_shadow")
ROOT = Path(__file__).resolve().parents[1]


def load_bundle(path, settings):
    payload = Path(path).read_bytes()
    def invalid(value):
        raise ValueError("nonfinite JSON constant: " + value)
    data = json.loads(payload, parse_constant=invalid)
    if (not isinstance(data, dict) or data.get("schema") != "explicit_floor_models_v1"
            or not isinstance(data.get("session"), str) or not data["session"]
            or not isinstance(data.get("models"), list) or not data["models"]):
        raise ValueError("nonempty explicit session/model bundle required")
    expected = dict(path=settings["floor_candidate"], sha256=settings["floor_sha256"])
    if data.get("heading_reference") != expected:
        raise ValueError("bundle heading reference must match the checked diagnostic config")
    models = [checked_explicit_floor_model(m) for m in data["models"]]
    if len({m["name"] for m in models}) != len(models):
        raise ValueError("unique explicit model names required")
    for model in models:
        if (model["session"] != data["session"] or model["heading_reference"] != expected
                or model.get("controlling_distance", False) is not False):
            raise ValueError("same-session non-controlling models with checked heading required")
    return dict(data, models=models), hashlib.sha256(payload).hexdigest()


def enforce_freshness(shadow, age_ms):
    """Late worker completion can revoke a range, never make one available."""
    if age_ms > 500.:
        shadow.update(status="WITHHELD", reason="frame_processing_too_old")
        for model in shadow["models"]:
            model.update(range_available=False, horizontal_camera_foot_range_m=None,
                         reason="frame_processing_too_old")


class FixedFloorShadow:
    def __init__(self, path, settings, support_source):
        if support_source not in SOURCES:
            raise ValueError("explicit baseline/colour/completion support source required")
        self.bundle, self.bundle_sha256 = load_bundle(path, settings)
        self.support_source = support_source
        self.camera_sha256 = settings["camera_sha256"]
        self.range_bounds = settings["diagnostic_range_m"]
        self.reset()

    def reset(self):
        self.quality = ConeSupportQualityGate()

    def failed(self, frame, observation, error):
        self.quality.reset()  # An unknown frame must require reconfirmation.
        return dict(schema="fixed_floor_shadow_v1", session=frame.session, frame=frame.sequence,
            model_session=self.bundle["session"], model_bundle_sha256=self.bundle_sha256,
            camera_candidate_sha256=self.camera_sha256,
            heading_reference_sha256=self.bundle["heading_reference"]["sha256"],
            coordinate_frame=COORDINATE_FRAME, support_source=self.support_source,
            support_pixel=copy.deepcopy((observation or {}).get("point")),
            image_quality_accepted=False, image_quality_reason="comparison_error",
            frame_age_limit_ms=500., status="WITHHELD", reason="fixed_floor_shadow_error",
            error=f"{type(error).__name__}: {error}",
            models=[dict(model_name=m["name"], range_available=False,
                         horizontal_camera_foot_range_m=None, reason="fixed_floor_shadow_error")
                    for m in self.bundle["models"]], controlling_distance=False,
            physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False, yaw_measured=False)

    def observe(self, frame, observation, camera, heading_reference):
        candidate = observation or {}
        point = candidate.get("point")
        if point is not None and point not in (candidate.get("support") or []):
            raise ValueError("fixed-floor shadow point must be an actual support column")
        quality = self.quality.update(frame.received_at, [dict(
            support=candidate.get("support") if point is not None else None,
            unavailable_reason=candidate.get("reason", "no_selected_support"))])
        reason = ("model_session_mismatch" if frame.session != self.bundle["session"] else
                  "support_point_unavailable" if point is None else
                  "image_support_quality_not_confirmed" if not quality["quality_accepted"] else None)
        result = dict(schema="fixed_floor_shadow_v1", session=frame.session, frame=frame.sequence,
            model_session=self.bundle["session"], model_bundle_sha256=self.bundle_sha256,
            camera_candidate_sha256=self.camera_sha256,
            heading_reference_sha256=self.bundle["heading_reference"]["sha256"],
            coordinate_frame=COORDINATE_FRAME, support_source=self.support_source,
            support_pixel=copy.deepcopy(point), image_quality_accepted=quality["quality_accepted"],
            image_quality_reason=quality["reason"], frame_age_limit_ms=500.,
            models=[], status="WITHHELD", reason=reason or "fixed_floor_intersection_unavailable",
            controlling_distance=False, physical_metric_verified=False,
            floor_contact_verified=False, usable_for_ffb=False, yaw_measured=False)
        for model in self.bundle["models"]:
            item = dict(model_name=model["name"], range_available=False,
                        horizontal_camera_foot_range_m=None, reason=reason)
            if reason is None:
                measured = measure_support(point, model, camera, heading_reference,
                                           session=frame.session, diagnostic_range_m=self.range_bounds)
                item.update(range_available=measured["range_available"], reason=measured["reason"],
                    horizontal_camera_foot_range_m=(measured["horizontal_camera_foot_range_m"]
                                                    if measured["range_available"] else None))
            result["models"].append(item)
        if any(m["range_available"] for m in result["models"]):
            result.update(status="CONDITIONAL_FIXED_FLOOR_SHADOW", reason="unverified_comparison_only")
        return result
