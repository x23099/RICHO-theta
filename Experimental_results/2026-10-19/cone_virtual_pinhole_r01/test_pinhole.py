import copy
from dataclasses import FrozenInstanceError
import json
import math
import unittest

import cv2
import numpy as np

import compare_pinhole as run
from cone_dataset import read_csv, sha256
import virtual_pinhole as virtual


def simple_parameters():
    return dict(camera_height=.59, pitch_deg=0., roll_deg=0., yaw_deg=0., radius_scale=.86,
                front_cx_offset=-80., front_cy_offset=-21., back_cx_offset=82., back_cy_offset=-18.)


def strings(rows):
    return [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows]


class PinholeUnitTests(unittest.TestCase):
    def test_virtual_K_and_bad_views(self):
        np.testing.assert_allclose(virtual.VirtualView().K, [[480, 0, 479.5], [0, 480, 479.5], [0, 0, 1]])
        for values in (dict(width=0), dict(height=True), dict(horizontal_fov_deg=180), dict(horizontal_fov_deg=float("nan"))):
            with self.assertRaises(ValueError):
                virtual.VirtualView(**values)
        view = virtual.VirtualView()
        with self.assertRaises(FrozenInstanceError):
            view.width = 640

    def test_assumed_equidistant_K_is_not_a_new_fitted_calibration(self):
        K, radius = virtual.equidistant_K(simple_parameters())
        self.assertAlmostEqual(K[0, 0], radius/(math.pi/2))
        self.assertEqual((K[0, 2], K[1, 2]), (320, 339))
        p = simple_parameters()
        del p["front_cy_offset"]
        with self.assertRaises(ValueError):
            virtual.equidistant_K(p)
        with self.assertRaises(ValueError):
            virtual.equidistant_K(dict(simple_parameters(), camera_height=0))

    def test_tf_axes_are_a_proper_right_handed_rotation(self):
        t = virtual.optical_to_ground_transform(simple_parameters())
        np.testing.assert_allclose(t[:3, :3], [[0, 0, 1], [-1, 0, 0], [0, -1, 0]], atol=1e-15)
        self.assertAlmostEqual(np.linalg.det(t[:3, :3]), 1.)
        np.testing.assert_allclose(t[:3, 3], [0, 0, .59])
        np.testing.assert_allclose(t[:3, :3] @ [1, 0, 0], [0, -1, 0])
        np.testing.assert_allclose(t[:3, :3] @ [0, 1, 0], [0, 0, -1])

    def test_reflection_or_scaled_matrix_cannot_be_used_as_tf(self):
        t = virtual.optical_to_ground_transform(simple_parameters())
        for change in (np.diag([1, -1, 1]), np.diag([2, 1, 1])):
            bad = t.copy()
            bad[:3, :3] = change
            with self.assertRaises(ValueError):
                virtual.validate_transform(bad)

    def test_trigonometric_floor_distance_and_translation(self):
        view = virtual.VirtualView()
        # A 45 degree downward ray: ground horizontal distance equals camera height.
        rows = virtual.floor_intersections([[479.5, 959.5]], view.K,
                                            virtual.optical_to_ground_transform(simple_parameters()))
        self.assertEqual(rows[0]["reason"], "valid")
        self.assertAlmostEqual(rows[0]["z_m"], .59)
        self.assertAlmostEqual(rows[0]["ground_z_m"], 0.)
        self.assertFalse(rows[0]["usable_for_ffb"])

    def test_general_rotations_match_direct_fisheye_geometry(self):
        points = [(280, 420), (310, 400), (340, 410), (380, 430)]
        for angles in ((0, 0, 0), (5, 2, -3), (-6, -2, 4)):
            p = dict(simple_parameters(), **dict(zip(("yaw_deg", "pitch_deg", "roll_deg"), angles)))
            direct = run.upstream.project_columns(points, p)
            proposed = virtual.project_columns(points, p)
            self.assertTrue(all(a["reason"] == b["reason"] == "valid" for a, b in zip(direct, proposed)))
            np.testing.assert_allclose([[a["x_m"], a["z_m"]] for a in direct],
                                       [[b["x_m"], b["z_m"]] for b in proposed], rtol=1e-12, atol=1e-12)

    def test_changing_virtual_focal_length_does_not_change_unrounded_distance(self):
        points = [(310, 410), (320, 420)]
        a = virtual.project_columns(points, simple_parameters(), virtual.VirtualView(horizontal_fov_deg=80))
        b = virtual.project_columns(points, simple_parameters(), virtual.VirtualView(width=1280, height=960, horizontal_fov_deg=110))
        np.testing.assert_allclose([[r["x_m"], r["z_m"]] for r in a], [[r["x_m"], r["z_m"]] for r in b], atol=1e-12)

    def test_view_truncation_never_reports_partial_bounds(self):
        rows = virtual.project_columns([(320, 420), (360, 425)], simple_parameters(),
                                       virtual.VirtualView(horizontal_fov_deg=50))
        self.assertTrue(any(r["reason"] == "outside_virtual_view" for r in rows))
        bound = run.upstream.bounds(rows)
        self.assertFalse(bound["projection_complete"])
        self.assertIsNone(bound["z_min_m"])

    def test_optical_centre_native_invalid_horizon_and_range_conditions(self):
        p = simple_parameters()
        rows = virtual.project_columns([(320, 339), (1000, 400), (321, 338), (320, 350)], p)
        self.assertEqual(rows[0]["reason"], "outside_front_lens_or_optical_centre")
        self.assertEqual(rows[1]["reason"], "outside_front_lens_or_optical_centre")
        self.assertEqual(rows[2]["reason"], "not_downward_floor_ray")
        self.assertEqual(rows[3]["reason"], "outside_radial_diagnostic_range")
        self.assertGreater(rows[3]["radial_m"], 4)

    def test_bad_pixels_and_empty_inputs(self):
        self.assertEqual(virtual.project_columns([], simple_parameters()), [])
        for points in ([1, 2], [(1, float("nan"))], [(1280, 500)], [(-1, 500)]):
            with self.assertRaises(ValueError):
                virtual.project_columns(points, simple_parameters())

    def test_quantization_is_explicit_not_silently_used_for_primary_result(self):
        a = virtual.project_columns([(311, 393)], simple_parameters())[0]
        b = virtual.project_columns([(311, 393)], simple_parameters(), quantized=True)[0]
        self.assertEqual(a["used_u"], a["virtual_u"])
        self.assertEqual(b["used_u"], round(a["virtual_u"]))
        self.assertNotEqual(a["z_m"], b["z_m"])

    def test_inverse_map_and_forward_projection_round_trip(self):
        view = virtual.VirtualView(width=96, height=96)
        maps = virtual.inverse_maps(simple_parameters(), view)
        self.assertEqual(maps[0].shape, (96, 96))
        selected = [(u, v) for u, v in ((20, 30), (40, 60), (70, 75))]
        native = [(float(maps[0][v, u]), float(maps[1][v, u])) for u, v in selected]
        projected = virtual.project_columns(native, simple_parameters(), view)
        np.testing.assert_allclose([[r["virtual_u"], r["virtual_v"]] for r in projected], selected, atol=2e-5)

    def test_rectification_in_memory_leaves_native_image_and_parameters_unchanged(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[300:500, 280:400] = 100
        p = simple_parameters()
        before_image, before_p = image.copy(), copy.deepcopy(p)
        maps = virtual.inverse_maps(p, virtual.VirtualView(width=96, height=96))
        result = virtual.rectify_in_memory(image, maps)
        self.assertEqual(result.shape, (96, 96, 3))
        np.testing.assert_array_equal(image, before_image)
        self.assertEqual(p, before_p)
        with self.assertRaises(ValueError):
            virtual.rectify_in_memory(image[:600], maps)


class SavedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.curves, cls.status, cls.models, cls.refs, cls.hashes = run.load_inputs()
        cls.rows, cls.examples = run.replay(cls.source, cls.curves, cls.status, cls.models)
        cls.directory = run.HERE / "results_r01"

    def test_all_frames_and_saved_csvs_recomputed_exactly(self):
        self.assertEqual(len(self.rows), 5143*3)
        self.assertEqual(strings(self.rows), read_csv(self.directory / "frame_comparison.csv"))
        self.assertEqual(strings(self.examples), read_csv(self.directory / "representative_columns.csv"))
        self.assertEqual(strings(run.summarize(self.rows, self.refs)), read_csv(self.directory / "summary.csv"))

    def test_independent_geometry_matches_per_column_and_range_classification(self):
        compared = 0
        for r in self.rows:
            compared += r["float_finite_pair_columns"]
            self.assertEqual(r["float_floor_reason_mismatches_within_view"], 0)
            for axis in ("x", "z"):
                error = r["float_d" + axis + "_abs_max_m"]
                if error is not None:
                    self.assertLessEqual(error, run.TOLERANCE_M)
        self.assertGreater(compared, 500000)

    def test_direct_path_reproduces_preexisting_projected_ranges(self):
        old = {(r["dataset"], r["session"], int(r["frame"]), r["model"]): r
               for r in read_csv(run.PROJECTION / "results_r01/projected_ranges.csv")}
        for r in self.rows:
            before = old[r["dataset"], r["session"], r["frame"], r["model"]]
            self.assertEqual(r["direct_complete"], before["projection_complete"] == "True")
            for field in run.FIELDS:
                value = r["direct_candidate_" + field]
                self.assertEqual("" if value is None else str(value), before["candidate_" + field])

    def test_rejected_or_absent_frames_not_reintroduced_by_pinhole(self):
        for r in self.rows:
            self.assertFalse(r["usable_for_ffb"] or r["floor_contact_verified"])
            for method in ("direct", "pinhole_float", "pinhole_rounded"):
                if not r["quality_accepted"]:
                    self.assertFalse(r[method + "_observation_available"])
                    self.assertTrue(all(r[method + "_observed_" + field] is None for field in run.FIELDS))

    def test_no_reference_label_or_input_mutation_changes_geometry(self):
        subset = self.source[:3]
        curves = {run.upstream.quality.key(r): self.curves[run.upstream.quality.key(r)] for r in subset}
        before = copy.deepcopy((subset, curves, self.models))
        original = run.replay(subset, curves, self.status, self.models)[0]
        changed = run.replay([dict(r, condition="ignored", reference_z_m=99) for r in subset], curves, self.status, self.models)[0]
        self.assertEqual([{k: v for k, v in r.items() if k != "condition"} for r in original],
                         [{k: v for k, v in r.items() if k != "condition"} for r in changed])
        self.assertEqual((subset, curves, self.models), before)

    def test_memory_rectification_results_and_all_hashes_reproduced(self):
        rows, _ = run.memory_views(self.models)
        self.assertEqual(strings(rows), read_csv(self.directory / "memory_rectification.csv"))
        p = json.loads((self.directory / "provenance.json").read_text())
        run.upstream.check_hashes(p["source_sha256"])
        for name, digest in p["output_sha256"].items():
            self.assertEqual(sha256(self.directory / name), digest)
        for key in ("new_metric_fit", "new_yolo_inference", "ros_tf_broadcast", "physical_output", "usable_for_ffb",
                    "original_images_edited", "rectified_images_saved"):
            self.assertIs(p[key], False)


if __name__ == "__main__":
    unittest.main()
