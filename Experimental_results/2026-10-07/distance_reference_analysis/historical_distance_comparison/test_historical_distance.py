import copy
import unittest

import compare_historical_distance as m


class HistoricalDistanceTests(unittest.TestCase):
    def test_legacy_sampling_is_zero_based_30_then_every_five(self):
        model=dict(warmup_frames=30,frame_step=5)
        self.assertEqual([f for f in range(1,42) if m.sampled(f,model)],[31,36,41])
        self.assertEqual(sum(m.sampled(f,model) for f in range(1,237)),42)

    def test_nominal_label_mismatch_rejected(self):
        ref=dict(expected_x_m=-.22,expected_z_m=.95)
        m.validate_reference("holdout_xm0.22_z0.95",ref)
        with self.assertRaises(ValueError):
            m.validate_reference("holdout_xm0.22_z1.20",ref)
        with self.assertRaises(ValueError):
            m.validate_reference("unknown",ref)

    def test_only_detector_overrides_and_no_mutation(self):
        recorded={k:i for i,k in enumerate(m.GEOMETRY)}
        before=copy.deepcopy(recorded)
        config=dict(camera_height=99,blue_ground_contact_hsv_s_min=130,
                    blue_ground_contact_x_scale=99,blue_collision_warning_ttc_sec=99)
        p=m.detector_parameters(recorded,config)
        self.assertEqual(recorded,before)
        self.assertEqual(p["camera_height"],recorded["camera_height"])
        self.assertEqual(p["blue_ground_contact_hsv_s_min"],130)
        self.assertNotIn("blue_ground_contact_x_scale",p)
        self.assertNotIn("blue_collision_warning_ttc_sec",p)

    def config(self):
        return dict(blue_ground_contact_x_scale=.6,blue_ground_contact_x_offset_m=.02,
                    blue_ground_contact_z_offset_m=0.,blue_calibration_input_x_max_m=.5,
                    blue_calibration_input_z_min_m=.65,blue_calibration_input_z_max_m=1.35,
                    blue_calibration_z_scale=999,blue_calibration_z_offset_m=999)

    def test_legacy_bev_coefficients_not_applied(self):
        r=m.calibrated(dict(x_m=.3,z_m=1.1),self.config())
        self.assertAlmostEqual(r["x_m"],.2)
        self.assertEqual(r["z_m"],1.1)
        self.assertEqual(r["calibration_valid"],1)

    def test_missing_is_not_zero_distance(self):
        r=m.calibrated(None,self.config())
        self.assertIsNone(r["z_m"])
        rows=[dict(variant="baseline",**r)]
        s=m.summarize(rows,dict(session="s",expected_x_m=0,expected_z_m=1),"all")
        self.assertIsNone(s["z_bias_m"])
        self.assertEqual(s["detected"],0)

    def test_range_rejected_contact_is_preserved_in_summary(self):
        r=dict(variant="baseline",raw_contact_x_m=0.,raw_contact_z_m=1.5,
               **m.calibrated(dict(x_m=0.,z_m=1.5),self.config()))
        self.assertEqual(r["calibration_valid"],0)
        s=m.summarize([r],dict(session="s",expected_x_m=0,expected_z_m=1.6),"all")
        self.assertAlmostEqual(s["z_bias_m"],-.1)
        self.assertEqual(s["detected"],1)

    def test_nonfinite_contact_rejected(self):
        with self.assertRaises(ValueError):
            m.calibrated(dict(x_m=float("nan"),z_m=1.),self.config())

    def test_historical_reproduction_checks_count_and_coordinates(self):
        ref=dict(session="s",raw_x_m=.3,raw_z_m=1.,estimated_x_m=.2,
                 estimated_z_m=1.,detected_samples=42,sampled_frames=42)
        row=dict(session="s",variant="historical_recipe",window="historical_sampled",
                 raw_x_median_m=.3,raw_z_median_m=1.,x_median_m=.2,z_median_m=1.,detected=42,frames=42)
        self.assertTrue(all(r["match"] for r in m.reproduce([row],[ref])))
        row["detected"]=41
        self.assertEqual(sum(r["match"] for r in m.reproduce([row],[ref])),5)

    def test_macro_error_does_not_weight_long_recordings_more(self):
        rows=[dict(window="all",variant="baseline",position_error_m=e,x_bias_m=e,z_bias_m=-e,
                   frames=n,detected=n) for e,n in ((.01,1000),(.09,10))]
        row=next(r for r in m.aggregate(rows) if r["variant"]=="baseline" and r["window"]=="all")
        self.assertAlmostEqual(row["z_session_median_mae_m"],.05)
        self.assertEqual(row["frames"],1010)


if __name__=="__main__":
    unittest.main()
