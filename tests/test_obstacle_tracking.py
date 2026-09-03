import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from obstacle_tracking import (  # noqa: E402
    BlueObstacleTracker,
    CausalTtcEstimator,
    ObstacleObservationGate,
)


class BlueObstacleTrackerDiagnosticsTest(unittest.TestCase):
    def test_reports_initialization_and_innovation(self):
        tracker = BlueObstacleTracker()

        first, first_diagnostics = tracker.update_with_diagnostics(
            (0.0, 1.0), timestamp=0.0
        )
        second, second_diagnostics = tracker.update_with_diagnostics(
            (0.1, 1.2), timestamp=0.1
        )

        self.assertIsNotNone(first)
        self.assertTrue(first_diagnostics["measurement_accepted"])
        self.assertEqual(first_diagnostics["rejection_reason"], "initialized")
        self.assertIsNotNone(second)
        self.assertTrue(second_diagnostics["measurement_accepted"])
        self.assertEqual(second_diagnostics["rejection_reason"], "accepted")
        self.assertAlmostEqual(second_diagnostics["innovation_x_m"], 0.1)
        self.assertAlmostEqual(second_diagnostics["innovation_z_m"], 0.2)
        self.assertGreater(second_diagnostics["nis"], 0.0)

    def test_reports_prediction_and_expiration_for_missing_measurements(self):
        tracker = BlueObstacleTracker(max_missing_sec=0.25)
        tracker.update((0.0, 1.0), timestamp=0.0)

        predicted, predicted_diagnostics = tracker.update_with_diagnostics(
            None, timestamp=0.1
        )
        expired, expired_diagnostics = tracker.update_with_diagnostics(
            None, timestamp=0.3
        )

        self.assertTrue(predicted["predicted"])
        self.assertEqual(
            predicted_diagnostics["rejection_reason"], "no_detection"
        )
        self.assertIsNone(expired)
        self.assertEqual(expired_diagnostics["rejection_reason"], "track_expired")

    def test_nis_gate_rejects_an_outlier_without_correcting_track(self):
        tracker = BlueObstacleTracker()
        tracker.update((0.0, 1.0), timestamp=0.0)

        track, diagnostics = tracker.update_with_diagnostics(
            (0.0, 3.0), timestamp=0.1, max_nis=5.991
        )

        self.assertFalse(diagnostics["measurement_accepted"])
        self.assertEqual(diagnostics["rejection_reason"], "nis_gate")
        self.assertGreater(diagnostics["nis"], 5.991)
        self.assertTrue(track["predicted"])
        self.assertAlmostEqual(track["z_m"], 1.0)

    def test_projected_position_does_not_mutate_tracker(self):
        tracker = BlueObstacleTracker()
        tracker.update((0.0, 1.0), timestamp=0.0)
        tracker.update((0.0, 0.9), timestamp=0.1)
        before = tracker.filter.statePost.copy()

        projected = tracker.projected_position(timestamp=0.2)

        self.assertLess(projected[1], float(before[1, 0]))
        self.assertTrue((before == tracker.filter.statePost).all())


class ObstacleObservationGateTest(unittest.TestCase):
    def test_explicit_normalization_distance_overrides_forward_range(self):
        gate = ObstacleObservationGate(min_normalized_area=2500.0)

        measurement, diagnostics = gate.filter_measurement(
            (0.3, 0.9),
            area_px=2300.0,
            predicted_z_m=0.9,
            normalization_distance_m=1.05,
            tracker_initialized=True,
        )

        self.assertEqual(measurement, (0.3, 0.9))
        self.assertAlmostEqual(diagnostics["normalization_distance_m"], 1.05)
        self.assertAlmostEqual(diagnostics["normalized_area"], 2535.75)

    def test_normalized_area_and_confirmation_are_both_required(self):
        gate = ObstacleObservationGate(
            min_normalized_area=2500.0,
            confirmation_frames=2,
        )

        rejected, area_diagnostics = gate.filter_measurement(
            (0.0, 1.0), area_px=1000.0, predicted_z_m=1.0
        )
        first, confirmation_diagnostics = gate.filter_measurement(
            (0.0, 1.0), area_px=3000.0, predicted_z_m=1.0
        )
        second, accepted_diagnostics = gate.filter_measurement(
            (0.01, 1.0), area_px=3000.0, predicted_z_m=1.0
        )

        self.assertIsNone(rejected)
        self.assertEqual(
            area_diagnostics["gate_rejection_reason"], "normalized_area_gate"
        )
        self.assertIsNone(first)
        self.assertEqual(
            confirmation_diagnostics["gate_rejection_reason"],
            "reacquisition_confirmation",
        )
        self.assertEqual(second, (0.01, 1.0))
        self.assertTrue(accepted_diagnostics["gate_passed"])

    def test_calibration_invalid_measurement_is_rejected_even_when_disabled(self):
        gate = ObstacleObservationGate(enabled=False)

        measurement, diagnostics = gate.filter_measurement(
            (0.0, 0.60),
            area_px=4000.0,
            predicted_z_m=0.65,
            tracker_initialized=True,
            measurement_valid=False,
            invalid_reason="calibration_range_gate",
        )

        self.assertIsNone(measurement)
        self.assertFalse(diagnostics["gate_passed"])
        self.assertEqual(
            diagnostics["gate_rejection_reason"], "calibration_range_gate"
        )


class CausalTtcEstimatorTest(unittest.TestCase):
    def test_applies_deadband_after_causal_median(self):
        estimator = CausalTtcEstimator(window_sec=0.3, deadband_mps=0.05)
        track = {"z_m": 1.0, "vz_mps": -0.10}

        approaching = estimator.update(track, timestamp=0.0)
        stopped = estimator.update(
            {"z_m": 0.9, "vz_mps": 0.0}, timestamp=0.1
        )

        self.assertAlmostEqual(approaching["ttc_sec"], 10.0)
        self.assertIsNone(stopped["ttc_sec"])

    def test_odom_static_uses_negative_ego_velocity(self):
        estimator = CausalTtcEstimator(
            deadband_mps=0.03, velocity_source="odom_static"
        )

        result = estimator.update(
            {"z_m": 1.0, "vz_mps": -0.1},
            timestamp=0.0,
            ego_linear_mps=0.2,
        )

        self.assertAlmostEqual(result["visual_smoothed_vz_mps"], -0.1)
        self.assertAlmostEqual(result["smoothed_vz_mps"], -0.2)
        self.assertAlmostEqual(result["ttc_sec"], 5.0)
        self.assertEqual(result["ttc_velocity_source"], "odom_static")

    def test_conservative_uses_more_negative_velocity(self):
        estimator = CausalTtcEstimator(
            deadband_mps=0.03, velocity_source="conservative"
        )

        odom_dominates = estimator.update(
            {"z_m": 1.0, "vz_mps": -0.1},
            timestamp=0.0,
            ego_linear_mps=0.2,
        )
        estimator.reset()
        visual_dominates = estimator.update(
            {"z_m": 1.0, "vz_mps": -0.3},
            timestamp=1.0,
            ego_linear_mps=0.2,
        )

        self.assertAlmostEqual(odom_dominates["smoothed_vz_mps"], -0.2)
        self.assertEqual(
            odom_dominates["ttc_velocity_source"], "conservative_odom"
        )
        self.assertAlmostEqual(visual_dominates["smoothed_vz_mps"], -0.3)
        self.assertEqual(
            visual_dominates["ttc_velocity_source"], "conservative_visual"
        )

    def test_missing_odom_falls_back_to_visual(self):
        estimator = CausalTtcEstimator(velocity_source="conservative")

        result = estimator.update(
            {"z_m": 1.0, "vz_mps": -0.1}, timestamp=0.0
        )

        self.assertAlmostEqual(result["smoothed_vz_mps"], -0.1)
        self.assertEqual(result["ttc_velocity_source"], "visual_fallback")

    def test_rejects_unknown_velocity_source(self):
        with self.assertRaises(ValueError):
            CausalTtcEstimator(velocity_source="unknown")


if __name__ == "__main__":
    unittest.main()
