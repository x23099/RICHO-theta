import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diagnose_box_contact_calibration import (audit_rows, calibrated_position, paired_spans,
                                             project_pixel, range_valid, sensitivity_rows,
                                             summarize_reference)

P = {"camera_height": .58, "radius_scale": .86, "front_cx_offset": -80, "front_cy_offset": -21,
     "pitch_deg": 1, "roll_deg": 2, "blue_ground_contact_x_scale": .6, "blue_ground_contact_x_offset_m": .02}


class ContactCalibrationDiagnosisTest(unittest.TestCase):
    def row(self, frame=1, x=.2, z=1.):
        a, b = calibrated_position(x, z, P)
        return {"session": "s", "variant": "baseline", "frame": str(frame), "detected": "1", "raw_contact_x_m": str(x),
                "raw_contact_z_m": str(z), "x_m": str(a), "z_m": str(b), "calibration_valid": int(range_valid(a, b, P)),
                "measurement_accepted": "0", "contact_pixel_x": "320", "contact_pixel_y": "450"}

    def test_legacy_bev_and_overlay_values_do_not_affect_ground_contact(self):
        p = dict(P, blue_calibration_z_scale=99, blue_calibration_z_offset_m=8, car_offset_z=4, car_offset_x=4)
        self.assertEqual(calibrated_position(.2, 1., p), calibrated_position(.2, 1., P))
        self.assertEqual(project_pixel((320, 450), p), project_pixel((320, 450), P))

    def test_unsupported_branch_rejected(self):
        with self.assertRaises(ValueError):
            calibrated_position(.2, 1., dict(P, blue_position_method="bev"))

    def test_audit_detects_coordinate_mismatch(self):
        row = self.row()
        self.assertEqual(audit_rows([row], P)["detected_audited"], 1)
        row["z_m"] = "1.1"
        with self.assertRaises(ValueError):
            audit_rows([row], P)

    def test_audit_detects_range_mismatch(self):
        row = self.row()
        row["calibration_valid"] = 0
        with self.assertRaises(ValueError):
            audit_rows([row], P)

    def test_range_bounds_inclusive(self):
        self.assertTrue(range_valid(.5, .65, {}))
        self.assertTrue(range_valid(-.5, 1.35, {}))
        self.assertFalse(range_valid(0, 1.351, {}))

    def reference(self, **kw):
        return dict(session="s", reference_kind="static_layout", start_frame="1", end_frame="2",
                    expected_x_m=".3", expected_z_m="1.", expected_distance_m="", **kw)

    def test_summary_includes_rejected_detections(self):
        r = summarize_reference([self.row(1), self.row(2, .4)], self.reference(), P)
        self.assertEqual(r["accepted"], 0)
        self.assertAlmostEqual(r["raw_x_median_m"], .3)
        self.assertAlmostEqual(r["current_x_median_m"], .2)
        self.assertAlmostEqual(r["current_x_mae_m"], .1)
        self.assertEqual(r["reference_quality"], "nominal_layout_not_for_fitting")

    def test_missing_detection_not_zero_error(self):
        rows = [dict(self.row(i), detected="0") for i in (1, 2)]
        r = summarize_reference(rows, self.reference(), P)
        self.assertIsNone(r["current_x_mae_m"])
        self.assertIsNone(r["anchor_pixel_x"])
        self.assertEqual(sensitivity_rows(r, P), [])

    def test_missing_frames_rejected(self):
        with self.assertRaises(ValueError):
            summarize_reference([self.row()], self.reference(), P)

    def test_initial_distance_does_not_become_z_truth(self):
        ref = self.reference()
        ref.update(reference_kind="initial_distance_only", expected_x_m="", expected_z_m="", expected_distance_m="1.3")
        r = summarize_reference([self.row(1), self.row(2)], ref, P)
        self.assertIsNone(r["current_z_mae_m"])
        self.assertGreater(r["current_distance_mae_m"], 0)

    def test_height_scaling_is_exact_for_frozen_pixel(self):
        a = project_pixel((320, 450), P)
        b = project_pixel((320, 450), dict(P, camera_height=.59))
        self.assertIsNotNone(a)
        self.assertAlmostEqual(b[1] / a[1], .59 / .58)

    def test_outside_lens_or_upward_pixel_has_no_floor_projection(self):
        self.assertIsNone(project_pixel((1279, 0), P))
        self.assertIsNone(project_pixel((320, 200), P))

    def test_sensitivity_does_not_modify_parameters(self):
        r = summarize_reference([self.row(1), self.row(2)], self.reference(), P)
        p = dict(P)
        rows = sensitivity_rows(r, p)
        self.assertEqual(p, P)
        self.assertEqual(len(rows), 12)
        self.assertTrue(all("NOT_REPLAY" in s["kind"] for s in rows))

    def test_lateral_offset_cannot_fix_span(self):
        rows = []
        for sign in (-1, 1):
            rows.append({"reference_kind": "static_layout", "variant": "v", "expected_z_m": 1.,
                         "expected_x_m": sign * .3, "raw_x_median_m": sign * .4,
                         "current_x_median_m": sign * .24 + .02, "x_scale": .6, "x_offset_m": .02})
        r = paired_spans(rows)[0]
        self.assertAlmostEqual(r["current_span_over_nominal"], .8)
        self.assertAlmostEqual(r["pair_midpoint_bias_m"], .02)
        self.assertAlmostEqual(r["nominal_implied_x_scale_not_fitted_or_approved"], .75)


if __name__ == "__main__":
    unittest.main()
