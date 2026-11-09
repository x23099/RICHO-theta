"""Synthetic geometry tests; never write to the human review decisions."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location(
    "reviewed_coordinate_audit",
    ROOT / "Experimental_results/2026-11-09/reviewed_coordinate_audit_r01/analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

from cone_fixed_floor_candidate import COORDINATE_FRAME, SCHEMA, measure_support


class ReviewedCoordinateAuditTests(unittest.TestCase):
    def setUp(self):
        self.camera = audit.load_config()[1]
        self.heading = np.array([[0., 0., 1., 0.], [-1., 0., 0., 0.],
                                 [0., -1., 0., .59], [0., 0., 0., 1.]])
        self.session = "synthetic"
        self.model = dict(
            schema=SCHEMA, name="synthetic", session=self.session,
            normal_optical=[0., -1., 0.], camera_to_floor_m=.59,
            coordinate_frame=COORDINATE_FRAME,
            heading_reference=dict(path="synthetic.json", sha256="0" * 64),
            evidence=["synthetic"], assumptions=["synthetic floor"],
            invalidation_conditions=["pose change"], physical_metric_verified=False,
            floor_contact_verified=False, usable_for_ffb=False)
        # Slanted in depth, so a pixel midpoint is not the 3-D midpoint.
        self.xyz = np.array([[1.2, .2, 0.], [1.8, -.25, 0.]])
        optical = (self.xyz - [0., 0., .59]) @ self.heading[:3, :3]
        self.pixels, ok = audit.project(optical, self.camera)
        self.assertTrue(ok.all())
        self.assertLess(self.pixels[0, 0], self.pixels[1, 0])

    def test_edge_locus_contains_projected_straight_physical_line(self):
        curve = audit.edge_curve(self.pixels, self.camera, samples=4097)
        line = self.xyz[0] + np.linspace(0., 1., 51)[:, None] * (self.xyz[1] - self.xyz[0])
        optical = (line - [0., 0., .59]) @ self.heading[:3, :3]
        points, ok = audit.project(optical, self.camera)
        self.assertTrue(ok.all())
        for point in points[1:-1]:
            self.assertLess(abs(audit.edge_offset(point, curve)["signed_y_below_reviewed_edge_px"]), 1e-4)

    def test_edge_offset_sign_and_no_extrapolation(self):
        curve = audit.edge_curve(self.pixels, self.camera)
        point = curve[len(curve)//2].copy()
        point[1] += 2.
        self.assertAlmostEqual(audit.edge_offset(point, curve)["signed_y_below_reviewed_edge_px"], 2., places=8)
        result = audit.edge_offset([curve[0, 0] - 1., curve[0, 1]], curve)
        self.assertFalse(result["x_within_reviewed_edge"])
        self.assertIsNone(result["signed_y_below_reviewed_edge_px"])

    def test_reversed_duplicate_and_invalid_points_rejected(self):
        for pixels in (self.pixels[::-1], self.pixels[[0, 0]], [[float("nan"), 400.], [340., 400.]]):
            with self.assertRaises(ValueError):
                audit.edge_curve(pixels, self.camera)
        with self.assertRaises(ValueError):
            audit.edge_offset([float("inf"), 0.], self.pixels)

    def test_conditional_edge_recovers_known_3d_midpoint_and_length(self):
        result = audit.conditional_edge(self.pixels, self.model, self.camera, self.heading, self.session, [.2, 4.])
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["range_m"], np.linalg.norm(self.xyz.mean(axis=0)[:2]), places=8)
        self.assertAlmostEqual(result["edge_length_m"], np.linalg.norm(self.xyz[1] - self.xyz[0]), places=8)
        self.assertFalse(result["physical_edge_identity_and_floor_contact_verified"])
        self.assertIn("NOT_pixel_mean", result["midpoint_method"])

    def test_pixel_midpoint_is_not_substituted_for_3d_midpoint(self):
        edge = audit.conditional_edge(self.pixels, self.model, self.camera, self.heading, self.session, [.2, 4.])
        pixel_mean = audit.conditional_point(self.pixels.mean(axis=0), self.model, self.camera, self.heading, self.session, [.2, 4.])
        self.assertGreater(abs(edge["range_m"] - pixel_mean["range_m"]), .01)

    def test_float_helper_agrees_with_integer_runtime_without_changing_it(self):
        pixel = np.rint(self.pixels[0]).astype(int)
        offline = audit.conditional_point(pixel, self.model, self.camera, self.heading, self.session, [.2, 4.])
        original = measure_support(pixel, self.model, self.camera, self.heading, session=self.session)
        self.assertEqual(offline["available"], original["range_available"])
        self.assertAlmostEqual(offline["range_m"], original["horizontal_camera_foot_range_m"], places=10)

    def test_cross_session_use_rejected_for_points_and_edges(self):
        for function, points in ((audit.conditional_point, self.pixels[0]), (audit.conditional_edge, self.pixels)):
            with self.assertRaisesRegex(ValueError, "cross-session"):
                function(points, self.model, self.camera, self.heading, "another", [.2, 4.])

    def test_out_of_range_remains_unavailable(self):
        result = audit.conditional_point(self.pixels[0], self.model, self.camera, self.heading, self.session, [.2, 1.])
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "outside_diagnostic_range")
        self.assertIsNone(result["range_m"])

    def test_floor_height_changes_scale_not_ground_truth(self):
        original = audit.conditional_edge(self.pixels, self.model, self.camera, self.heading, self.session, [.2, 4.])
        larger = dict(self.model, camera_to_floor_m=.649)
        result = audit.conditional_edge(self.pixels, larger, self.camera, self.heading, self.session, [.2, 4.])
        self.assertAlmostEqual(result["range_m"] / original["range_m"], 1.1, places=8)
        self.assertAlmostEqual(result["edge_length_m"] / original["edge_length_m"], 1.1, places=8)
        self.assertFalse(result["physical_edge_identity_and_floor_contact_verified"])


if __name__ == "__main__":
    unittest.main()
