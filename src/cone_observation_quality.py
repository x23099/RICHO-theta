"""Causal, offline-only quality gate for ONE externally associated cone.

Acceptance means temporal consistency of a bbox-bottom floor hypothesis, NOT
verified contact, metric accuracy, obstacle absence, TTC or permission for FFB.
No association, camera, detector, ROS, or hardware functionality is provided.
"""

from dataclasses import asdict, dataclass
import math

from cone_observation import checked_bbox
from obstacle_tracking import BlueObstacleTracker, ObstacleObservationGate


@dataclass(frozen=True)
class ConeQualitySettings:
    confirmation_frames: int = 3
    confirmation_distance_m: float = 0.15
    max_nis: float = 9.21
    measurement_std_m: float = 0.03
    process_accel_std_mps2: float = 1.5
    track_memory_sec: float = 0.5
    max_frame_gap_sec: float = 0.2
    shape_memory_sec: float = 1.0
    max_shape_factor: float = 2.0

    def __post_init__(self):
        if type(self.confirmation_frames) is not int or self.confirmation_frames < 2:
            raise ValueError("confirmation_frames must be an integer >= 2")
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"positive finite {name} required")
        if self.shape_memory_sec < self.track_memory_sec or self.max_shape_factor <= 1:
            raise ValueError("shape memory >= track memory and shape factor > 1 required")


class ConeObservationQualityGate:
    """Consume monotonically timed frames, including empty/ambiguous frames.

    ``candidates`` must be externally associated to the intended single object.
    Multiple candidates fail closed; this is NOT a multi-object selector.
    Only accepted measurements update the shape anchor. Missing/rejected frames
    interrupt confirmation. Internal KF predictions never become observations.
    """

    def __init__(self, projector, settings=None):
        self.projector = projector
        self.settings = settings or ConeQualitySettings()
        self.tracker = BlueObstacleTracker(
            measurement_std_m=self.settings.measurement_std_m,
            process_accel_std_mps2=self.settings.process_accel_std_mps2,
            max_missing_sec=self.settings.track_memory_sec)
        self.confirmation = ObstacleObservationGate(
            confirmation_frames=self.settings.confirmation_frames,
            confirmation_distance_m=self.settings.confirmation_distance_m)
        self.reset()

    def reset(self):
        self.tracker.reset()
        self.confirmation.reset()
        self.last_time = None
        self.last_good_time = None
        self.last_shape = None
        self.recovering = True

    def update(self, timestamp, candidates, *, frame_width, frame_height):
        now = float(timestamp)
        if not math.isfinite(now) or (self.last_time is not None and now <= self.last_time):
            self.reset()
            raise ValueError("finite strictly increasing timestamps required; state reset")
        if self.last_time is not None and now-self.last_time > self.settings.max_frame_gap_sec:
            self.tracker.reset()
            self.confirmation.reset()
            self.recovering = True
        self.last_time = now
        result = dict(quality_accepted=False, reason="", projection_candidate=False,
                      candidate_x_m=None, candidate_z_m=None, observed_x_m=None,
                      observed_z_m=None, filtered_x_m=None, filtered_z_m=None,
                      nis=None, confirmation_count=0, internal_prediction=False,
                      floor_contact_verified=False, usable_for_ffb=False)

        def reject(reason, *, advance=True):
            if advance:
                track, _ = self.tracker.update_with_diagnostics(None, timestamp=now)
                result["internal_prediction"] = bool(track and track["predicted"])
            self.confirmation.reset()
            self.recovering = True
            return dict(result, reason=reason)

        # Expire before considering a new measurement: no stale track can accept it.
        if (self.last_good_time is not None
                and now-self.last_good_time > self.settings.track_memory_sec):
            self.tracker.reset()
            self.recovering = True
        if (self.last_good_time is not None
                and now-self.last_good_time > self.settings.shape_memory_sec):
            self.last_shape = None
        if len(candidates) != 1:
            return reject("no_candidate" if not candidates else "ambiguous_candidates")
        candidate = candidates[0]
        projection = self.projector.project(
            candidate, frame_width=frame_width, frame_height=frame_height)
        result["projection_candidate"] = projection["projection_candidate"]
        result["candidate_x_m"], result["candidate_z_m"] = projection["x_m"], projection["z_m"]
        if not projection["projection_candidate"]:
            return reject("projection:"+projection["reason"])
        x1, y1, x2, y2 = checked_bbox(candidate, frame_width, frame_height)
        shape = (x2-x1, y2-y1, (x2-x1)/(y2-y1))
        if self.last_shape is not None and any(
            not 1/self.settings.max_shape_factor <= value/anchor <= self.settings.max_shape_factor
            for value, anchor in zip(shape, self.last_shape)):
            return reject("abrupt_bbox_shape_change")
        measurement = (projection["x_m"], projection["z_m"])
        if self.recovering:
            confirmed, diagnostics = self.confirmation.filter_measurement(
                measurement, tracker_initialized=False)
            result["confirmation_count"] = diagnostics["confirmation_count"]
            if confirmed is None:
                # Keep the candidate confirmation, but never correct the KF yet.
                track, _ = self.tracker.update_with_diagnostics(None, timestamp=now)
                result["internal_prediction"] = bool(track and track["predicted"])
                return dict(result, reason="confirmation_pending")
        track, diagnostics = self.tracker.update_with_diagnostics(
            measurement, timestamp=now, max_nis=self.settings.max_nis)
        result["nis"] = diagnostics["nis"] if diagnostics["nis"] != "" else None
        if not diagnostics["measurement_accepted"]:
            result["internal_prediction"] = bool(track and track["predicted"])
            return reject(diagnostics["rejection_reason"], advance=False)
        self.recovering = False
        self.last_shape, self.last_good_time = shape, now
        return dict(result, quality_accepted=True, reason="temporally_consistent_hypothesis",
                    observed_x_m=measurement[0], observed_z_m=measurement[1],
                    filtered_x_m=track["x_m"], filtered_z_m=track["z_m"])
