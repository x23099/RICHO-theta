import unittest
import diagnose_distance_geometry as geometry

P = dict(camera_height=.58, radius_scale=.86, front_cx_offset=-80,
         front_cy_offset=-21, pitch_deg=1., roll_deg=2.)


class GeometryDiagnosisTests(unittest.TestCase):
    def test_inverse_round_trip(self):
        z = geometry.project_pixel((314, 433), P)[1]
        self.assertAlmostEqual(geometry.nominal_pixel_y(314, z, P), 433.)

    def test_inverse_unreachable_is_missing_not_zero(self):
        self.assertIsNone(geometry.nominal_pixel_y(314, 100., P))

    def test_pixel_band_contains_anchor_not_assumed_truth(self):
        edge = dict(pixel_x=314, pixel_y=433, assumed_pixel_half_width=2,
                    review_kind="nonblind_visual_estimate_not_ground_truth")
        p = dict(P)
        r = geometry.edge_projection(edge, p, 1.1)
        self.assertLess(r["manual_band_z_min_m"], r["manual_anchor_z_m"])
        self.assertGreater(r["manual_band_z_max_m"], r["manual_anchor_z_m"])
        self.assertEqual(r["nominal_inside_assumed_pixel_band"], 0)
        self.assertEqual(p, P)
        self.assertEqual(r["reference_quality"], geometry.REFERENCE["reference_quality"])

    def test_z_offset_affects_nominal_inverse(self):
        edge = dict(pixel_x=314, pixel_y=433, assumed_pixel_half_width=2, review_kind="illustration")
        a = geometry.edge_projection(edge, P, 1.1)
        b = geometry.edge_projection(edge, dict(P, blue_ground_contact_z_offset_m=.1), 1.2)
        self.assertAlmostEqual(a["model_pixel_y_for_nominal"], b["model_pixel_y_for_nominal"])
        self.assertAlmostEqual(b["manual_anchor_z_m"]-a["manual_anchor_z_m"], .1)

    def test_invalid_band_rejected(self):
        edge = dict(pixel_x=1279, pixel_y=0, assumed_pixel_half_width=2, review_kind="illustration")
        with self.assertRaises(ValueError):
            geometry.edge_projection(edge, P, 1.1)

    def test_negative_band_rejected(self):
        edge = dict(pixel_x=314, pixel_y=433, assumed_pixel_half_width=-1, review_kind="illustration")
        with self.assertRaises(ValueError):
            geometry.edge_projection(edge, P, 1.1)

    def test_height_interval_matches_linear_floor_geometry(self):
        bounds = geometry.common_error_intervals(dict(manual_band_z_min_m=1.,manual_band_z_max_m=1.2),1.1,P)
        self.assertAlmostEqual(bounds[0]["lower"],.58*1.1/1.2)
        self.assertAlmostEqual(bounds[0]["upper"],.58*1.1)
        self.assertAlmostEqual(bounds[1]["lower"],-.1)
        self.assertAlmostEqual(bounds[1]["upper"],.1)

    def test_height_interval_respects_existing_z_offset(self):
        a=geometry.common_error_intervals(dict(manual_band_z_min_m=1.,manual_band_z_max_m=1.2),1.1,P)
        b=geometry.common_error_intervals(dict(manual_band_z_min_m=1.1,manual_band_z_max_m=1.3),1.2,
                                         dict(P,blue_ground_contact_z_offset_m=.1))
        for x,y in zip(a,b):
            self.assertAlmostEqual(x["lower"],y["lower"])
            self.assertAlmostEqual(x["upper"],y["upper"])

    def test_disjoint_and_touching_intervals(self):
        rows=[dict(parameter="height",lower=.5,upper=.6),dict(parameter="height",lower=.61,upper=.7)]
        self.assertFalse(geometry.intersect_intervals(rows)["common_value_possible"])
        self.assertAlmostEqual(geometry.intersect_intervals(rows)["separation_gap"],.01)
        rows[1]["lower"]=.6
        self.assertTrue(geometry.intersect_intervals(rows)["common_value_possible"])

    def test_different_parameter_intervals_rejected(self):
        with self.assertRaises(ValueError):
            geometry.intersect_intervals([dict(parameter="height",lower=.5,upper=.6),
                                          dict(parameter="offset",lower=.5,upper=.6)])

    def test_origin_confirmation_not_absolute_pose_measurement(self):
        self.assertTrue(geometry.REFERENCE["reference_origin_confirmed"])
        self.assertFalse(geometry.REFERENCE["camera_height_changed_between_trials"])
        self.assertFalse(geometry.REFERENCE["camera_tilt_changed_between_trials"])
        self.assertIsNone(geometry.REFERENCE["physical_camera_height_m"])


if __name__ == "__main__":
    unittest.main()
