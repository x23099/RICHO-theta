"""2-of-3 direction consistency tests; no ROS, camera or FFB."""
import importlib.util
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('risk_consistency',
                                              ROOT / 'src/driver_risk_consistency.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.unit = module.DirectionConsistency(clock=self.clock)

    def offer(self, value, *, level='WARNING', valid=True, step=0.2):
        self.clock.now += step
        return self.unit.offer(value, risk_level=level, valid=valid)

    def test_steady_agreement_confirms_without_added_latency(self):
        self.offer(0.5)
        self.offer(0.6)
        result = self.offer(0.7)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], -1)
        self.assertEqual(result['gradient_normalized'], 0.7)
        self.assertEqual(result['added_latency_sec'], 0.0)
        self.assertEqual(result['risk_level'], 'WARNING')

    def test_single_outlier_keeps_the_confirmed_direction_and_reports_latency(self):
        self.offer(0.5)
        self.offer(0.6)
        self.offer(-0.5)
        result = self.unit.snapshot()
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], -1)
        self.assertEqual(result['gradient_normalized'], 0.6)
        self.assertAlmostEqual(result['added_latency_sec'], 0.2)

    def test_two_contradictions_withhold_instead_of_keeping_previous(self):
        self.offer(0.5)
        self.offer(-0.5)
        result = self.offer(-0.6)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], 1)
        self.offer(0.4)
        self.offer(0.4)
        result = self.offer(0.4)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], -1)

    def test_full_disagreement_is_not_confirmed(self):
        self.offer(0.5)
        self.offer(-0.5)
        result = self.offer(0.0)
        self.assertFalse(result['confirmed'])
        self.assertIsNone(result['direction'])
        self.assertEqual(result['reason'], 'disagreement')

    def test_invalid_sample_clears_the_window(self):
        self.offer(0.5)
        self.offer(0.6)
        result = self.offer(0.7, valid=False)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'invalid_sample')
        self.assertEqual(result['samples'], 0)

    def test_non_finite_value_is_treated_as_invalid(self):
        self.offer(0.5)
        self.offer(0.6)
        self.clock.now += 0.2
        result = self.unit.offer(math.nan)
        self.assertEqual(result['reason'], 'invalid_sample')

    def test_stale_window_is_not_confirmed(self):
        self.offer(0.5)
        self.offer(0.6)
        self.offer(0.7)
        self.clock.now += 1.0
        result = self.unit.snapshot()
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'stale')

    def test_deadband_maps_small_values_to_zero(self):
        for value in (0.05, -0.09, 0.1, -0.1):
            self.unit.reset()
            for _ in range(3):
                result = self.offer(value)
            self.assertTrue(result['confirmed'])
            self.assertEqual(result['direction'], 0)

    def test_clock_reversal_closes_the_unit(self):
        self.offer(0.5)
        self.clock.now -= 1.0
        result = self.unit.offer(0.5)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'clock_reversed')
        self.clock.now += 5
        self.assertFalse(self.unit.offer(0.5)['confirmed'])

    def test_unknown_level_is_bounded_and_flags_stay_false(self):
        result = None
        for _ in range(3):
            result = self.offer(0.5, level='not-a-level')
        self.assertEqual(result['risk_level'], 'UNKNOWN')
        for key in ('controlling_distance', 'physical_metric_verified', 'usable_for_ffb',
                    'published_to_ros'):
            self.assertFalse(result[key])

    def test_bad_configuration_is_rejected(self):
        for kwargs in (dict(window=0), dict(window=3, required=4), dict(deadband=1.5),
                       dict(max_sample_age_sec=0), dict(window=2.5)):
            with self.assertRaises(ValueError):
                module.DirectionConsistency(**kwargs)


if __name__ == '__main__':
    unittest.main()
