import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from preflight_field_experiment import (  # noqa: E402
    check_config,
    check_record_storage,
    check_ttc_profile,
    validate_experiment_config,
)


class FieldExperimentPreflightTest(unittest.TestCase):
    def test_accepts_raw_ground_distance_trial_configuration(self):
        config_path = SRC_DIR / "bird_eye_config_raw_ground_distance.json"

        result = check_config(config_path)

        self.assertEqual(result.status, "PASS")
        self.assertIn("area_mode=raw_ground_distance", result.detail)
        self.assertIn("normalized_area_min=2000", result.detail)
        self.assertIn("nis_max=9.21", result.detail)
        self.assertIn("confirm_frames=2", result.detail)
        self.assertIn("hsv_v_min=30", result.detail)
        self.assertIn("max_aspect=1.5", result.detail)
        self.assertIn("illumination=none", result.detail)

    def test_candidate_config_matches_candidate_profile(self):
        result = check_ttc_profile(
            SRC_DIR / "bird_eye_config_ttc_candidate_20260902.json",
            SRC_DIR / "dynamic_ttc_evaluation_profile_v3_candidate.json",
        )

        self.assertEqual(result.status, "PASS")
        self.assertIn("matched 8 runtime parameters", result.detail)

    def test_conservative_candidate_matches_schema3_profile(self):
        result = check_ttc_profile(
            SRC_DIR / "bird_eye_config_ttc_conservative_candidate_20260903.json",
            SRC_DIR / "dynamic_ttc_evaluation_profile_v4_candidate.json",
        )

        self.assertEqual(result.status, "PASS")
        self.assertIn("matched 9 runtime parameters", result.detail)

    def test_ttc_profile_mismatch_fails_preflight(self):
        config = json.loads(
            (SRC_DIR / "bird_eye_config_ttc_candidate_20260902.json").read_text()
        )
        config["blue_ttc_deadband_mps"] = 0.05
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / "config.json"
            config_path.write_text(json.dumps(config))
            result = check_ttc_profile(
                config_path,
                SRC_DIR / "dynamic_ttc_evaluation_profile_v3_candidate.json",
            )

        self.assertEqual(result.status, "FAIL")
        self.assertIn("blue_ttc_deadband_mps", result.detail)

    def test_accepts_blue_baseline_configuration(self):
        config = {
            "blue_position_method": "ground_contact",
            "blue_tracking_enabled": 1,
            "blue_observation_gate_enabled": 1,
            "blue_ttc_enabled": 1,
            "blue_collision_candidate_enabled": 1,
            "camera_height": 0.58,
            "scale": 0.008,
            "car_width": 0.354,
            "blue_ground_contact_min_area": 300,
            "blue_observation_normalized_area_min": 2503.7,
            "blue_observation_nis_max": 9.21,
            "blue_ttc_velocity_window_sec": 0.3,
            "blue_ttc_deadband_mps": 0.05,
            "blue_collision_warning_ttc_sec": 4.0,
            "blue_collision_critical_ttc_sec": 2.0,
            "blue_collision_warning_exit_ttc_sec": 5.0,
            "blue_collision_warning_confirm_frames": 3,
            "blue_collision_warning_clear_frames": 3,
            "blue_collision_warning_hold_sec": 0.8,
            "blue_collision_forward_motion_threshold_mps": 0.03,
        }

        self.assertEqual(validate_experiment_config(config), [])

    def test_rejects_disabled_gate_and_reversed_ttc_levels(self):
        config = {
            "blue_position_method": "ground_contact",
            "blue_tracking_enabled": 1,
            "blue_observation_gate_enabled": 0,
            "blue_ttc_enabled": 1,
            "blue_collision_candidate_enabled": 1,
            "camera_height": 0.58,
            "scale": 0.008,
            "car_width": 0.354,
            "blue_ground_contact_min_area": 300,
            "blue_observation_normalized_area_min": 2503.7,
            "blue_observation_nis_max": 9.21,
            "blue_ttc_velocity_window_sec": 0.3,
            "blue_ttc_deadband_mps": 0.05,
            "blue_collision_warning_ttc_sec": 2.0,
            "blue_collision_critical_ttc_sec": 4.0,
            "blue_collision_warning_exit_ttc_sec": 1.0,
            "blue_collision_warning_confirm_frames": 0,
            "blue_collision_warning_clear_frames": 3,
            "blue_collision_warning_hold_sec": 0.8,
            "blue_collision_forward_motion_threshold_mps": 0.03,
        }

        errors = validate_experiment_config(config)

        self.assertTrue(any("blue_observation_gate_enabled" in item for item in errors))
        self.assertTrue(any("critical TTC" in item for item in errors))
        self.assertTrue(any("warning exit TTC" in item for item in errors))
        self.assertTrue(any("warning_confirm_frames" in item for item in errors))

    def test_storage_check_uses_requested_threshold(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            passing = check_record_storage(Path(temporary_dir), 0.0)
            impossible = check_record_storage(Path(temporary_dir), 10 ** 9)

        self.assertEqual(passing.status, "PASS")
        self.assertEqual(impossible.status, "FAIL")

    def test_rejects_invalid_area_mode_and_hsv_value(self):
        config = {
            "blue_position_method": "ground_contact",
            "blue_tracking_enabled": 1,
            "blue_observation_gate_enabled": 1,
            "blue_ttc_enabled": 1,
            "blue_collision_candidate_enabled": 1,
            "camera_height": 0.58,
            "scale": 0.008,
            "car_width": 0.354,
            "blue_ground_contact_min_area": 300,
            "blue_observation_normalized_area_min": 2000,
            "blue_observation_nis_max": 9.21,
            "blue_ttc_velocity_window_sec": 0.3,
            "blue_ttc_deadband_mps": 0.05,
            "blue_collision_warning_ttc_sec": 4.0,
            "blue_collision_critical_ttc_sec": 2.0,
            "blue_collision_warning_exit_ttc_sec": 5.0,
            "blue_collision_warning_confirm_frames": 3,
            "blue_collision_warning_clear_frames": 3,
            "blue_collision_warning_hold_sec": 0.8,
            "blue_collision_forward_motion_threshold_mps": 0.03,
            "blue_observation_area_distance_mode": "unknown",
            "blue_ground_contact_hsv_v_min": 300,
            "blue_ground_contact_max_aspect_ratio": 0,
            "blue_ground_contact_illumination_mode": "unknown",
        }

        errors = validate_experiment_config(config)

        self.assertTrue(any("area_distance_mode" in item for item in errors))
        self.assertTrue(any("hsv_v_min" in item for item in errors))
        self.assertTrue(any("max_aspect_ratio" in item for item in errors))
        self.assertTrue(any("illumination_mode" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
