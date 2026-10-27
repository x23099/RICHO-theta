"""No-device cadence tests, including the existing nine-recording time grid."""
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scene_sampling_clock import FixedSceneCadence
from cone_distance_core import ConeDistanceEngine
from run_cone_distance_replay import read_rows
from theta_rtc_frames import NativeFrame


class SceneClockTest(unittest.TestCase):
    def test_first_image_anchors_origin_not_zero(self):
        clock = FixedSceneCadence()
        result = clock.take(12.03)
        self.assertEqual(result["target_time_sec"], 12.03)
        self.assertEqual(clock.next_target, 13.03)

    def test_frame_lateness_does_not_accumulate(self):
        clock = FixedSceneCadence()
        selected = []
        for value in (.05, 1.075, 2.05, 3.075, 4.05):
            if clock.due(value):
                selected.append(clock.take(value))
        self.assertEqual(len(selected), 5)
        self.assertEqual([r["target_time_sec"] for r in selected], [.05, 1.05, 2.05, 3.05, 4.05])
        self.assertEqual(clock.next_target, 5.05)

    def test_deadline_exact_included_previous_float_excluded(self):
        clock = FixedSceneCadence()
        clock.take(.03)
        self.assertFalse(clock.due(math.nextafter(clock.next_target, -math.inf)))
        self.assertTrue(clock.due(clock.next_target))

    def test_one_frame_crossing_many_deadlines_only_one_job(self):
        clock = FixedSceneCadence()
        clock.take(0.)
        result = clock.take(10.1)
        self.assertEqual(result["skipped_targets"], 9)
        self.assertEqual(result["target_time_sec"], 1.)
        self.assertEqual(clock.next_target, 11.)
        self.assertFalse(clock.due(10.1))

    def test_large_gap_does_not_loop_through_all_missed_jobs(self):
        clock = FixedSceneCadence()
        clock.take(0.)
        result = clock.take(10**12+.1)
        self.assertEqual(result["skipped_targets"], 10**12-1)
        self.assertGreater(clock.next_target, 10**12+.1)

    def test_busy_does_not_consume_deadline_or_queue_old_image(self):
        clock = FixedSceneCadence()
        clock.take(0.)
        self.assertFalse(clock.due(1.2, busy=True))
        self.assertFalse(clock.due(2.2, busy=True))
        self.assertEqual(clock.next_target, 1.)
        result = clock.take(2.3)
        self.assertEqual(result["source_time_sec"], 2.3)
        self.assertEqual(result["skipped_targets"], 1)
        self.assertEqual(clock.next_target, 3.)

    def test_due_queries_are_pure(self):
        clock = FixedSceneCadence()
        clock.take(0.)
        for _ in range(5):
            self.assertTrue(clock.due(1.2))
        self.assertEqual(clock.take(1.2)["target_time_sec"], 1.)

    def test_not_due_or_duplicate_take_refused(self):
        clock = FixedSceneCadence()
        clock.take(0.)
        for value in (0., .1, .999):
            with self.subTest(value=value), self.assertRaises(ValueError):
                clock.take(value)

    def test_invalid_interval_and_time_refused(self):
        for value in (0, -1, float("nan"), float("inf"), True, "1"):
            with self.subTest(interval=value), self.assertRaises(ValueError):
                FixedSceneCadence(value)
        for value in (-1, float("nan"), float("inf"), True, "0"):
            with self.subTest(time=value), self.assertRaises(ValueError):
                FixedSceneCadence().take(value)

    def test_reversed_source_after_selection_refused(self):
        clock = FixedSceneCadence()
        clock.take(1.)
        with self.assertRaises(ValueError):
            clock.due(.9)

    def test_unrepresentable_extreme_deadlines_refuse_without_catchup_loop(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            FixedSceneCadence().take(1e308)
        clock = FixedSceneCadence()
        clock.take(0.)
        with self.assertRaisesRegex(ValueError, "not representable"):
            clock.take(1e308)

    def test_every_prefix_has_identical_selected_jobs(self):
        times = [n*.034 for n in range(400)]
        def select(values):
            clock = FixedSceneCadence()
            return [(n, clock.take(t)) for n, t in enumerate(values) if clock.due(t)]
        all_jobs = select(times)
        for cut in (1, 50, 157, 399):
            self.assertEqual(select(times[:cut]), [r for r in all_jobs if r[0] < cut])

    def test_engine_reset_does_not_keep_old_origin(self):
        engine = ConeDistanceEngine()
        engine.reset("old")
        ticket = engine.begin_scene(NativeFrame("old", 1, 100., 100., None))
        self.assertEqual(ticket.target_time_sec, 100.)
        engine.reset("new")
        ticket = engine.begin_scene(NativeFrame("new", 1, 5., 5., None))
        self.assertEqual(ticket.target_time_sec, 5.)
        self.assertEqual(engine.scene_cadence.next_target, 6.)

    def test_source_age_not_replaced_by_target_time_after_busy_gap(self):
        engine = ConeDistanceEngine()
        engine.reset("test")
        first = engine.begin_scene(NativeFrame("test", 1, 0., 0., None))
        engine.complete_scene(first, dict(accepted=False, reason="test"), .1)
        late = engine.begin_scene(NativeFrame("test", 100, 3.3, 3.3, None))
        self.assertEqual(late.target_time_sec, 1.)
        engine.complete_scene(late, dict(accepted=False, reason="test"), 3.4)
        self.assertEqual(engine.pose.last_time, 3.3)


class RecordedGridTest(unittest.TestCase):
    def test_matches_all_preexisting_492_sample_frames_and_targets(self):
        path = ROOT / "Experimental_results/2026-10-22/scene_uniform_validation_r01/intake_r01/sampling_plan.json"
        plan = json.loads(path.read_text())
        count = 0
        for entry in plan["sessions"]:
            csv_path = Path(entry["session_path"]) / "detections.csv"
            if not csv_path.exists():
                self.skipTest("local original recording timestamps unavailable")
            clock = FixedSceneCadence()
            selected = []
            for row in read_rows(csv_path):
                t = float(row["time_sec"])
                if clock.due(t):
                    info = clock.take(t)
                    selected.append((int(row["frame"]), t, info["target_time_sec"]))
            expected = [(r["frame"], r["time_sec"], r["target_time_sec"]) for r in entry["selected"]]
            with self.subTest(session=entry["session"]):
                self.assertEqual(selected, expected)
            count += len(selected)
        self.assertEqual(count, 492)


if __name__ == "__main__":
    unittest.main()
