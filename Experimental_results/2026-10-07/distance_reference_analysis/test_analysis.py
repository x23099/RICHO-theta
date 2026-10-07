"""Small deterministic checks for the dated offline aggregation."""
import unittest
import analyze_distance_reference as analysis


class SummaryTests(unittest.TestCase):
    def test_empty_is_missing_not_zero_distance(self):
        self.assertEqual(analysis.describe([],.9),{"n":0})

    def test_signed_bias_and_absolute_error(self):
        result=analysis.describe([1.,1.1,1.2],1.2)
        self.assertAlmostEqual(result["bias_m"],-.1)
        self.assertAlmostEqual(result["mae_m"],.1)
        self.assertAlmostEqual(result["iqr_m"],.1)

    def test_rejected_observation_remains_in_distance_statistics(self):
        row=dict(detected="1",measurement_accepted="0",calibration_valid="0",track_available="0",
                 track_predicted="0",z_m="1.5",raw_z_m="1.5",x_m="0",rejection_reason="calibration_range_gate",
                 collision_risk_level="CLEAR",collision_ffb_active="0")
        result=analysis.summarize("z1p30","live","all",[row])
        self.assertEqual(result["detected_z_n"],1)
        self.assertEqual(result["accepted_z_n"],0)
        self.assertAlmostEqual(result["detected_z_bias_m"],.2)

    def test_missing_detected_coordinate_fails(self):
        row=dict(detected="1",measurement_accepted="0",calibration_valid="0",track_available="0",
                 track_predicted="0",z_m="",rejection_reason="none")
        with self.assertRaises(AssertionError):
            analysis.summarize("z1p30","live","all",[row])

    def test_nobox_has_no_distance_bias_or_false_zero(self):
        row=dict(detected="0",measurement_accepted="0",calibration_valid="0",track_available="0",
                 track_predicted="0",rejection_reason="no_detection",collision_risk_level="CLEAR",collision_ffb_active="0")
        result=analysis.summarize("no_box","live","all",[row])
        self.assertEqual(result["detected_z_n"],0)
        self.assertNotIn("detected_z_bias_m",result)


if __name__=="__main__":
    unittest.main()
