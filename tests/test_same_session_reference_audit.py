"""Inventory-only synthetic checks; no camera image or label changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "same_session_reference_audit",
    ROOT / "Experimental_results/2026-11-09/same_session_reference_audit_r01/analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class SameSessionReferenceAuditTests(unittest.TestCase):
    def test_exact_session_and_frame_identity(self):
        path = f"somewhere/decoded_{audit.SESSIONS[0]}_f002427.png"
        self.assertEqual(audit.identity(path), (audit.SESSIONS[0], 2427))

    def test_other_session_and_derived_images_not_native_evidence(self):
        self.assertIsNone(audit.identity("decoded_other_f002427.png"))
        self.assertIsNone(audit.identity("upper_support_b559e424_f035562.png"))
        self.assertIsNone(audit.identity(f"decoded_{audit.SESSIONS[0]}_f002427.jpg"))

    def test_duplicate_paths_are_one_frame_not_extra_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for folder in ("a", "b"):
                path = Path(directory)/folder/f"decoded_{audit.SESSIONS[0]}_f002427.png"
                path.parent.mkdir(); path.write_bytes(b"synthetic-identical-bytes")
                paths.append(path)
            groups = audit.group_sources(paths)
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(next(iter(groups.values()))["paths"]), 2)

    def test_same_identity_conflicting_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for folder in ("a", "b"):
                path = Path(directory)/folder/f"decoded_{audit.SESSIONS[0]}_f002427.png"
                path.parent.mkdir(); path.write_bytes(folder.encode())
                paths.append(path)
            with self.assertRaisesRegex(ValueError, "differing PNG bytes"):
                audit.group_sources(paths)

    def test_visual_screening_is_not_human_or_metric_approval(self):
        paper = audit.observed_content(audit.SESSIONS[0], 2427)
        absent = audit.observed_content(audit.SESSIONS[0], 35562)
        self.assertEqual(paper["visual_content"], "floor_paper_visible")
        self.assertIn("not_visible", absent["visual_content"])
        self.assertFalse(paper["physical_measurements_added"])
        self.assertFalse(paper["same_pose_ground_truth_verified"])
        self.assertIn("assistant", paper["reviewed_by"])

    def test_unknown_frame_is_not_silently_classified_as_paper_absent(self):
        with self.assertRaisesRegex(ValueError, "visual screening"):
            audit.observed_content(audit.SESSIONS[0], 999999)


if __name__ == "__main__":
    unittest.main()
