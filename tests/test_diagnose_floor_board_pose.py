"""No camera/model/network. Injected geometry is NOT real checkerboard evidence."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from angular_fisheye_geometry import project
from cone_distance_core import load_config
from diagnose_floor_board_pose import analyse_board_frame
from fisheye_intrinsic_calibration import Board


class FloorBoardTests(unittest.TestCase):
    def setUp(self):
        self.camera = load_config()[1]
        self.image = np.zeros((720, 1280, 3), np.uint8)
        world = Board(square_mm=20.).object_points.reshape(-1, 3)
        rotation = np.array([[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]])
        self.points, valid = project((world-[-.5, 0, .59]) @ rotation, self.camera)
        self.assertTrue(valid.all())

    def test_no_floor_declaration_no_plane(self):
        with patch("diagnose_floor_board_pose._detect", return_value=self.points):
            r = analyse_board_frame(self.image, self.camera, square_mm=20.)
        self.assertEqual(r["status"], "FLOOR_PLACEMENT_NOT_CONFIRMED_NO_FLOOR_POSE")
        self.assertEqual(r["pose_candidates"], [])

    def test_floor_plane_has_no_vehicle_transform_and_keeps_solutions(self):
        before = self.image.copy()
        with patch("diagnose_floor_board_pose._detect", return_value=self.points):
            r = analyse_board_frame(self.image, self.camera, square_mm=20., floor_placement_confirmed=True)
        self.assertEqual(len(r["pose_candidates"]), 2)
        best = min(r["pose_candidates"], key=lambda x: x["native_reprojection_rmse_px"])
        self.assertAlmostEqual(best["camera_to_printed_plane_m"], .59, places=7)
        self.assertIsNone(best["camera_to_floor_m_if_thickness_supplied"])
        self.assertFalse(r["physical_metric_verified"])
        self.assertFalse(r["base_link_transform_available"])
        self.assertFalse(r["vehicle_heading_verified"])
        self.assertTrue(all(not c["selected"] for c in r["pose_candidates"]))
        np.testing.assert_array_equal(before, self.image)

    def test_measured_board_thickness_is_added_not_hidden(self):
        with patch("diagnose_floor_board_pose._detect", return_value=self.points):
            r = analyse_board_frame(self.image, self.camera, square_mm=20., floor_placement_confirmed=True,
                                    board_thickness_mm=3.)
        best = min(r["pose_candidates"], key=lambda x: x["native_reprojection_rmse_px"])
        self.assertAlmostEqual(best["camera_to_floor_m_if_thickness_supplied"], .593, places=7)

    def test_missing_board_produces_no_pose(self):
        with patch("diagnose_floor_board_pose._detect", return_value=None):
            r = analyse_board_frame(self.image, self.camera, square_mm=20., floor_placement_confirmed=True)
        self.assertEqual(r["status"], "BOARD_NOT_FOUND")
        self.assertEqual(r["pose_candidates"], [])

    def test_partial_grid_never_filled_in(self):
        with patch("diagnose_floor_board_pose._detect", return_value=self.points[:-1]):
            r = analyse_board_frame(self.image, self.camera, square_mm=20., floor_placement_confirmed=True)
        self.assertEqual(r["status"], "INVALID_OR_PARTIAL_GRID")
        self.assertEqual(r["pose_candidates"], [])

    def test_rear_roi_not_used_for_front_model(self):
        with self.assertRaises(ValueError):
            analyse_board_frame(self.image, self.camera, square_mm=20., roi=(640, 0, 640, 720))

    def test_square_size_and_thickness_must_be_finite(self):
        for kwargs in (dict(square_mm=float("nan")), dict(square_mm=20., board_thickness_mm=-1.),
                       dict(square_mm=20., board_thickness_mm=True)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                analyse_board_frame(self.image, self.camera, **kwargs)


if __name__ == "__main__":
    unittest.main()
