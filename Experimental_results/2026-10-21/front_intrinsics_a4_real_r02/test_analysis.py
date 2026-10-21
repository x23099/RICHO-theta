"""Local recovery / pre-fit invariants; no hardware output or calibration bypass."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from extract import inspect
from recover_exports import union_fields, reference_match, signal_intervals
from audit_sparse_limits import selected_frames
from fisheye_intrinsic_calibration import Board, fit_candidate
from cone_dataset import write_csv

HERE = Path(__file__).resolve().parent


class LocalAnalysisTests(unittest.TestCase):
    def test_optional_csv_fields_survive_recovery(self):
        rows = [dict(frame=1, reason='not_found'), dict(frame=2, reason='candidate', native_png='raw.png')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'attempts.csv'
            write_csv(path, rows, fields=union_fields(rows))
            with path.open(newline='') as stream:
                decoded = list(csv.DictReader(stream))
            self.assertEqual(len(decoded), 2)
            self.assertEqual(decoded[1]['native_png'], 'raw.png')

    def test_reference_match_requires_full_native_frame(self):
        reference = np.zeros((720, 1280, 3), np.uint8)
        self.assertTrue(reference_match(reference, reference)[1])
        self.assertFalse(reference_match(np.full_like(reference, 20), reference)[1])
        with self.assertRaises(ValueError):
            reference_match(reference[:, :640], reference)

    def test_signal_intervals_do_not_bridge_good_frames(self):
        rows = [dict(frame=i, time_sec=i/30, matches_no_signal_reference=i in (2, 3, 5))
                for i in range(1, 7)]
        self.assertEqual([(r['first_frame'], r['last_frame']) for r in signal_intervals(rows)], [(2, 3), (5, 5)])

    def test_fixed_window_is_excluded_by_entire_point_set(self):
        grid = np.mgrid[0:9, 0:6].T.reshape(-1, 2)*8 + [200, 240]
        image = np.zeros((720, 1280, 3), np.uint8)
        with patch('extract.cv2.findChessboardCornersSB', return_value=(True, grid.astype(np.float32).reshape(-1,1,2))):
            row = inspect(image, Board(square_mm=20))
        self.assertTrue(row['excluded_fixed_window'])
        self.assertFalse(row['eligible'])

    def test_large_foreground_with_same_centroid_is_not_window(self):
        grid = np.mgrid[0:9, 0:6].T.reshape(-1, 2)*20 + [180, 200]
        image = np.zeros((720, 1280, 3), np.uint8)
        with patch('extract.cv2.findChessboardCornersSB', return_value=(True, grid.astype(np.float32).reshape(-1,1,2))):
            row = inspect(image, Board(square_mm=20))
        self.assertFalse(row['excluded_fixed_window'])
        self.assertTrue(row['eligible'])

    def test_dense_audit_selects_only_unsampled_geometry_neighbours(self):
        rows = [dict(frame=21, reason='grid_too_small', centre_y=190),
                dict(frame=81, reason='grid_too_small', centre_y=300)]
        frames = selected_frames(rows, 100)
        self.assertTrue(all(1 <= i <= 41 and (i-1)%5 for i in frames))
        self.assertEqual(len(frames), 32)

    def test_real_54_views_rejected_before_intrinsic_solver(self):
        data = json.loads((HERE/'extraction_r01/observations.json').read_text())
        with patch('fisheye_intrinsic_calibration.cv2.fisheye.calibrate') as solver:
            with self.assertRaisesRegex(ValueError, 'coverage insufficient'):
                fit_candidate([r['corners_native'] for r in data['retained_views']], Board(**data['board']))
        solver.assert_not_called()


if __name__ == '__main__':
    unittest.main()
