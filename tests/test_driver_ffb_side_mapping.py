"""Side-based FFB mapping (policy B) tests; no ROS, G923 or FFB output."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ffb_side_mapping', ROOT / 'src/driver_ffb_side_mapping.py')
mapping = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mapping)


class SideMappingTests(unittest.TestCase):
    def test_left_obstacle_resists_left_with_base_magnitude(self):
        result = mapping.command('WARNING', +0.25, 0.0)
        self.assertEqual(result['direction'], -1)
        self.assertEqual(result['normalized_magnitude'], 0.25)

    def test_right_obstacle_resists_right(self):
        result = mapping.command('WARNING', -0.25, 0.0)
        self.assertEqual(result['direction'], 1)

    def test_gradient_scales_magnitude_but_never_flips_direction(self):
        base = mapping.command('WARNING', +0.25, 0.0)
        positive = mapping.command('WARNING', +0.25, +0.5)
        negative = mapping.command('WARNING', +0.25, -0.5)
        self.assertEqual(base['direction'], -1)
        self.assertEqual(positive['direction'], -1)
        self.assertEqual(negative['direction'], -1)
        self.assertAlmostEqual(positive['normalized_magnitude'], 0.25 * 1.3)
        self.assertAlmostEqual(negative['normalized_magnitude'], 0.25 * 1.3)

    def test_centered_obstacle_has_no_direction(self):
        result = mapping.command('WARNING', +0.01, 0.5)
        self.assertEqual(result['direction'], 0)
        self.assertEqual(result['normalized_magnitude'], 0.25)
        self.assertEqual(result['reason'], 'centered_no_direction')

    def test_inactive_levels_and_invalid_snapshot(self):
        self.assertEqual(mapping.command('CLEAR', +0.25, 0.9)['normalized_magnitude'], 0.0)
        invalid = mapping.command('CRITICAL', +0.25, 0.9, valid=False)
        self.assertEqual((invalid['direction'], invalid['normalized_magnitude']), (0, 0.0))
        self.assertEqual(mapping.command('CRITICAL', float('nan'), 0.9)['reason'], 'invalid_snapshot')

    def test_gradient_deadband_keeps_base_magnitude(self):
        result = mapping.command('CRITICAL', -0.3, 0.05)
        self.assertEqual(result['normalized_magnitude'], 0.40)
        self.assertEqual(result['reason'], 'base_without_gradient_modulation')

    def test_magnitude_is_clamped(self):
        result = mapping.command('CRITICAL', +0.3, 1.0)
        self.assertAlmostEqual(result['normalized_magnitude'], min(1.0, 0.40 * 1.6))

    def test_unknown_level_is_bounded_and_flags_stay_false(self):
        result = mapping.command('not-a-level', +0.25, 0.5)
        self.assertEqual(result['risk_level'], 'UNKNOWN')
        for key in ('controlling_distance', 'physical_metric_verified', 'floor_contact_verified',
                    'usable_for_ffb', 'published_to_ros'):
            self.assertFalse(result[key])


if __name__ == '__main__':
    unittest.main()
