import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from register_recording_archive import (  # noqa: E402
    load_manifest,
    register_archive,
    validate_dataset_id,
)


class RecordingArchiveRegistrationTest(unittest.TestCase):
    @staticmethod
    def _make_archive(path):
        payload = b"recording metadata"
        with tarfile.open(path, "w:xz") as archive:
            info = tarfile.TarInfo("trial/metadata.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    def test_registers_and_updates_an_archive_without_losing_drive_state(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive = root / "recording.tar.xz"
            manifest = root / "manifest.csv"
            self._make_archive(archive)

            first = register_archive(
                manifest,
                "p0b-static-20260818",
                archive,
                captured_date="2026-08-18",
                experiment_stage="P0-B",
            )
            updated = register_archive(
                manifest,
                "p0b-static-20260818",
                archive,
                drive_path=(
                    "RICHO-theta-recordings/raw/2026-08-18/recording.tar.xz"
                ),
            )

            self.assertEqual(first["integrity_status"], "tar_xz_pass")
            self.assertEqual(first["archive_members"], 1)
            self.assertEqual(len(first["sha256"]), 64)
            self.assertEqual(updated["captured_date"], "2026-08-18")
            self.assertNotEqual(updated["uploaded_at_utc"], "")
            self.assertEqual(len(load_manifest(manifest)), 1)

    def test_rejects_invalid_dataset_id(self):
        with self.assertRaises(ValueError):
            validate_dataset_id("P0-B/2026-08-18")


if __name__ == "__main__":
    unittest.main()
