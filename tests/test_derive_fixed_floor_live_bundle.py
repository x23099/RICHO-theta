"""Synthetic native geometry and temporary PNGs only; no physical approval."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from angular_fisheye_geometry import project
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_fixed_floor_live_load import validate_live_payload
from derive_fixed_floor_live_bundle import (build_parser, checkerboard_reference, derive, main,
                                          rectangle_references, source)
from fisheye_intrinsic_calibration import Board


class DeriveFloorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.settings, self.camera, _, _ = load_config()
        self.world = np.array([[0., 0, 0], [.296, 0, 0], [.296, .210, 0], [0, .210, 0]])
        self.rotation = np.array([[0., 0, 1], [-1., 0, 0], [0, -1., 0]])
        self.camera_position = np.array([-.8, -.1, .575])
        self.pixels, valid = project((self.world-self.camera_position)@self.rotation, self.camera)
        self.assertTrue(valid.all())
        self.image = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillConvexPoly(self.image, np.rint(self.pixels).astype(np.int32), (255, 255, 255))
        self.png = self.folder/"decoded_synthetic_f000001.png"
        self.assertTrue(cv2.imwrite(str(self.png), self.image))
        self.spec = dict(schema="native_floor_rectangles_v1", frames=[dict(file=self.png.name,
            sha256=digest(self.png), corners_native_xy=self.pixels.tolist(), side_lengths_mm=[296, 210],
            side_assignment="both", coordinates_source="synthetic projected geometry, NOT real evidence")])
        self.path = self.folder/"references.json"
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.spec))

    def items(self):
        return rectangle_references(self.path, self.folder)[0]

    def arguments(self):
        return ["--references", str(self.path), "--image-dir", str(self.folder),
                "--board-thickness-mm", "15", "--external-height-mm", "590",
                "--board-on-floor", "--rigid-board", "--static-camera",
                "--output-dir", str(self.folder/"derived")]

    def test_rectangle_keeps_both_assignments_and_both_planar_solutions(self):
        bundle, reports = derive(self.items(), self.settings, self.camera, board_thickness_mm=15, external_height_mm=590)
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(r["pose"]["solution_count"] == 2 for r in reports))
        self.assertEqual(len(bundle["models"]), 8)
        self.assertEqual(len({m["name"] for m in bundle["models"]}), 8)
        best = min([m for m in bundle["models"] if m["height_source"] == "image_plane_plus_thickness"],
                   key=lambda m: m["native_reprojection_rmse_px"])
        self.assertAlmostEqual(best["camera_to_floor_m"], .590, places=7)
        self.assertTrue(all(r["pose"]["selected_solution"] is None for r in reports))

    def test_no_default_height_or_thickness_is_assumed(self):
        with self.assertRaisesRegex(ValueError, "no default height"):
            derive(self.items(), self.settings, self.camera)

    def test_thickness_and_external_height_remain_distinct_controls(self):
        bundle, _ = derive(self.items(), self.settings, self.camera, board_thickness_mm=20, external_height_mm=650)
        models = bundle["models"]
        external = [m for m in models if m["height_source"] == "external_height_image_normal"]
        self.assertTrue(all(m["camera_to_floor_m"] == .650 for m in external))
        self.assertTrue(any(abs(m["camera_to_floor_m"]-.595) < 1e-7 for m in models))
        self.assertTrue(all(m["usable_for_ffb"] is False and m["physical_metric_verified"] is False
                            and m["floor_contact_verified"] is False for m in models))

    def test_invalid_measurements_refused(self):
        for options in (dict(board_thickness_mm=True), dict(board_thickness_mm=-1),
                        dict(external_height_mm=float("nan")), dict(external_height_mm=0)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                derive(self.items(), self.settings, self.camera, **options)

    def test_large_residual_does_not_silently_select_a_convenient_solution(self):
        from floor_reference_pose import planar_floor_pose_candidates
        items = self.items()
        ref = items[0]["references"][0]
        pose = planar_floor_pose_candidates(ref["pixels"], ref["world"], self.camera)
        pose["candidates"][0]["fit_native_rmse_px"] = 100.
        with patch("derive_fixed_floor_live_bundle.planar_floor_pose_candidates", return_value=pose):
            bundle, reports = derive(items, self.settings, self.camera, board_thickness_mm=15)
        self.assertEqual(len(bundle["models"]), 4)
        self.assertTrue(any(m["native_reprojection_rmse_px"] == 100 for m in bundle["models"]))
        self.assertTrue(all(r["pose"]["selected_solution"] is None for r in reports))

    def test_nonpositive_front_depth_cannot_produce_a_model(self):
        invalid = dict(candidates=[dict(camera_height_above_floor_m=.5,
            all_reference_points_positive_depth=False, all_projected_in_calibrated_domain=True, solution_index=0)])
        with patch("derive_fixed_floor_live_bundle.planar_floor_pose_candidates", return_value=invalid):
            with self.assertRaisesRegex(ValueError, "model not exported"):
                derive(self.items(), self.settings, self.camera, board_thickness_mm=15)

    def test_mixed_session_and_duplicate_frames_refused(self):
        items = self.items()
        for field, value in (("session", "another"), ("frame", 1)):
            second = dict(items[0], frame=2)
            second[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                derive([items[0], second], self.settings, self.camera, board_thickness_mm=15)

    def test_unknown_source_name_and_hash_refused(self):
        with self.assertRaises(ValueError):
            source(self.folder/"arbitrary.png")
        self.spec["frames"][0]["sha256"] = "0"*64
        self.save()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.items()

    def test_paths_cannot_escape_image_directory(self):
        self.spec["frames"][0]["file"] = "../"+self.png.name
        self.save()
        with self.assertRaises(ValueError):
            self.items()

    def test_partial_rear_crossing_and_duplicate_corners_refused(self):
        for pixels in (self.pixels[:3].tolist(), [[900, 400], *self.pixels[1:].tolist()],
                       [self.pixels[0].tolist()]*4, self.pixels[[0, 2, 1, 3]].tolist()):
            self.spec["frames"][0]["corners_native_xy"] = pixels
            self.save()
            with self.subTest(pixels=pixels), self.assertRaises(ValueError):
                self.items()

    def test_ambiguous_assignment_cannot_silently_select_long_edge(self):
        self.spec["frames"][0]["side_assignment"] = "choose_nearest_height"
        self.save()
        with self.assertRaises(ValueError):
            self.items()

    def test_confirmations_required_before_output(self):
        args = self.arguments()
        args.remove("--rigid-board")
        with self.assertRaises(ValueError):
            main(args)
        self.assertFalse((self.folder/"derived").exists())

    def test_complete_command_produces_loader_compatible_bytes_without_image_edit(self):
        original = self.png.read_bytes()
        self.assertEqual(main(self.arguments()), 0)
        output = self.folder/"derived"
        payload = (output/"prepared_floor.json").read_bytes()
        adapter, evidence = validate_live_payload(payload, self.settings, digest(DEFAULT_CONFIG), self.folder,
                                                  "synthetic", 1, "support_completion_shadow")
        self.assertEqual(len(adapter.bundle["models"]), 8)
        self.assertEqual(evidence["source_frames"][0]["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.png.read_bytes(), original)
        report = json.loads((output/"derivation_report.json").read_text())
        self.assertIsNone(report["selected_solution"])
        self.assertFalse(report["original_images_modified"])
        self.assertFalse(report["intrinsics_refitted"])
        with self.assertRaises(ValueError):
            validate_live_payload(payload, self.settings, digest(DEFAULT_CONFIG), self.folder,
                                  "new-session", 1, "baseline")

    def test_existing_output_never_overwritten(self):
        folder = self.folder/"derived"
        folder.mkdir()
        marker = folder/"marker.txt"
        marker.write_text("existing")
        with self.assertRaises(ValueError):
            main(self.arguments())
        self.assertEqual(marker.read_text(), "existing")

    def test_checkerboard_failure_has_no_rectangle_fallback(self):
        with patch("derive_fixed_floor_live_bundle.detect_board", return_value=(None, "grid_too_small")):
            with self.assertRaisesRegex(ValueError, "no rectangle fallback"):
                checkerboard_reference(self.png, 20, (0, 300, 640, 340))

    def test_complete_checkerboard_points_use_existing_pose_solver(self):
        board = Board(square_mm=20.)
        pixels, _ = project((board.object_points.reshape(-1, 3)-self.camera_position)@self.rotation, self.camera)
        with patch("derive_fixed_floor_live_bundle.detect_board", return_value=(pixels, "injected_synthetic_grid")):
            items = checkerboard_reference(self.png, 20, (0, 300, 640, 340))
        bundle, reports = derive(items, self.settings, self.camera, board_thickness_mm=15)
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(bundle["models"]), 2)
        self.assertEqual(len(reports[0]["corners_or_grid_native_xy"]), 54)

    def test_checkerboard_rear_roi_and_missing_square_size_refused(self):
        for square, roi in ((None, (0, 300, 640, 340)), (20, (640, 300, 640, 340))):
            with self.subTest(square=square), self.assertRaises(ValueError):
                checkerboard_reference(self.png, square, roi)

    def test_input_changed_during_fit_leaves_no_prepared_model(self):
        from derive_fixed_floor_live_bundle import derive as original_derive
        def changing(*args, **kwargs):
            result = original_derive(*args, **kwargs)
            self.png.write_bytes(self.png.read_bytes()+b"changed")
            return result
        with patch("derive_fixed_floor_live_bundle.derive", side_effect=changing):
            with self.assertRaises(ValueError):
                main(self.arguments())
        self.assertFalse((self.folder/"derived/prepared_floor.json").exists())

    def test_modes_are_explicit(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--references", "x", "--checkerboard-image", "y", "--output-dir", "z"])

    def test_checkerboard_requires_explicit_floor_board_roi(self):
        with self.assertRaisesRegex(ValueError, "explicit floor-board ROI"):
            main(["--checkerboard-image", str(self.png), "--square-mm", "20", "--board-thickness-mm", "15",
                  "--board-on-floor", "--rigid-board", "--static-camera", "--output-dir", str(self.folder/"unused")])

    def test_mode_specific_options_not_silently_ignored(self):
        for options in (["--square-mm", "20"], ["--roi", "0", "300", "640", "340"]):
            with self.subTest(options=options), self.assertRaises(ValueError):
                main(self.arguments()+options)


if __name__ == "__main__":
    unittest.main()
