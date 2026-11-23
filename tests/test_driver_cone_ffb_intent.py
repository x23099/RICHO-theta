"""Cone-distance FFB intent tests (policy B); no camera, ROS or G923."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
SPEC = importlib.util.spec_from_file_location('cone_ffb_intent', ROOT / 'src/driver_cone_ffb_intent.py')
intent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intent)

CAL = dict(schema='lateral_calibration_table_v1', distances=[1.0, 1.5, 2.0],
           cx_ref=[306.5, 308.2, 305.7], k_m_per_px=[0.00401, 0.00570, 0.00739])


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class CalibrationTests(unittest.TestCase):
    def test_checked_calibration_requires_ascending_matching_columns(self):
        self.assertEqual(intent.checked_calibration(CAL)['distances'], [1.0, 1.5, 2.0])
        bad = dict(CAL, distances=[1.5, 1.0, 2.0])
        with self.assertRaises(ValueError):
            intent.checked_calibration(bad)
        with self.assertRaises(ValueError):
            intent.checked_calibration(dict(CAL, k_m_per_px=[0.004, 0.005]))
        with self.assertRaises(ValueError):
            intent.checked_calibration(dict(CAL, k_m_per_px=[0.004, -0.005, 0.007]))

    def test_estimate_left_matches_the_calibration_points_and_interpolates(self):
        calibration = intent.checked_calibration(CAL)
        left, reason = intent.estimate_left(1.5, 264.6, calibration)
        self.assertAlmostEqual(left, (308.2 - 264.6) * 0.0057, places=4)
        self.assertEqual(reason, 'estimated_from_box_centre')
        left, _ = intent.estimate_left(1.25, 306.5, calibration)
        self.assertIsNotNone(left)
        self.assertLess(left, (308.2 - 264.6) * 0.0057)

    def test_estimate_left_rejects_invalid_inputs_and_clamps_the_distance(self):
        calibration = intent.checked_calibration(CAL)
        left, reason = intent.estimate_left(2.6, 300.0, calibration)
        self.assertIsNotNone(left)
        self.assertIn('clamped_to_calibration_edge', reason)
        self.assertIsNone(intent.estimate_left(float('nan'), 300.0, calibration)[0])
        self.assertIsNone(intent.estimate_left(1.5, None, calibration)[0])


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.unit = intent.ConeFfbIntent(CAL)

    def offer(self, box_x, range_m=1.5, speed=0.5, yaw=0.0, step=0.2):
        self.clock.now += step
        return self.unit.offer(range_m, box_x, speed, yaw, at_sec=self.clock.now)

    def test_left_cone_needs_three_consecutive_snapshots_to_confirm(self):
        first = self.offer(264.6)
        self.assertFalse(first['confirmed'])
        self.assertEqual(first['left_m'], 0.2485)
        self.assertEqual(first['direction'], 0)
        self.offer(264.6)
        third = self.offer(264.6)
        self.assertTrue(third['confirmed'])
        self.assertEqual(third['direction'], -1)
        self.assertGreater(third['normalized_magnitude'], 0.0)

    def test_right_cone_resists_right(self):
        for _ in range(3):
            result = self.offer(355.3)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], 1)

    def test_centered_cone_has_no_direction(self):
        for _ in range(3):
            result = self.offer(308.2)
        self.assertEqual(result['direction'], 0)
        self.assertFalse(result['confirmed'])

    def test_side_flip_needs_three_new_snapshots(self):
        for _ in range(3):
            self.offer(264.6)
        self.assertFalse(self.offer(355.3)['confirmed'])
        self.assertFalse(self.offer(355.3)['confirmed'])
        flipped = self.offer(355.3)
        self.assertTrue(flipped['confirmed'])
        self.assertEqual(flipped['direction'], 1)

    def test_outside_calibration_and_invalid_snapshot_withhold(self):
        result = self.offer(300.0, range_m=2.8)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['direction'], 0)
        result = self.unit.offer(300.0, 1.5, 0.5, 0.0, valid=False, at_sec=1.0)
        self.assertFalse(result['confirmed'])

    def test_flags_stay_false(self):
        for _ in range(3):
            result = self.offer(264.6)
        for key in ('controlling_distance', 'physical_metric_verified', 'floor_contact_verified',
                    'usable_for_ffb', 'published_to_ros'):
            self.assertFalse(result[key])


if __name__ == '__main__':
    unittest.main()
