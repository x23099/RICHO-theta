#!/usr/bin/env python3
"""Single-obstacle tracking shared by the GUI and offline evaluation tools."""

from __future__ import annotations

import math
import statistics
import time
from collections import deque

import cv2
import numpy as np


class BlueObstacleTracker:
    """Track one obstacle in vehicle coordinates with a constant-velocity KF."""

    def __init__(
        self,
        process_accel_std_mps2=1.5,
        measurement_std_m=0.03,
        max_missing_sec=0.25,
        max_dt_sec=0.2,
    ):
        self.process_accel_std_mps2 = max(
            1e-6, float(process_accel_std_mps2)
        )
        self.measurement_std_m = max(1e-6, float(measurement_std_m))
        self.max_missing_sec = max(0.0, float(max_missing_sec))
        self.max_dt_sec = max(1e-3, float(max_dt_sec))
        self.filter = cv2.KalmanFilter(4, 2)
        self.filter.measurementMatrix = np.array(
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
            dtype=np.float32,
        )
        measurement_variance = self.measurement_std_m ** 2
        self.filter.measurementNoiseCov = np.eye(2, dtype=np.float32) * (
            measurement_variance
        )
        self.last_diagnostics = {}
        self.reset()

    def reset(self):
        self.initialized = False
        self.last_update_time = None
        self.last_measurement_time = None
        self.filter.statePre = np.zeros((4, 1), dtype=np.float32)
        self.filter.statePost = np.zeros((4, 1), dtype=np.float32)
        self.filter.errorCovPost = np.diag(
            [
                self.measurement_std_m ** 2,
                self.measurement_std_m ** 2,
                0.25,
                0.25,
            ]
        ).astype(np.float32)

    def _set_motion_model(self, dt):
        dt = max(1e-3, min(float(dt), self.max_dt_sec))
        self.filter.transitionMatrix = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        accel_variance = self.process_accel_std_mps2 ** 2
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        self.filter.processNoiseCov = np.array(
            [
                [dt4 / 4.0, 0.0, dt3 / 2.0, 0.0],
                [0.0, dt4 / 4.0, 0.0, dt3 / 2.0],
                [dt3 / 2.0, 0.0, dt2, 0.0],
                [0.0, dt3 / 2.0, 0.0, dt2],
            ],
            dtype=np.float32,
        ) * accel_variance

    @staticmethod
    def _result(state, predicted, missing_age_sec):
        x_m, z_m, vx_mps, vz_mps = state.reshape(-1)
        return {
            "x_m": float(x_m),
            "z_m": float(z_m),
            "distance_m": math.hypot(float(x_m), float(z_m)),
            "vx_mps": float(vx_mps),
            "vz_mps": float(vz_mps),
            "predicted": bool(predicted),
            "missing_age_sec": float(missing_age_sec),
        }

    def update_with_diagnostics(self, measurement, timestamp=None, max_nis=None):
        """Update the filter and return ``(track, innovation diagnostics)``."""

        now = time.monotonic() if timestamp is None else float(timestamp)
        diagnostics = {
            "measurement_available": measurement is not None,
            "measurement_accepted": False,
            "rejection_reason": "no_detection" if measurement is None else "",
            "predicted_x_m": "",
            "predicted_z_m": "",
            "innovation_x_m": "",
            "innovation_z_m": "",
            "innovation_cov_xx": "",
            "innovation_cov_xz": "",
            "innovation_cov_zz": "",
            "nis": "",
        }
        if not self.initialized:
            if measurement is None:
                self.last_diagnostics = diagnostics
                return None, diagnostics
            x_m, z_m = (float(measurement[0]), float(measurement[1]))
            state = np.array([[x_m], [z_m], [0.0], [0.0]], dtype=np.float32)
            self.filter.statePre = state.copy()
            self.filter.statePost = state.copy()
            self.initialized = True
            self.last_update_time = now
            self.last_measurement_time = now
            diagnostics["measurement_accepted"] = True
            diagnostics["rejection_reason"] = "initialized"
            self.last_diagnostics = diagnostics
            return self._result(state, False, 0.0), diagnostics

        dt = max(1e-3, now - self.last_update_time)
        self._set_motion_model(dt)
        predicted_state = self.filter.predict()
        self.last_update_time = now
        diagnostics["predicted_x_m"] = float(predicted_state[0, 0])
        diagnostics["predicted_z_m"] = float(predicted_state[1, 0])

        if measurement is not None:
            measurement_array = np.array(
                [[float(measurement[0])], [float(measurement[1])]],
                dtype=np.float32,
            )
            innovation = measurement_array - (
                self.filter.measurementMatrix @ predicted_state
            )
            innovation_covariance = (
                self.filter.measurementMatrix
                @ self.filter.errorCovPre
                @ self.filter.measurementMatrix.T
                + self.filter.measurementNoiseCov
            )
            nis = float(
                innovation.T
                @ np.linalg.solve(innovation_covariance, innovation)
            )
            diagnostics.update(
                innovation_x_m=float(innovation[0, 0]),
                innovation_z_m=float(innovation[1, 0]),
                innovation_cov_xx=float(innovation_covariance[0, 0]),
                innovation_cov_xz=float(innovation_covariance[0, 1]),
                innovation_cov_zz=float(innovation_covariance[1, 1]),
                nis=nis,
            )
            if max_nis is None or nis <= float(max_nis):
                diagnostics["measurement_accepted"] = True
                diagnostics["rejection_reason"] = "accepted"
                corrected_state = self.filter.correct(measurement_array)
                self.last_measurement_time = now
                self.last_diagnostics = diagnostics
                return self._result(corrected_state, False, 0.0), diagnostics
            diagnostics["rejection_reason"] = "nis_gate"

        missing_age_sec = max(0.0, now - self.last_measurement_time)
        if missing_age_sec > self.max_missing_sec:
            self.reset()
            diagnostics["rejection_reason"] = (
                "track_expired"
                if measurement is None
                else "nis_gate_track_expired"
            )
            self.last_diagnostics = diagnostics
            return None, diagnostics
        self.last_diagnostics = diagnostics
        return self._result(predicted_state, True, missing_age_sec), diagnostics

    def update(self, measurement, timestamp=None):
        """Update with ``(x_m, z_m)`` or predict briefly when it is ``None``."""

        track, _ = self.update_with_diagnostics(measurement, timestamp=timestamp)
        return track

    def projected_position(self, timestamp=None):
        """Project the posterior state without mutating the Kalman filter."""

        if not self.initialized:
            return None
        now = time.monotonic() if timestamp is None else float(timestamp)
        dt = max(0.0, min(now - self.last_update_time, self.max_dt_sec))
        x_m, z_m, vx_mps, vz_mps = self.filter.statePost.reshape(-1)
        return float(x_m + vx_mps * dt), float(z_m + vz_mps * dt)


class ObstacleObservationGate:
    """Reject implausible contour observations before Kalman correction."""

    def __init__(
        self,
        enabled=True,
        min_area_px=None,
        min_normalized_area=None,
        min_fill_ratio=None,
        min_solidity=None,
        max_nis=None,
        confirmation_frames=1,
        confirmation_distance_m=0.15,
    ):
        self.enabled = bool(enabled)
        self.min_area_px = min_area_px
        self.min_normalized_area = min_normalized_area
        self.min_fill_ratio = min_fill_ratio
        self.min_solidity = min_solidity
        self.max_nis = max_nis
        self.confirmation_frames = max(1, int(confirmation_frames))
        self.confirmation_distance_m = max(
            0.0, float(confirmation_distance_m)
        )
        self.reset()

    def reset(self):
        self.confirmation_count = 0
        self.confirmation_position = None

    def filter_measurement(
        self,
        measurement,
        area_px=None,
        predicted_z_m=None,
        tracker_initialized=False,
        fill_ratio=None,
        solidity=None,
    ):
        diagnostics = {
            "gate_enabled": self.enabled,
            "normalized_area": "",
            "gate_passed": False,
            "gate_rejection_reason": "no_detection",
            "confirmation_count": self.confirmation_count,
        }
        if measurement is None:
            if not tracker_initialized:
                self.reset()
            return None, diagnostics
        if not self.enabled:
            diagnostics.update(
                gate_passed=True,
                gate_rejection_reason="",
            )
            return measurement, diagnostics

        area = float(area_px) if area_px is not None else math.nan
        reference_z = (
            float(predicted_z_m)
            if predicted_z_m is not None
            else float(measurement[1])
        )
        normalized_area = area * max(reference_z, 0.2) ** 2
        diagnostics["normalized_area"] = normalized_area
        if self.min_area_px is not None and area < float(self.min_area_px):
            diagnostics["gate_rejection_reason"] = "area_gate"
            if not tracker_initialized:
                self.reset()
            return None, diagnostics
        if (
            self.min_normalized_area is not None
            and normalized_area < float(self.min_normalized_area)
        ):
            diagnostics["gate_rejection_reason"] = "normalized_area_gate"
            if not tracker_initialized:
                self.reset()
            return None, diagnostics
        if self.min_fill_ratio is not None and (
            fill_ratio is None or float(fill_ratio) < float(self.min_fill_ratio)
        ):
            diagnostics["gate_rejection_reason"] = "fill_ratio_gate"
            if not tracker_initialized:
                self.reset()
            return None, diagnostics
        if self.min_solidity is not None and (
            solidity is None or float(solidity) < float(self.min_solidity)
        ):
            diagnostics["gate_rejection_reason"] = "solidity_gate"
            if not tracker_initialized:
                self.reset()
            return None, diagnostics

        if not tracker_initialized and self.confirmation_frames > 1:
            if (
                self.confirmation_position is None
                or math.dist(self.confirmation_position, measurement)
                <= self.confirmation_distance_m
            ):
                self.confirmation_count += 1
            else:
                self.confirmation_count = 1
            self.confirmation_position = tuple(measurement)
            diagnostics["confirmation_count"] = self.confirmation_count
            if self.confirmation_count < self.confirmation_frames:
                diagnostics[
                    "gate_rejection_reason"
                ] = "reacquisition_confirmation"
                return None, diagnostics
            self.reset()

        diagnostics.update(
            gate_passed=True,
            gate_rejection_reason="",
            confirmation_count=self.confirmation_count,
        )
        return measurement, diagnostics


class CausalTtcEstimator:
    """Compute TTC from a causal median of the tracked forward velocity."""

    def __init__(self, window_sec=0.3, deadband_mps=0.05, enabled=True):
        self.window_sec = max(0.01, float(window_sec))
        self.deadband_mps = max(0.0, float(deadband_mps))
        self.enabled = bool(enabled)
        self.history = deque()

    def reset(self):
        self.history.clear()

    def update(self, track, timestamp=None):
        now = time.monotonic() if timestamp is None else float(timestamp)
        if not self.enabled or track is None:
            self.reset()
            return {"smoothed_vz_mps": None, "ttc_sec": None}
        self.history.append((now, float(track["vz_mps"])))
        while self.history and self.history[0][0] < now - self.window_sec:
            self.history.popleft()
        smoothed_vz_mps = float(
            statistics.median(value for _, value in self.history)
        )
        ttc_sec = None
        if float(track["z_m"]) > 0.0 and smoothed_vz_mps < -self.deadband_mps:
            ttc_sec = float(track["z_m"]) / -smoothed_vz_mps
        return {
            "smoothed_vz_mps": smoothed_vz_mps,
            "ttc_sec": ttc_sec,
        }
