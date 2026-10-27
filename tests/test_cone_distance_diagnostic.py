"""Camera/GPU/socket-free checks for the shared cone distance pipeline."""
import ast
import asyncio
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import (DEFAULT_CONFIG, ConeDistanceEngine, checked_target_roi, digest,
                                load_config, observe_support, render_distance, select_front_boxes)
from cone_distance_worker import DistanceWorker, YoloConePredictor
from cone_scene_diagnostic import estimate_scene, extract_guarded_curve_planes
from run_cone_distance_replay import load_saved_run
from theta_rtc_frames import LatestNativeFrame, NativeFrame


def native_cone():
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
    return image


BOX = dict(x1=290., y1=305., x2=350., y2=405., confidence=.9, class_id=0)


def frame(sequence=100, source=3.1, image=None, session="test"):
    return NativeFrame(session, sequence, source, source, native_cone() if image is None else image)


def initialized_engine():
    engine = ConeDistanceEngine()
    engine.reset("test")
    for index in range(4):
        f = frame(index*30+1, float(index))
        ticket = engine.begin_scene(f)
        engine.complete_scene(ticket, dict(accepted=True, up=engine.prior_up.tolist(), reason="synthetic_scene"), index+.1)
    return engine


def stable_measurements(engine):
    return [engine.measure(frame(100+i, 3.1+i/30), [BOX], 3.11+i/30) for i in range(3)]


class PortLineageTest(unittest.TestCase):
    def test_promoted_functions_are_ast_identical_to_frozen_algorithms(self):
        def nodes(path):
            return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(path.read_text()).body
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        current = nodes(ROOT / "src/cone_scene_diagnostic.py")
        sources = {
            "Experimental_results/2026-10-21/scene_vertical_gravity_r01/scene_geometry.py":
                ("angle_degrees", "unit", "infer_up", "align_up_preserving_heading_reference"),
            "Experimental_results/2026-10-23/scene_ray_reuse_r01/cached_curve_geometry.py": ("_plane_from_subset",),
            "Experimental_results/2026-10-23/scene_bin_reduction_r01/guarded_curve_geometry.py":
                ("bin_winners", "extract_guarded_curve_planes"),
            "Experimental_results/2026-10-23/causal_pose_replay_r01/causal_pose.py":
                ("direction", "angle", "PastOnlyPose")}
        for path, names in sources.items():
            old = nodes(ROOT / path)
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(current[name], old[name])

    def test_native_recorded_scene_matches_saved_single_frame_decision(self):
        path = ROOT / "Experimental_results/2026-10-23/scene_halfsecond_replay_r01/scene_results_r01/image_diagnostics.csv"
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        selected = [rows[0], next(r for r in rows if r["accepted"] == "True")]
        engine = ConeDistanceEngine()
        for row in selected:
            source = Path(row["source_native_png"])
            if not source.exists():
                self.skipTest("local native replay PNG unavailable")
            self.assertEqual(digest(source), row["png_sha256"])
            result = estimate_scene(cv2.imread(str(source)), engine.camera, engine.prior_up)
            result.pop("curve_rows")
            self.assertEqual(result, json.loads(row["full_pose_json"]))


class ConfigAndSupportTest(unittest.TestCase):
    def setUp(self):
        self.engine = ConeDistanceEngine()

    def test_config_keeps_height_and_nonphysical_flags(self):
        self.assertEqual(self.engine.transform[2, 3], .59)
        self.assertFalse(self.engine.settings["physical_metric_verified"])
        self.assertFalse(self.engine.settings["usable_for_ffb"])

    def test_changed_camera_hash_refused(self):
        data = json.loads(DEFAULT_CONFIG.read_text())
        data["camera_sha256"] = "0"*64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "changed diagnostic"):
                load_config(path)

    def test_native_shape_required_no_resize(self):
        with self.assertRaises(ValueError):
            observe_support(np.zeros((960, 1920, 3), np.uint8), BOX, self.engine.camera)

    def test_actual_lower_envelope_point_is_in_trimmed_support(self):
        image = native_cone()
        before = image.copy()
        result = observe_support(image, BOX, self.engine.camera)
        self.assertIn(result["point"], result["support"])
        self.assertEqual(result["point"], [320, 400])
        self.assertNotEqual(result["point"][1], BOX["y2"])
        self.assertFalse(result["floor_contact_verified"])
        np.testing.assert_array_equal(before, image)

    def test_no_colour_never_uses_bbox_bottom(self):
        result = observe_support(np.zeros((720, 1280, 3), np.uint8), BOX, self.engine.camera)
        self.assertIsNone(result["point"])
        self.assertEqual(result["reason"], "no_supported_colour_contour")

    def test_competing_colours_are_rejected(self):
        image = np.zeros((720, 1280, 3), np.uint8)
        cv2.rectangle(image, (295, 320), (313, 390), (0, 0, 255), -1)
        cv2.rectangle(image, (327, 320), (345, 390), (0, 255, 255), -1)
        self.assertEqual(observe_support(image, BOX, self.engine.camera)["reason"], "ambiguous_competing_colour_contours")

    def test_front_and_rear_are_not_mixed(self):
        rear = dict(BOX, x1=930., x2=990.)
        self.assertEqual(select_front_boxes([BOX, rear], self.engine.camera, .5), [BOX])

    def test_explicit_target_scope_excludes_only_bbox_centres(self):
        left = dict(BOX, x1=180., x2=220.)
        self.assertEqual(len(select_front_boxes([BOX, left], self.engine.camera, .5)), 2)
        self.assertEqual(select_front_boxes([BOX, left], self.engine.camera, .5, (270, 0, 350, 720)), [BOX])
        for roi in ((0, 0, 1280, 720), (0, 0, 640.0, 720), (350, 0, 270, 720), (True, 0, 640, 720)):
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                checked_target_roi(roi)


class EngineStateTest(unittest.TestCase):
    def test_three_support_frames_then_conditional_output(self):
        rows = stable_measurements(initialized_engine())
        self.assertEqual([r["distance_available"] for r in rows], [False, False, True])
        result = rows[-1]
        self.assertGreater(result["distance_forward_m"], 0)
        self.assertEqual(result["target_frame"], "paper7_ground_reference")
        for name in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb", "target_association_physically_verified"):
            self.assertIs(result[name], False)

    def test_missing_detection_does_not_hold_previous_distance(self):
        engine = initialized_engine()
        stable_measurements(engine)
        result = engine.measure(frame(103, 3.2), [], 3.21)
        self.assertFalse(result["distance_available"])
        self.assertIsNone(result["distance_forward_m"])
        self.assertIn("no_candidate", result["blockers"])

    def test_multiple_front_cones_not_arbitrarily_selected(self):
        engine = initialized_engine()
        stable_measurements(engine)
        result = engine.measure(frame(103, 3.2), [BOX, dict(BOX, x1=180., x2=220.)], 3.21)
        self.assertEqual(result["front_candidates"], 2)
        self.assertIn("ambiguous_front_cones", result["blockers"])
        self.assertIsNone(result["distance_forward_m"])

    def test_no_own_scene_initialization_no_distance(self):
        engine = ConeDistanceEngine()
        engine.reset("test")
        result = stable_measurements(engine)[-1]
        self.assertTrue(result["quality_accepted"])
        self.assertFalse(result["scene_initialized"])
        self.assertIsNone(result["distance_forward_m"])

    def test_pending_scene_blocks_then_rejection_is_not_bypassed(self):
        engine = initialized_engine()
        stable_measurements(engine)
        ticket = engine.begin_scene(frame(104, 4.01))
        result = engine.measure(frame(105, 4.02), [BOX], 4.03)
        self.assertIn("newer_scene_processing_pending", result["blockers"])
        engine.complete_scene(ticket, dict(accepted=False, reason="synthetic_rejection"), 4.04)
        result = engine.measure(frame(106, 4.05), [BOX], 4.06)
        self.assertIn("latest_scene_image_rejected", result["blockers"])

    def test_scene_completion_does_not_refresh_source_age(self):
        engine = initialized_engine()
        stable_measurements(engine)
        result = engine.measure(frame(103, 4.01), [BOX], 4.02)
        self.assertIn("scene_confirmation_older_than_one_second", result["blockers"])

    def test_slow_current_frame_withheld_without_stretching_ttl(self):
        engine = initialized_engine()
        stable_measurements(engine)
        result = engine.measure(frame(103, 3.2), [BOX], 3.701)
        self.assertIn("frame_processing_too_old", result["blockers"])
        self.assertIsNone(result["distance_forward_m"])

    def test_current_processing_clock_is_sampled_after_support(self):
        engine = initialized_engine()
        stable_measurements(engine)
        clock = iter((3.21, 3.701))
        result = engine.measure(frame(103, 3.2), [BOX], lambda: next(clock))
        self.assertIn("frame_processing_too_old", result["blockers"])

    def test_duplicate_source_or_wrong_session_refused(self):
        engine = initialized_engine()
        stable_measurements(engine)
        for f in (frame(102, 3.2), frame(104, 3.2, session="old"), frame(104, 3.1)):
            with self.subTest(), self.assertRaises(ValueError):
                engine.measure(f, [BOX], 3.3)

    def test_old_scene_future_cannot_mutate_reconnected_session(self):
        engine = initialized_engine()
        ticket = engine.begin_scene(frame(104, 4.01))
        engine.reset("new")
        self.assertFalse(engine.complete_scene(ticket, dict(accepted=True, up=engine.prior_up.tolist(), reason="old"), 4.1))
        self.assertFalse(engine.pose.ready)
        self.assertEqual(engine.scene_reason, "no_scene_observation")

    def test_scene_cadence_capacity_one(self):
        engine = ConeDistanceEngine()
        engine.reset("test")
        ticket = engine.begin_scene(frame(1, 0.0))
        self.assertFalse(engine.scene_due(5))
        with self.assertRaises(ValueError):
            engine.begin_scene(frame(2, .1))
        engine.complete_scene(ticket, dict(accepted=False, reason="test"), .1)
        self.assertFalse(engine.scene_due(.99))
        self.assertTrue(engine.scene_due(1.0))

    def test_bad_detector_values_fail_closed(self):
        engine = initialized_engine()
        stable_measurements(engine)
        result = engine.measure(frame(103, 3.2), [dict(BOX, confidence=float("nan"))], 3.21)
        self.assertIn("invalid_detector_output", result["blockers"])
        self.assertIsNone(result["distance_forward_m"])

    def test_later_evidence_cannot_change_past_results(self):
        engine = initialized_engine()
        rows = stable_measurements(engine)
        before = copy.deepcopy(rows)
        ticket = engine.begin_scene(frame(104, 4.01))
        rotated = [1., 0., 0.]
        engine.complete_scene(ticket, dict(accepted=True, reason="later", up=rotated), 4.02)
        self.assertFalse(engine.pose.ready)
        self.assertEqual(rows, before)

    def test_annotated_display_does_not_change_original(self):
        result = stable_measurements(initialized_engine())[-1]
        image = native_cone()
        before = image.copy()
        view = render_distance(image, result, replay=True)
        self.assertEqual(view.shape, before.shape)
        self.assertFalse(np.array_equal(view, before))
        np.testing.assert_array_equal(image, before)


class WorkerAndEntrypointTest(unittest.TestCase):
    def wait_update(self, worker, sequence):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            with worker.lock:
                if worker.latest is not None and worker.latest[0].sequence == sequence:
                    return worker.latest
                if worker.error:
                    self.fail(worker.error)
            worker.updated.wait(.02)
            worker.updated.clear()
        self.fail("bounded worker result wait timed out")

    def test_cone_thread_with_completed_scene_futures_writes_diagnostic_log(self):
        from concurrent.futures import Future
        class CompletedScenePool:
            def __init__(self, **kwargs):
                pass
            def submit(self, function, *args):
                future = Future()
                future.set_result(function(*args))
                return future
            def shutdown(self, **kwargs):
                pass
        with tempfile.TemporaryDirectory() as directory:
            slot = LatestNativeFrame()
            slot.begin("test")
            current_time = [10.0]
            worker = DistanceWorker(slot, DEFAULT_CONFIG, lambda f: [BOX], Path(directory)/"rows.jsonl",
                clock=lambda: current_time[0], scene_function=lambda *args: dict(accepted=True,
                    up=ConeDistanceEngine().prior_up.tolist(), reason="synthetic_scene"))
            # Complete futures deterministically so test-clock jumps are not
            # confused with actual OS thread scheduling delays. Cone worker is
            # real; pending/late scene futures are exercised separately.
            with patch("cone_distance_worker.ThreadPoolExecutor", CompletedScenePool):
                worker.start()
                try:
                    for index, timestamp in enumerate((10., 11., 12., 13., 13.03, 13.06, 13.09), 1):
                        current_time[0] = timestamp
                        slot.publish("test", native_cone(), timestamp-10, timestamp)
                        self.wait_update(worker, index)
                    self.assertTrue(worker.latest[1]["distance_available"])
                finally:
                    worker.close()
            self.assertFalse(worker.thread.is_alive())
            rows = [json.loads(line) for line in (Path(directory)/"rows.jsonl").read_text().splitlines()]
            self.assertEqual([r["frame"] for r in rows], list(range(1, 8)))
            self.assertTrue(all(r["usable_for_ffb"] is False for r in rows))

    def test_disconnect_while_predicting_cannot_publish_visible_result(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = LatestNativeFrame()
            slot.begin("test")
            entered, release = threading.Event(), threading.Event()
            def predictor(frame):
                entered.set()
                if not release.wait(1):
                    raise RuntimeError("test predictor release timed out")
                return [BOX]
            worker = DistanceWorker(slot, DEFAULT_CONFIG, predictor, Path(directory)/"rows.jsonl",
                clock=lambda: 10.0, scene_function=lambda *args: dict(accepted=False, reason="synthetic"))
            slot.publish("test", native_cone(), 0., 10.)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                slot.end("test")
                release.set()
                self.assertTrue(worker.updated.wait(1))
                self.assertIsNone(worker.poll(10., None)[0])
                self.assertIsNone(worker.latest)
            finally:
                release.set()
                worker.close()

    def test_stale_inference_logged_as_withheld_not_as_valid_output(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = LatestNativeFrame()
            slot.begin("test")
            current_time = [10.0]
            def predictor(frame):
                current_time[0] = 10.501
                return [BOX]
            worker = DistanceWorker(slot, DEFAULT_CONFIG, predictor, Path(directory)/"rows.jsonl",
                clock=lambda: current_time[0], scene_function=lambda *args: dict(accepted=False, reason="synthetic"))
            slot.publish("test", native_cone(), 0., 10.)
            worker.start()
            try:
                self.assertTrue(worker.updated.wait(1))
            finally:
                worker.close()
            row = json.loads((Path(directory)/"rows.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["reason"], "frame_processing_too_old")
            self.assertFalse(row["distance_available"])
            self.assertIsNone(row["distance_forward_m"])

    def test_worker_result_pairing_source_ttl_and_session_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = DistanceWorker(LatestNativeFrame(), DEFAULT_CONFIG, lambda f: [], Path(directory)/"unused.jsonl")
            f = frame()
            worker.latest = (f, dict(reason="test"))
            self.assertEqual(worker.poll(3.2, frame(101, 3.2))[0][0].sequence, 100)
            self.assertIsNone(worker.poll(3.601, frame(102, 3.6))[0])
            self.assertIsNone(worker.poll(3.2, frame(session="new"))[0])
            self.assertIsNone(worker.poll(3.2, None)[0])

    def test_untrusted_weights_rejected_before_torch_import(self):
        with tempfile.TemporaryDirectory() as directory:
            weights = Path(directory)/"weights.pt"
            weights.write_bytes(b"not a model; must never deserialize")
            with self.assertRaisesRegex(ValueError, "checkpoint matching"):
                YoloConePredictor(weights, ConeDistanceEngine().settings, Path(directory)/"out")
            self.assertFalse((Path(directory)/"out").exists())

    def test_core_and_replay_do_not_import_hardware_or_gpu(self):
        forbidden = {"rclpy", "evdev", "torch", "ultralytics", "aiortc"}
        for path in ("cone_distance_core.py", "cone_scene_diagnostic.py", "run_cone_distance_replay.py"):
            for node in ast.walk(ast.parse((ROOT/"src"/path).read_text())):
                imports = ([n.name for n in node.names] if isinstance(node, ast.Import)
                           else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                self.assertFalse(forbidden.intersection(n.split(".")[0] for n in imports))


if __name__ == "__main__":
    unittest.main()
