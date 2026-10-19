import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import audit
from cone_dataset import read_csv, sha256
from cone_detection_diagnostics import extract_predictions


class Tensor:
    def __init__(self, value):
        self.value = value

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.value


class AuditUnitTests(unittest.TestCase):
    def test_original_frame_table_requires_one_based_complete_frames(self):
        rows = [dict(frame=1, time_sec=.01), dict(frame=2, time_sec=.05)]
        self.assertEqual(audit.valid_frame_table(rows), [.01, .05])
        for bad in ([], rows[1:], rows + [rows[-1]], [dict(frame=1, time_sec=float("nan"))],
                    [rows[0], dict(frame=2, time_sec=.01)]):
            with self.assertRaises(ValueError):
                audit.valid_frame_table(bad)

    def test_hash_fingerprint_compares_values_not_dict_order(self):
        self.assertEqual(audit.fingerprint(dict(a=1, b=2)), audit.fingerprint(dict(b=2, a=1)))
        self.assertNotEqual(audit.fingerprint(dict(a=1)), audit.fingerprint(dict(a=2)))

    def test_intake_short_and_absolute_hash_keys_both_resolve(self):
        root = Path("/tmp/audit_test_unused_session")
        short = {name: "digest_"+name for name in ("raw.avi", "metadata.json", "detections.csv")}
        absolute = {str(root / name): digest for name, digest in short.items()}
        self.assertEqual(audit.file_hashes(dict(source_sha256=short), dict(path=str(root))), absolute)
        self.assertEqual(audit.file_hashes(dict(source_sha256=absolute), dict(path=str(root))), absolute)
        with self.assertRaises(ValueError):
            audit.file_hashes({}, dict(path=str(root)))

    def test_sample_must_equal_exact_native_decoded_frame(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        sample = dict(path="not_read_from_disk", group="synthetic_test", session="test", frame="1",
                      manifest="synthetic", source_raw_sha256="raw", png_sha256="png",
                      decoded_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest())
        with patch.object(cv2, "imread", return_value=image.copy()):
            self.assertTrue(audit.verify_sample(image, sample, "raw")["pixels_equal"])
            altered = image.copy()
            altered[0, 0] = 1
            with self.assertRaises(ValueError):
                audit.verify_sample(altered, sample, "raw")
            with self.assertRaises(ValueError):
                audit.verify_sample(image, sample, "wrong_video")

    def test_prediction_export_uses_original_coordinates_without_second_scale(self):
        result = SimpleNamespace(orig_shape=(720, 1280), boxes=SimpleNamespace(
            xyxy=Tensor([[1001., 321., 1050., 410.]]), conf=Tensor([.8]), cls=Tensor([0.])))
        image = dict(image="synthetic", width=1280, height=720)
        exported = extract_predictions(result, image)
        self.assertEqual(exported[0]["x1"], 1001.)
        self.assertEqual(exported[0]["y2"], 410.)
        result.orig_shape = (544, 960)
        with self.assertRaises(ValueError):
            extract_predictions(result, image)

    def test_paper_roi_offset_restored_to_native_coordinates(self):
        path = audit.OLD / "white_paper_visibility_r01/analyze.py"
        spec = importlib.util.spec_from_file_location("audit_paper_reader", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[390:406, 315:346] = 255
        before = image.copy()
        result = module.paper_corner(image, 170, roi=(300, 380, 70, 40))
        self.assertTrue(result["corner_candidate"])
        self.assertEqual((result["pixel_x"], result["pixel_y"]), (315, 405))
        np.testing.assert_array_equal(image, before)

    def test_recording_source_contract_and_historical_methods_match(self):
        report = audit.audit_code()
        c = report["current_contract"]
        self.assertTrue(c["cap_read_assigns_ret_frame"])
        self.assertTrue(c["records_input_frame_not_bev"])
        self.assertTrue(c["raw_writer_receives_raw_frame"])
        self.assertTrue(c["input_frame_not_reassigned"])
        self.assertEqual(c["explicit_raw_calibration_overlay_calls"], 0)
        self.assertTrue(all(r["ast_equal"] for r in report["methods"]))
        self.assertFalse(report["capture_runtime_revision_proved"])

    def test_ast_route_guard_detects_processed_view_and_inplace_overwrite(self):
        code = (audit.ROOT / "src/bird_eye.py").read_text()
        self.assertFalse(audit.raw_route_contract(code.replace("self.record_frames(frame, bev_img", "self.record_frames(bev_img, bev_img"))["records_input_frame_not_bev"])
        bad = code.replace("ret, frame = self.cap.read()", "ret, frame = self.cap.read()\n        frame[0, 0] = 0")
        self.assertFalse(audit.raw_route_contract(bad)["input_frame_not_reassigned"])

    def test_reference_sensitivity_does_not_promote_uncertain_pixels(self):
        rows, scope = audit.same_video_reference_audit()
        self.assertEqual(len(rows), 6)
        self.assertFalse(scope["exact_floor_apex_pixels_human_confirmed"])
        self.assertIn("NOT_RECORDED", scope["floor_after"])
        for r in rows:
            self.assertFalse(r["fit_eligible"] or r["pixel_gt_verified"] or r["usable_for_ffb"])
            self.assertLess(r["hypothetical_pm2px_z_min_m"], r["z_m"])
            self.assertGreater(r["hypothetical_pm2px_z_max_m"], r["z_m"])


class SavedAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = audit.HERE / "results_r01"
        cls.provenance = json.loads((cls.directory / "provenance.json").read_text())

    def test_ten_sessions_same_recorded_geometry_capture_parameters(self):
        rows = read_csv(self.directory / "sessions.csv")
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({r["geometry_fingerprint"] for r in rows}), 1)
        self.assertEqual(len({r["capture_fingerprint"] for r in rows}), 1)
        self.assertTrue(all(float(r["frame_width"]) == 1280 and float(r["frame_height"]) == 720
                            and r["fourcc_text"] == "MJPG" for r in rows))
        self.assertEqual(sum(int(r["decoded_frames"]) for r in rows), self.provenance["raw_frames_decoded"])

    def test_video_headers_distinguish_raw_from_processed(self):
        rows = read_csv(self.directory / "video_headers.csv")
        self.assertEqual(len(rows), 30)
        self.assertEqual({r["view"] for r in rows}, {"raw", "bev", "detection"})
        self.assertTrue(all(r["width"] == "1280" and r["height"] == "720" for r in rows if r["view"] == "raw"))

    def test_all_native_png_provenance_rechecked(self):
        rows = read_csv(self.directory / "native_samples.csv")
        self.assertEqual(len(rows), self.provenance["native_pngs_verified"])
        for r in rows:
            self.assertEqual(r["pixels_equal"], "True")
            image = cv2.imread(r["file"])
            self.assertEqual(image.shape, (720, 1280, 3))
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), r["decoded_bgr_sha256"])
            self.assertEqual(sha256(r["file"]), r["png_sha256"])

    def test_absent_per_frame_parameters_or_camera_internal_state_not_invented(self):
        rows = read_csv(self.directory / "sessions.csv")
        for r in rows:
            self.assertEqual(r["git_revision_recorded"], "False")
            self.assertEqual(r["geometry_per_frame_recorded"], "False")
            self.assertEqual(r["camera_serial_recorded"], "False")
            self.assertEqual(r["camera_internal_correction_state_recorded"], "False")

    def test_references_and_native_bbox_outputs_recomputed(self):
        def strings(rows):
            return [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows]
        self.assertEqual(strings(audit.same_video_reference_audit()[0]), read_csv(self.directory / "same_video_floor_sensitivity.csv"))
        self.assertEqual(strings(audit.bbox_coordinate_audit()), read_csv(self.directory / "bbox_coordinate_audit.csv"))

    def test_sources_outputs_and_production_configs_unchanged(self):
        for name, digest in self.provenance["source_sha256"].items():
            self.assertEqual(sha256(name), digest, name)
        for name, digest in self.provenance["output_sha256"].items():
            self.assertEqual(sha256(self.directory / name), digest)
        for flag in ("new_inference_or_fit", "images_edited_or_created", "runtime_changes", "physical_output", "usable_for_ffb"):
            self.assertIs(self.provenance[flag], False)


if __name__ == "__main__":
    unittest.main()
