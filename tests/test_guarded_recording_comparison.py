"""Synthetic committed recording only. No camera, inference model, RTC or ROS."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_motion_range import MotionRangeEngine, load_motion_profile
from cone_upper_support_candidate import observe_upper_completion
from driver_withheld_evidence import WithheldEvidenceRecorder
from run_guarded_recording_comparison import compare_recording, hash_regular, main, wait_for_writer
from theta_rtc_frames import NativeFrame

SESSION = "a" * 32
BOX = dict(x1=301., y1=305., x2=339., y2=399.6, confidence=.95, class_id=0)


class RecordingComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source";self.source.mkdir()
        self.evidence = self.root / "evidence"
        self.reference = self.root / "reference.json"
        self.output = self.root / "comparison"
        settings, camera, _, _ = load_config()
        original = ROOT / "Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json"
        profile, sha = load_motion_profile(original, settings)
        (self.source / "motion_profile_used.json").write_bytes(original.read_bytes())
        metadata = dict(profile_sha256=sha, config_sha256=digest(DEFAULT_CONFIG),
            metric="horizontal_camera_foot_range_m_NOT_base_link_or_contact",
            physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
        (self.source / "motion_engine_summary.json").write_text(json.dumps(metadata))
        engine = MotionRangeEngine(settings, camera, profile, sha, acknowledged=True, observer=observe_upper_completion)
        image = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
        image.flags.writeable = False
        frame = NativeFrame(SESSION, 1, .1, 10., image)
        result = engine.measure(frame, [BOX], 10.01)
        self.assertEqual(result["reason"], "colour_contour_reaches_roi_edge")
        self.line = json.dumps(result) + "\n"
        self.log = self.source / "motion_distance_frames.jsonl";self.log.write_text(self.line)
        recorder = WithheldEvidenceRecorder(self.evidence, self.log)
        self.addCleanup(lambda: recorder.close(1.))
        self.assertTrue(recorder.offer(frame, result, self.line))
        self.assertTrue(recorder.close(2.)["writer_stopped"])
        self.index = json.loads((self.evidence / "evidence_index.jsonl").read_text())
        self.ref = dict(schema="offline_self_body_boundary_v1", image_size=[1280, 720],
            layout="dual_fisheye_front_left_unremapped", session=SESSION, source_frame=1,
            source_png_sha256=self.index["png_sha256"], boundary_xy=[[280, 458], [360, 458]],
            independent_physical_measurement=False, cross_session_mount_verified=False,
            live_authorized=False, floor_contact_verified=False)
        self.write_ref()

    def write_ref(self):self.reference.write_text(json.dumps(self.ref))

    def run_comparison(self, **options):
        return compare_recording(self.source, self.evidence, self.reference, self.output, **options)

    def failed(self):
        self.assertEqual(json.loads((self.output / "comparison_summary.json").read_text())["state"], "failed")
        self.assertFalse((self.output / "comparison_frames.jsonl").exists())

    def test_closed_recording_produces_separate_source_labelled_log_and_no_input_changes(self):
        before = {str(p): p.read_bytes() for p in [*self.source.iterdir(), *self.evidence.iterdir(), self.reference]}
        summary = self.run_comparison()
        self.assertEqual(summary["state"], "complete")
        self.assertEqual(summary["rows_committed"], 1)
        self.assertEqual(summary["numeric_comparison_rows"], 1)
        data = (self.output / "comparison_frames.jsonl").read_bytes()
        row = json.loads(data)
        self.assertEqual(row["frame"], 1);self.assertEqual(row["session"], SESSION)
        self.assertEqual(row["comparison_support_pixel"], [320, 400])
        self.assertTrue(row["baseline_reproduced"]);self.assertTrue(row["source_log_verified"])
        self.assertEqual(row["source_log_line_sha256"], self.index["source_log_line_sha256"])
        self.assertIn("NOT_live_display", row["result_kind"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), summary["comparison_log_sha256"])
        self.assertFalse(list(self.output.glob("*.png")))
        for path, data in before.items():self.assertEqual(Path(path).read_bytes(), data)

    def test_body_veto_does_not_turn_hidden_point_into_distance(self):
        self.ref["boundary_xy"] = [[280, 400], [360, 400]];self.write_ref()
        summary = self.run_comparison()
        self.assertEqual(summary["numeric_comparison_rows"], 0)
        row = json.loads((self.output / "comparison_frames.jsonl").read_text())
        self.assertFalse(row["comparison_distance_available"])
        self.assertEqual(row["body_review_reason"], "possible_self_body_occlusion")

    def test_wrong_reference_session_is_not_rebound(self):
        self.ref["session"] = "b" * 32;self.write_ref()
        with self.assertRaisesRegex(ValueError, "no rebinding"):self.run_comparison()
        self.failed()

    def test_other_session_in_same_evidence_folder_gets_no_comparison_value(self):
        directory = self.root / "multi-session"
        image = cv2.imread(str(self.evidence / self.index["image_file"]));image.flags.writeable = False
        first = json.loads(self.line);second = copy.deepcopy(first)
        second.update(session="b" * 32, source_time_sec=12., completed_time_sec=12.01, media_time_sec=.2)
        lines = [json.dumps(r) + "\n" for r in (first, second)]
        self.log.write_text("".join(lines))
        recorder = WithheldEvidenceRecorder(directory, self.log)
        self.addCleanup(lambda: recorder.close(1.))
        for n, (measurement, line) in enumerate(zip((first, second), lines), 1):
            frame = NativeFrame(measurement["session"], 1, measurement["media_time_sec"], measurement["source_time_sec"], image)
            self.assertTrue(recorder.offer(frame, measurement, line))
            deadline = time.monotonic() + 2
            while recorder.snapshot()["saved"] < n and time.monotonic() < deadline:time.sleep(.005)
            self.assertEqual(recorder.snapshot()["saved"], n)
        recorder.close(2.);self.evidence = directory
        index = json.loads((directory / "evidence_index.jsonl").read_text().splitlines()[0])
        self.ref["source_png_sha256"] = index["png_sha256"];self.write_ref()
        summary = self.run_comparison()
        rows = [json.loads(line) for line in (self.output / "comparison_frames.jsonl").read_text().splitlines()]
        self.assertEqual(summary["rows_committed"], 2)
        self.assertEqual(summary["numeric_comparison_rows"], 1)
        other = next(r for r in rows if r["session"] != SESSION)
        self.assertFalse(other["reference_scope_verified"])
        self.assertFalse(other["comparison_distance_available"])
        self.assertEqual(other["reason"], "withheld_reference_session_mismatch")

    def test_wrong_reference_frame_or_hash_is_not_accepted(self):
        self.ref["source_frame"] = 2;self.write_ref()
        with self.assertRaisesRegex(ValueError, "reference"):self.run_comparison()
        self.failed()

    def test_wrong_reference_hash_is_not_accepted(self):
        self.ref["source_png_sha256"] = "0" * 64;self.write_ref()
        with self.assertRaisesRegex(ValueError, "reference"):self.run_comparison()
        self.failed()

    def test_other_source_log_is_not_used_as_if_corresponding(self):
        self.log.write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "not found"):self.run_comparison()
        self.failed()

    def test_incomplete_writer_is_rejected_without_comparison_log(self):
        p = self.evidence / "evidence_status.json";status = json.loads(p.read_text())
        status["shutdown_complete"] = False;p.write_text(json.dumps(status))
        with self.assertRaisesRegex(ValueError, "incompletely"):self.run_comparison()
        self.failed()

    def test_live_writer_without_wait_is_not_called_a_complete_recording(self):
        p = self.evidence / "evidence_status.json";status = json.loads(p.read_text())
        status.update(writer_done=False, shutdown_complete=False);p.write_text(json.dumps(status))
        with self.assertRaises(TimeoutError):self.run_comparison()
        self.failed()

    def test_orphan_file_or_partial_index_is_not_silently_ignored(self):
        (self.evidence / "orphan.part").write_bytes(b"incomplete")
        with self.assertRaisesRegex(ValueError, "complete verified"):self.run_comparison()
        self.failed()

    def test_config_or_engine_profile_mismatch_is_rejected(self):
        p = self.source / "motion_engine_summary.json";meta = json.loads(p.read_text())
        meta["config_sha256"] = "0" * 64;p.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, "engine"):self.run_comparison()
        self.failed()

    def test_baseline_observation_mismatch_is_not_a_candidate(self):
        with patch("cone_guarded_lower_edge_shadow.compare_guarded_lower_edge", return_value={"baseline": {}}):
            with self.assertRaisesRegex(ValueError, "baseline"):self.run_comparison()
        self.failed()

    def test_source_modified_during_comparison_is_not_committed(self):
        from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge
        def changed(*args, **kwargs):
            result = compare_guarded_lower_edge(*args, **kwargs)
            self.log.write_text(self.line + "\n")
            return result
        with patch("cone_guarded_lower_edge_shadow.compare_guarded_lower_edge", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "input changed"):self.run_comparison()
        self.failed()

    def test_corrupt_png_is_rejected_before_comparison(self):
        (self.evidence / self.index["image_file"]).write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "SHA"):self.run_comparison()
        self.failed()

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir();marker = self.output / "user-data";marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "new output"):self.run_comparison()
        self.assertEqual(marker.read_text(), "keep")

    def test_output_cannot_be_nested_in_input_or_evidence(self):
        for root in (self.source, self.evidence):
            with self.assertRaisesRegex(ValueError, "outside"):
                compare_recording(self.source, self.evidence, self.reference, root / "new")
            self.assertFalse((root / "new").exists())

    def test_symlink_reference_and_regular_hash_size_cap_are_rejected(self):
        link = self.root / "ref-link.json";link.symlink_to(self.reference)
        with self.assertRaises(OSError):compare_recording(self.source, self.evidence, link, self.output)
        self.failed()
        with self.assertRaises(ValueError):hash_regular(self.log, 1)

    def test_wait_cancellation_is_explicit_and_does_not_touch_recording(self):
        stop = threading.Event();stop.set()
        with self.assertRaises(InterruptedError):self.run_comparison(wait_sec=1, stop=stop)
        self.failed()

    def test_wait_bounds_are_finite_and_bounded(self):
        for value in (True, -1, float("nan"), 3601):
            with self.assertRaises(ValueError):wait_for_writer(self.evidence, value, .25)

    def test_wait_can_observe_atomic_writer_completion(self):
        from types import SimpleNamespace
        values = iter([b'{"writer_done":false}', b'{"writer_done":true,"shutdown_complete":true}'])
        stop = SimpleNamespace(is_set=lambda: False, wait=lambda delay: None)
        with patch("run_guarded_recording_comparison.read_regular", side_effect=lambda *a: next(values)):
            wait_for_writer(self.evidence, 1, .1, stop=stop, clock=lambda: 0)

    def test_disk_publish_failure_does_not_leave_a_completed_log_or_touch_input(self):
        original = self.log.read_bytes()
        with patch("run_guarded_recording_comparison.os.link", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):self.run_comparison()
        self.failed();self.assertEqual(self.log.read_bytes(), original)
        self.assertTrue((self.output / "comparison_frames.jsonl.part").exists())

    def test_no_control_authority_or_main_display_change_in_outputs(self):
        summary = self.run_comparison();row = json.loads((self.output / "comparison_frames.jsonl").read_text())
        for item in (summary, row):
            for flag in ("physical_metric_verified", "floor_contact_verified", "controlling_distance",
                         "usable_for_ffb", "published_to_ros"):
                self.assertIs(item[flag], False)
        self.assertFalse(summary["main_display_modified"])

    def test_no_live_entry_point_imports_this_post_recording_command(self):
        for name in ("driver_motion_process.py", "driver_motion_bridge.py", "webrtc_receive_ui.py",
                     "run_cone_motion_live.py"):
            self.assertNotIn("run_guarded_recording_comparison", (ROOT / "src" / name).read_text())

    def test_cli_does_not_start_anything_on_help(self):
        with self.assertRaises(SystemExit) as raised:main(["--help"])
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
