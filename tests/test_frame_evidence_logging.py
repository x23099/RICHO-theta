"""Log-only same-frame evidence fields; no camera, GPU, or socket."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG, ConeDistanceEngine, observe_support
from cone_distance_worker import DistanceWorker
from summarize_cone_distance_live import summarize, validate_row
from theta_rtc_frames import LatestNativeFrame, NativeFrame
import run_cone_distance_live as live


BOX = dict(x1=290., y1=305., x2=350., y2=405., confidence=.9, class_id=0)


def cone_image():
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
    return image


def frame(sequence=1, source=10.):
    return NativeFrame("synthetic", sequence, source, source, cone_image())


def measure(engine, sequence=1, source=10., boxes=None):
    return engine.measure(frame(sequence, source), [BOX] if boxes is None else boxes, source+.01)


class EngineEvidenceTests(unittest.TestCase):
    def test_default_engine_has_no_evidence_block(self):
        engine = ConeDistanceEngine()
        engine.reset("synthetic")
        self.assertNotIn("frame_evidence", measure(engine))

    def test_evidence_block_contains_same_frame_facts(self):
        engine = ConeDistanceEngine(frame_evidence=True)
        engine.reset("synthetic")
        row = measure(engine)
        evidence = row["frame_evidence"]
        self.assertEqual(evidence["schema"], "cone_frame_evidence_v1")
        self.assertEqual(evidence["input"]["session"], "synthetic")
        self.assertEqual(evidence["input"]["frame"], 1)
        self.assertEqual(evidence["input"]["received_time_sec"], 10.)
        self.assertEqual((evidence["input"]["width"], evidence["input"]["height"]), (1280, 720))
        self.assertEqual(evidence["selected_detector_boxes"][0]["x1"], BOX["x1"])
        support = evidence["support_observation"]
        self.assertEqual(support["point"], [320, 400])
        self.assertIn(support["point"], support["support"])
        self.assertIs(support["floor_contact_verified"], False)

    def test_evidence_pose_floor_and_freshness_are_explicit(self):
        engine = ConeDistanceEngine(frame_evidence=True)
        engine.reset("synthetic")
        evidence = measure(engine)["frame_evidence"]
        pose = evidence["pose"]
        self.assertIs(pose["initialized"], False)
        self.assertIs(pose["physical_transform_verified"], False)
        self.assertIs(pose["usable_for_ffb"], False)
        floor = evidence["floor_model"]
        self.assertEqual(floor["target_frame"], "paper7_ground_reference")
        self.assertEqual(floor["config_sha256"], engine.config_sha256)
        self.assertEqual(floor["camera_candidate_sha256"], engine.settings["camera_sha256"])
        self.assertEqual(floor["floor_candidate_sha256"], engine.settings["floor_sha256"])
        fresh = evidence["freshness"]
        self.assertEqual(fresh["limit_ms"], 500.)
        self.assertAlmostEqual(fresh["age_ms"], 10.)
        self.assertIs(fresh["within_limit"], True)

    def test_evidence_does_not_change_controlling_result(self):
        plain = ConeDistanceEngine()
        evidence = ConeDistanceEngine(frame_evidence=True)
        for engine in (plain, evidence):
            engine.reset("synthetic")
        base = measure(plain)
        extended = measure(evidence)
        extended.pop("frame_evidence")
        self.assertEqual(base, extended)

    def test_evidence_requires_explicit_bool(self):
        with self.assertRaisesRegex(ValueError, "frame-evidence"):
            ConeDistanceEngine(frame_evidence="yes")

    def test_no_selected_box_is_recorded_without_bbox_substitution(self):
        engine = ConeDistanceEngine(frame_evidence=True)
        engine.reset("synthetic")
        evidence = measure(engine, boxes=[])["frame_evidence"]
        self.assertEqual(evidence["selected_detector_boxes"], [])
        self.assertIsNone(evidence["support_observation"]["point"])

    def test_mask_diagnostics_identify_the_touching_edge(self):
        image = np.zeros((720, 1280, 3), np.uint8)
        cv2.rectangle(image, (280, 320), (345, 400), (0, 0, 255), -1)
        result = observe_support(image, BOX, ConeDistanceEngine().camera, evidence=True)
        self.assertEqual(result["reason"], "colour_contour_reaches_roi_edge")
        self.assertEqual(result["crop_bounds"], [286, 301, 354, 409])
        self.assertEqual(result["mask_shape"], [68, 108])
        self.assertEqual(result["selected_contour_bounds"][0], 286)
        self.assertEqual(result["touches"], dict(left=True, top=False, right=False, bottom=False))
        self.assertEqual(result["touching_edges"], ["left"])

    def test_mask_diagnostics_are_absent_without_the_flag(self):
        result = observe_support(cone_image(), BOX, ConeDistanceEngine().camera)
        self.assertNotIn("crop_bounds", result)
        self.assertNotIn("touches", result)

    def test_engine_evidence_carries_mask_diagnostics(self):
        engine = ConeDistanceEngine(frame_evidence=True)
        engine.reset("synthetic")
        diagnostics = measure(engine)["frame_evidence"]["support_observation"]["mask_diagnostics"]
        self.assertEqual(diagnostics["mask_shape"],
                         [diagnostics["crop_bounds"][2]-diagnostics["crop_bounds"][0],
                          diagnostics["crop_bounds"][3]-diagnostics["crop_bounds"][1]])
        self.assertIn("left", diagnostics["touches"])


class WorkerAndSummaryTests(unittest.TestCase):
    def test_worker_writes_evidence_and_summary_counts_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slot = LatestNativeFrame()
            slot.begin("synthetic")
            slot.publish("synthetic", cone_image(), 0., 10.)
            log = root/"input"/"distance_frames.jsonl"
            log.parent.mkdir()
            worker = DistanceWorker(slot, DEFAULT_CONFIG,
                lambda frame: [BOX], log, clock=lambda: 10., frame_evidence=True,
                scene_function=lambda *args: dict(accepted=False, reason="synthetic_only"))
            worker.start()
            try:
                self.assertTrue(worker.updated.wait(1))
            finally:
                worker.close()
            row = json.loads(log.read_text().splitlines()[0])
            self.assertEqual(row["frame_evidence"]["input"]["frame"], row["frame"])
            self.assertEqual(row["frame_evidence"]["selected_detector_boxes"][0]["x2"], BOX["x2"])
            self.assertIs(row["usable_for_ffb"], False)

            result = summarize(log.parent, root/"report", plots=False)
            self.assertEqual(result["frame_evidence"]["recorded_frames"], 1)
            self.assertEqual(result["frame_evidence"]["frames_with_one_selected_box"], 1)
            self.assertEqual(result["frame_evidence"]["frames_with_support_point"], 1)
            self.assertIs(result["frame_evidence"]["controlling_distance"], False)
            self.assertEqual(result["frame_evidence"]["frames_with_pose_available"], 0)

    def test_worker_resyncs_freshness_to_the_logged_age(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slot = LatestNativeFrame()
            slot.begin("synthetic")
            slot.publish("synthetic", cone_image(), 0., 10.)
            clock = [10.0]
            def predictor(_frame):
                clock[0] += 0.02
                return [BOX]
            log = root/"input"/"distance_frames.jsonl"
            log.parent.mkdir()
            worker = DistanceWorker(slot, DEFAULT_CONFIG, predictor, log,
                clock=lambda: clock[0], frame_evidence=True,
                scene_function=lambda *args: dict(accepted=False, reason="synthetic_only"))
            worker.start()
            try:
                self.assertTrue(worker.updated.wait(1))
            finally:
                worker.close()
            row = json.loads(log.read_text().splitlines()[0])
            fresh = row["frame_evidence"]["freshness"]
            self.assertEqual(fresh["age_ms"], row["frame_age_ms"])
            self.assertEqual(fresh["within_limit"], row["frame_age_ms"] <= 500.)
            self.assertEqual(fresh["blockers"], row["blockers"])
            self.assertEqual(fresh["primary_reason"], row["reason"])

    def test_validator_rejects_mismatched_frame_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.capture_row(Path(directory))
        bad = copy.deepcopy(row)
        bad["frame_evidence"]["input"]["frame"] += 1
        with self.assertRaisesRegex(ValueError, "same input frame"):
            validate_row(bad)

    def test_validator_rejects_unobserved_support_point(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.capture_row(Path(directory))
        bad = copy.deepcopy(row)
        bad["frame_evidence"]["support_observation"]["point"] = [999, 699]
        with self.assertRaisesRegex(ValueError, "actual observed column"):
            validate_row(bad)

    def test_validator_rejects_inconsistent_mask_touch(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.capture_row(Path(directory))
        bad = copy.deepcopy(row)
        bad["frame_evidence"]["support_observation"]["mask_diagnostics"]["touches"]["left"] = True
        with self.assertRaisesRegex(ValueError, "touching edge list"):
            validate_row(bad)

    def test_validator_rejects_approval_flags_in_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.capture_row(Path(directory))
        for key in ("floor_contact_verified",):
            bad = copy.deepcopy(row)
            bad["frame_evidence"]["support_observation"][key] = True
            with self.assertRaisesRegex(ValueError, "unverified baseline support"):
                validate_row(bad)
        bad = copy.deepcopy(row)
        bad["frame_evidence"]["floor_model"]["physical_metric_verified"] = True
        with self.assertRaisesRegex(ValueError, "paper-reference floor model"):
            validate_row(bad)
        bad = copy.deepcopy(row)
        bad["frame_evidence"]["pose"]["usable_for_ffb"] = True
        with self.assertRaisesRegex(ValueError, "unverified pose"):
            validate_row(bad)

    def capture_row(self, root):
        slot = LatestNativeFrame()
        slot.begin("synthetic")
        slot.publish("synthetic", cone_image(), 0., 10.)
        log = root/"input"/"distance_frames.jsonl"
        log.parent.mkdir()
        worker = DistanceWorker(slot, DEFAULT_CONFIG,
            lambda frame: [BOX], log, clock=lambda: 10., frame_evidence=True,
            scene_function=lambda *args: dict(accepted=False, reason="synthetic_only"))
        worker.start()
        try:
            self.assertTrue(worker.updated.wait(1))
        finally:
            worker.close()
        return json.loads(log.read_text().splitlines()[0])


class CliTests(unittest.TestCase):
    def test_frame_evidence_flag_is_opt_in(self):
        base = ["--weights", "unused.pt", "--output-dir", "unused"]
        self.assertFalse(live.build_parser().parse_args(base).frame_evidence)
        self.assertTrue(live.build_parser().parse_args(base+["--frame-evidence"]).frame_evidence)


if __name__ == "__main__":
    unittest.main()
