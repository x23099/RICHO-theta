"""Opt-in rigid-mount range experiment. No control, ROS, FFB or static scene pose.

Range is horizontal from the camera plumb point to a visible support point,
NOT forward/base_link/contact distance. Height/tilt are assumed fixed relative
to a locally planar floor; pitch/roll/bounce compensation is NOT implemented.
"""
import copy
import hashlib
import json
import math

import numpy as np

from angular_fisheye_geometry import unproject
from cone_distance_core import checked_target_roi, select_front_boxes
from cone_fixed_floor_live_load import bounded_regular_bytes
from cone_support_completion_candidate import observe_lateral_completion
from cone_support_quality import SupportQualitySettings
from theta_rtc_frames import finite_time, native_frame

PROFILE_SCHEMA = "experimental_rigid_mount_range_v1"
FLAGS = dict(physical_metric_verified=False, floor_contact_verified=False,
             controlling_distance=False, usable_for_ffb=False, published_to_ros=False)


def parse_motion_profile(payload, settings):
    def invalid(value):
        raise ValueError("nonfinite profile value: "+value)
    data = json.loads(payload, parse_constant=invalid)
    if (not isinstance(data, dict) or data.get("schema") != PROFILE_SCHEMA
            or data.get("camera_sha256") != settings["camera_sha256"]
            or data.get("image_size") != [1280, 720] or data.get("native_ray_basis") != "unmodified"
            or data.get("metric") != "horizontal_camera_foot_range_m"
            or any(data.get(k) is not False for k in FLAGS)
            or data.get("mount_or_floor_tilt_compensated") is not False
            or data.get("cross_session_mount_verified") is not False):
        raise ValueError("explicit unverified native rigid-mount range profile required")
    source = data.get("source")
    if (not isinstance(source, dict) or not isinstance(source.get("image_sha256"), str)
            or len(source["image_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in source["image_sha256"])
            or not isinstance(source.get("session"), str) or not source["session"].strip()
            or type(source.get("frame")) is not int or source["frame"] < 1):
        raise ValueError("source image hash/session/frame required")
    models = data.get("models")
    if not isinstance(models, list) or not 1 <= len(models) <= 8:
        raise ValueError("1..8 explicit floor-normal hypotheses required")
    names = []
    for model in models:
        if not isinstance(model, dict) or type(model.get("id")) is not str or not model["id"]:
            raise ValueError("explicit model id required")
        normal = np.asarray(model.get("up_optical"), float)
        height = model.get("height_m")
        if (normal.shape != (3,) or not np.isfinite(normal).all() or
                not np.isclose(np.linalg.norm(normal), 1., atol=1e-8, rtol=0)
                or type(height) not in (int, float) or not math.isfinite(height) or not 0 < height < 3):
            raise ValueError("unit up direction and finite positive height required")
        names.append(model["id"])
    if len(set(names)) != len(names) or data.get("primary_model") not in names:
        raise ValueError("unique models and explicit primary diagnostic hypothesis required")
    return copy.deepcopy(data), hashlib.sha256(payload).hexdigest()


def load_motion_profile(path, settings):
    return parse_motion_profile(bounded_regular_bytes(path, 256*1024), settings)


def checked_current_support(observation):
    """Spatial part only; no static-scene temporal anchor or invented points."""
    settings = SupportQualitySettings()
    if not isinstance(observation, dict) or observation.get("point") is None:
        return None, "support_point_unavailable"
    try:
        if np.iscomplexobj(observation.get("support")):
            return None, "invalid_current_support"
        support = np.asarray(observation.get("support"), float)
        point = np.asarray(observation["point"], float)
    except (ValueError, TypeError):
        return None, "invalid_current_support"
    if (support.ndim != 2 or support.shape[1] != 2 or len(support) < settings.min_columns
            or point.shape != (2,) or not np.isfinite(support).all() or not np.isfinite(point).all()
            or not np.equal(support, np.rint(support)).all() or not np.equal(point, np.rint(point)).all()
            or np.any(support < [0, 0]) or np.any(support >= [640, 720])
            or np.any(np.diff(support[:, 0]) <= 0)):
        return None, "invalid_or_unordered_current_support"
    if not np.any(np.all(support == point, axis=1)):
        return None, "point_not_in_current_observed_support"
    span = float(support[-1, 0]-support[0, 0])
    if span < settings.min_span_px:
        return None, "insufficient_support_span"
    if len(support)/(span+1) < settings.min_coverage or max(np.diff(support[:, 0])) > settings.max_column_gap_px:
        return None, "disconnected_current_support"
    return point.astype(int).tolist(), "current_image_support_only_NOT_contact_or_temporal_association"


def horizontal_range(ray, model):
    """Fixed normal/height only; world translation and in-plane yaw are absent."""
    r, up = np.asarray(ray, float), np.asarray(model["up_optical"], float)
    if (r.shape != (3,) or up.shape != (3,) or not np.isfinite(r).all() or not np.isfinite(up).all()
            or not np.isclose(np.linalg.norm(r), 1., atol=1e-8, rtol=0)
            or not np.isclose(np.linalg.norm(up), 1., atol=1e-8, rtol=0)):
        raise ValueError("unit finite ray and up direction required")
    h = model["height_m"]
    if type(h) not in (int, float) or not math.isfinite(h) or h <= 0:
        raise ValueError("finite positive floor height required")
    incidence = -float(up @ r)
    if incidence < .03:
        return None
    scale = h/incidence
    return float(math.sqrt(max(0., scale*scale-h*h)))


def revoke_range(result, reason):
    result.update(distance_available=False, horizontal_camera_foot_range_m=None, reason=reason)
    for item in result["models"]:
        item.update(range_available=False, horizontal_camera_foot_range_m=None, reason=reason)
    return result


class MotionRangeEngine:
    """Current-frame experimental metric; target association is not a tracker."""
    def __init__(self, settings, camera, profile, profile_sha256, *, acknowledged=False,
                 target_roi=None, observer=observe_lateral_completion):
        if acknowledged is not True:
            raise ValueError("explicit --experimental-rigid-mount acknowledgement required")
        # Validate even programmatically supplied profiles; own an immutable copy.
        self.profile, _ = parse_motion_profile(json.dumps(profile).encode(), settings)
        self.profile_sha256 = profile_sha256
        self.settings, self.camera = copy.deepcopy(settings), camera
        self.target_roi, self.observer = checked_target_roi(target_roi), observer
        self.session, self.last_frame, self.last_source = None, 0, None

    def reset(self, session):
        self.session, self.last_frame, self.last_source = session, 0, None

    def measure(self, frame, boxes, completed_at, *, observer=None):
        # Per-call observer for a freshly computed SAME-frame comparison.
        # Default callers and all state/selection/age/geometry guards are unchanged.
        if observer is not None and not callable(observer):
            raise ValueError('callable current-frame observer required')
        native_frame(frame.image)
        now, source = finite_time(completed_at), finite_time(frame.received_at)
        if (not isinstance(frame.session, str) or not frame.session or type(frame.sequence) is not int
                or frame.sequence < 1 or source > now):
            raise ValueError("valid native frame identity and causal source time required")
        if self.session != frame.session:
            self.reset(frame.session)
        if frame.sequence <= self.last_frame or self.last_source is not None and source <= self.last_source:
            raise ValueError("strictly increasing source frame/time required")
        self.last_frame, self.last_source = frame.sequence, source
        result = dict(schema="cone_motion_range_v1", session=frame.session, frame=frame.sequence,
            media_time_sec=frame.media_time, source_time_sec=source, completed_time_sec=now,
            frame_age_ms=1000*(now-source), frame_age_limit_ms=1000*self.settings["frame_max_age_sec"],
            profile_sha256=self.profile_sha256, profile_source=copy.deepcopy(self.profile["source"]),
            primary_model=self.profile["primary_model"], distance_available=False,
            horizontal_camera_foot_range_m=None, models=[], support_pixel=None,
            target_roi_native_xyxy=self.target_roi, front_candidates=0,
            reason="no_candidate", static_scene_required=False,
            temporal_target_association_verified=False, cross_session_mount_verified=False,
            mount_or_floor_tilt_compensated=False, assumed_rigid_mount_locally_planar_floor=True,
            **FLAGS)
        if now-source > self.settings["frame_max_age_sec"]:
            return revoke_range(result, "frame_processing_too_old")
        try:
            selected = select_front_boxes(boxes, self.camera, self.settings["confidence"], self.target_roi)
        except (ValueError, TypeError, KeyError):
            return revoke_range(result, "invalid_detector_output")
        result["front_candidates"] = len(selected)
        result["selected_detector_boxes"] = [dict(b) for b in selected]
        if len(selected) != 1:
            return revoke_range(result, "no_candidate" if not selected else "ambiguous_front_cones")
        observe = self.observer if observer is None else observer
        observation = observe(frame.image, selected[0], self.camera)
        result["support_observation"] = copy.deepcopy(observation)
        point, reason = checked_current_support(observation)
        if point is None:
            return revoke_range(result, observation.get("reason") if observation.get("point") is None else reason)
        result["support_pixel"] = point
        result["support_reason"] = reason
        rays, valid = unproject([point], self.camera, image_size=(1280, 720))
        if not valid[0]:
            return revoke_range(result, "support_outside_calibration_domain")
        low, high = self.settings["diagnostic_range_m"]
        for model in self.profile["models"]:
            value = horizontal_range(rays[0], model)
            accepted = value is not None and low <= value <= high
            result["models"].append(dict(id=model["id"], range_available=accepted,
                horizontal_camera_foot_range_m=value if accepted else None,
                reason="unverified_rigid_mount_range" if accepted else "grazing_or_outside_range"))
        primary = next(m for m in result["models"] if m["id"] == self.profile["primary_model"])
        if primary["range_available"]:
            result.update(distance_available=True,
                horizontal_camera_foot_range_m=primary["horizontal_camera_foot_range_m"],
                reason="EXPERIMENTAL_FIXED_MOUNT_NOT_VERIFIED_CONTACT")
        else:
            result["reason"] = primary["reason"]  # No fallback to a more convenient solution.
        return result
