import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from inventory_recording_archives import discover_archives, inspect_archive


class RecordingArchiveInventoryTest(unittest.TestCase):
    def test_inventory_reads_tar_xz_without_extracting(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive_path = Path(temporary_dir) / "recording.tar.xz"
            with tarfile.open(archive_path, mode="w:xz") as archive:
                for name, content in (
                    ("trial/metadata.json", b"{}"),
                    ("trial/detections.csv", b"detected\n1\n"),
                    ("trial/raw.avi", b"video"),
                    ("partial/raw.avi", b"video"),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))

            row = inspect_archive(archive_path)

            self.assertEqual(row["tar_xz_status"], "PASS")
            self.assertEqual(row["recording_sessions"], 2)
            self.assertEqual(row["complete_core_sessions"], 1)
            self.assertEqual(row["metadata_sessions"], 1)
            self.assertEqual(row["detections_sessions"], 1)
            self.assertEqual(
                row["sha256"], hashlib.sha256(archive_path.read_bytes()).hexdigest()
            )
            self.assertEqual(discover_archives([Path(temporary_dir)]), [archive_path])


if __name__ == "__main__":
    unittest.main()
