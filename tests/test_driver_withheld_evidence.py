"""Synthetic native pixels/local pipes only. No camera, model, ROS or RTC."""
import argparse
from contextlib import redirect_stderr
import hashlib
import io
import json
import signal
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
sys.path.insert(0, str(ROOT/"src"))
from driver_motion_bridge import add_motion_arguments, bridge_from_args
from driver_motion_process import main as worker_main, serve
from driver_motion_protocol import read_message, write_frame
from driver_withheld_evidence import EvidenceLimits, WithheldEvidenceRecorder, evidence_path
from verify_driver_withheld_evidence import verify
from theta_rtc_frames import NativeFrame

SESSION = "a"*32


def frame(n=1, source=10., pixels=None):
    if pixels is None:
        pixels = np.full((720, 1280, 3), n, np.uint8)
    pixels.flags.writeable = False
    return NativeFrame(SESSION, n, n/30., source, pixels)


def result(f, reason="colour_contour_reaches_roi_edge", available=False):
    return dict(schema="cone_motion_range_v1", session=f.session, frame=f.sequence,
        source_time_sec=f.received_at, primary_model="synthetic", distance_available=available,
        horizontal_camera_foot_range_m=1. if available else None, reason=reason, models=[],
        physical_metric_verified=False, floor_contact_verified=False, controlling_distance=False,
        usable_for_ffb=False, published_to_ros=False)


def offer(recorder, f, r=None):
    r = result(f) if r is None else r
    return recorder.offer(f, r, json.dumps(r)+"\n")


class EvidenceRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recorders = []
        self.addCleanup(self.close_all)

    def close_all(self):
        for recorder in self.recorders:
            recorder.close(timeout=1.)

    def recorder(self, **limits):
        r = WithheldEvidenceRecorder(self.root/f"evidence{len(self.recorders)}", self.root/"measurements.jsonl", EvidenceLimits(**limits))
        self.recorders.append(r)
        return r

    def wait(self, predicate):
        deadline = time.monotonic()+3
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("bounded evidence wait expired")
            time.sleep(.005)

    def test_native_png_exact_pixels_sidecar_hash_and_full_measurement(self):
        r = self.recorder()
        f = frame(pixels=np.random.default_rng(42).integers(0, 256, (720, 1280, 3), dtype=np.uint8))
        measurement = result(f)
        line = json.dumps(measurement)+"\n"
        self.assertTrue(r.offer(f, measurement, line))
        self.wait(lambda: r.snapshot()["saved"] == 1)
        status = r.close(1.)
        self.assertTrue(status["writer_stopped"])
        index = json.loads((r.directory/"evidence_index.jsonl").read_text())
        sidecar_bytes = (r.directory/index["sidecar_file"]).read_bytes()
        sidecar = json.loads(sidecar_bytes)
        png = (r.directory/index["image_file"]).read_bytes()
        decoded = cv2.imread(str(r.directory/index["image_file"]))
        np.testing.assert_array_equal(decoded, f.image)
        self.assertEqual(decoded.shape, (720, 1280, 3))
        self.assertEqual(sidecar["measurement"], measurement)
        self.assertEqual(sidecar["decoded_bgr_sha256"], hashlib.sha256(f.image.tobytes()).hexdigest())
        self.assertEqual(index["png_sha256"], hashlib.sha256(png).hexdigest())
        self.assertEqual(index["sidecar_sha256"], hashlib.sha256(sidecar_bytes).hexdigest())
        self.assertEqual(index["source_log_line_sha256"], hashlib.sha256(line.encode()).hexdigest())
        self.assertFalse(sidecar["image_modified"])
        self.assertTrue(sidecar["worker_withheld_NOT_proof_of_GUI_display"])
        self.assertTrue(json.loads((r.directory/"evidence_status.json").read_text())["shutdown_complete"])
        r.result_log.write_text(line)
        verified = verify(r.directory, r.result_log)
        self.assertEqual(verified["verified_pairs"], 1)
        self.assertTrue(verified["source_log_checked"])
        self.assertTrue(verified["capture_shutdown_complete"])

    def saved_pair(self):
        r = self.recorder()
        f = frame()
        line = json.dumps(result(f))+"\n"
        self.assertTrue(r.offer(f, result(f), line))
        self.wait(lambda: r.snapshot()["saved"] == 1)
        r.close(1.)
        r.result_log.write_text(line)
        return r

    def test_verifier_rejects_corrupt_png(self):
        r = self.saved_pair()
        path = next(r.directory.glob("*.png"))
        path.write_bytes(path.read_bytes()+b"changed")
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            verify(r.directory, r.result_log)

    def test_verifier_does_not_follow_index_paths_or_sidecar_source_paths(self):
        r = self.saved_pair()
        index_path = r.directory/"evidence_index.jsonl"
        index = json.loads(index_path.read_text())
        index["image_file"] = "../outside.png"
        index_path.write_text(json.dumps(index)+"\n")
        with self.assertRaisesRegex(ValueError, "filename"):
            verify(r.directory)

    def test_verifier_requires_matching_explicit_source_log(self):
        r = self.saved_pair()
        other = self.root/"other.jsonl"
        other.write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "not found"):
            verify(r.directory, other)
        self.assertFalse(verify(r.directory)["source_log_checked"])

    def test_verifier_ignores_unfinished_tail_and_orphan_file(self):
        r = self.saved_pair()
        with (r.directory/"evidence_index.jsonl").open("ab") as stream:
            stream.write(b'{"incomplete')
        (r.directory/"unfinished.png.part").write_bytes(b"not a PNG")
        verified = verify(r.directory, r.result_log)
        self.assertEqual(verified["verified_pairs"], 1)
        self.assertTrue(verified["incomplete_index_tail_ignored"])
        self.assertFalse(verified["capture_shutdown_complete"])
        self.assertIn("unfinished.png.part", verified["nonindexed_files_NOT_verified"])

    def test_verifier_rejects_symlink_instead_of_reading_target(self):
        r = self.saved_pair()
        path = next(r.directory.glob("*.png"))
        target = self.root/"external.png"
        target.write_bytes(path.read_bytes())
        path.unlink()  # Only a generated file in this test's TemporaryDirectory.
        path.symlink_to(target)
        with self.assertRaises(OSError):
            verify(r.directory)

    def test_numeric_other_reason_and_stale_rejection_not_saved(self):
        r = self.recorder()
        f = frame()
        self.assertFalse(offer(r, f, result(f, available=True)))
        self.assertFalse(offer(r, f, result(f, reason="no_candidate")))
        self.assertFalse(offer(r, f, result(f, reason="frame_processing_too_old")))
        r.close(1.)
        self.assertEqual(r.snapshot()["saved"], 0)
        self.assertEqual(list(r.directory.glob("*.png")), [])

    def test_interval_count_limit_and_duplicate(self):
        r = self.recorder(max_frames=2)
        self.assertTrue(offer(r, frame(1, 10.)))
        self.wait(lambda: r.snapshot()["saved"] == 1)
        self.assertFalse(offer(r, frame(1, 10.)))
        self.assertFalse(offer(r, frame(2, 10.5)))
        self.assertTrue(offer(r, frame(3, 11.)))
        self.wait(lambda: r.snapshot()["saved"] == 2)
        self.assertFalse(offer(r, frame(4, 12.)))
        self.assertEqual(len(list(r.directory.glob("*.png"))), 2)
        self.assertEqual(r.snapshot()["skipped_interval"], 1)
        self.assertEqual(r.snapshot()["skipped_quota"], 1)

    def test_byte_budget_does_not_write_oversized_pair(self):
        r = self.recorder(max_bytes=1024*1024)
        pixels = np.random.default_rng(1).integers(0, 256, (720, 1280, 3), dtype=np.uint8)
        self.assertTrue(offer(r, frame(pixels=pixels)))
        self.wait(lambda: r.snapshot()["budget_exhausted"])
        r.close(1.)
        self.assertEqual(list(r.directory.glob("*.png")), [])
        self.assertEqual(r.snapshot()["png_and_sidecar_bytes"], 0)
        self.assertEqual(r.snapshot()["skipped_after_encoding_budget"], 1)
        self.assertTrue(json.loads((r.directory/"evidence_status.json").read_text())["shutdown_complete"])

    def test_slow_save_has_only_one_waiting_slot_and_close_is_bounded(self):
        gate, entered = threading.Event(), threading.Event()
        r = self.recorder(interval_sec=.1)
        original = r._save
        def slow(item, index):
            entered.set()
            gate.wait(3.)
            return original(item, index)
        try:
            with patch.object(r, "_save", side_effect=slow):
                self.assertTrue(offer(r, frame(1, 10.)))
                self.assertTrue(entered.wait(1.))
                self.assertTrue(offer(r, frame(2, 11.)))
                started = time.monotonic()
                self.assertFalse(offer(r, frame(3, 12.)))
                self.assertLess(time.monotonic()-started, .1)
                status = r.close(timeout=.01)
                self.assertFalse(status["writer_stopped"])
                self.assertEqual(r.pending.qsize(), 1)
                gate.set()
                self.wait(lambda: not r.thread.is_alive())
        finally:
            gate.set()

    def test_encoding_failure_only_disables_recorder(self):
        r = self.recorder()
        with patch("cv2.imencode", return_value=(False, None)):
            self.assertTrue(offer(r, frame()))
            self.wait(lambda: r.snapshot()["error"] is not None)
            self.assertFalse(offer(r, frame(2, 12.)))
        self.assertIn("encoding failed", r.snapshot()["error"])
        self.assertEqual(r.snapshot()["saved"], 0)

    def test_file_write_failure_only_disables_recorder(self):
        r = self.recorder()
        with patch("driver_withheld_evidence._atomic_new", side_effect=OSError("synthetic full disk")):
            self.assertTrue(offer(r, frame()))
            self.wait(lambda: r.snapshot()["error"] is not None)
        self.assertIn("full disk", r.snapshot()["error"])
        self.assertEqual(r.snapshot()["saved"], 0)

    def test_bad_frame_identity_or_mutable_pixels_never_get_filenames(self):
        for kind in ("identity", "mutable", "mismatch"):
            r = self.recorder()
            f = frame()
            if kind == "identity":
                f = NativeFrame("../bad", 1, 1., 10., f.image)
            elif kind == "mutable":
                f.image.flags.writeable = True
            measurement = result(f)
            if kind == "mismatch":
                measurement["frame"] = 8
            self.assertFalse(offer(r, f, measurement))
            self.assertIsNotNone(r.snapshot()["error"])
            r.close(1.)
            self.assertEqual(list(r.directory.glob("*.png")), [])

    def test_source_line_mismatch_disables_saving_not_measurement(self):
        r = self.recorder()
        f = frame()
        measurement = result(f)
        changed = dict(measurement, frame=99)
        self.assertTrue(r.offer(f, measurement, json.dumps(changed)+"\n"))
        self.wait(lambda: r.snapshot()["error"] is not None)
        self.assertEqual(measurement["frame"], 1)
        self.assertEqual(r.snapshot()["saved"], 0)

    def test_existing_directory_never_overwritten(self):
        folder = self.root/"existing"
        folder.mkdir()
        sentinel = folder/"user.txt"
        sentinel.write_text("keep")
        with self.assertRaises(FileExistsError):
            WithheldEvidenceRecorder(folder, self.root/"log")
        self.assertEqual(sentinel.read_text(), "keep")

    def test_closed_recorder_rejects_new_frames(self):
        r = self.recorder()
        r.close(1.)
        self.assertFalse(offer(r, frame()))

    def test_limits_are_finite_bounded_and_paths_stay_under_recordings(self):
        for kw in (dict(max_frames=True), dict(max_frames=101), dict(max_bytes=1),
                   dict(interval_sec=float("nan")), dict(interval_sec=0)):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                EvidenceLimits(**kw)
        good = evidence_path(self.root/"recordings"/"new", repo_root=self.root)
        self.assertEqual(good, self.root/"recordings"/"new")
        for path in (self.root/"recordings", self.root/"elsewhere"):
            with self.assertRaises(ValueError):
                evidence_path(path, repo_root=self.root)
        outside = self.root/"outside"
        outside.mkdir()
        link = self.root/"recordings"/"link"
        link.parent.mkdir(exist_ok=True)
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            evidence_path(link/"new", repo_root=self.root)


class EvidenceServeTests(unittest.TestCase):
    def exercise(self, output, path, evidence=None):
        source = io.BytesIO()
        for n in (1, 2):
            write_frame(source, frame(n, 10.+.001*n))
        source.seek(0)
        class Engine:
            settings = dict(frame_max_age_sec=.5)
            def measure(self, f, boxes, now):
                return result(f)
        predictor = lambda f: []
        return serve(Engine(), predictor, source, output, path, clock=lambda: 10.1, evidence=evidence)

    def test_default_off_creates_only_existing_measurement_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"motion_distance_frames.jsonl"
            result = self.exercise(io.BytesIO(), path)
            self.assertEqual(result["processed"], 2)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [path.name])

    def test_result_is_sent_before_evidence_offer_and_bad_saver_cannot_change_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = io.BytesIO()
            self.exercise(baseline, root/"baseline.jsonl")
            output = io.BytesIO()
            calls = []
            class Broken:
                def offer(self, f, r, line):
                    seen = io.BytesIO(output.getvalue())
                    self_result = []
                    try:
                        while True:
                            self_result.append(read_message(seen))
                    except EOFError:
                        pass
                    assert any(m.get("type") == "result" for m in self_result)
                    calls.append(f.sequence)
                    raise OSError("synthetic saver failure")
            with redirect_stderr(io.StringIO()):
                self.exercise(output, root/"evidence.jsonl", Broken())
            self.assertEqual(calls, [1])
            self.assertEqual(output.getvalue(), baseline.getvalue())
            self.assertEqual((root/"baseline.jsonl").read_bytes(), (root/"evidence.jsonl").read_bytes())


class EvidenceCLITests(unittest.TestCase):
    def parser(self):
        parser = argparse.ArgumentParser()
        parser.set_defaults(cam_width=1280, cam_height=720, front_lens="left", mock_camera=False)
        add_motion_arguments(parser)
        return parser

    def test_disabled_by_default_and_cannot_silently_enable_without_motion(self):
        self.assertIsNone(bridge_from_args(self.parser().parse_args([])))
        with self.assertRaisesRegex(ValueError, "requires --motion-distance"):
            bridge_from_args(self.parser().parse_args(["--motion-withheld-evidence-dir", "recordings/new"]))

    def test_limits_without_directory_fail_before_any_process(self):
        with self.assertRaisesRegex(ValueError, "limits require"):
            bridge_from_args(self.parser().parse_args(["--motion-distance", "--motion-withheld-evidence-max-frames", "4"]))

    def test_enabled_options_reach_child_without_starting_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weights = root/"fake.pt"
            weights.write_bytes(b"fixture only")
            args = self.parser().parse_args(["--motion-distance", "--motion-experimental-rigid-mount",
                "--motion-python", sys.executable, "--motion-weights", str(weights),
                "--motion-profile", str(ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json"),
                "--motion-output-dir", str(root/"output"), "--motion-withheld-evidence-dir", "recordings/new",
                "--motion-withheld-evidence-max-frames", "8", "--motion-withheld-evidence-max-mib", "16",
                "--motion-withheld-evidence-interval-sec", ".5"])
            with patch("driver_withheld_evidence.evidence_path", return_value=root/"recordings"/"new"):
                bridge = bridge_from_args(args)
            try:
                command = bridge.command
                for flag, value in (("--withheld-evidence-max-frames", "8"), ("--withheld-evidence-max-mib", "16"),
                                    ("--withheld-evidence-interval-sec", "0.5")):
                    self.assertEqual(command[command.index(flag)+1], value)
                self.assertIsNone(bridge.process)
                summary = bridge.close()
                self.assertTrue(summary["withheld_evidence_requested"])
                self.assertIsNone(summary["image_files_written"])
            finally:
                if not bridge.stop_event.is_set():
                    bridge.close()


class EvidenceWorkerStartupTests(unittest.TestCase):
    def test_saver_initialization_failure_does_not_prevent_worker_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.BytesIO()
            fake_predictor = SimpleNamespace(weights_sha256="synthetic_NOT_weights", gpu=dict(name="NOT_CUDA"))
            profile = ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json"
            with patch("cone_distance_worker.YoloConePredictor", return_value=fake_predictor), \
                    patch("driver_withheld_evidence.evidence_path", return_value=root/"evidence"), \
                    patch("driver_withheld_evidence.WithheldEvidenceRecorder", side_effect=PermissionError("synthetic permission")), \
                    patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO())), \
                    patch("sys.stdout", SimpleNamespace(buffer=output)), redirect_stderr(io.StringIO()):
                code = worker_main(["--weights", str(root/"fixture_not_model"), "--profile", str(profile),
                    "--output-dir", str(root), "--experimental-rigid-mount", "--withheld-evidence-dir", "recordings/new"])
            self.assertEqual(code, 0)
            output.seek(0)
            self.assertEqual(read_message(output), dict(type="request"))
            summary = json.loads((root/"motion_engine_summary.json").read_text())
            self.assertFalse(summary["withheld_evidence"]["recorder_started"])
            self.assertIn("synthetic permission", summary["withheld_evidence_initialization_error"])

    def test_sigterm_is_ignored_during_bounded_evidence_close_then_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = dict(handler=signal.SIG_DFL, closed=False)
            def set_signal(signum, handler):
                previous = state["handler"]
                state["handler"] = handler
                return previous
            def terminate(*a, **kw):
                state["handler"](signal.SIGTERM, None)
            def close(timeout):
                self.assertEqual(timeout, .25)
                self.assertIs(state["handler"], signal.SIG_IGN)
                state["closed"] = True
            recorder = SimpleNamespace(close=close)
            fake_predictor = SimpleNamespace(weights_sha256="synthetic_NOT_weights", gpu=dict(name="NOT_CUDA"))
            profile = ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json"
            with patch("cone_distance_worker.YoloConePredictor", return_value=fake_predictor), \
                    patch("driver_withheld_evidence.evidence_path", return_value=root/"evidence"), \
                    patch("driver_withheld_evidence.WithheldEvidenceRecorder", return_value=recorder), \
                    patch("signal.signal", side_effect=set_signal), \
                    patch("driver_motion_process.serve", side_effect=terminate), \
                    patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO())), \
                    patch("sys.stdout", SimpleNamespace(buffer=io.BytesIO())):
                code = worker_main(["--weights", str(root/"fixture_not_model"), "--profile", str(profile),
                    "--output-dir", str(root), "--experimental-rigid-mount", "--withheld-evidence-dir", "recordings/new"])
            self.assertEqual(code, 0)
            self.assertTrue(state["closed"])
            self.assertIs(state["handler"], signal.SIG_DFL)


if __name__ == "__main__":
    unittest.main()
