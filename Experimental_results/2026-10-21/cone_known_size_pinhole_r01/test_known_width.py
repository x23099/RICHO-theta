import copy
import json
from pathlib import Path
import unittest

import numpy as np

import analyze
from known_width import (BASE_SIDE_M, VIRTUAL_K, envelope_endpoints, estimate_native_span,
                         pinhole_width_position, raw_to_rectified)


class KnownWidthTests(unittest.TestCase):
    def setUp(self):
        self.T = np.array([[0., 0., 1., 0.], [-1., 0., 0., 0.], [0., -1., 0., .59], [0., 0., 0., 1.]])
        optical = np.array([[-BASE_SIDE_M/2, .59, 2.], [BASE_SIDE_M/2, .59, 2.]])
        homogeneous = optical @ VIRTUAL_K.T
        self.uv = homogeneous[:, :2]/homogeneous[:, 2, None]

    def test_known_frontal_edge_recovers_position_without_floor_intersection(self):
        row = pinhole_width_position(self.uv, VIRTUAL_K, self.T)
        self.assertAlmostEqual(row["z_forward_m"], 2.)
        self.assertAlmostEqual(row["optical_z_m"], 2.)
        self.assertAlmostEqual(row["height_above_floor_m"], 0.)
        self.assertFalse(row["physical_width_correspondence_verified"])
        self.assertFalse(row["usable_for_ffb"])

    def test_camera_height_does_not_scale_known_width_depth(self):
        other = self.T.copy()
        other[2, 3] = 1.59
        a = pinhole_width_position(self.uv, VIRTUAL_K, self.T)
        b = pinhole_width_position(self.uv, VIRTUAL_K, other)
        self.assertEqual(a["z_forward_m"], b["z_forward_m"])
        self.assertAlmostEqual(b["height_above_floor_m"]-a["height_above_floor_m"], 1.)

    def test_virtual_focal_resolution_choice_not_a_distance_fit(self):
        K = VIRTUAL_K.copy()
        K[:2] *= 2
        a = pinhole_width_position(self.uv, VIRTUAL_K, self.T)
        b = pinhole_width_position(self.uv*2, K, self.T)
        self.assertEqual(a["z_forward_m"], b["z_forward_m"])

    def test_partial_visible_width_overestimates_distance(self):
        uv = self.uv.copy()
        uv[:, 0] = uv[:, 0].mean()+(uv[:, 0]-uv[:, 0].mean())*.5
        row = pinhole_width_position(uv, VIRTUAL_K, self.T)
        self.assertAlmostEqual(row["z_forward_m"], 4.)
        self.assertFalse(row["usable_for_ffb"])

    def test_wrong_known_size_scales_depth(self):
        row = pinhole_width_position(self.uv, VIRTUAL_K, self.T, width_m=BASE_SIDE_M*1.2)
        self.assertAlmostEqual(row["z_forward_m"], 2.4)

    def test_outside_diagnostic_range_is_retained_not_clipped(self):
        uv = self.uv.copy()
        uv[:, 0] = uv[:, 0].mean()+(uv[:, 0]-uv[:, 0].mean())*.2
        row = pinhole_width_position(uv, VIRTUAL_K, self.T)
        self.assertAlmostEqual(row["z_forward_m"], 10.)
        self.assertTrue(row["estimated"])
        self.assertFalse(row["in_diagnostic_range"])

    def test_bad_width_nan_or_reflection_cannot_be_approved(self):
        self.assertFalse(pinhole_width_position(self.uv[::-1], VIRTUAL_K, self.T)["estimated"])
        for uv in (np.full((2,2), np.nan), self.uv.astype(complex)):
            with self.assertRaises(ValueError):
                pinhole_width_position(uv, VIRTUAL_K, self.T)
        reflected = self.T.copy()
        reflected[:3, 0] *= -1
        with self.assertRaises(ValueError):
            pinhole_width_position(self.uv, VIRTUAL_K, reflected)

    def test_envelope_keeps_full_actual_endpoints_not_trimmed_support(self):
        points = np.array([(x, 400+x % 2) for x in range(300, 341)])
        np.testing.assert_array_equal(envelope_endpoints(points), [points[0], points[-1]])
        with self.assertRaises(ValueError):
            envelope_endpoints(points[::-1])

    def test_no_mutation_of_calibration_or_endpoints(self):
        uv, K, T = self.uv.copy(), VIRTUAL_K.copy(), self.T.copy()
        pinhole_width_position(uv, K, T)
        np.testing.assert_array_equal(uv, self.uv)
        np.testing.assert_array_equal(K, VIRTUAL_K)
        np.testing.assert_array_equal(T, self.T)

    def test_square_yaw_is_not_silently_treated_as_same_physical_edge(self):
        rows = analyze.square_yaw_simulation()
        self.assertAlmostEqual(rows[0]["estimated_z_m"], 1.3)
        self.assertGreater(abs(rows[-1]["error_z_m"]), .05)

    def test_reference_labels_cannot_affect_replay_estimate(self):
        previous = json.loads((analyze.DAY19/"cone_distance_methods_r01/results_r01/provenance.json").read_text())
        p = previous["geometries"]["height_only59"]
        row = dict(dataset="fixture", session="fixture", frame=1, time_sec=0., condition="centre",
                   reference_x_m=0., reference_z_m=2., quality_accepted=True, envelope_reason="fixture")
        points = np.array([[295., 378.], [329., 378.]])
        a = analyze.replay([row], {analyze.key(row):points}, {}, {"fixture":p})
        changed = dict(row, reference_z_m=100., reference_x_m=-3., condition="different_label")
        b = analyze.replay([changed], {analyze.key(row):points}, {}, {"fixture":p})
        for field in ("estimated", "z_forward_m", "x_right_m", "reason", "width_rectified_px"):
            self.assertEqual(a[0][field], b[0][field])


class SavedStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(__file__).resolve().parent/"results_r01"
        cls.provenance = json.loads((cls.folder/"provenance.json").read_text())
        cls.rows = analyze.read_csv(cls.folder/"all_frame_estimates.csv")

    def test_all_frames_and_methods_retained(self):
        self.assertEqual(self.provenance["frames"], 6876)
        self.assertEqual(len(self.rows), 6876*6)
        self.assertEqual(len({(r["dataset"],r["session"],r["frame"]) for r in self.rows}), 6876)
        self.assertTrue(all(r["usable_for_ffb"] == "False" for r in self.rows))

    def test_new_2m_negative_windows_not_invented_as_known_size_objects(self):
        negative = [r for r in self.rows if r["dataset"] == "paper_cone_20261019"
                    and r["condition"] in ("paper_before", "paper_after") and r["method"] == "visible_full_span"]
        self.assertEqual(len(negative), (391+240)*3)
        self.assertTrue(all(r["estimated"] == "False" for r in negative))

    def test_saved_summary_recomputes_exactly(self):
        numeric = ("left_x", "left_y", "right_x", "right_y", "width_rectified_px", "endpoint_v_difference_px", "optical_z_m",
                   "x_right_m", "z_forward_m", "height_above_floor_m", "horizontal_distance_m", "floor_x_m", "floor_z_m", "reference_x_m", "reference_z_m")
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row["frame"] = int(row["frame"])
            for field in numeric:
                row[field] = float(row[field]) if row[field] else None
            for field in ("estimated", "quality_accepted", "in_diagnostic_range"):
                row[field] = row[field] == "True"
        recomputed = analyze.summarize(rows)
        saved = analyze.read_csv(self.folder/"summary.csv")
        self.assertEqual(len(recomputed), len(saved))
        for a, b in zip(recomputed, saved):
            for field, value in a.items():
                self.assertEqual("" if value is None else str(value), b[field])

    def test_58_59_height_changes_not_misreported_as_width_depth_improvement(self):
        by_key = {(r["dataset"],r["session"],r["frame"],r["method"],r["model"]):r for r in self.rows}
        for key, row in by_key.items():
            if key[-1] != "recorded58" or row["estimated"] != "True":
                continue
            other = by_key[(*key[:-1], "height_only59")]
            self.assertEqual(row["z_forward_m"], other["z_forward_m"])

    def test_sources_and_outputs_unchanged(self):
        for path, digest in self.provenance["source_sha256"].items():
            self.assertEqual(analyze.sha256(Path(path)), digest)
        for name, digest in self.provenance["output_sha256"].items():
            self.assertEqual(analyze.sha256(self.folder/name), digest)

    def test_all_saved_rectification_and_positions_with_independent_ray_math(self):
        from fisheye_floor_geometry import legacy_front_diagnostic_geometry, optical_rays
        for model, parameters in self.provenance["models"].items():
            rows = [r for r in self.rows if r["model"] == model and r["estimated"] == "True"]
            raw = np.array([[[float(r["left_x"]),float(r["left_y"])],
                             [float(r["right_x"]),float(r["right_y"])]] for r in rows])
            camera, transform = legacy_front_diagnostic_geometry(parameters)
            rays, valid = optical_rays(raw.reshape(-1, 2), camera)
            self.assertTrue(valid.all())
            projected = rays @ VIRTUAL_K.T
            uv = (projected[:, :2]/projected[:, 2, None]).reshape(-1, 2, 2)
            saved_uv = np.array([json.loads(r["rectified_endpoints_json"]) for r in rows])
            np.testing.assert_allclose(uv, saved_uv, atol=1e-9, rtol=0)
            z = 480*BASE_SIDE_M/(uv[:, 1, 0]-uv[:, 0, 0])
            mean = uv.mean(axis=1)
            optical = np.column_stack(((mean[:, 0]-479.5)/480*z, (mean[:, 1]-479.5)/480*z, z))
            target = optical @ transform[:3, :3].T + transform[:3, 3]
            saved = np.array([[float(r["z_forward_m"]), -float(r["x_right_m"]), float(r["height_above_floor_m"])] for r in rows])
            np.testing.assert_allclose(target, saved, atol=1e-10, rtol=0)


if __name__ == "__main__":
    unittest.main()
