"""Read-only checks of the saved native paper audit and fitting separation."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]/"src"))
sys.path.insert(0, str(HERE.parent/"cone_geometry_candidates_r01"))
from cone_dataset import read_csv, sha256
from geometry_models import fit_model, project_floor_to_pixels, project_pixels_to_floor

spec = importlib.util.spec_from_file_location("paper7_audit_module", HERE/"analyze.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class Paper7AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = HERE/"analysis_r01"
        cls.intake = json.loads((HERE/"intake_summary.json").read_text())
        cls.provenance = json.loads((cls.output/"provenance.json").read_text())
        cls.points = read_csv(cls.output/"reference_points_primary170.csv")

    def test_complete_frame_ledger_and_no_duplicate_observations(self):
        source = read_csv(Path(self.intake["session"])/"detections.csv")
        ledger = read_csv(self.output/"frame_ledger.csv")
        self.assertEqual(len(source), 7650)
        self.assertEqual([(r["frame"], float(r["time_sec"])) for r in source],
                         [(r["frame"], float(r["time_sec"])) for r in ledger])
        obs = read_csv(self.output/"corner_candidates.csv")
        counts = Counter(r["frame"] for r in obs)
        self.assertTrue(all(v == 3 for v in counts.values()))
        self.assertEqual(len({(r["frame"], r["threshold"]) for r in obs}), len(obs))
        for row in ledger:
            expected = row["phase"] in {p[0] for p in audit.POSES}
            self.assertEqual(row["frame"] in counts, expected)

    def test_roles_and_disjoint_windows_are_fixed(self):
        self.assertEqual({r["point_id"] for r in self.points},
                         {"C080","C130","C200","L130","R130","H100","H160"})
        for index, left in enumerate(audit.POSES):
            for right in audit.POSES[index+1:]:
                self.assertTrue(left[2] < right[1] or right[2] < left[1])
        self.assertEqual({r["point_id"] for r in self.points if r["role"] == "diagnostic"},
                         {"C080","C130","C200","L130","R130"})
        self.assertEqual({r["point_id"] for r in self.points if r["role"] == "held_out_from_future_fit"},
                         {"H100","H160"})

    def test_primary_medians_recompute_from_saved_observations(self):
        obs = read_csv(self.output/"corner_candidates.csv")
        for point in self.points:
            selected = [r for r in obs if r["phase"] == point["point_id"]
                        and r["threshold"] == "170" and r["corner_candidate"] == "True"]
            self.assertEqual(len(selected), int(point["candidate_frames"]))
            for axis in ("x", "y"):
                self.assertEqual(float(point["pixel_"+axis]), np.median([float(r["pixel_"+axis]) for r in selected]))
            self.assertEqual(point["usable_for_ffb"], "False")

    def test_fit_reproduces_and_rejects_holdouts(self):
        fitted = json.loads((self.output/"centre2_offline_candidate.json").read_text())
        base = dict(self.intake["metadata"]["parameters"], camera_height=.59)
        train = [r for r in self.points if r["role"] == "diagnostic"]
        recomputed = fit_model(train, base, "centre2")
        self.assertEqual(fitted["fit_ids"], [r["point_id"] for r in train])
        self.assertEqual(fitted["free_parameters"], ["front_cx_offset","front_cy_offset"])
        for key in fitted["free_parameters"]:
            self.assertAlmostEqual(fitted["parameters"][key], recomputed["parameters"][key], places=8)
        with self.assertRaises(ValueError):
            fit_model(self.points, base, "centre2")
        self.assertFalse(self.provenance["holdouts_in_solver"])

    def test_projection_formula_roundtrip_for_all_seven_points(self):
        fitted = json.loads((self.output/"centre2_offline_candidate.json").read_text())
        worlds = np.array([[float(r["reference_x_m"]),float(r["reference_z_m"])] for r in self.points])
        base = {key:self.intake["metadata"]["parameters"][key] for key in audit.CAMERA_KEYS}
        for p in (base, dict(base,camera_height=.59), fitted["parameters"]):
            np.testing.assert_allclose(project_pixels_to_floor(project_floor_to_pixels(worlds,p),p), worlds,
                                       rtol=0, atol=1e-6)

    def test_native_image_dimensions_and_pixel_hashes(self):
        files = []
        for name in ("raw_sample_manifest.csv", "interval_review_manifest.csv"):
            for row in read_csv(HERE/name):
                path = HERE/row["file"]
                raw = cv2.imread(str(path))
                self.assertEqual(raw.shape, (720,1280,3))
                self.assertEqual(sha256(path), row["png_sha256"])
                self.assertEqual(hashlib.sha256(raw.tobytes()).hexdigest(), row["decoded_bgr_sha256"])
                files.append(path)
        self.assertEqual(len(files), 51)

    def test_source_and_analysis_hashes_unchanged(self):
        for path,digest in self.provenance["source_sha256"].items():
            self.assertEqual(sha256(Path(path)), digest, path)
        for name,digest in self.provenance["output_sha256"].items():
            self.assertEqual(sha256(self.output/name), digest, name)
        self.assertFalse(self.provenance["physical_output"])
        self.assertFalse(self.provenance["production_settings_changed"])
        self.assertFalse(self.provenance["usable_for_ffb"])


if __name__ == "__main__":
    unittest.main()
