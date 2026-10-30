"""Synthetic-only fixed-floor comparison integration; no physical approval."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import ConeDistanceEngine, load_config
from cone_fixed_floor_shadow import FixedFloorShadow, enforce_freshness, load_bundle
from cone_distance_worker import DistanceWorker
from run_cone_distance_live import build_parser
from summarize_cone_distance_live import summarize, validate_row
from theta_rtc_frames import LatestNativeFrame, NativeFrame

ORIGINAL_BUNDLE = ROOT / "Experimental_results/2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/explicit_floor_models.json"
BOX = dict(x1=290., y1=305., x2=350., y2=405., confidence=.95, class_id=0)


def image():
    pixels = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(pixels, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
    return pixels


class FixedFloorShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bundle = json.loads(ORIGINAL_BUNDLE.read_text())
        self.bundle["session"] = "synthetic"
        for model in self.bundle["models"]:
            model["session"] = "synthetic"
        self.path = self.directory / "models.json"
        self.write_bundle()

    def write_bundle(self):
        self.path.write_text(json.dumps(self.bundle))

    def engine(self, **kwargs):
        engine = ConeDistanceEngine(colour_support_shadow=True, support_completion_shadow=True,
                                   fixed_floor_models=self.path, **kwargs)
        engine.reset("synthetic")
        return engine

    def measured(self, engine=None, age=.01, boxes=None, count=3):
        engine = engine or self.engine()
        result = None
        for number in range(1, count+1):
            timestamp=number/30
            result = engine.measure(NativeFrame(engine.session, number, timestamp, timestamp, image()),
                                    [BOX] if boxes is None else boxes, timestamp+age)
        return result

    def reportable(self, row):
        return dict(row, predict_ms=0., support_geometry_ms=0., cone_service_ms=0.,
                    inference_source="injected_predictor_not_verified_cuda")

    def test_default_disabled(self):
        engine = ConeDistanceEngine()
        engine.reset("synthetic")
        self.assertNotIn("fixed_floor_shadow", self.measured(engine))

    def test_existing_decisions_match_frozen_preintegration_engine(self):
        path = ROOT / "Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/source_snapshot/cone_distance_core.py"
        module = types.ModuleType("fixed_shadow_reference")
        module.__file__ = str(ROOT / "src/cone_distance_core.py")
        sys.modules[module.__name__] = module
        exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
        old = module.ConeDistanceEngine(colour_support_shadow=True, support_completion_shadow=True)
        old.reset("synthetic")
        new = self.engine()
        for number in range(1, 5):
            frame = NativeFrame("synthetic", number, number/30, number/30, image())
            expected = old.measure(frame, [BOX], number/30+.01)
            actual = new.measure(frame, [BOX], number/30+.01)
            actual.pop("fixed_floor_shadow")
            self.assertEqual(expected, actual)

    def test_three_confirmations_and_all_models_not_winner(self):
        first = self.measured(count=1)["fixed_floor_shadow"]
        self.assertFalse(any(m["range_available"] for m in first["models"]))
        result = self.measured()
        self.assertTrue(all(m["range_available"] for m in result["fixed_floor_shadow"]["models"]))
        self.assertEqual(len(result["fixed_floor_shadow"]["models"]), 3)
        self.assertFalse(result["distance_available"])
        self.assertFalse(result["scene_initialized"])

    def test_session_mismatch_never_calls_geometry(self):
        from unittest.mock import patch
        engine = self.engine()
        engine.reset("different")
        with patch("cone_fixed_floor_shadow.measure_support", side_effect=AssertionError("must not calculate")):
            shadow = self.measured(engine)["fixed_floor_shadow"]
        self.assertEqual(shadow["reason"], "model_session_mismatch")
        self.assertTrue(all(m["horizontal_camera_foot_range_m"] is None for m in shadow["models"]))

    def test_no_support_and_baseline_selection_do_not_fallback(self):
        no_target = self.measured(boxes=[])["fixed_floor_shadow"]
        self.assertEqual(no_target["reason"], "support_point_unavailable")
        engine = self.engine(fixed_floor_support_source="baseline")
        narrow = dict(BOX, x1=301., x2=339.)
        result = self.measured(engine, boxes=[narrow])
        self.assertIsNotNone(result["support_completion_shadow"]["candidate"]["point"])
        self.assertIsNone(result["fixed_floor_shadow"]["support_pixel"])

    def test_reset_loses_quality_confirmation(self):
        engine = self.engine()
        self.measured(engine)
        engine.reset("synthetic")
        self.assertFalse(self.measured(engine, count=1)["fixed_floor_shadow"]["image_quality_accepted"])

    def test_late_engine_and_worker_completion_revoke_comparison_numbers(self):
        shadow = self.measured(age=.51)["fixed_floor_shadow"]
        self.assertEqual(shadow["reason"], "frame_processing_too_old")
        self.assertFalse(any(m["range_available"] for m in shadow["models"]))
        shadow = self.measured()["fixed_floor_shadow"]
        enforce_freshness(shadow, 501.)
        enforce_freshness(shadow, 1.)  # Can never re-enable revoked values.
        self.assertTrue(all(m["horizontal_camera_foot_range_m"] is None for m in shadow["models"]))

    def test_support_source_needs_explicit_shadow_flag(self):
        with self.assertRaises(ValueError):
            ConeDistanceEngine(fixed_floor_models=self.path)
        with self.assertRaises(ValueError):
            self.engine(fixed_floor_support_source="auto")

    def test_comparison_exception_is_logged_without_changing_baseline(self):
        from unittest.mock import patch
        engine = self.engine()
        with patch.object(engine.fixed_floor_shadow, "observe", side_effect=RuntimeError("injected")):
            row = self.measured(engine)
        self.assertEqual(row["fixed_floor_shadow"]["reason"], "fixed_floor_shadow_error")
        self.assertFalse(row["distance_available"])
        self.assertNotIn("invalid_detector_output", row["blockers"])
        validate_row(self.reportable(row))

    def test_heading_hash_mismatch_rejected(self):
        self.bundle["heading_reference"]["sha256"] = "0"*64
        self.write_bundle()
        with self.assertRaises(ValueError):
            self.engine()

    def test_duplicate_name_and_mixed_session_refused(self):
        for field, value in (("name", self.bundle["models"][0]["name"]), ("session", "other")):
            original = copy.deepcopy(self.bundle)
            self.bundle["models"][1][field] = value
            self.write_bundle()
            with self.assertRaises(ValueError):
                self.engine()
            self.bundle = original

    def test_physical_approval_refused(self):
        self.bundle["models"][0]["physical_metric_verified"] = True
        self.write_bundle()
        with self.assertRaises(ValueError):
            self.engine()

    def test_report_counts_separate_from_distance(self):
        row = self.reportable(self.measured())
        validate_row(row)
        source = self.directory / "log"
        source.mkdir()
        (source / "distance_frames.jsonl").write_text(json.dumps(row)+"\n")
        summary = summarize(source, self.directory / "report", plots=False)
        self.assertEqual(summary["conditional_output_frames"], 0)
        self.assertEqual(summary["fixed_floor_shadow"]["frames_with_comparison_range"], 1)
        self.assertEqual(summary["status"], "INCOMPLETE_CAPTURE")

    def test_report_rejects_authority_and_wrong_frame_or_source(self):
        row = self.reportable(self.measured())
        for key, value in (("controlling_distance", True), ("frame", 999), ("support_pixel", [319, 400])):
            bad = copy.deepcopy(row)
            bad["fixed_floor_shadow"][key] = value
            with self.assertRaises(ValueError):
                validate_row(bad)

    def test_report_rejects_session_mismatch_and_stale_numeric_range(self):
        for key, value in (("model_session", "other"),):
            row = self.reportable(self.measured())
            row["fixed_floor_shadow"][key] = value
            with self.assertRaises(ValueError):
                validate_row(row)
        row = self.reportable(self.measured(age=.51))
        row["fixed_floor_shadow"]["models"][0].update(range_available=True, horizontal_camera_foot_range_m=1.)
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_worker_and_cli_forward_explicit_flags(self):
        slot = LatestNativeFrame()
        worker = DistanceWorker(slot, ROOT / "src/cone_distance_diagnostic_config.json", lambda _: [],
            self.directory / "worker.jsonl", support_completion_shadow=True, fixed_floor_models=self.path)
        self.addCleanup(worker.close)
        self.assertEqual(worker.engine.fixed_floor_shadow.bundle["session"], "synthetic")
        parsed = build_parser().parse_args(["--weights", "not-loaded.pt", "--output-dir", "unused",
                                           "--fixed-floor-models", str(self.path)])
        self.assertEqual(parsed.fixed_floor_models, self.path)
        self.assertIsNone(build_parser().parse_args(["--weights", "x", "--output-dir", "y"]).fixed_floor_models)


if __name__ == "__main__":
    unittest.main()
