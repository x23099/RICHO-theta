"""Offline synthetic logs only. No capture, model, ROS or network."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from report_driver_motion_logs import COMPACT, distribution, read_jsonl, report, summarize


def frame(n=1, session="a"*32, available=True):
    source = 10. + .1*n
    return dict(schema="cone_motion_range_v1", session=session, frame=n,
                source_time_sec=source, media_time_sec=.1*n, completed_time_sec=source+.02,
                distance_available=available, horizontal_camera_foot_range_m=1. if available else None,
                reason="synthetic" if available else "synthetic_withheld", primary_model="ippe_0",
                physical_metric_verified=False, floor_contact_verified=False, controlling_distance=False,
                usable_for_ffb=False, published_to_ros=False, frame_age_ms=20., predict_ms=10.,
                support_geometry_ms=5., inference_source="synthetic_NOT_live_cuda", profile_sha256="b"*64)


def event(row, accepted=True):
    return dict(result={k: row[k] for k in COMPACT}, accepted_current_session_and_age=accepted)


class MotionLogReportTests(unittest.TestCase):
    def test_counts_not_gui_time_and_no_false_accuracy(self):
        rows = [frame(1), frame(2, available=False), frame(4)]
        out, _ = summarize(rows, [event(rows[0]), event(rows[1]), event(rows[2], False)])
        s = out["sessions"][0]
        self.assertEqual((s["numeric_results"], s["bridge_accepted_numeric"], s["bridge_retired"]), (2, 1, 1))
        self.assertAlmostEqual(s["processed_result_interval_hz"], 2/.3)
        self.assertAlmostEqual(s["processed_withheld_fraction"], 1/3)
        self.assertIsNone(out["gui_time_withheld_fraction"])
        self.assertIsNone(out["physical_accuracy_error_m"])
        self.assertIsNone(out["end_to_end_camera_latency_ms"])
        self.assertEqual(s["inference_sources"], {"synthetic_NOT_live_cuda": 3})

    def test_session_clocks_are_not_merged(self):
        rows = [frame(1), frame(2), frame(1, "c"*32)]
        out, _ = summarize(rows, [event(r) for r in rows])
        self.assertEqual(len(out["sessions"]), 2)
        self.assertIsNone(out["sessions"][1]["processed_result_interval_hz"])

    def test_missing_bridge_event_is_not_silently_counted_as_accepted(self):
        rows = [frame(1), frame(2)]
        out, _ = summarize(rows, [event(rows[0])])
        self.assertEqual(out["sessions"][0]["frames_without_bridge_event"], 1)
        self.assertEqual(out["sessions"][0]["bridge_accepted"], 1)

    def test_duplicate_and_wrong_pair_rejected(self):
        a, b = frame(), frame(2)
        for rows, events in (([a, a], []), ([a], [event(a), event(a)]), ([a], [event(b)])):
            with self.subTest(rows=rows, events=events), self.assertRaises(ValueError):
                summarize(rows, events)
        bad = event(a)
        bad["result"]["reason"] = "other_run"
        with self.assertRaises(ValueError):
            summarize([a], [bad])

    def test_bad_types_numbers_flags_and_timing_rejected(self):
        changes = [dict(frame=True), dict(distance_available=1), dict(predict_ms=float("nan")),
                   dict(frame_age_ms=-1), dict(frame_age_ms=1), dict(source_time_sec=100),
                   dict(physical_metric_verified=True), dict(horizontal_camera_foot_range_m=float("inf")),
                   dict(inference_source=None), dict(profile_sha256="unknown")]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize([{**frame(), **change}], [])

    def test_nonincreasing_times_and_profile_change_rejected(self):
        a = frame()
        for change in (dict(media_time_sec=.1), dict(profile_sha256="c"*64)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize([a, {**frame(2), **change}], [])

    def test_withheld_value_and_nonboolean_acceptance_rejected(self):
        a = frame(available=False)
        with self.assertRaises(ValueError):
            summarize([{**a, "horizontal_camera_foot_range_m": 1.}], [])
        e = event(a)
        e["accepted_current_session_and_age"] = 1
        with self.assertRaises(ValueError):
            summarize([a], [e])

    def test_percentiles_nearest_rank_and_empty(self):
        self.assertEqual(distribution(range(1, 21))["p95"], 19)
        self.assertIsNone(distribution([])["max"])

    def test_reader_rejects_truncation_duplicates_nonfinite_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"log.jsonl"
            for data in (b'', b'{}', b'{"a":NaN}\n', b'{"a":1,"a":2}\n', b'[]\n'):
                path.write_bytes(data)
                with self.subTest(data=data), self.assertRaises(ValueError):
                    read_jsonl(path)

    def test_scalar_projection_keeps_same_input_hash_and_still_checks_nested_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"log.jsonl"
            path.write_text('{"keep":1,"large":{"support":[1,2,3]}}\n')
            full, sha = read_jsonl(path)
            projected, projected_sha = read_jsonl(path, fields=("keep", "missing"))
            self.assertEqual(projected, [{"keep": 1}])
            self.assertEqual(sha, projected_sha)
            self.assertIn("large", full[0])
            path.write_text('{"keep":1,"large":{"bad":NaN}}\n')
            with self.assertRaises(ValueError):
                read_jsonl(path, fields=("keep",))

    def test_report_does_not_overwrite_or_modify_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root/"input"
            input_dir.mkdir()
            a = frame()
            files = {"motion_distance_frames.jsonl": json.dumps(a)+"\n",
                     "motion_bridge_events.jsonl": json.dumps(event(a))+"\n"}
            for name, content in files.items():
                (input_dir/name).write_text(content)
            report(input_dir, root/"report")
            self.assertTrue((root/"report"/"frames.csv").is_file())
            for name, content in files.items():
                self.assertEqual((input_dir/name).read_text(), content)
            with self.assertRaises(FileExistsError):
                report(input_dir, root/"report")
            with self.assertRaises(ValueError):
                report(input_dir, input_dir/"output")


if __name__ == "__main__":
    unittest.main()
