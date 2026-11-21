"""3-consecutive direction consistency tests; no ROS, camera or FFB."""
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

    def feed(self, values, **kwargs):
        result = None
        for value in values:
            result = self.offer(value, **kwargs)
        return result

    def test_three_consecutive_samples_confirm(self):
        result = self.feed([0.5, 0.6, 0.7])
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], -1)
        self.assertEqual(result['gradient_normalized'], 0.7)
        self.assertAlmostEqual(result['added_latency_sec'], 0.4)
        self.assertEqual(result['risk_level'], 'WARNING')

    def test_single_outlier_does_not_confirm(self):
        self.feed([0.5, 0.6])
        result = self.offer(-0.5)
        self.assertFalse(result['confirmed'])
        self.assertIsNone(result['direction'])
        self.assertEqual(result['reason'], 'disagreement')

    def test_direction_change_needs_three_consecutive_new_votes(self):
        self.feed([0.5, 0.5, 0.5])
        self.assertFalse(self.offer(-0.5)['confirmed'])
        self.assertFalse(self.offer(-0.5)['confirmed'])
        result = self.offer(-0.5)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], 1)

    def test_alternating_signs_never_confirm(self):
        results = [self.offer(value) for value in (0.5, -0.5) * 6]
        self.assertFalse(any(result['confirmed'] for result in results))

    def test_long_gap_expires_old_votes(self):
        self.feed([0.5, 0.6])
        result = self.offer(-0.5, step=2.0)
        self.assertFalse(result['confirmed'])
        self.assertIn(result['reason'], ('warming_up', 'stale'))

    def test_stale_window_without_new_samples_is_not_confirmed(self):
        self.feed([0.5, 0.6, 0.7])
        self.clock.now += 1.0
        result = self.unit.snapshot()
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'stale')

    def test_invalid_and_nonfinite_samples_clear_the_window(self):
        self.feed([0.5, 0.6])
        self.assertFalse(self.offer(0.7, valid=False)['confirmed'])
        self.assertEqual(self.unit.snapshot()['samples'], 0)
        self.feed([0.5, 0.6])
        self.clock.now += 0.2
        self.assertEqual(self.unit.offer(math.nan)['reason'], 'invalid_sample')

    def test_deadband_maps_small_values_to_zero(self):
        for value in (0.05, -0.09, 0.1, -0.1):
            self.unit.reset()
            result = self.feed([value, value, value])
            self.assertTrue(result['confirmed'])
            self.assertEqual(result['direction'], 0)

    def test_clock_reversal_closes_the_unit(self):
        self.feed([0.5, 0.5])
        self.clock.now -= 1.0
        result = self.unit.offer(0.5)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'clock_reversed')
        self.clock.now += 5
        self.assertFalse(self.unit.offer(0.5)['confirmed'])

    def test_unknown_level_is_bounded_and_flags_stay_false(self):
        result = self.feed([0.5, 0.5, 0.5], level='not-a-level')
        self.assertEqual(result['risk_level'], 'UNKNOWN')
        for key in ('controlling_distance', 'physical_metric_verified', 'usable_for_ffb',
                    'published_to_ros'):
            self.assertFalse(result[key])

    def test_bad_configuration_is_rejected(self):
        for kwargs in (dict(window=0), dict(window=3, required=4), dict(deadband=1.5),
                       dict(max_sample_age_sec=0), dict(window=2.5)):
            with self.assertRaises(ValueError):
                module.DirectionConsistency(**kwargs)

    def test_default_is_three_consecutive(self):
        unit = module.DirectionConsistency(clock=self.clock)
        self.assertEqual((unit.window, unit.required), (3, 3))


if __name__ == '__main__':
    unittest.main()
