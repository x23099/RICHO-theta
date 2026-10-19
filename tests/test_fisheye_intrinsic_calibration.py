import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from fisheye_intrinsic_calibration import (Board, FRONT_ROI, checked_corners, corner_rms,
                                         coverage, detect_board, fit_candidate, partition_views)
from prepare_fisheye_calibration import board_target, extract, fit, new_output
from cone_dataset import sha256


def synthetic_views():
    board = Board()
    K = np.array([[210., 0., 320.], [0., 212., 340.], [0., 0., 1.]])
    D = np.array([.02, -.01, .001, -.0002])
    rng = np.random.default_rng(17)
    views = []
    for _ in range(300):
        rvec = rng.uniform([-.65, -.65, -.3], [.65, .65, .3]).reshape(3, 1)
        rotation = cv2.Rodrigues(rvec)[0]
        centre = rng.uniform([-.95, -.85, .5], [.95, .85, 1.0])
        tvec = centre-rotation @ board.object_points.reshape(-1, 3).mean(axis=0)
        points = cv2.fisheye.projectPoints(board.object_points, rvec, tvec, K, D)[0].reshape(-1, 2)
        try:
            checked_corners(points, board)
        except ValueError:
            continue
        if all(corner_rms(points, old) >= 12 for old in views):
            views.append(points)
        if len(views) == 40:
            break
    return board, K, D, views


def image_board():
    im = np.full((720, 1280, 3), 140, np.uint8)
    x, y, step = 100, 180, 30
    im[y-20:y+7*step+20, x-20:x+10*step+20] = 255
    for row in range(7):
        for col in range(10):
            im[y+row*step:y+(row+1)*step, x+col*step:x+(col+1)*step] = 0 if (row+col) % 2 == 0 else 255
    return im


class FisheyeIntrinsicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        cls.board, cls.K, cls.D, cls.views = synthetic_views()
        cls.result = fit_candidate(cls.views, cls.board)

    def test_synthetic_intrinsics_recovered_not_physical_validation(self):
        self.assertEqual(len(self.views), 40)
        np.testing.assert_allclose(self.result["K"], self.K, atol=1e-4)
        np.testing.assert_allclose(self.result["D"], self.D, atol=1e-4)
        self.assertLess(self.result["pose_validation_rms_px"], 1e-4)
        self.assertEqual(self.result["decision"], "CANDIDATE_ONLY")
        self.assertFalse(self.result["usable_for_ffb"])
        self.assertFalse(self.result["camera_to_floor_extrinsics_measured"])

    def test_validation_split_is_fixed_before_fit(self):
        train, validation = partition_views(self.views)
        self.assertEqual(validation, list(range(4, 40, 5)))
        self.assertFalse(set(train) & set(validation))
        self.assertEqual(train, self.result["train_indices"])

    def test_validation_points_do_not_change_fitted_intrinsics(self):
        views = [p.copy() for p in self.views]
        for i in self.result["validation_indices"]:
            views[i] += [.2, -.2]
        other = fit_candidate(views, self.board)
        np.testing.assert_array_equal(other["K"], self.result["K"])
        np.testing.assert_array_equal(other["D"], self.result["D"])

    def test_measured_square_size_does_not_fake_metric_accuracy(self):
        other = fit_candidate(self.views, Board(square_mm=29.5))
        np.testing.assert_allclose(other["K"], self.result["K"], atol=1e-5)
        self.assertFalse(other["physical_floor_distance_verified"])

    def test_insufficient_and_duplicate_views_refused(self):
        with self.assertRaises(ValueError):
            fit_candidate(self.views[:19], self.board)
        with self.assertRaises(ValueError):
            fit_candidate([self.views[0]]*20, self.board)

    def test_grid_dimensions_and_metric_units(self):
        self.assertEqual(self.board.count, 54)
        np.testing.assert_array_equal(self.board.object_points[0, 0], [0, 0, 0])
        self.assertAlmostEqual(self.board.object_points[0, 8, 0], .24)
        for size in (0, float("nan"), -1):
            with self.assertRaises(ValueError):
                Board(square_mm=size)

    def test_blank_and_non_native_images_do_not_invent_board(self):
        self.assertIsNone(detect_board(np.full((720, 1280, 3), 128, np.uint8), self.board)[0])
        with self.assertRaises(ValueError):
            detect_board(np.zeros((600, 500, 3), np.uint8), self.board)

    def test_detector_restores_native_roi_origin_and_does_not_mutate(self):
        image = image_board()
        before = image.copy()
        a, _ = detect_board(image, self.board)
        b, _ = detect_board(image, self.board, (50, 50, 500, 600))
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertLess(corner_rms(a, b), .2)
        self.assertAlmostEqual(np.mean(a[:, 0]), 249.5, delta=.2)
        np.testing.assert_array_equal(before, image)

    def test_grid_symmetry_is_near_duplicate(self):
        self.assertEqual(corner_rms(self.views[0], self.views[0][::-1]), 0)

    def test_corners_must_not_cross_lenses_or_be_nonfinite(self):
        for p in (self.views[0]+[640, 0], np.full((54, 2), np.nan), np.zeros((53, 2)), np.zeros((54, 2), complex)):
            with self.assertRaises(ValueError):
                checked_corners(p, self.board)

    def test_coverage_reports_native_domain(self):
        c = coverage(self.views, FRONT_ROI)
        self.assertGreaterEqual(c["centre_bins"], 4)
        self.assertTrue(c["observed_pixel_max"][0] < 640)

    def test_print_target_physical_page_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = new_output(Path(directory)/"target")
            result = board_target(output)
            self.assertEqual(result["inner_corners"], [9, 6])
            self.assertEqual(result["pattern_squares"], [10, 7])
            self.assertEqual(result["page_mm"], [420, 297])
            self.assertIn('width="420.0mm"', (output/"checkerboard.svg").read_text())
            self.assertTrue((output/"checkerboard.pdf").read_bytes().startswith(b"%PDF"))
            with self.assertRaises(FileExistsError):
                new_output(output)

    def test_video_extract_saves_only_native_pixels_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = new_output(root/"target")
            board_target(target)
            video = root/"raw.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 30, (1280, 720))
            self.assertTrue(writer.isOpened())
            for _ in range(3):
                writer.write(image_board())
            writer.release()
            output = new_output(root/"extract")
            result = extract(video, target/"board_spec.json", output, sample_every=1, max_frames=10, save_raw=True)
            self.assertEqual(result["retained_views"], 1)
            data = json.loads((output/"observations.json").read_text())
            self.assertEqual(len(data["attempts"]), 3)
            self.assertEqual(data["attempts"][-1]["reason"], "near_duplicate_pose")
            cap = cv2.VideoCapture(str(video))
            ok, native = cap.read()
            cap.release()
            self.assertTrue(ok)
            np.testing.assert_array_equal(native, cv2.imread(str(output/data["retained_views"][0]["native_png"])))

    def test_fit_command_schema_and_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/"synthetic_source.txt"
            source.write_text("Synthetic fixture only, not a calibration recording")
            data = dict(schema="single_fisheye_native_corners_v1", image_size=[1280, 720],
                        roi_native_xywh=list(FRONT_ROI), selected_lens="front_left", board=vars(self.board),
                        source_sha256={str(source):sha256(source)},
                        retained_views=[dict(retained_index=i, retained=True, frame=i*15+1, corners_native=p.tolist())
                                        for i, p in enumerate(self.views)])
            observations = root/"observations.json"
            observations.write_text(json.dumps(data))
            output = new_output(root/"candidate")
            result = fit(observations, 30., output)
            self.assertTrue((output/"intrinsics_candidate.json").is_file())
            self.assertFalse(result["usable_for_ffb"])
            self.assertEqual(result["observations_sha256"], sha256(observations))
            source.write_text("changed")
            with self.assertRaises(ValueError):
                fit(observations, 30., new_output(root/"rejected"))

    def test_fitted_views_must_have_native_single_lens_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations = root/"observations.json"
            observations.write_text(json.dumps(dict(schema="not_native")))
            with self.assertRaises(ValueError):
                fit(observations, 30., new_output(root/"rejected"))


if __name__ == "__main__":
    unittest.main()
