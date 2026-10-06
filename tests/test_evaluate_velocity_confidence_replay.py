import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate_velocity_confidence_replay import evaluate_rows
from offline_velocity_confidence import ConfidenceSettings


def fast_rows(count=16):
    return [{"frame": i + 1, "time_sec": i / 30, "monotonic_time_sec": i / 30,
             "track_available": "1", "track_predicted": "0", "measurement_accepted": "1",
             "calibration_valid": "1", "z_m": 1 - i / 30, "relative_vz_mps": -1,
             "visual_smoothed_vz_mps": -1, "ttc_velocity_source": "conservative_visual",
             "ttc_sec": 1 - i / 30, "odom_available": "1", "odom_linear_mps": 0,
             "path_in_collision_corridor": "1", "collision_risk_level": "CRITICAL"}
            for i in range(count)]


class VelocityConfidenceReplayTests(unittest.TestCase):
    def test_baseline_retains_immediate_critical(self):
        summary, rows = evaluate_rows("fast", {}, fast_rows(), candidate=False)
        self.assertEqual(summary["recorded_risk_mismatches"], 0)
        self.assertEqual(rows[0]["risk"], "CRITICAL")

    def test_fast_target_not_clipped_to_stationary_robot(self):
        _, rows = evaluate_rows("fast", {}, fast_rows())
        self.assertEqual(rows[0]["risk"], "UNKNOWN")
        self.assertEqual(rows[0]["virtual_active"], 1)
        first = next(r for r in rows if r["risk"] == "CRITICAL")
        self.assertLessEqual(float(first["time_sec"]), .1)
        self.assertEqual(first["confidence_reason"], "fast_consistent_critical_evidence")

    def test_maturity_only_fails_fast_response_comparison(self):
        settings = ConfidenceSettings(fast_critical_evidence=False)
        _, rows = evaluate_rows("fast", {}, fast_rows(), settings=settings)
        first = next(r for r in rows if r["risk"] == "CRITICAL")
        self.assertGreater(float(first["time_sec"]), .1)

    def test_consistent_fast_approach_keeps_critical_after_onset(self):
        for noisy in (False, True):
            source = fast_rows(45)
            for i, row in enumerate(source):
                noise = [.003, -.003, .004, -.001, .002][i % 5] if noisy else 0
                row.update(z_m=1.8 - i / 30 + noise, ttc_sec=1.8 - i / 30 + noise)
            _, rows = evaluate_rows("continuous_fast", {}, source)
            onset = next(i for i, row in enumerate(rows) if row["risk"] == "CRITICAL")
            self.assertLessEqual(float(rows[onset]["time_sec"]), .1)
            self.assertTrue(all(row["risk"] == "CRITICAL" for row in rows[onset:]))

    def test_new_visual_warning_waits_for_evidence_and_confirmation(self):
        source = fast_rows()
        for i, row in enumerate(source):
            z = 2 - .5 * i / 30
            row.update(z_m=z, ttc_sec=z / .5, visual_smoothed_vz_mps=-.5,
                       relative_vz_mps=-.5, odom_linear_mps=.2)
        _, baseline = evaluate_rows("new_warning", {}, source, candidate=False)
        _, candidate = evaluate_rows("new_warning", {}, source)
        self.assertEqual(candidate[0]["risk"], "UNKNOWN")
        self.assertEqual(candidate[0]["virtual_active"], 1)
        first_base = next(float(r["time_sec"]) for r in baseline if r["risk"] == "WARNING")
        first_candidate = next(float(r["time_sec"]) for r in candidate if r["risk"] == "WARNING")
        self.assertAlmostEqual(first_candidate - first_base, .2)

    def test_odom_source_is_not_suppressed(self):
        source = fast_rows(1)
        source[0]["ttc_velocity_source"] = "conservative_odom"
        _, rows = evaluate_rows("odom", {}, source)
        self.assertEqual(rows[0]["risk"], "CRITICAL")
        self.assertEqual(rows[0]["alert_withheld"], 0)

    def test_uncertain_data_after_confirmed_warning_remains_bounded_hold(self):
        source = fast_rows(40)
        for row in source:
            row["odom_linear_mps"] = .2
        for row in source[7:]:
            row.update(measurement_accepted="0", track_predicted="1")
        _, rows = evaluate_rows("occlusion", {}, source)
        self.assertEqual(rows[7]["risk"], "WARNING_HOLD")
        self.assertEqual(rows[-1]["risk"], "UNKNOWN")

    def test_clear_static_and_retreat_do_not_gain_alarms(self):
        for in_path, ttc, speed in [("0", "", 0), ("1", "", 0), ("1", "", -.2)]:
            source = fast_rows()
            for row in source:
                row.update(path_in_collision_corridor=in_path, ttc_sec=ttc,
                           odom_linear_mps=speed, visual_smoothed_vz_mps=0, collision_risk_level="PATH")
            summary, _ = evaluate_rows("clear", {}, source)
            self.assertEqual(summary["virtual_active_frames"], 0)

    def test_no_input_mutation(self):
        source = fast_rows()
        saved = copy.deepcopy(source)
        evaluate_rows("fast", {}, source)
        self.assertEqual(source, saved)

    def test_missing_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_rows("invalid", {}, [{}])


if __name__ == "__main__":
    unittest.main()
