import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from analyze_field_recording import (  # noqa: E402
    automatic_status,
    ensure_output_paths,
    safe_extract_archive,
    summarize_session_integrity,
)


class FieldRecordingAnalysisTest(unittest.TestCase):
    def test_safe_extracts_regular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "recording.tar.xz"
            payload = b"frame,time_sec\n1,0.0\n"
            with tarfile.open(archive_path, mode="w:xz") as archive:
                info = tarfile.TarInfo("trial/detections.csv")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            destination = root / "output"
            safe_extract_archive(archive_path, destination, 1024)

            self.assertEqual(
                (destination / "trial" / "detections.csv").read_bytes(), payload
            )

    def test_rejects_parent_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "unsafe.tar.xz"
            with tarfile.open(archive_path, mode="w:xz") as archive:
                info = tarfile.TarInfo("../outside.txt")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))

            with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                safe_extract_archive(archive_path, root / "output", 1024)

            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_archive_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "unsafe.tar.xz"
            with tarfile.open(archive_path, mode="w:xz") as archive:
                info = tarfile.TarInfo("trial/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                archive.addfile(info)

            with self.assertRaisesRegex(ValueError, "links are not allowed"):
                safe_extract_archive(archive_path, root / "output", 1024)

    def test_enforces_extraction_size_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "large.tar.xz"
            with tarfile.open(archive_path, mode="w:xz") as archive:
                info = tarfile.TarInfo("trial/raw.avi")
                info.size = 5
                archive.addfile(info, io.BytesIO(b"12345"))

            with self.assertRaisesRegex(ValueError, "extraction limit"):
                safe_extract_archive(archive_path, root / "output", 4)

    def test_refuses_to_overwrite_existing_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "live_summary.csv").write_text("existing")

            with self.assertRaisesRegex(FileExistsError, "--overwrite"):
                ensure_output_paths(output_dir, overwrite=False)

            paths = ensure_output_paths(output_dir, overwrite=True)
            self.assertIn("analysis_report.md", paths)

    def test_diagnostic_requires_predefined_requirements_for_pass(self):
        integrity = [{"decision": "PASS"}]
        timing = [{"fps_within_one_percent": 1}]

        status, reasons = automatic_status(
            True, integrity, timing, [], "raw_ground_distance", None
        )

        self.assertEqual(status, "DIAGNOSTIC")
        self.assertIn("no predefined requirement", reasons[0])

    def test_requirement_failure_produces_fail(self):
        status, reasons = automatic_status(
            True,
            [{"decision": "PASS"}],
            [{"fps_within_one_percent": 1}],
            [],
            "raw_ground_distance",
            [{"result": "FAIL"}],
        )

        self.assertEqual(status, "FAIL")
        self.assertTrue(reasons)

    def test_selected_gate_failure_produces_fail(self):
        status, reasons = automatic_status(
            True,
            [{"decision": "PASS"}],
            [{"fps_within_one_percent": 1}],
            [
                {
                    "normalization_mode": "raw_ground_distance",
                    "decision": "FAIL",
                },
                {"normalization_mode": "forward_z", "decision": "PASS"},
            ],
            "raw_ground_distance",
            None,
        )

        self.assertEqual(status, "FAIL")
        self.assertIn("raw_ground_distance observation gate failed", reasons)

    def test_dynamic_ttc_failure_produces_fail(self):
        status, reasons = automatic_status(
            True,
            [{"decision": "PASS"}],
            [{"fps_within_one_percent": 1}],
            [],
            "raw_ground_distance",
            [{"result": "PASS"}],
            [{"decision": "FAIL"}],
        )

        self.assertEqual(status, "FAIL")
        self.assertIn("one or more fixed dynamic TTC conditions failed", reasons)

    def test_dynamic_session_is_excluded_from_static_gate_decision(self):
        status, reasons = automatic_status(
            True,
            [{"decision": "PASS"}],
            [{"fps_within_one_percent": 1}],
            [
                {
                    "session": "approach_trial",
                    "normalization_mode": "raw_ground_distance",
                    "decision": "FAIL",
                }
            ],
            "raw_ground_distance",
            [{"result": "PASS"}],
            [{"session": "approach_trial", "decision": "PASS"}],
        )

        self.assertEqual(status, "PASS")
        self.assertNotIn("raw_ground_distance observation gate failed", reasons)

    def test_static_session_still_requires_gate_pass_in_mixed_archive(self):
        status, reasons = automatic_status(
            True,
            [{"decision": "PASS"}],
            [{"fps_within_one_percent": 1}],
            [
                {
                    "session": "approach_trial",
                    "normalization_mode": "raw_ground_distance",
                    "decision": "FAIL",
                },
                {
                    "session": "static_trial",
                    "normalization_mode": "raw_ground_distance",
                    "decision": "FAIL",
                },
            ],
            "raw_ground_distance",
            [{"result": "PASS"}],
            [{"session": "approach_trial", "decision": "PASS"}],
        )

        self.assertEqual(status, "FAIL")
        self.assertIn("raw_ground_distance observation gate failed", reasons)

    def test_integrity_requires_all_three_videos(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "trial"
            session.mkdir()
            (session / "metadata.json").write_text("{}")
            (session / "detections.csv").write_text(
                "frame,time_sec,monotonic_time_sec\n1,0.0,0.0\n"
            )
            row = summarize_session_integrity(session, "archive.tar.xz")

            self.assertEqual(row["required_files_complete"], 0)
            self.assertEqual(row["video_counts_match"], 0)
            self.assertEqual(row["decision"], "FAIL")


if __name__ == "__main__":
    unittest.main()
