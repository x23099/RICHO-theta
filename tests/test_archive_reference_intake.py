"""Synthetic archive safety/provenance tests; no submitted data extraction."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "archive_reference_intake",
    ROOT/"Experimental_results/2026-11-09/archive_reference_intake_r01/inspect_archives.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
BATCH_SPEC = importlib.util.spec_from_file_location(
    "complete_archive_intake",
    ROOT/"Experimental_results/2026-11-09/archive_reference_intake_r01/inspect_complete_batch.py")
batch = importlib.util.module_from_spec(BATCH_SPEC)
BATCH_SPEC.loader.exec_module(batch)


def add_member(tar, name, data):
    member = tarfile.TarInfo(name); member.size = len(data)
    tar.addfile(member, io.BytesIO(data))


class ArchiveReferenceIntakeTests(unittest.TestCase):
    def test_unsafe_paths_refused(self):
        for name in ("/tmp/payload", "a/../payload", "..\\payload"):
            with self.assertRaises(ValueError):
                audit.safe_member_name(name)

    def test_synthetic_and_logs_not_mislabeled_camera_evidence(self):
        self.assertEqual(audit.classify("run/verification/SYNTHETIC_preview.png"), "synthetic_image_NOT_camera_evidence")
        self.assertEqual(audit.classify("run/decoded_session_f000001.png"), "native_decoded_camera_png_candidate")
        self.assertEqual(audit.classify("run/distance_frames.jsonl"), "structured_log_NOT_video")
        self.assertEqual(audit.classify("run/raw.avi"), "video_candidate")

    def test_regular_member_matches_existing_bytes_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); reference = root/"reference"; reference.mkdir()
            (reference/"known.json").write_bytes(b"synthetic-existing-data")
            archive = root/"data.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                add_member(tar, "known.json", b"synthetic-existing-data")
                add_member(tar, "unknown.json", b"not-extracted")
            with patch.object(audit, "ROOT", root):
                rows = audit.inspect_archive(archive, reference, {})
            self.assertEqual([r["relation"] for r in rows], ["same_as_existing_file", "not_in_existing_target_folder"])
            self.assertFalse((reference/"unknown.json").exists())

    def test_existing_filename_does_not_hide_changed_member_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); reference = root/"reference"; reference.mkdir()
            (reference/"known.json").write_bytes(b"old")
            archive = root/"data.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                add_member(tar, "known.json", b"new")
            with patch.object(audit, "ROOT", root):
                rows = audit.inspect_archive(archive, reference, {})
            self.assertEqual(rows[0]["relation"], "different_from_existing_file")
            self.assertEqual((reference/"known.json").read_bytes(), b"old")

    def test_symbolic_archive_member_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root/"data.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                member = tarfile.TarInfo("link"); member.type = tarfile.SYMTYPE; member.linkname = "/tmp/no-extraction"
                tar.addfile(member)
            with self.assertRaisesRegex(ValueError, "nonregular"):
                audit.inspect_archive(archive, root, {})

    def test_duplicate_regular_member_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root/"data.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                add_member(tar, "one.json", b"first")
                add_member(tar, "one.json", b"second")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                audit.inspect_archive(archive, root, {})

    def test_completed_batch_counts_repeated_names_not_upload_versions(self):
        from collections import Counter
        counts = Counter(batch.BATCH_ONE+batch.BATCH_TWO+batch.BATCH_THREE)
        self.assertEqual(sum(counts.values()), 23)
        self.assertEqual(len(counts), 14)
        self.assertEqual(sum(value > 1 for value in counts.values()), 9)

    def test_renamed_native_copy_requires_matching_camera_hash(self):
        row = dict(kind="other_image_requires_provenance", member="report_assets/upper_support_b559e424_f035562.png",
                   sha256="1"*64)
        self.assertEqual(batch.image_role(row, {"1"*64}), "native_camera_png_byte_copy")
        self.assertEqual(batch.image_role(row, set()), "image_role_unresolved")


if __name__ == "__main__":
    unittest.main()
