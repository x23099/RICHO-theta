import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from preflight_field_experiment import (  # noqa: E402
    check_record_storage,
    validate_experiment_config,
)


class FieldExperimentPreflightTest(unittest.TestCase):
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
            "blue_collision_warning_ttc_sec": 4.0,
            "blue_collision_critical_ttc_sec": 2.0,
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
            "blue_collision_warning_ttc_sec": 2.0,
            "blue_collision_critical_ttc_sec": 4.0,
        }

        errors = validate_experiment_config(config)

        self.assertTrue(any("blue_observation_gate_enabled" in item for item in errors))
        self.assertTrue(any("critical TTC" in item for item in errors))

    def test_storage_check_uses_requested_threshold(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            passing = check_record_storage(Path(temporary_dir), 0.0)
            impossible = check_record_storage(Path(temporary_dir), 10 ** 9)

        self.assertEqual(passing.status, "PASS")
        self.assertEqual(impossible.status, "FAIL")


if __name__ == "__main__":
    unittest.main()
