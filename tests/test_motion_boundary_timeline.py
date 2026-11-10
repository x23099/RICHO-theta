"""Synthetic source/completion sequences only. No GUI or physical motion labels."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Experimental_results/2026-11-10/motion_boundary_timeline_r01"))
from timeline import summarize


def row(i, state="numeric_clear_of_body_boundary", timestamp=None):
    t = i / 30 if timestamp is None else timestamp
    return dict(session="a" * 32, frame=i, source_time_sec=t, completed_time_sec=t+.01,
                state=state, range_m=.7 if state.startswith("numeric") else None)


class TimelineTests(unittest.TestCase):
    def test_empty_input_is_not_a_successful_recovery(self):
        r = summarize([])
        self.assertEqual(r["conflict_episodes"], [])
        self.assertEqual(r["processed_records"], 0)

    def test_alternating_numeric_withheld_conflict_is_one_episode(self):
        states = ["numeric_clear_of_body_boundary", "numeric_body_boundary_conflict",
                  "boundary_withheld_body_boundary_conflict", "numeric_body_boundary_conflict",
                  "numeric_clear_of_body_boundary"]
        r = summarize([row(i, s) for i, s in enumerate(states, 1)])
        e = r["conflict_episodes"][0]
        self.assertEqual((e["first_frame"], e["last_frame"], e["count"]), (2, 4, 3))
        self.assertEqual(e["next_clear_numeric"]["frame"], 5)
        self.assertEqual(len(r["state_runs"]), 5)
        self.assertFalse(r["gui_hold_duration_measured"])

    def test_source_gap_splits_episode_and_does_not_invent_transition(self):
        r = summarize([row(1, "numeric_body_boundary_conflict"),
                       row(2, "numeric_body_boundary_conflict", timestamp=1.)])
        self.assertEqual(len(r["conflict_episodes"]), 2)
        self.assertEqual(r["transitions"], {})

    def test_other_withheld_breaks_conflict_episode(self):
        r = summarize([row(1, "numeric_body_boundary_conflict"), row(2, "other_withheld:no_candidate"),
                       row(3, "numeric_clear_of_body_boundary")])
        e = r["conflict_episodes"][0]
        self.assertEqual(e["next_processed"]["frame"], 2)
        self.assertEqual(e["next_clear_numeric"]["frame"], 3)

    def test_open_ended_episode_has_no_invented_recovery(self):
        r = summarize([row(1, "numeric_body_boundary_conflict")])
        e = r["conflict_episodes"][0]
        self.assertIsNone(e["next_processed"])
        self.assertIsNone(e["next_clear_numeric"])
        self.assertEqual(e["source_span_ms"], 0)

    def test_unknown_session_or_out_of_order_records_are_rejected(self):
        for altered in (dict(row(2), session="b" * 32), row(1), row(2, timestamp=.01)):
            with self.assertRaises(ValueError):summarize([row(1), altered])

    def test_invalid_times_or_limits_are_rejected(self):
        for value in (True, -1, float("nan")):
            with self.assertRaises(ValueError):summarize([], gap_limit_sec=value)
        for changed in (dict(source_time_sec=float("nan")), dict(completed_time_sec=0.), dict(frame=True)):
            with self.assertRaises(ValueError):summarize([dict(row(1), **changed)])

    def test_no_conflict_counts_every_row_in_runs(self):
        r = summarize([row(i) for i in range(1, 5)])
        self.assertEqual(r["conflict_episodes"], [])
        self.assertEqual(sum(x["count"] for x in r["state_runs"]), 4)


if __name__ == "__main__":
    unittest.main()
