import csv
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from diagnose_lateral_gate_asymmetry import (  # noqa: E402
    lateral_pair_diagnosis,
    summarize_inputs,
)


class LateralGateAsymmetryTest(unittest.TestCase):
    @staticmethod
    def _csv_bytes(rows):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode()

    def test_reads_tar_xz_without_extracting_and_compares_sides(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive_path = Path(temporary_dir) / "recordings.tar.xz"
            common = {
                "detected": "1",
                "measurement_accepted": "0",
                "rejection_reason": "normalized_area_gate",
            }
            sessions = {
                "left": [
                    dict(common, x_m="-0.4", z_m="0.9", area_px="2400", normalized_area="1944")
                ],
                "right": [
                    dict(common, x_m="0.4", z_m="1.0", area_px="2500", normalized_area="2500")
                ],
            }
            with tarfile.open(archive_path, "w:xz") as archive:
                for label, rows in sessions.items():
                    csv_data = self._csv_bytes(rows)
                    csv_info = tarfile.TarInfo(f"root/{label}/detections.csv")
                    csv_info.size = len(csv_data)
                    archive.addfile(csv_info, io.BytesIO(csv_data))
                    metadata_data = json.dumps(
                        {
                            "experiment_label": label,
                            "parameters": {
                                "blue_observation_normalized_area_min": 2503.678
                            },
                        }
                    ).encode()
                    metadata_info = tarfile.TarInfo(f"root/{label}/metadata.json")
                    metadata_info.size = len(metadata_data)
                    archive.addfile(metadata_info, io.BytesIO(metadata_data))

            summaries = summarize_inputs([archive_path])
            diagnosis = lateral_pair_diagnosis(summaries)

            self.assertEqual(len(summaries), 2)
            self.assertAlmostEqual(summaries[0]["normalized_area_threshold"], 2503.678)
            self.assertAlmostEqual(
                diagnosis["normalized_area_ratio_left_to_right"], 1944 / 2500
            )
            self.assertAlmostEqual(
                diagnosis["z_squared_ratio_left_to_right"], 0.81
            )
            self.assertAlmostEqual(
                diagnosis["raw_area_ratio_left_to_right"], 2400 / 2500
            )


if __name__ == "__main__":
    unittest.main()
