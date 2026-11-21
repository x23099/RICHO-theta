"""Yellow saturation floor: default 80 preserved, experimental override applies."""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import cone_colour_support_candidate as colour_support
from cone_colour_support_candidate import observe_separated_support
from cone_distance_core import load_config
from cone_support_completion_candidate import _context
from cone_upper_support_candidate import _upper_context

BOX = dict(x1=300., y1=300., x2=340., y2=420., class_id=0, confidence=.9)


def yellow_image(saturation):
    image = np.zeros((720, 1280, 3), np.uint8)
    hsv = np.zeros((120, 40, 3), np.uint8)
    hsv[:, :] = (23, saturation, 200)
    image[300:420, 300:340] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return image


class YellowFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load_config()[1]

    def setUp(self):
        self.original = colour_support.YELLOW_SATURATION_MIN
        self.addCleanup(setattr, colour_support, 'YELLOW_SATURATION_MIN', self.original)

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(self.original, 80)
        self.assertEqual(colour_support.checked_yellow_saturation_min(80), 80)
        for value in (-1, 256, 1.5, True, '80'):
            with self.assertRaises(ValueError):
                colour_support.checked_yellow_saturation_min(value)

    def test_low_saturation_yellow_is_kept_at_80_and_dropped_at_130(self):
        image = yellow_image(100)
        colour_support.YELLOW_SATURATION_MIN = 80
        low = observe_separated_support(image, BOX, self.camera)
        self.assertEqual(low['selected_colour'], 'yellow')
        colour_support.YELLOW_SATURATION_MIN = 130
        high = observe_separated_support(image, BOX, self.camera)
        self.assertIsNone(high['selected_colour'])
        self.assertEqual(high['reason'], 'insufficient_upper_body_colour_evidence')

    def test_completion_context_reads_the_same_constant(self):
        image = yellow_image(100)
        colour_support.YELLOW_SATURATION_MIN = 80
        baseline = observe_separated_support(image, BOX, self.camera)
        seed = baseline['seed_xyxy']
        info, pixels, label = _context(image, BOX, self.camera, 'yellow', seed, 4)
        self.assertIsNotNone(label)
        colour_support.YELLOW_SATURATION_MIN = 130
        info, pixels, label = _context(image, BOX, self.camera, 'yellow', seed, 4)
        self.assertIsNone(label)
        self.assertEqual(info['reason'], 'seed_not_one_colour_component')

    def test_upper_context_uses_the_same_constant(self):
        image = yellow_image(100)
        colour_support.YELLOW_SATURATION_MIN = 80
        seed = observe_separated_support(image, BOX, self.camera)['seed_xyxy']
        info, pixels = _upper_context(image, BOX, self.camera, 'yellow', seed, 4)
        self.assertIsNotNone(pixels)
        colour_support.YELLOW_SATURATION_MIN = 130
        info, pixels = _upper_context(image, BOX, self.camera, 'yellow', seed, 4)
        self.assertIsNone(pixels)
        self.assertEqual(info['reason'], 'seed_not_one_colour_component')

    def test_environment_override_is_read_at_import_and_default_is_80(self):
        with mock.patch.dict(os.environ, {'THETA_YELLOW_S_MIN': '170'}):
            importlib.reload(colour_support)
            self.assertEqual(colour_support.YELLOW_SATURATION_MIN, 170)
        os.environ.pop('THETA_YELLOW_S_MIN', None)
        importlib.reload(colour_support)
        self.assertEqual(colour_support.YELLOW_SATURATION_MIN, 80)

    def test_saturated_cone_is_kept_at_130(self):
        image = yellow_image(240)
        colour_support.YELLOW_SATURATION_MIN = 130
        result = observe_separated_support(image, BOX, self.camera)
        self.assertEqual(result['selected_colour'], 'yellow')


if __name__ == '__main__':
    unittest.main()
