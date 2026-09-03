import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
V2_PROFILE = SRC_DIR / "dynamic_ttc_evaluation_profile_v2_candidate.json"
V4_PROFILE = SRC_DIR / "dynamic_ttc_evaluation_profile_v4_candidate.json"
V5_PROFILE = SRC_DIR / "dynamic_ttc_evaluation_profile_v5_candidate.json"
sys.path.insert(0, str(SRC_DIR))

from evaluate_dynamic_ttc_conditions import (  # noqa: E402
    DEFAULT_PROFILE,
    evaluate_session,
    expected_motion,
    load_profile,
    nominal_speed_mps,
)


def profile():
    result = copy.deepcopy(load_profile(DEFAULT_PROFILE))
    result["minimum_accuracy_interval_frames"] = 1
    return result


def row(timestamp, odom_linear, smoothed_vz, ttc, corridor=True, valid=True):
    return {
        "frame": int(round(timestamp * 100)) + 1,
        "time_sec": timestamp,
        "monotonic_time_sec": timestamp,
        "detected": 1,
        "track_available": 1,
        "track_predicted": 0,
        "measurement_accepted": 1,
        "calibration_valid": int(valid),
        "filtered_z_m": 0.8,
        "smoothed_vz_mps": smoothed_vz,
        "ttc_sec": ttc,
        "odom_available": 1,
        "odom_linear_mps": odom_linear,
        "odom_angular_radps": 0.0,
        "path_in_collision_corridor": int(corridor),
        "collision_risk_level": "CLEAR",
    }


class DynamicTtcConditionTest(unittest.TestCase):
    def test_parses_motion_and_nominal_speed_from_label(self):
        label = "approach_center_v0p20_r01"

        self.assertEqual(expected_motion(label), "approach")
        self.assertEqual(nominal_speed_mps(label), 0.20)
        self.assertEqual(expected_motion("retreat_center_v0p10_r01"), "retreat")
        self.assertIsNone(nominal_speed_mps("approach_unknown"))

    def test_rejects_incomplete_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps({"schema_version": 1}))

            with self.assertRaisesRegex(ValueError, "missing="):
                load_profile(path)

    def test_rejects_inconsistent_warning_thresholds(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            invalid = profile()
            invalid["critical_ttc_sec"] = invalid["warning_ttc_sec"]
            path.write_text(json.dumps(invalid))

            with self.assertRaisesRegex(ValueError, "thresholds are inconsistent"):
                load_profile(path)

    def test_v2_rejects_warning_without_calibration_range_margin(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            invalid = copy.deepcopy(load_profile(V2_PROFILE))
            invalid["warning_ttc_sec"] = 4.1
            path.write_text(json.dumps(invalid))

            with self.assertRaisesRegex(ValueError, "feasibility margin"):
                load_profile(path)

    def test_v2_scores_motion_tracking_and_steady_direction_separately(self):
        candidate = copy.deepcopy(load_profile(V2_PROFILE))
        candidate["minimum_accuracy_interval_frames"] = 1
        candidate["speed_mae_absolute_limit_mps"] = 1.0
        candidate["direction_stability_frames"] = 3
        moving = [
            row(0.00, 0.10, +0.10, ""),
            row(0.04, 0.10, +0.10, ""),
            row(0.08, 0.10, -0.10, 8.0),
            row(0.12, 0.10, -0.10, 7.6),
            row(0.16, 0.10, -0.10, 7.2),
            row(0.20, 0.10, -0.10, 6.8),
        ]
        stopped = [row(0.24 + index * 0.04, 0.0, 0.0, "") for index in range(8)]
        for stopped_row in stopped:
            stopped_row["track_available"] = 0
            stopped_row["calibration_valid"] = 0
        settled = [
            row(0.56 + index * 0.04, 0.0, 0.0, "", corridor=False)
            for index in range(3)
        ]

        result = evaluate_session(
            "approach_center_v0p10_r01",
            "trial",
            {"parameters": {}},
            moving + stopped + settled,
            candidate,
        )

        self.assertEqual(result["decision"], "PASS")
        self.assertLess(result["track_rate"], candidate["minimum_motion_track_rate"])
        self.assertEqual(result["motion_track_rate"], 1.0)
        self.assertAlmostEqual(result["direction_response_delay_sec"], 0.08)
        self.assertEqual(result["steady_direction_correct_rate"], 1.0)

    def test_v3_schema_preserves_v2_direction_metrics(self):
        candidate = copy.deepcopy(load_profile(V4_PROFILE))
        candidate["minimum_accuracy_interval_frames"] = 1
        candidate["speed_mae_absolute_limit_mps"] = 1.0
        candidate["direction_stability_frames"] = 2
        rows = [
            row(0.00, 0.10, -0.10, 8.0),
            row(0.04, 0.10, -0.10, 7.6),
            row(0.08, 0.10, -0.10, 7.2),
        ]

        result = evaluate_session(
            "approach_center_v0p10_r01",
            "trial",
            {"parameters": {}},
            rows,
            candidate,
        )

        self.assertEqual(result["direction_response_delay_sec"], 0.0)
        self.assertEqual(result["steady_direction_correct_rate"], 1.0)

    def test_v3_rejects_unknown_velocity_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            invalid = copy.deepcopy(load_profile(V4_PROFILE))
            invalid["velocity_source"] = "unknown"
            path.write_text(json.dumps(invalid))

            with self.assertRaisesRegex(ValueError, "velocity_source"):
                load_profile(path)

    def test_v3_fails_when_runtime_velocity_source_does_not_match(self):
        candidate = copy.deepcopy(load_profile(V4_PROFILE))
        candidate["minimum_accuracy_interval_frames"] = 1
        rows = [
            row(0.00, 0.10, -0.10, 8.0),
            row(0.04, 0.10, -0.10, 7.6),
            row(0.08, 0.10, -0.10, 7.2),
        ]
        for item in rows:
            item["ttc_velocity_source"] = "visual"

        result = evaluate_session(
            "approach_center_v0p10_r01",
            "trial",
            {"parameters": {"blue_ttc_velocity_source": "visual"}},
            rows,
            candidate,
        )

        self.assertIn("configured_velocity_source", result["reasons"])
        self.assertIn("velocity_source_match_rate", result["reasons"])

    def test_v3_accepts_conservative_runtime_provenance(self):
        candidate = copy.deepcopy(load_profile(V4_PROFILE))
        candidate["minimum_accuracy_interval_frames"] = 1
        rows = [
            row(0.00, 0.10, -0.10, 8.0),
            row(0.04, 0.10, -0.10, 7.6),
            row(0.08, 0.10, -0.10, 7.2),
        ]
        for item in rows:
            item["ttc_velocity_source"] = "conservative_odom"

        result = evaluate_session(
            "approach_center_v0p10_r01",
            "trial",
            {"parameters": {"blue_ttc_velocity_source": "conservative"}},
            rows,
            candidate,
        )

        self.assertNotIn("configured_velocity_source", result["reasons"])
        self.assertNotIn("velocity_source_match_rate", result["reasons"])
        self.assertEqual(result["velocity_source_match_rate"], 1.0)

    def test_schema4_adds_half_odom_resolution_to_speed_limit(self):
        candidate = copy.deepcopy(load_profile(V5_PROFILE))
        candidate["minimum_accuracy_interval_frames"] = 1
        rows = [row(index * 0.04, 0.159923, -0.159923, 4.5) for index in range(3)]
        for item in rows:
            item["ttc_velocity_source"] = "conservative_odom"

        result = evaluate_session(
            "approach_center_v0p20_r01",
            "trial",
            {"parameters": {"blue_ttc_velocity_source": "conservative"}},
            rows,
            candidate,
        )

        self.assertAlmostEqual(result["nominal_speed_error_mps"], 0.040077)
        self.assertAlmostEqual(result["nominal_speed_error_limit_mps"], 0.041066)
        self.assertNotIn("nominal_speed_error_mps", result["reasons"])

    def test_high_speed_scores_accuracy_before_warning_and_safety_after_it(self):
        rows = [
            row(0.00, 0.20, -0.20, 3.9),
            row(0.04, 0.20, -0.20, 3.9),
            row(0.08, 0.20, -0.20, 3.9),
            row(0.12, 0.20, +0.20, "", valid=False),
            row(0.16, 0.00, +0.20, "", corridor=False),
            row(0.20, 0.00, +0.20, "", corridor=False),
            row(0.24, 0.00, +0.20, "", corridor=False),
        ]

        result = evaluate_session(
            "approach_center_v0p20_r01",
            "trial",
            {"parameters": {}},
            rows,
            profile(),
        )

        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["accuracy_interval_frames"], 1)
        self.assertGreaterEqual(result["warning_hold_frames"], 1)
        self.assertEqual(result["longest_confirmable_warning_run_frames"], 3)
        self.assertEqual(result["path_while_forward_after_warning_frames"], 0)
        self.assertEqual(result["final_state"], "CLEAR")

    def test_high_speed_fails_if_first_warning_is_too_late(self):
        rows = [
            row(0.00, 0.20, -0.20, 3.0),
            row(0.04, 0.20, -0.20, 3.0),
            row(0.08, 0.20, -0.20, 3.0),
            row(0.12, 0.00, -0.20, "", corridor=False),
            row(0.16, 0.00, -0.20, "", corridor=False),
            row(0.20, 0.00, -0.20, "", corridor=False),
        ]

        result = evaluate_session(
            "approach_center_v0p20_r01",
            "trial",
            {"parameters": {}},
            rows,
            profile(),
        )

        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("first_raw_warning_ttc_sec", result["reasons"])

    def test_retreat_requires_correct_direction_and_no_ttc(self):
        rows = [
            row(0.00, -0.10, +0.10, "", corridor=False),
            row(0.04, -0.10, +0.10, "", corridor=False),
            row(0.08, -0.10, +0.10, "", corridor=False),
        ]

        result = evaluate_session(
            "retreat_center_v0p10_r01",
            "trial",
            {"parameters": {}},
            rows,
            profile(),
        )

        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["false_ttc_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
