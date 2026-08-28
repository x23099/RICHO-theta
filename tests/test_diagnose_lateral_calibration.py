import csv
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from diagnose_lateral_calibration import (  # noqa: E402
    build_model_results,
    fit_model,
    load_csv_points,
    parse_dataset_spec,
    parse_position_label,
    selection_decision,
)


def point(dataset, raw_x, expected_x):
    return {
        "dataset": dataset,
        "role": "trusted",
        "median_raw_x_m": raw_x,
        "median_raw_z_m": 1.0,
        "expected_x_m": expected_x,
    }


class LateralCalibrationDiagnosisTest(unittest.TestCase):
    def test_dataset_spec(self):
        name, path = parse_dataset_spec("p0a=/tmp/recording.tar.xz")
        self.assertEqual(name, "p0a")
        self.assertEqual(path, Path("/tmp/recording.tar.xz"))

    def test_parses_p_decimal_and_center_labels(self):
        self.assertEqual(
            parse_position_label("static_left_xm0p40_z1p00_r01_20260818"),
            (-0.4, 1.0),
        )
        self.assertEqual(
            parse_position_label("static_right_xp0p40_z1p00_r01"),
            (0.4, 1.0),
        )
        self.assertEqual(
            parse_position_label("static_center_z1p00_r03"),
            (0.0, 1.0),
        )

    def test_csv_loader_preserves_recorded_raw_coordinate(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "positions.csv"
            with path.open("w", newline="") as output_file:
                writer = csv.DictWriter(
                    output_file,
                    fieldnames=(
                        "session", "expected_x_m", "expected_z_m", "raw_x_m",
                        "raw_z_m", "estimated_x_m", "estimated_z_m",
                        "detected_samples",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "session": "holdout_xp0.2_z1.0",
                        "expected_x_m": 0.2,
                        "expected_z_m": 1.0,
                        "raw_x_m": 0.3,
                        "raw_z_m": 0.98,
                        "estimated_x_m": 0.21,
                        "estimated_z_m": 0.98,
                        "detected_samples": 42,
                    }
                )
            rows = load_csv_points(path, "holdout", "trusted", 0.6, 0.02)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_coordinate_source"], "recorded")
        self.assertAlmostEqual(rows[0]["current_error_x_m"], 0.01)
        self.assertEqual(rows[0]["samples"], 42)

    def test_affine_fit_and_selection_reject_non_generalizing_refit(self):
        dataset_a = [point("a", -0.4, -0.2), point("a", 0.4, 0.2)]
        dataset_b = [point("b", -0.2, -0.2), point("b", 0.2, 0.2)]
        coefficients = fit_model(dataset_a, "affine")
        self.assertAlmostEqual(coefficients[0], 0.5)

        rows = build_model_results(dataset_a + dataset_b, 0.75, 0.0)
        decision = selection_decision(rows)
        self.assertEqual(decision["decision"], "KEEP_CURRENT")
        self.assertFalse(decision["family_passes"]["affine"])


if __name__ == "__main__":
    unittest.main()
