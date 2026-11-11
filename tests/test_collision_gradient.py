import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from collision_risk import (  # noqa: E402
    SteeringGradientFilter,
    evaluate_candidate_steering,
    gradient_to_direction,
    path_risk_from_eta,
)


class PathRiskFromEtaTest(unittest.TestCase):
    def test_clear_path_has_zero_risk(self):
        self.assertEqual(path_risk_from_eta(1.0, False), 0.0)

    def test_risk_is_inverse_eta(self):
        self.assertAlmostEqual(path_risk_from_eta(5.0, True), 0.2)
        self.assertAlmostEqual(path_risk_from_eta(2.0, True), 0.5)

    def test_eta_is_clamped_to_bounds(self):
        self.assertAlmostEqual(path_risk_from_eta(0.01, True), 10.0)
        self.assertAlmostEqual(path_risk_from_eta(100.0, True), 0.1)

    def test_missing_eta_inside_corridor_gets_floor_risk(self):
        self.assertAlmostEqual(path_risk_from_eta(None, True), 0.1)

    def test_invalid_bounds_are_rejected(self):
        with self.assertRaises(ValueError):
            path_risk_from_eta(1.0, True, min_ttc_sec=0.0)
        with self.assertRaises(ValueError):
            path_risk_from_eta(
                1.0,
                True,
                min_ttc_sec=2.0,
                max_ttc_sec=1.0,
            )


class CandidateSteeringTest(unittest.TestCase):
    def evaluate(self, **overrides):
        arguments = {
            "linear_mps": 0.2,
            "angular_radps": 0.0,
            "obstacle_forward_m": 1.0,
            "obstacle_left_m": 0.0,
            "vehicle_width_m": 0.354,
            "safety_margin_m": 0.10,
        }
        arguments.update(overrides)
        return evaluate_candidate_steering(**arguments)

    def test_centered_obstacle_has_no_direction_bias(self):
        result = self.evaluate()

        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["gradient_raw"], 0.0, places=6)
        self.assertEqual(result["direction"], 0)

    def test_left_obstacle_produces_positive_gradient(self):
        result = self.evaluate(obstacle_left_m=0.15)

        self.assertGreater(result["gradient_raw"], 0.0)
        self.assertGreater(result["gradient_normalized"], 0.0)
        self.assertEqual(result["direction"], -1)

    def test_right_obstacle_produces_negative_gradient(self):
        result = self.evaluate(obstacle_left_m=-0.30)

        self.assertLess(result["gradient_raw"], 0.0)
        self.assertLess(result["gradient_normalized"], 0.0)
        self.assertEqual(result["direction"], 1)

    def test_left_gradient_magnitude_matches_eta_definition(self):
        result = self.evaluate(obstacle_left_m=0.30)

        self.assertAlmostEqual(result["gradient_raw"], 0.649, places=3)
        self.assertGreater(result["risk_left"], 0.0)
        self.assertEqual(result["risk_right"], 0.0)
        self.assertTrue(result["corridor_left"])
        self.assertFalse(result["corridor_right"])

    def test_low_speed_suppresses_gradient(self):
        result = self.evaluate(linear_mps=0.0)

        self.assertTrue(result["valid"])
        self.assertEqual(result["gradient_raw"], 0.0)
        self.assertEqual(result["reason"], "low_speed")

    def test_reverse_motion_flips_gradient_sign(self):
        forward = self.evaluate(
            linear_mps=0.2,
            obstacle_forward_m=1.0,
            obstacle_left_m=0.30,
        )
        reverse = self.evaluate(
            linear_mps=-0.2,
            obstacle_forward_m=-1.0,
            obstacle_left_m=0.30,
        )

        self.assertGreater(forward["gradient_raw"], 0.0)
        self.assertGreater(reverse["gradient_raw"], 0.0)
        self.assertAlmostEqual(
            forward["gradient_raw"],
            reverse["gradient_raw"],
            places=4,
        )
        self.assertGreater(reverse["risk_left"], 0.0)
        self.assertEqual(reverse["risk_right"], 0.0)
        self.assertEqual(reverse["direction"], -1)

    def test_inactive_risk_levels_suppress_gradient(self):
        for level in ("CLEAR", "PATH"):
            result = self.evaluate(
                obstacle_left_m=0.15,
                risk_level=level,
            )
            self.assertEqual(result["gradient_raw"], 0.0)
            self.assertEqual(result["reason"], "inactive_risk_level")

    def test_non_finite_obstacle_fails_closed(self):
        result = self.evaluate(obstacle_forward_m=math.nan)

        self.assertFalse(result["valid"])
        self.assertEqual(result["gradient_raw"], 0.0)
        self.assertEqual(result["reason"], "invalid_obstacle")

    def test_invalid_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(delta_radps=0.0)
        with self.assertRaises(ValueError):
            self.evaluate(g_scale=0.0)
        with self.assertRaises(ValueError):
            self.evaluate(vehicle_width_m=-0.1)
        with self.assertRaises(ValueError):
            self.evaluate(linear_mps=math.nan)

    def test_path_factory_receives_left_center_right_omegas(self):
        calls = []

        def factory(linear_mps, angular_radps):
            calls.append((linear_mps, angular_radps))
            return [(0.1, 0.0, 0.0), (0.2, 0.0, 0.0)]

        evaluate_candidate_steering(
            0.2,
            0.1,
            1.0,
            0.0,
            0.354,
            delta_radps=0.15,
            path_factory=factory,
        )

        self.assertEqual(len(calls), 3)
        self.assertAlmostEqual(calls[0][1], 0.1 - 0.15)
        self.assertAlmostEqual(calls[1][1], 0.1)
        self.assertAlmostEqual(calls[2][1], 0.1 + 0.15)


class GradientDirectionTest(unittest.TestCase):
    def test_sign_convention(self):
        self.assertEqual(gradient_to_direction(0.2), -1)
        self.assertEqual(gradient_to_direction(-0.2), 1)
        self.assertEqual(gradient_to_direction(0.05), 0)
        self.assertEqual(gradient_to_direction(-0.05), 0)
        self.assertEqual(gradient_to_direction(0.1), 0)
        self.assertEqual(gradient_to_direction(math.nan), 0)

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaises(ValueError):
            gradient_to_direction(0.2, threshold=-0.1)
        with self.assertRaises(ValueError):
            gradient_to_direction(0.2, threshold=math.nan)


class SteeringGradientFilterTest(unittest.TestCase):
    def test_ema_smooths_then_deadband_zeroes_small_values(self):
        gradient_filter = SteeringGradientFilter(
            ema_alpha=0.5,
            deadband=0.1,
        )

        self.assertAlmostEqual(gradient_filter.update(0.8), 0.4)
        self.assertAlmostEqual(gradient_filter.update(0.8), 0.6)
        self.assertAlmostEqual(gradient_filter.update(0.05), 0.325)
        self.assertAlmostEqual(gradient_filter.update(0.0), 0.1625)
        self.assertEqual(gradient_filter.update(0.0), 0.0)

    def test_clear_or_path_resets_internal_state(self):
        gradient_filter = SteeringGradientFilter(
            ema_alpha=0.5,
            deadband=0.0,
        )
        gradient_filter.update(1.0)

        self.assertEqual(
            gradient_filter.update(1.0, risk_level="CLEAR"),
            0.0,
        )
        self.assertEqual(gradient_filter.value, 0.0)
        self.assertAlmostEqual(gradient_filter.update(1.0), 0.5)

    def test_invalid_update_resets_state(self):
        gradient_filter = SteeringGradientFilter(
            ema_alpha=0.5,
            deadband=0.0,
        )
        gradient_filter.update(1.0)

        self.assertEqual(gradient_filter.update(1.0, valid=False), 0.0)
        self.assertEqual(gradient_filter.value, 0.0)

    def test_values_are_clamped_before_filtering(self):
        gradient_filter = SteeringGradientFilter(
            ema_alpha=1.0,
            deadband=0.0,
        )

        self.assertEqual(gradient_filter.update(5.0), 1.0)
        gradient_filter.reset()
        self.assertEqual(gradient_filter.update(-5.0), -1.0)

    def test_invalid_construction_is_rejected(self):
        with self.assertRaises(ValueError):
            SteeringGradientFilter(ema_alpha=0.0)
        with self.assertRaises(ValueError):
            SteeringGradientFilter(ema_alpha=1.5)
        with self.assertRaises(ValueError):
            SteeringGradientFilter(deadband=-0.1)


if __name__ == "__main__":
    unittest.main()
