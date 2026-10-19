import sys
import unittest
from pathlib import Path

import numpy as np


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from bird_eye import make_rectilinear_view_map  # noqa: E402


class RectilinearViewMapTest(unittest.TestCase):
    def test_forward_center_uses_calibrated_front_lens_center(self):
        map_x, map_y = make_rectilinear_view_map(
            in_w=1280,
            in_h=720,
            out_w=800,
            out_h=450,
            radius_scale=0.86,
            front_cx_offset=-80.0,
            front_cy_offset=-21.0,
        )

        self.assertEqual(map_x.shape, (450, 800))
        self.assertEqual(map_y.shape, (450, 800))
        self.assertEqual(map_x.dtype, np.float32)
        self.assertEqual(map_y.dtype, np.float32)
        self.assertAlmostEqual(float(map_x[225, 400]), 320.0, places=5)
        self.assertAlmostEqual(float(map_y[225, 400]), 339.0, places=5)

    def test_rear_center_uses_calibrated_back_lens_center(self):
        map_x, map_y = make_rectilinear_view_map(
            in_w=1280,
            in_h=720,
            out_w=800,
            out_h=450,
            yaw_deg=180.0,
            back_cx_offset=82.0,
            back_cy_offset=-18.0,
        )

        self.assertAlmostEqual(float(map_x[225, 400]), 962.0, places=4)
        self.assertAlmostEqual(float(map_y[225, 400]), 342.0, places=4)

    def test_rejects_invalid_projection_parameters(self):
        with self.assertRaises(ValueError):
            make_rectilinear_view_map(1280, 720, 800, 450, fov_deg=180.0)
        with self.assertRaises(ValueError):
            make_rectilinear_view_map(
                1280, 720, 800, 450, front_lens="unknown"
            )


if __name__ == "__main__":
    unittest.main()
