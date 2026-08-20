import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from evaluate_live_trial_requirements import (  # noqa: E402
    REQUIREMENT_FIELDS,
    evaluate_requirements,
)


def requirement(**overrides):
    row = dict.fromkeys(REQUIREMENT_FIELDS, "")
    row.update({
        "rule_id": "side",
        "experiment_label_glob": "static_*",
        "min_trials": "1",
        "min_detection_rate": "0.98",
        "max_detection_rate": "",
        "min_measurement_acceptance_rate": "0.98",
        "min_track_rate": "0.98",
        "max_track_rate": "",
        "max_warning_or_critical_rate": "0.01",
    })
    row.update(overrides)
    return row


class LiveTrialRequirementEvaluationTest(unittest.TestCase):
    def test_fails_when_no_warning_is_caused_by_missing_tracking(self):
        summaries = [
            {
                "experiment_label": "static_left",
                "detection_rate": "1.0",
                "measurement_acceptance_rate": "0.0",
                "track_rate": "0.0",
                "warning_or_critical_rate": "0.0",
            }
        ]

        result = evaluate_requirements(summaries, [requirement()])[0]

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("measurement_acceptance_rate=0.000000", result["reasons"])
        self.assertIn("track_rate=0.000000", result["reasons"])

    def test_passes_complete_trials_and_enforces_minimum_count(self):
        summaries = [
            {
                "experiment_label": f"static_center_r{index}",
                "detection_rate": "1.0",
                "measurement_acceptance_rate": "0.99",
                "track_rate": "1.0",
                "warning_or_critical_rate": "0.0",
            }
            for index in range(3)
        ]

        result = evaluate_requirements(
            summaries,
            [
                requirement(
                    rule_id="center",
                    experiment_label_glob="static_center_*",
                    min_trials="3",
                )
            ],
        )[0]

        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["matched_trials"], 3)

    def test_missing_required_metric_fails_closed(self):
        summaries = [{"experiment_label": "static_left", "detection_rate": "1.0"}]

        result = evaluate_requirements(summaries, [requirement()])[0]

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("track_rate is unavailable", result["reasons"])

    def test_supports_hysteresis_metrics_and_alternate_label_column(self):
        summaries = [
            {
                "session": "approach_v0p20_r01",
                "filtered_warning_frames": "20",
                "warning_hold_frames": "5",
                "maximum_warning_entry_delay_sec": "0.08",
                "path_while_forward_after_warning_frames": "0",
                "final_state": "CLEAR",
            }
        ]
        rule = requirement(
            experiment_label_glob="approach_v0p20_*",
            min_detection_rate="",
            min_measurement_acceptance_rate="",
            min_track_rate="",
            max_warning_or_critical_rate="",
            min_filtered_warning_frames="1",
            min_warning_hold_frames="1",
            max_warning_entry_delay_sec="0.5",
            max_path_while_forward_after_warning_frames="0",
            expected_final_state="CLEAR",
        )

        result = evaluate_requirements(
            summaries, [rule], label_column="session"
        )[0]

        self.assertEqual(result["result"], "PASS")

    def test_applies_per_trial_maximum_and_group_mean(self):
        summaries = [
            {
                "session": "point_1",
                "position_error_m": "0.02",
                "detection_rate": "1.0",
                "odom_available_rate": "1.0",
            },
            {
                "session": "point_2",
                "position_error_m": "0.07",
                "detection_rate": "1.0",
                "odom_available_rate": "1.0",
            },
        ]
        rule = requirement(
            experiment_label_glob="point_*",
            min_trials="2",
            min_detection_rate="1.0",
            min_measurement_acceptance_rate="",
            min_track_rate="",
            max_warning_or_critical_rate="",
            min_odom_available_rate="0.95",
            max_position_error_m="0.08",
            max_mean_position_error_m="0.05",
        )

        result = evaluate_requirements(
            summaries, [rule], label_column="session"
        )[0]

        self.assertEqual(result["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
