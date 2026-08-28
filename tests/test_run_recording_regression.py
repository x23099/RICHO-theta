import argparse
import csv
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from register_recording_archive import sha256_file  # noqa: E402
from run_recording_regression import (  # noqa: E402
    SUITE_FIELDS,
    build_report,
    find_archive,
    load_regression_suite,
    run_dataset,
    select_datasets,
)


def dataset(**overrides):
    row = {
        "dataset_id": "static-example",
        "enabled": "1",
        "config_path": "src/bird_eye_config_raw_ground_distance.json",
        "labels_path": "",
        "requirements_path": (
            "Experimental_results/2026-08-26_1700_regression_requirements.csv"
        ),
        "dynamic_ttc_profile_path": "",
        "expected_status": "PASS",
        "expected_sessions": 2,
        "expected_gate_sessions": 2,
        "expected_gate_pass_sessions": 2,
        "expected_occlusion_events": 0,
        "expected_track_expired_events": 0,
        "expected_reacquired_events": 0,
        "expected_dynamic_sessions": 0,
        "expected_dynamic_pass_sessions": 0,
        "notes": "test",
    }
    row.update(overrides)
    return row


class RecordingRegressionTest(unittest.TestCase):
    def test_loads_and_validates_suite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "suite.csv"
            with path.open("w", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=SUITE_FIELDS)
                writer.writeheader()
                writer.writerow({**dataset(), "expected_sessions": "2"})

            rows = load_regression_suite(path)

            self.assertEqual(rows[0]["expected_sessions"], 2)
            self.assertEqual(rows[0]["expected_status"], "PASS")

    def test_rejects_duplicate_dataset_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "suite.csv"
            with path.open("w", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=SUITE_FIELDS)
                writer.writeheader()
                writer.writerow({**dataset(), "expected_sessions": "2"})
                writer.writerow({**dataset(), "expected_sessions": "2"})

            with self.assertRaisesRegex(ValueError, "duplicate dataset_id"):
                load_regression_suite(path)

    def test_selects_enabled_or_explicit_datasets(self):
        rows = [dataset(), dataset(dataset_id="disabled", enabled="0")]

        self.assertEqual(
            [row["dataset_id"] for row in select_datasets(rows, [])],
            ["static-example"],
        )
        self.assertEqual(
            [row["dataset_id"] for row in select_datasets(rows, ["disabled"])],
            ["disabled"],
        )

    def test_rejects_ambiguous_archive_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "recording.tar.xz").write_bytes(b"a")
            (root / "b" / "recording.tar.xz").write_bytes(b"b")

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                find_archive("recording.tar.xz", [root])

    def test_report_marks_skipped_suite_incomplete(self):
        report = build_report(
            [
                {
                    "dataset_id": "missing",
                    "sha256_match": "",
                    "actual_status": "",
                    "actual_sessions": "",
                    "actual_gate_sessions": "",
                    "actual_gate_pass_sessions": "",
                    "actual_track_expired_events": "",
                    "actual_reacquired_events": "",
                    "actual_dynamic_sessions": "",
                    "actual_dynamic_pass_sessions": "",
                    "decision": "SKIP",
                    "reasons": "archive not found",
                }
            ]
        )

        self.assertIn("総合判定: **INCOMPLETE**", report)
        self.assertIn("## 差分または未実行", report)

    def test_hash_mismatch_fails_before_analysis(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "recording.tar.xz"
            archive.write_bytes(b"recording")
            called = []

            result = run_dataset(
                dataset(),
                {
                    "archive_filename": archive.name,
                    "size_bytes": str(archive.stat().st_size),
                    "sha256": "0" * 64,
                },
                [root],
                root / "output",
                overwrite=False,
                allow_missing=False,
                analysis_runner=lambda _args: called.append(True),
            )

            self.assertEqual(result["decision"], "FAIL")
            self.assertIn("SHA-256", result["reasons"])
            self.assertEqual(called, [])

    def test_runs_analysis_and_matches_registered_expectations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "recording.tar.xz"
            archive.write_bytes(b"recording")
            expected_sha256 = sha256_file(archive)

            def fake_analysis(args: argparse.Namespace):
                args.output_dir.mkdir(parents=True)
                with (args.output_dir / "archive_inventory.csv").open(
                    "w", newline=""
                ) as output_file:
                    writer = csv.DictWriter(output_file, fieldnames=["sha256"])
                    writer.writeheader()
                    writer.writerow({"sha256": expected_sha256})
                with (args.output_dir / "live_summary.csv").open(
                    "w", newline=""
                ) as output_file:
                    writer = csv.DictWriter(
                        output_file, fieldnames=["experiment_label"]
                    )
                    writer.writeheader()
                    writer.writerow({"experiment_label": "left"})
                    writer.writerow({"experiment_label": "right"})
                with (args.output_dir / "gate_regression.csv").open(
                    "w", newline=""
                ) as output_file:
                    writer = csv.DictWriter(
                        output_file,
                        fieldnames=[
                            "normalization_mode",
                            "decision",
                            "occlusion_events",
                            "events_track_expired",
                            "events_reacquired",
                        ],
                    )
                    writer.writeheader()
                    for _index in range(2):
                        writer.writerow(
                            {
                                "normalization_mode": "raw_ground_distance",
                                "decision": "PASS",
                                "occlusion_events": 0,
                                "events_track_expired": 0,
                                "events_reacquired": 0,
                            }
                        )
                (args.output_dir / "analysis_report.md").write_text("PASS")
                return "PASS"

            result = run_dataset(
                dataset(),
                {
                    "archive_filename": archive.name,
                    "size_bytes": str(archive.stat().st_size),
                    "sha256": expected_sha256,
                },
                [root],
                root / "output",
                overwrite=False,
                allow_missing=False,
                analysis_runner=fake_analysis,
            )

            self.assertEqual(result["decision"], "PASS")
            self.assertEqual(result["actual_sessions"], 2)
            self.assertEqual(result["actual_gate_pass_sessions"], 2)
            self.assertEqual(result["sha256_match"], 1)


if __name__ == "__main__":
    unittest.main()
