import sys
import unittest
from pathlib import Path

import cv2


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from camera_capture_properties import (  # noqa: E402
    exposure_summary,
    read_capture_properties,
)


class FakeCapture:
    def getBackendName(self):
        return "V4L2"

    def get(self, property_id):
        values = {
            cv2.CAP_PROP_AUTO_EXPOSURE: 3.0,
            cv2.CAP_PROP_EXPOSURE: -6.0,
            cv2.CAP_PROP_GAIN: 12.0,
        }
        return values.get(property_id, -1.0)


class CapturePropertiesTest(unittest.TestCase):
    def test_reads_exposure_values_without_setting_capture(self):
        properties = read_capture_properties(FakeCapture())

        self.assertEqual(properties["backend"], "V4L2")
        self.assertEqual(properties["auto_exposure"], 3.0)
        self.assertEqual(properties["exposure"], -6.0)
        self.assertIn("auto_exposure=3.0", exposure_summary(properties))


if __name__ == "__main__":
    unittest.main()
