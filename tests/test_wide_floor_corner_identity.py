"""凸角・点順・背景追跡の合成回帰。実画像の物理正解を承認しない。"""
import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FOLDER = ROOT / "Experimental_results/2026-11-09/wide_floor_geometry_r01"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corner = load("wide_floor_corner_identity_test", FOLDER/"audit_corner_identity.py")
paired = load("wide_floor_paired_test", FOLDER/"audit_same_frame_pose.py")
from angular_fisheye_geometry import project
from cone_distance_core import load_config


class CornerIdentityTests(unittest.TestCase):
    def test_concave_elbow_is_distinguished_for_both_polygon_windings(self):
        polygon = np.array([[0, 0], [10, 0], [10, 2], [2, 2], [2, 10], [0, 10]])
        for p in (polygon, polygon[::-1]):
            vertices = corner.polygon_vertices(p)
            concave = [r for r in vertices if r["kind"] == "concave"]
            self.assertEqual([(r["x"], r["y"]) for r in concave], [(2., 2.)])
            self.assertEqual(sum(r["kind"] == "convex" for r in vertices), 5)

    def test_degenerate_polygon_does_not_invent_a_corner(self):
        self.assertEqual(corner.polygon_vertices([[0, 0], [1, 0], [2, 0]]), [])
        with self.assertRaises(ValueError):
            corner.polygon_vertices([[0, 0], [1, 1]])

    def test_closer_concave_vertex_does_not_win_convex_proposal(self):
        vertices = [dict(x=0., y=0., kind="concave", distance_px=0., contour_index=0),
                    dict(x=1., y=1., kind="convex", distance_px=1.4, contour_index=0)]
        self.assertEqual(corner.convex_proposal(vertices)["kind"], "convex")
        self.assertIsNone(corner.convex_proposal(vertices[:1]))

    def test_absent_vertices_do_not_return_seed_as_observation(self):
        gray = np.full((720, 1280), 200, np.uint8)
        self.assertEqual(corner.nearby_vertices(gray, [300, 400], 110), [])
        self.assertIsNone(corner.convex_proposal([]))

    def test_contour_inspection_preserves_input_pixels(self):
        gray = np.full((720, 1280), 200, np.uint8)
        gray[390:401, 300:303] = 0
        gray[398:401, 300:315] = 0
        before = gray.copy()
        vertices = corner.nearby_vertices(gray, [300, 400], 110)
        self.assertEqual(corner.convex_proposal(vertices)["kind"], "convex")
        np.testing.assert_array_equal(gray, before)

    def test_all_24_assignments_and_both_solutions_are_kept_not_adopted(self):
        camera = load_config()[1]
        world = corner.original.vehicle_world(corner.original.HYPOTHESES[0])
        transform = np.array([[0., 0., 1., .02], [-1., 0., 0., -.03],
                              [0., -1., 0., .59], [0., 0., 0., 1.]])
        pixels, _ = project((world-transform[:3, 3]) @ transform[:3, :3], camera)
        holdout, _ = project((np.array([[1.4, 0., 0.]])-transform[:3, 3]) @ transform[:3, :3], camera)
        before = pixels.copy()
        rows = corner.evaluate_permutations(pixels, [(holdout[0], [0., 1.4])], camera)
        self.assertEqual(len(rows), 48)
        self.assertEqual(len({r["permutation"] for r in rows}), 24)
        self.assertTrue(all(r["mapping_adopted"] is False for r in rows))
        self.assertTrue(all(r["holdout_used_for_diagnostic_rejection_only"] for r in rows))
        np.testing.assert_array_equal(pixels, before)


class BackgroundMotionTests(unittest.TestCase):
    def test_known_ray_rotation_is_proper_and_recovered(self):
        source = np.array([[1., 0, 1], [0, 1., 1], [-1., .3, 1], [.5, -.6, 1]])
        source /= np.linalg.norm(source, axis=1)[:, None]
        rotation = cv2.Rodrigues(np.array([.01, -.02, .03]))[0]
        target = source @ rotation.T
        fitted = paired.proper_ray_rotation(source, target)
        np.testing.assert_allclose(fitted, rotation, atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(fitted), 1.)

    def test_nonunit_or_too_few_rays_are_refused(self):
        with self.assertRaises(ValueError):
            paired.proper_ray_rotation(np.ones((3, 3)), np.ones((3, 3)))
        with self.assertRaises(ValueError):
            paired.proper_ray_rotation(np.zeros((2, 3)), np.zeros((2, 3)))

    def test_flat_image_reports_no_features_without_invented_motion(self):
        image = np.zeros((720, 1280), np.uint8)
        result, tracks = paired.background_motion(image, image, load_config()[1])
        self.assertEqual(result["status"], "no_background_features")
        self.assertEqual(tracks, [])

    def test_synthetic_translation_is_tracked_without_altering_images(self):
        reference = np.full((720, 1280), 150, np.uint8)
        for x in (200, 260, 320, 380, 440):
            for y in (120, 170, 220):
                cv2.rectangle(reference, (x, y), (x+8, y+8), 30, -1)
        current = cv2.warpAffine(reference, np.array([[1., 0., 2.], [0., 1., -1.]]), (1280, 720))
        before, after = reference.copy(), current.copy()
        result, tracks = paired.background_motion(reference, current, load_config()[1])
        self.assertGreaterEqual(len(tracks), 8)
        self.assertAlmostEqual(result["median_dx_px"], 2., delta=.1)
        self.assertAlmostEqual(result["median_dy_px"], -1., delta=.1)
        self.assertFalse(result["physical_motion_measured"])
        self.assertFalse(result["scene_points_used_for_floor_fit"])
        np.testing.assert_array_equal(reference, before)
        np.testing.assert_array_equal(current, after)

    def test_resized_input_is_refused(self):
        with self.assertRaises(ValueError):
            paired.background_motion(np.zeros((360, 640), np.uint8),
                                     np.zeros((360, 640), np.uint8), load_config()[1])


if __name__ == "__main__":
    unittest.main()
