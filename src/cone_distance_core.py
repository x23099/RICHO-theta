"""Current-frame, static-camera diagnostic distance. No ROS / hardware / GPU.

Own-session past-only scene pose + observed colour support, angular KB4 rays,
conditional floor intersection. Never infer floor contact from a YOLO bbox.
The image-space support gate is reused unchanged; its acceptance does NOT mean
the boundary is a surveyed contact point. Output cannot grant FFB permission.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from angular_fisheye_geometry import camera_from_candidate, floor_from_rays, unproject
from cone_observation import checked_bbox
from cone_scene_diagnostic import PastOnlyPose, align_up_preserving_heading_reference
from cone_support_quality import ConeSupportQualityGate
from fisheye_floor_geometry import checked_transform
from scene_sampling_clock import FixedSceneCadence
from theta_rtc_frames import finite_time, native_frame

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "src/cone_distance_diagnostic_config.json"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_config(path=DEFAULT_CONFIG):
    data = json.loads(Path(path).read_text())
    if (data.get("schema") != "cone_static_distance_diagnostic_v1"
            or data.get("physical_metric_verified") is not False or data.get("usable_for_ffb") is not False):
        raise ValueError("explicit non-physical diagnostic configuration required")
    for key in ("confidence", "nms_iou"):
        value = data[key]
        if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError("confidence / IoU must be finite in (0,1]")
    if (type(data["imgsz"]) is not int or data["imgsz"] < 32 or data["imgsz"] % 32
            or type(data["max_det"]) is not int or data["max_det"] < 1):
        raise ValueError("positive max_det and image-size multiple of 32 required")
    if (type(data["scene_interval_sec"]) not in (float, int) or data["scene_interval_sec"] != 1.0
            or type(data["frame_max_age_sec"]) not in (float, int) or data["frame_max_age_sec"] != 0.5):
        raise ValueError("screened 1s scene cadence / 0.5s frame bound required")
    lo, hi = data["diagnostic_range_m"]
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (lo, hi)) or not 0 < lo < hi:
        raise ValueError("finite positive diagnostic range required")
    for key in ("camera", "floor"):
        source = ROOT / data[key + "_candidate"]
        if digest(source) != data[key + "_sha256"]:
            raise ValueError("changed diagnostic candidate: " + key)
    camera = camera_from_candidate(json.loads((ROOT / data["camera_candidate"]).read_text()))
    floor = json.loads((ROOT / data["floor_candidate"]).read_text())
    if (floor.get("schema") != "conditional_paper5_floor_rotation_v1"
            or floor.get("physical_transform_independently_measured") is not False
            or floor.get("target_frame") != "paper7_ground_reference"):
        raise ValueError("conditional paper-reference transform required, NOT measured base_link")
    transform = checked_transform(floor["transform_target_from_source"])
    prior = checked_transform(floor["nominal_transform"])[:3, :3].T @ np.array([0., 0., 1.])
    return data, camera, transform, prior


def checked_target_roi(roi):
    if roi is None:
        return None
    if (len(roi) != 4 or any(type(v) is not int for v in roi)
            or not 0 <= roi[0] < roi[2] <= 640 or not 0 <= roi[1] < roi[3] <= 720):
        raise ValueError("explicit integer front-native target ROI x1 y1 x2 y2 required")
    return tuple(roi)


def select_front_boxes(boxes, camera, confidence, target_roi=None):
    """Full front lens unless an explicit diagnostic scope was requested.

    Scope filters bbox CENTRES only, not the contour crop. Outside the scope is
    not monitored. This is a declared operator choice, NOT automatic tracking.
    """
    target_roi = checked_target_roi(target_roi)
    selected = []
    for box in boxes:
        xyxy = checked_bbox(box, 1280, 720)
        score, cls = float(box["confidence"]), float(box["class_id"])
        if not math.isfinite(score) or not 0 <= score <= 1 or not math.isfinite(cls) or cls != 0:
            raise ValueError("finite single-class traffic_cone predictions required")
        if score < confidence:
            continue
        x1, y1, x2, y2 = xyxy
        cx, cy = (x1+x2)/2, (y1+y2)/2
        if target_roi is not None:
            a, b, c, d = target_roi
            if not a <= cx <= c or not b <= cy <= d:
                continue
        _, valid = unproject([[(x1 + x2) / 2, (y1 + y2) / 2]], camera, image_size=(1280, 720))
        if valid[0]:
            selected.append(box)
    return selected


def observe_support(image, box, camera):
    """Frozen V30 segmentation guards and trimmed actual lower envelope.

    The point is an ACTUAL envelope column nearest the observed top-row median
    x. It must belong to the trimmed support; no fitted/extrapolated base point.
    """
    native_frame(image)
    x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
    result = dict(support=None, point=None, reason="", floor_contact_verified=False)
    corners = [[x, y] for x in (x1, x2) for y in (y1, y2)]
    _, valid = unproject(corners, camera, image_size=(1280, 720))
    if not valid.all():
        return dict(result, reason="bbox_crosses_front_angular_domain")
    left, top, right, bottom = math.floor(x1)-4, math.floor(y1)-4, math.ceil(x2)+4, math.ceil(y2)+4
    if left < 0 or top < 0 or right > 1280 or bottom > 720:
        return dict(result, reason="expanded_roi_outside_native_image")
    hsv = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    mask = (cv2.inRange(hsv, (0, 80, 30), (10, 255, 255))
            | cv2.inRange(hsv, (170, 80, 30), (179, 255, 255))
            | cv2.inRange(hsv, (15, 80, 30), (40, 255, 255)))
    return support_from_colour_mask(mask, left, top)


def support_from_colour_mask(mask, left, top):
    """Shared unchanged observed-envelope guards; never a verified contact.

    The baseline passes its union mask. Experimental colour-separated masks
    may use this routine only as non-controlling shadow observations.
    """
    if (not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.dtype != np.uint8
            or not mask.size or type(left) is not int or type(top) is not int
            or left < 0 or top < 0 or left+mask.shape[1] > 1280 or top+mask.shape[0] > 720):
        raise ValueError("native bounded uint8 colour mask required")
    bottom, right = top+mask.shape[0], left+mask.shape[1]
    result = dict(support=None, point=None, reason="", floor_contact_verified=False)
    contours = sorted((c for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
                       if cv2.contourArea(c) >= 20), key=cv2.contourArea, reverse=True)
    if not contours:
        return dict(result, reason="no_supported_colour_contour")
    contour = contours[0]
    if len(contours) > 1 and cv2.contourArea(contours[1]) >= .25 * cv2.contourArea(contour):
        return dict(result, reason="ambiguous_competing_colour_contours")
    bx, by, bw, bh = cv2.boundingRect(contour)
    if bx == 0 or by == 0 or bx+bw >= right-left or by+bh >= bottom-top:
        return dict(result, reason="colour_contour_reaches_roi_edge")
    if bw < 5 or bh < 8:
        return dict(result, reason="insufficient_colour_extent")
    points = contour[:, 0, :] + [left, top]
    xs = np.unique(points[:, 0])
    envelope = np.asarray([(x, max(points[points[:, 0] == x, 1])) for x in xs])
    lo, hi = xs[0], xs[-1]
    support = envelope[(xs >= lo+.1*(hi-lo)) & (xs <= hi-.1*(hi-lo))]
    tip_y = points[:, 1].min()
    tip_x = float(np.median(points[points[:, 1] == tip_y, 0]))
    base_x = min(xs, key=lambda x: (abs(x-tip_x), x))
    point = [int(base_x), int(max(points[points[:, 0] == base_x, 1]))]
    if point[1] - tip_y < 4 or not any(np.array_equal(point, row) for row in support):
        return dict(result, support=support.tolist(), reason="base_point_outside_observed_support")
    return dict(result, support=support.tolist(), point=point, reason="unverified_visible_colour_support")


@dataclass(frozen=True)
class SceneTicket:
    session: str
    frame: int
    source_time: float
    target_time_sec: float
    skipped_targets: int


class ConeDistanceEngine:
    """One ordered cone worker owns this state; scene workers return tickets.

    complete_scene runs on the cone worker, not on the scene worker thread. A
    late scene result cannot modify another session. A pending newer scene
    blocks output until it completes, including potentially rejected images.
    """
    def __init__(self, config=DEFAULT_CONFIG, *, target_roi=None, colour_support_shadow=False):
        if type(colour_support_shadow) is not bool:
            raise ValueError("explicit bool colour support shadow required")
        self.colour_support_shadow = colour_support_shadow
        self.settings, self.camera, self.transform, self.prior_up = load_config(config)
        self.target_roi = checked_target_roi(target_roi)
        self.session = None
        self.reset(None)

    def reset(self, session):
        self.session = session
        self.quality = ConeSupportQualityGate()
        self.pose = PastOnlyPose()
        self.pending = None
        self.last_scene_source = None
        self.scene_cadence = FixedSceneCadence(self.settings["scene_interval_sec"])
        self.last_frame = 0
        self.last_time = None
        self.scene_reason = "no_scene_observation"

    def scene_due(self, source_time):
        return self.scene_cadence.due(source_time, busy=self.pending is not None)

    def begin_scene(self, frame):
        if frame.session != self.session or not self.scene_due(frame.received_at):
            raise ValueError("same-session scene cadence required; capacity one")
        timing = self.scene_cadence.take(frame.received_at)
        ticket = SceneTicket(frame.session, frame.sequence, finite_time(frame.received_at),
                             timing["target_time_sec"], timing["skipped_targets"])
        self.pending = ticket
        self.last_scene_source = frame.received_at
        return ticket

    def complete_scene(self, ticket, result, completed_at):
        if ticket is not self.pending or ticket.session != self.session:
            return False
        if finite_time(completed_at) < ticket.source_time:
            raise ValueError("scene completion cannot precede its source")
        if type(result.get("accepted")) is not bool:
            raise ValueError("explicit scene acceptance required")
        self.pose.ingest(ticket.frame, ticket.source_time, result["accepted"], result.get("up"))
        self.scene_reason = result["reason"]
        self.pending = None
        return True

    def measure(self, frame, boxes, completed_at):
        native_frame(frame.image)
        source = finite_time(frame.received_at)
        now = finite_time(completed_at() if callable(completed_at) else completed_at)
        if (frame.session != self.session or type(frame.sequence) is not int
                or frame.sequence <= self.last_frame or source > now
                or self.last_time is not None and source <= self.last_time):
            raise ValueError("same-session strictly increasing source frame/time required")
        self.last_frame, self.last_time = frame.sequence, source
        colour = dict(support=None, point=None, reason="no_candidate")
        detection_error = None
        shadow = None
        try:
            selected = select_front_boxes(boxes, self.camera, self.settings["confidence"], self.target_roi)
            if len(selected) == 1:
                colour = observe_support(frame.image, selected[0], self.camera)
                candidates = [dict(support=colour["support"], unavailable_reason=colour["reason"])]
            else:
                colour["reason"] = "no_candidate" if not selected else "ambiguous_front_cones"
                candidates = [dict(support=None) for _ in selected]
        except (ValueError, TypeError, KeyError) as exc:
            selected, candidates = [], []
            detection_error = "invalid_detector_output"
            colour["reason"] = detection_error
        if self.colour_support_shadow and len(selected) == 1 and detection_error is None:
            try:
                from cone_colour_support_candidate import observe_separated_support
                shadow = observe_separated_support(frame.image, selected[0], self.camera)
            except Exception as exc:
                shadow = dict(reason="shadow_observation_error", error=f"{type(exc).__name__}: {exc}",
                              point=None, support=None, controlling_distance=False,
                              floor_contact_verified=False, usable_for_ffb=False)
        quality = self.quality.update(source, candidates)
        if callable(completed_at):
            now = finite_time(completed_at())
        pose = self.pose.query(frame.sequence, now, "bounded_between_samples_1s")
        blockers = []
        if now - source > self.settings["frame_max_age_sec"]:
            blockers.append("frame_processing_too_old")
        if detection_error:
            blockers.append(detection_error)
        if colour["point"] is None:
            blockers.append(colour["reason"])
        if not quality["quality_accepted"]:
            blockers.append(quality["reason"])
        if self.pending is not None:
            blockers.append("newer_scene_processing_pending")
        if not pose["pose_available"]:
            blockers.append(pose["pose_reason"])
        forward, right = None, None
        if not blockers:
            rays, valid = unproject([colour["point"]], self.camera, image_size=(1280, 720))
            transform = align_up_preserving_heading_reference(self.transform, pose["up_optical"])
            xyz, valid = floor_from_rays(rays, valid, transform)
            if valid[0] and xyz[0, 0] > 0:
                radial = float(np.hypot(*xyz[0, :2]))
                lo, hi = self.settings["diagnostic_range_m"]
                if lo <= radial <= hi:
                    forward, right = float(xyz[0, 0]), float(-xyz[0, 1])
                else:
                    blockers.append("outside_diagnostic_range")
            else:
                blockers.append("floor_intersection_unavailable")
        result = dict(session=frame.session, frame=frame.sequence, source_time_sec=source,
            completed_time_sec=now, frame_age_ms=1000*(now-source), front_candidates=len(selected),
            colour_reason=colour["reason"], quality_accepted=quality["quality_accepted"], quality_reason=quality["reason"],
            scene_initialized=pose["initialized"], scene_pending=self.pending is not None,
            scene_reason=self.scene_reason, pose_reason=pose["pose_reason"],
            scene_source_frame=pose["latest_scene_frame"], scene_age_sec=pose["latest_scene_age_sec"],
            distance_available=not blockers, reason=blockers[0] if blockers else "CONDITIONAL_DIAGNOSTIC_NOT_VERIFIED_CONTACT",
            blockers=blockers, distance_forward_m=forward, lateral_right_m=right,
            base_pixel=colour["point"], target_frame="paper7_ground_reference",
            target_roi_native_xyxy=self.target_roi, target_association_physically_verified=False,
            physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False)
        if self.colour_support_shadow:
            result["colour_support_shadow"] = dict(
                candidate=shadow, controlling_distance=False, usable_for_ffb=False,
                status=("one_selected_candidate" if shadow is not None else "not_one_valid_selected_candidate"))
            result["selected_detector_boxes"] = [
                {key: float(box[key]) for key in ("x1", "y1", "x2", "y2", "confidence", "class_id")}
                for box in selected]
        return result


def render_distance(image, result, *, replay=False):
    """Separate annotated copy only. Saved native inputs must remain untouched."""
    native_frame(image)
    display = image.copy()
    cv2.rectangle(display, (0, 0), (1280, 115), (0, 0, 0), -1)
    label = "RECORDED RECOMPUTATION" if replay else "LIVE DIAGNOSTIC"
    number = (f"forward {result['distance_forward_m']:.3f} m" if result["distance_available"] else "WITHHELD")
    cv2.putText(display, f"{label} | {number} | NO ROS / FFB", (12, 27), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 255, 255), 1)
    cv2.putText(display, result["reason"][:110], (12, 53), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
    cv2.putText(display, "Conditional paper7 frame, NOT validated base_link / contact distance", (12, 78),
                cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
    roi = result.get("target_roi_native_xyxy")
    scope = f"explicit ROI {roi}; OUTSIDE NOT MONITORED" if roi else "full front lens; multiple cones withheld"
    cv2.putText(display, f"frame {result['frame']} | {scope}", (12, 103), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
    if result.get("base_pixel") is not None:
        cv2.circle(display, tuple(result["base_pixel"]), 4, (0, 255, 255), 1)
    return display
