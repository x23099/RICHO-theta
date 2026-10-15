"""Offline math/guard regressions only, not physical calibration tests."""
import json
import math
import unittest

from contact_diagnose import HERE, ConeGroundProjector, envelope, project_point
from cone_dataset import read_csv, sha256


class ContactDiagnosisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters = json.loads((HERE / "intake_summary.json").read_text())["inputs"][0]["metadata"]["parameters"]

    def test_same_equation_as_bbox_projector(self):
        p = ConeGroundProjector(self.parameters, width=1280, height=720, front_lens="left")
        for pixel in ((318, 443), (313, 405), (312, 379), (242, 406), (379, 401)):
            x, y = pixel
            result = p.project(dict(x1=x-10, x2=x+10, y1=y-30, y2=y, confidence=1, class_id=0),
                               frame_width=1280, frame_height=720)
            self.assertTrue(result["projection_candidate"])
            self.assertEqual(project_point(pixel, self.parameters), (result["x_m"], result["z_m"]))
            self.assertFalse(result["usable_for_ffb"])

    def test_nonfinite_or_outside_native_image(self):
        for point in ((math.nan, 405), (313, math.inf), (-1, 405), (1280, 405), (313, 720), (1,)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                project_point(point, self.parameters)

    def test_upward_or_outside_lens_rejected(self):
        for point in ((320, 200), (0, 0), (960, 430)):
            self.assertIsNone(project_point(point, self.parameters))

    def test_invalid_camera_height(self):
        for height in (0, -1, math.inf, math.nan):
            with self.subTest(height=height), self.assertRaises(ValueError):
                project_point((313, 405), dict(self.parameters, camera_height=height))

    def test_height_scales_intersection_not_pixels(self):
        x, z = project_point((313, 405), self.parameters)
        scaled = project_point((313, 405), dict(self.parameters, camera_height=self.parameters["camera_height"]*.9))
        self.assertAlmostEqual(scaled[0], .9*x)
        self.assertAlmostEqual(scaled[1], .9*z)

    def test_envelope_contains_point_and_zero_width_is_exact(self):
        pixel = (312, 379)
        z = project_point(pixel, self.parameters)[1]
        low, high = envelope(pixel, self.parameters)
        self.assertLess(low, z)
        self.assertGreater(high, z)
        self.assertEqual(envelope(pixel, self.parameters, 0), (z, z))
        for invalid in (-1, 1.5, 11):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                envelope(pixel, self.parameters, invalid)

    def test_saved_artifact_hashes_and_same_frame_values(self):
        output = HERE / "contact_diagnosis_r01"
        provenance = json.loads((output / "provenance.json").read_text())
        for path, digest in provenance["source_sha256"].items():
            from pathlib import Path
            self.assertEqual(sha256(Path(path)), digest)
        for name, digest in provenance["output_sha256"].items():
            self.assertEqual(sha256(output / name), digest)
        rows = read_csv(output / "paired_contact_comparison.csv")
        self.assertEqual(len(rows), 5)
        for row in rows:
            p = provenance["camera_geometry"][row["condition"]]
            expected = project_point((float(row["manual_pixel_x"]), float(row["manual_pixel_y"])), p)
            self.assertEqual(expected, (float(row["manual_x_m"]), float(row["manual_z_m"])))
            low, high = envelope((float(row["manual_pixel_x"]), float(row["manual_pixel_y"])), p)
            self.assertEqual((low, high), (float(row["hypothetical_3px_z_min_m"]), float(row["hypothetical_3px_z_max_m"])))
            self.assertEqual(row["review_kind"], "nonblind_illustrative")
            self.assertEqual(row["usable_for_ffb"], "False")
            self.assertEqual(row["floor_contact_verified"], "False")
        self.assertFalse(provenance["physical_output"])
        self.assertFalse(provenance["fitted_parameters"])


if __name__ == "__main__":
    unittest.main()
