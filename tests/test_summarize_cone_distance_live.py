"""Offline report checks; fixture distances/times are synthetic, NOT measurements."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from summarize_cone_distance_live import CONDITIONAL, main, statistics, summarize


def row(session="first", frame=1, source=10., available=False):
    return dict(session=session, frame=frame, source_time_sec=source, completed_time_sec=source+.01,
        frame_age_ms=1000*((source+.01)-source), predict_ms=6., support_geometry_ms=3., cone_service_ms=10.,
        distance_available=available, distance_forward_m=1.3 if available else None,
        lateral_right_m=0. if available else None,
        reason=CONDITIONAL if available else "scene_initialization_pending",
        blockers=[] if available else ["scene_initialization_pending"],
        scene_initialized=available, scene_pending=False, quality_accepted=True,
        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False,
        target_frame="paper7_ground_reference", target_roi_native_xyxy=[270, 0, 350, 720],
        inference_source="injected_predictor_not_verified_cuda")


def finalized():
    return dict(physical_metric_verified=False, usable_for_ffb=False, physical_output=False,
        runtime_status="STOPPED", worker_error=None, run_error=None, cleanup_errors=[],
        shutdown=dict(worker_stopped=True, scene_job_running=False, shutdown_complete=True))


class LiveReportTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.input = self.root/"input"
        self.input.mkdir()
        self.output = self.root/"report"

    def write(self, rows, final=True):
        (self.input/"distance_frames.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows))
        if final:
            (self.input/"live_summary.json").write_text(json.dumps(finalized()))

    def report(self, **kwargs):
        return summarize(self.input, self.output, plots=False, **kwargs)

    def test_session_reset_and_processed_denominator_are_explicit(self):
        rows = [row(), row(frame=4, source=10.2, available=True), row("second", 1, 11.)]
        self.write(rows)
        result = self.report()
        self.assertEqual(result["status"], "FINALIZED_DIAGNOSTIC_LOG")
        self.assertEqual(result["processed_frames"], 3)
        self.assertEqual(result["conditional_output_frames"], 1)
        self.assertEqual(result["session_count"], 2)
        first = result["sessions"][0]
        self.assertEqual(first["unlogged_sequence_numbers_between_logged_frames"], 2)
        self.assertEqual(first["conditional_fraction_of_processed_frames"], .5)
        self.assertAlmostEqual(first["first_conditional_source_offset_sec"], .2)
        self.assertAlmostEqual(first["processed_completion_hz"], 5.)
        self.assertIsNone(result["sessions"][1]["processed_completion_hz"])
        self.assertFalse(result["display_availability_measured"])
        self.assertFalse(result["physical_metric_verified"])
        self.assertTrue(result["contains_injected_or_unverified_predictor"])
        self.assertIn("注入テスト", (self.output/"report.md").read_text())
        self.assertEqual(rows, [json.loads(line) for line in (self.input/"distance_frames.jsonl").read_text().splitlines()])

    def test_empty_log_is_no_frame_evidence(self):
        self.write([])
        result = self.report()
        self.assertEqual(result["status"], "NO_FRAME_EVIDENCE")
        self.assertEqual(result["sessions"], [])

    def test_no_final_summary_is_incomplete_not_approved(self):
        self.write([row()], final=False)
        result = self.report()
        self.assertTrue(result["missing_live_summary"])
        self.assertEqual(result["status"], "INCOMPLETE_CAPTURE")

    def test_failed_or_inconsistent_finalization_is_incomplete(self):
        self.write([row()])
        for change in (dict(runtime_status="RUN_FAILED"), dict(worker_error="synthetic failure"),
                       dict(cleanup_errors=["failed"]), dict(run_error="failed"),
                       dict(shutdown=dict(worker_stopped=True, scene_job_running=True, shutdown_complete=True))):
            with self.subTest(change=change):
                final = dict(finalized(), **change)
                (self.input/"live_summary.json").write_text(json.dumps(final))
                output = self.root/("case_"+str(len(list(self.root.iterdir()))))
                result = summarize(self.input, output, plots=False)
                self.assertEqual(result["status"], "INCOMPLETE_CAPTURE")

    def test_truncated_last_line_requires_explicit_option_and_stays_incomplete(self):
        self.write([row()])
        with (self.input/"distance_frames.jsonl").open("ab") as stream:
            stream.write(b'{"session":')
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            self.report()
        self.assertFalse(self.output.exists())
        result = self.report(allow_truncated_last_line=True)
        self.assertEqual(result["processed_frames"], 1)
        self.assertTrue(result["truncated_final_line_ignored"])
        self.assertEqual(result["status"], "INCOMPLETE_CAPTURE")

    def test_invalid_middle_or_newline_terminated_line_is_never_skipped(self):
        for payload in (b"broken\n", b"broken\n"+json.dumps(row()).encode()):
            with self.subTest(payload=payload):
                (self.input/"distance_frames.jsonl").write_bytes(payload)
                with self.assertRaisesRegex(ValueError, "invalid JSON"):
                    self.report(allow_truncated_last_line=True)

    def test_valid_last_object_without_newline_is_not_truncated(self):
        self.write([row()])
        (self.input/"distance_frames.jsonl").write_text(json.dumps(row()))
        result = self.report()
        self.assertFalse(result["truncated_final_line_ignored"])
        self.assertEqual(result["status"], "FINALIZED_DIAGNOSTIC_LOG")

    def test_duplicate_or_reverse_frame_or_time_is_rejected(self):
        cases = ([row(), row()], [row(), row(frame=2, source=9.)],
                 [row(frame=3), row(frame=2, source=11.)])
        for rows in cases:
            with self.subTest(rows=rows):
                self.write(rows)
                with self.assertRaisesRegex(ValueError, "nonincreasing"):
                    self.report()

    def test_retired_session_may_not_reappear(self):
        self.write([row(), row("second", 1, 11.), row("first", 2, 12.)])
        with self.assertRaisesRegex(ValueError, "retired session"):
            self.report()

    def test_available_distance_cannot_have_blockers_or_expired_age(self):
        for change in (dict(blockers=["blocked"]), dict(scene_initialized=False), dict(scene_pending=True),
                       dict(quality_accepted=False), dict(reason="withheld"), dict(distance_forward_m=0.),
                       dict(completed_time_sec=10.6, frame_age_ms=600.)):
            with self.subTest(change=change):
                self.write([dict(row(available=True), **change)])
                with self.assertRaisesRegex(ValueError, "inconsistent available"):
                    self.report()

    def test_withheld_distance_has_no_stale_numeric_output(self):
        self.write([dict(row(), distance_forward_m=1.3)])
        with self.assertRaisesRegex(ValueError, "withheld distance"):
            self.report()

    def test_nonfinite_bool_and_wrong_numeric_types_are_rejected(self):
        for change in (dict(predict_ms=float("nan")), dict(lateral_right_m=float("inf")),
                       dict(distance_available=1), dict(frame=True), dict(predict_ms="3"),
                       dict(source_time_sec=True), dict(predict_ms=10**400), dict(reason="")):
            with self.subTest(change=change):
                self.write([dict(row(), **change)])
                with self.assertRaises(ValueError):
                    self.report()

    def test_inconsistent_age_is_rejected(self):
        self.write([dict(row(), frame_age_ms=100.)])
        with self.assertRaisesRegex(ValueError, "frame age inconsistent"):
            self.report()

    def test_unapproved_coordinate_or_physical_claims_are_rejected(self):
        for change in (dict(physical_metric_verified=True), dict(usable_for_ffb=True),
                       dict(floor_contact_verified=True), dict(target_frame="base_link")):
            with self.subTest(change=change):
                self.write([dict(row(), **change)])
                with self.assertRaises(ValueError):
                    self.report()

    def test_summary_physical_output_claim_is_not_accepted(self):
        self.write([row()])
        (self.input/"live_summary.json").write_text(json.dumps(dict(finalized(), physical_output=True)))
        with self.assertRaisesRegex(ValueError, "summary flag"):
            self.report()

    def test_target_scope_is_preserved_and_roi_conflicts_are_rejected(self):
        self.write([row()])
        result = self.report()
        self.assertEqual(result["sessions"][0]["target_roi_native_xyxy"], [270, 0, 350, 720])
        self.assertIn("範囲の外は監視対象外", (self.output/"report.md").read_text())
        self.write([row(), dict(row(frame=2, source=11.), target_roi_native_xyxy=None)])
        with self.assertRaisesRegex(ValueError, "ROI changed"):
            summarize(self.input, self.root/"conflict", plots=False)
        self.write([row()])
        (self.input/"live_summary.json").write_text(json.dumps(dict(finalized(), target_roi_native_xyxy=None)))
        with self.assertRaisesRegex(ValueError, "ROI disagrees"):
            summarize(self.input, self.root/"conflict", plots=False)

    def test_primary_reason_and_all_blockers_are_counted_separately(self):
        first = row()
        first["blockers"] += ["support_pending", "support_pending"]
        self.write([first])
        session = self.report()["sessions"][0]
        self.assertEqual(session["reasons"], {"scene_initialization_pending": 1})
        self.assertEqual(session["blockers"], {"scene_initialization_pending": 1, "support_pending": 1})

    def test_existing_output_and_inputs_are_not_overwritten(self):
        self.write([row()])
        self.output.mkdir()
        sentinel = self.output/"sentinel"
        sentinel.write_text("keep")
        with self.assertRaisesRegex(ValueError, "new report"):
            self.report()
        self.assertEqual(sentinel.read_text(), "keep")

    def test_quantile_and_empty_stats(self):
        self.assertEqual(statistics([]), dict(count=0, median=None, p95=None, maximum=None))
        self.assertEqual(statistics([2.])["p95"], 2.)
        self.assertAlmostEqual(statistics([0., 10.])["p95"], 9.5)

    def test_graph_is_generated_and_marked_as_injected_test_data(self):
        self.write([row(), row(frame=2, source=10.1, available=True)])
        result = summarize(self.input, self.output)
        self.assertTrue(result["plots_generated"])
        self.assertTrue(result["contains_injected_or_unverified_predictor"])
        plot = self.output/"processing_diagnostics.png"
        self.assertTrue(plot.read_bytes().startswith(b"\x89PNG"))
        self.assertIn("processing_diagnostics.png", result["output_sha256"])

    def test_cli_missing_input_is_an_error_not_no_evidence(self):
        self.assertEqual(main(["--input-dir", str(self.root/"missing"), "--output-dir", str(self.output), "--no-plots"]), 1)

    def test_launcher_report_dispatch_needs_no_camera_or_model(self):
        self.write([row()])
        import os
        result = subprocess.run(["bash", str(ROOT/"start_cone_distance.sh"), "report", "--input-dir",
            str(self.input), "--output-dir", str(self.output), "--no-plots"],
            env=dict(os.environ, THETA_DISTANCE_PYTHON=sys.executable), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT physical approval", result.stdout)


if __name__ == "__main__":
    unittest.main()
