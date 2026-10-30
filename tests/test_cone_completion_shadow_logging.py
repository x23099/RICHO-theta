"""Completion logging remains non-controlling; synthetic pixels only."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import ConeDistanceEngine, DEFAULT_CONFIG
from cone_distance_worker import DistanceWorker
from run_cone_distance_live import build_parser
from summarize_cone_distance_live import summarize, validate_row
from theta_rtc_frames import LatestNativeFrame, NativeFrame


class ContiguousSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "Experimental_results/2026-10-30/cone_completion_logging_r01/replay_contiguous.py"
        spec = importlib.util.spec_from_file_location("logging_contiguous_metrics", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def spans(self, available):
        return self.module.point_spans([dict(frame=i+1, new_point=[3, 4] if point else None)
                                       for i, point in enumerate(available)], "new")

    def test_empty_has_no_missing_span(self):
        self.assertEqual(self.spans([]), [])

    def test_last_available_has_no_inverted_span(self):
        self.assertEqual(self.spans([True, True]), [])
        self.assertEqual(self.spans([False, True]), [[1, 1]])

    def test_all_missing_is_one_inclusive_span(self):
        self.assertEqual(self.spans([False, False, False]), [[1, 3]])

    def test_interior_and_final_missing_are_separate(self):
        self.assertEqual(self.spans([True, False, False, True, False]), [[2, 3], [5, 5]])

BOX = dict(x1=301., y1=305., x2=339., y2=405., confidence=.9, class_id=0)
WIDE = dict(BOX, x1=290., x2=350.)


def image():
    pixels = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(pixels, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
    return pixels


def reportable(row):
    return dict(row, predict_ms=0., support_geometry_ms=0., cone_service_ms=0.,
                inference_source="injected_predictor_not_verified_cuda")


class CompletionLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "Experimental_results/2026-10-30/cone_completion_logging_r01/source_snapshot/cone_distance_core.py"
        module = types.ModuleType("completion_reference_core")
        module.__file__ = str(ROOT / "src/cone_distance_core.py")
        sys.modules[module.__name__] = module
        exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
        cls.Reference = module.ConeDistanceEngine

    def engines(self, old_shadow=False):
        engines = (self.Reference(DEFAULT_CONFIG, colour_support_shadow=old_shadow),
                   ConeDistanceEngine(DEFAULT_CONFIG, colour_support_shadow=old_shadow, support_completion_shadow=True))
        for engine in engines:
            engine.reset("synthetic")
        return engines

    def strip_new_fields(self, row, old_shadow=False):
        row = dict(row)
        row.pop("support_completion_shadow")
        if not old_shadow:
            row.pop("selected_detector_boxes")
        return row

    def test_default_engine_has_no_completion_field(self):
        engine = ConeDistanceEngine()
        engine.reset("synthetic")
        result = engine.measure(NativeFrame("synthetic", 1, 0., 0., image()), [BOX], .01)
        self.assertNotIn("support_completion_shadow", result)
        self.assertNotIn("selected_detector_boxes", result)

    def test_default_matches_byte_frozen_engine_results(self):
        reference, _ = self.engines()
        current = ConeDistanceEngine()
        current.reset("synthetic")
        for index in range(1, 5):
            frame = NativeFrame("synthetic", index, index/30, index/30, image())
            self.assertEqual(reference.measure(frame, [WIDE], index/30+.01), current.measure(frame, [WIDE], index/30+.01))

    def test_completion_point_does_not_grant_distance_or_pose(self):
        reference, current = self.engines()
        frame = NativeFrame("synthetic", 1, 0., 0., image())
        old = reference.measure(frame, [BOX], .01)
        new = current.measure(frame, [BOX], .01)
        self.assertTrue(new["support_completion_shadow"]["candidate"]["completion_granted"])
        self.assertEqual(new["support_completion_shadow"]["candidate"]["point"], [320, 400])
        self.assertFalse(new["distance_available"])
        self.assertFalse(new["scene_initialized"])
        self.assertEqual(old, self.strip_new_fields(new))

    def test_existing_colour_shadow_is_independent_and_preserved(self):
        reference, current = self.engines(old_shadow=True)
        frame = NativeFrame("synthetic", 1, 0., 0., image())
        old, new = [engine.measure(frame, [BOX], .01) for engine in (reference, current)]
        self.assertIsNone(new["colour_support_shadow"]["candidate"]["point"])
        self.assertIsNotNone(new["support_completion_shadow"]["candidate"]["point"])
        self.assertEqual(old, self.strip_new_fields(new, old_shadow=True))

    def test_flags_require_real_bools(self):
        for value in (0, 1, None, "yes"):
            with self.assertRaises(ValueError):
                ConeDistanceEngine(support_completion_shadow=value)

    def test_missing_multiple_and_invalid_boxes_never_log_completion_point(self):
        for boxes in ([], [BOX, WIDE], [dict(BOX, confidence=float("nan"))]):
            _, current = self.engines()
            row = current.measure(NativeFrame("synthetic", 1, 0., 0., image()), boxes, .01)
            self.assertIsNone(row["support_completion_shadow"]["candidate"])
            self.assertFalse(row["distance_available"])

    def test_completion_failure_is_not_detector_failure(self):
        reference, current = self.engines()
        frame = NativeFrame("synthetic", 1, 0., 0., image())
        expected = reference.measure(frame, [WIDE], .01)
        with patch("cone_support_completion_candidate.observe_lateral_completion", side_effect=RuntimeError("test only")):
            row = current.measure(frame, [WIDE], .01)
        self.assertEqual(row["support_completion_shadow"]["candidate"]["reason"], "completion_shadow_observation_error")
        self.assertNotIn("invalid_detector_output", row["blockers"])
        self.assertEqual(expected, self.strip_new_fields(row))
        validate_row(reportable(row))

    def test_completion_cost_can_withhold_stale_frame_not_extend_freshness(self):
        _, current = self.engines()
        clock = [0.]
        from cone_support_completion_candidate import observe_lateral_completion
        def delayed(*args):
            result = observe_lateral_completion(*args)
            clock[0] = .6
            return result
        with patch("cone_support_completion_candidate.observe_lateral_completion", side_effect=delayed):
            row = current.measure(NativeFrame("synthetic", 1, 0., 0., image()), [BOX], lambda: clock[0])
        self.assertIn("frame_processing_too_old", row["blockers"])
        self.assertFalse(row["distance_available"])
        self.assertEqual(row["frame_age_ms"], 600)

    def test_initialized_pose_does_not_adopt_completion_point(self):
        reference, current = self.engines()
        for engine in (reference, current):
            for i in range(4):
                frame = NativeFrame("synthetic", i*30+1, float(i), float(i), image())
                ticket = engine.begin_scene(frame)
                engine.complete_scene(ticket, dict(accepted=True, reason="synthetic_only", up=engine.prior_up.tolist()), i+.1)
        for i in range(5):
            t = 3.1+i*.03
            frame = NativeFrame("synthetic", 100+i, t, t, image())
            old, new = [engine.measure(frame, [BOX], t+.01) for engine in (reference, current)]
            self.assertTrue(new["scene_initialized"])
            self.assertFalse(new["distance_available"])
            self.assertEqual(old, self.strip_new_fields(new))

    def test_worker_serializes_completion_flag_and_original_bbox(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = LatestNativeFrame()
            slot.begin("synthetic")
            slot.publish("synthetic", image(), 0., 10.)
            path = Path(directory) / "distance_frames.jsonl"
            worker = DistanceWorker(slot, DEFAULT_CONFIG, lambda _: [BOX], path, clock=lambda: 10.,
                support_completion_shadow=True, scene_function=lambda *args: dict(accepted=False, reason="synthetic_only"))
            worker.start()
            try:
                self.assertTrue(worker.updated.wait(1))
            finally:
                worker.close()
            row = json.loads(path.read_text().splitlines()[0])
            self.assertTrue(row["support_completion_shadow"]["candidate"]["completion_granted"])
            self.assertNotIn("colour_support_shadow", row)
            self.assertEqual(row["selected_detector_boxes"][0]["x1"], BOX["x1"])
            self.assertFalse(row["distance_available"])
            summary = summarize(Path(directory), Path(directory) / "report", plots=False)
            self.assertEqual(summary["support_completion_shadow"]["completion_granted_frames"], 1)
            self.assertEqual(summary["conditional_output_frames"], 0)
            self.assertEqual(summary["status"], "INCOMPLETE_CAPTURE")

    def test_cli_completion_flag_is_opt_in_and_not_old_flag(self):
        base = ["--weights", "unused.pt", "--output-dir", "unused"]
        self.assertFalse(build_parser().parse_args(base).support_completion_shadow)
        args = build_parser().parse_args([*base, "--support-completion-shadow"])
        self.assertTrue(args.support_completion_shadow)
        self.assertFalse(args.colour_support_shadow)

    def sample_row(self):
        _, engine = self.engines()
        return reportable(engine.measure(NativeFrame("synthetic", 1, 0., 0., image()), [BOX], .01))

    def test_report_rejects_controlling_or_verified_wrapper(self):
        for field in ("controlling_distance", "physical_metric_verified", "usable_for_ffb"):
            row = self.sample_row()
            row["support_completion_shadow"][field] = True
            with self.assertRaises(ValueError):
                validate_row(row)

    def test_report_rejects_controlling_or_verified_candidate(self):
        for field in ("controlling_distance", "physical_metric_verified", "floor_contact_verified", "usable_for_ffb"):
            row = self.sample_row()
            row["support_completion_shadow"]["candidate"][field] = True
            with self.assertRaises(ValueError):
                validate_row(row)

    def test_report_requires_actual_support_point(self):
        row = self.sample_row()
        row["support_completion_shadow"]["candidate"]["point"] = [1, 1]
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_report_rejects_grant_without_attempt_or_point(self):
        for change in (dict(completion_attempted=False), dict(point=None), dict(completion_granted=1)):
            row = self.sample_row()
            row["support_completion_shadow"]["candidate"].update(change)
            with self.assertRaises(ValueError):
                validate_row(row)

    def test_completion_only_report_does_not_count_point_as_distance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self.sample_row()
            (root / "distance_frames.jsonl").write_text(json.dumps(row)+"\n")
            summary = summarize(root, root / "report", plots=False)
            self.assertEqual(summary["support_completion_shadow"]["unverified_image_point_frames"], 1)
            self.assertEqual(summary["conditional_output_frames"], 0)
            self.assertFalse(summary["physical_metric_verified"])
            self.assertIn("左右枠接触", (root / "report/report.md").read_text())


if __name__ == "__main__":
    unittest.main()
