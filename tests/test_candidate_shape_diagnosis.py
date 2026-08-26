import csv
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from diagnose_candidate_shapes import compare  # noqa: E402


class CandidateShapeDiagnosisTest(unittest.TestCase):
    def test_separates_horizontal_false_candidate_and_position_outlier(self):
        fields = [
            "session", "phase_label", "detected", "x_m", "z_m", "area_px",
            "bbox_aspect_ratio", "bbox_fill_ratio", "contour_solidity",
            "source_pixel_x", "source_pixel_y", "raw_distance_m",
        ]
        with tempfile.TemporaryDirectory() as temporary_dir:
            no_target = Path(temporary_dir) / "no_target.csv"
            target = Path(temporary_dir) / "target.csv"
            with no_target.open("w", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        **dict.fromkeys(fields, ""),
                        "session": "none",
                        "detected": "1",
                        "x_m": "0.3",
                        "z_m": "0.6",
                        "area_px": "500",
                        "bbox_aspect_ratio": "2.0",
                        "bbox_fill_ratio": "0.5",
                        "contour_solidity": "0.8",
                        "source_pixel_x": "400",
                        "source_pixel_y": "470",
                        "raw_distance_m": "0.67",
                    }
                )
            with target.open("w", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=fields)
                writer.writeheader()
                cases = [
                    ("visible", "0.0", "0.8"),
                    ("visible", "0.01", "0.9"),
                    ("reappearing", "0.02", "1.1"),
                    ("visible", "1.0", "3.0"),
                ]
                for phase, x_m, aspect in cases:
                    writer.writerow(
                        {
                            **dict.fromkeys(fields, ""),
                            "session": "target",
                            "phase_label": phase,
                            "detected": "1",
                            "x_m": x_m,
                            "z_m": "1.0",
                            "area_px": "2500",
                            "bbox_aspect_ratio": aspect,
                            "bbox_fill_ratio": "0.8",
                            "contour_solidity": "0.9",
                            "source_pixel_x": "320",
                            "source_pixel_y": "430",
                            "raw_distance_m": "1.0",
                        }
                    )

            rows = compare([no_target], [target], max_aspect_ratio=1.5)

            self.assertEqual(rows[0]["candidate_accepted"], 0)
            self.assertEqual(rows[1]["observations"], 3)
            self.assertEqual(rows[1]["candidate_accepted"], 3)


if __name__ == "__main__":
    unittest.main()
