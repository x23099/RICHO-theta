"""Stored-observation lifecycle assertions; fixture is explicitly synthetic."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT/"Experimental_results/2026-11-02/fixed_floor_lifecycle_replay_r01"
sys.path[:0] = [str(ROOT/"src"), str(HERE)]
spec = importlib.util.spec_from_file_location("lifecycle_replay_scenarios", HERE/"run.py")
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)
from replay import LogicalFileExecutor, audit_rows, run_case


class LifecycleReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.original, cls.models, cls.images, cls.schedule = scenario.synthetic_inputs(cls.folder)
        cls.rows, cls.flat, cls.summary = run_case(cls.original, cls.models, cls.images, cls.folder/"case",
            cls.schedule, kind="SYNTHETIC_ONLY_unit_test")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def row(self, frame):
        return self.rows[frame-1]

    def test_complete_rows_and_baseline_fields_unchanged(self):
        self.assertEqual(len(self.rows), 180)
        audit_rows(self.original, self.rows)
        self.assertEqual(self.summary["original_fields_unchanged"], 180)

    def test_model_never_applies_before_request_or_completion(self):
        self.assertTrue(all("fixed_floor_shadow" not in r for r in self.rows[:12]))
        self.assertEqual(self.row(13)["fixed_floor_load"]["activated_frame"], 13)
        self.assertLessEqual(self.row(13)["fixed_floor_load"]["load_completed_at_sec"], self.row(13)["source_time_sec"])

    def test_three_quality_frames_required_after_activation(self):
        self.assertFalse(self.flat[12]["comparison_available"])
        self.assertFalse(self.flat[13]["comparison_available"])
        self.assertTrue(self.flat[14]["comparison_available"])

    def test_missing_observation_never_carries_last_distance(self):
        self.assertTrue(all(not r["comparison_available"] for r in self.flat[34:44]))
        self.assertFalse(self.flat[44]["comparison_available"])
        self.assertFalse(self.flat[45]["comparison_available"])
        self.assertTrue(self.flat[46]["comparison_available"])

    def test_stale_processing_revokes_all_comparison_models(self):
        self.assertAlmostEqual(self.row(60)["frame_age_ms"], 600., places=7)
        self.assertFalse(self.flat[59]["comparison_available"])
        self.assertEqual(self.flat[59]["comparison_reason"], "frame_processing_too_old")

    def test_disconnect_requires_manual_reload(self):
        self.assertTrue(all("fixed_floor_shadow" not in r for r in self.rows[70:87]))
        self.assertTrue(self.flat[89]["comparison_available"])
        self.assertTrue(all("fixed_floor_shadow" not in r for r in self.rows[160:]))

    def test_bad_reload_immediately_revokes_model_and_never_falls_back(self):
        self.assertTrue(self.flat[109]["comparison_available"])
        self.assertTrue(all("fixed_floor_shadow" not in r for r in self.rows[110:132]))
        self.assertEqual(self.row(113)["fixed_floor_load"]["state"], "rejected")
        self.assertTrue(self.flat[134]["comparison_available"])

    def test_authority_and_timing_claims_never_granted(self):
        self.assertFalse(self.summary["physical_metric_verified"])
        self.assertFalse(self.summary["usable_for_ffb"])
        self.assertTrue(self.summary["logical_schedule_is_not_measured_latency"])
        for row in self.rows:
            self.assertFalse(row["fixed_floor_load"]["controlling_distance"])

    def test_auditor_refuses_baseline_mutation(self):
        changed = copy.deepcopy(self.rows)
        changed[0]["reason"] = "forged"
        with self.assertRaises(ValueError):
            audit_rows(self.original, changed)

    def test_auditor_refuses_time_reversal_even_when_both_sides_match(self):
        changed = copy.deepcopy([self.rows[1], self.rows[0]])
        original = copy.deepcopy([self.original[1], self.original[0]])
        with self.assertRaisesRegex(ValueError, "increasing"):
            audit_rows(original, changed)

    def test_auditor_refuses_early_activation(self):
        changed = copy.deepcopy(self.rows)
        changed[12]["fixed_floor_load"]["load_completed_at_sec"] += 1.
        with self.assertRaises(ValueError):
            audit_rows(self.original, changed)

    def test_auditor_refuses_stale_value_release(self):
        changed = copy.deepcopy(self.rows)
        fixed = changed[59]["fixed_floor_shadow"]
        fixed["models"][0].update(range_available=True, horizontal_camera_foot_range_m=1.)
        with self.assertRaises(ValueError):
            audit_rows(self.original, changed)

    def test_absent_action_frames_and_repeated_input_are_not_fabricated(self):
        with self.assertRaises(ValueError):
            run_case(self.original, self.models, self.images, self.folder/"invalid-action",
                [dict(after_frame=999, action="request")], kind="SYNTHETIC_ONLY")
        with self.assertRaises(ValueError):
            run_case(self.original[:2]+self.original[:1], self.models, self.images, self.folder/"repeated",
                [], kind="SYNTHETIC_ONLY")

    def test_existing_output_not_overwritten(self):
        with self.assertRaises(FileExistsError):
            run_case(self.original, self.models, self.images, self.folder/"case", [], kind="SYNTHETIC_ONLY")

    def test_end_of_input_does_not_invent_a_post_load_frame(self):
        rows, _, summary = run_case(self.original[:1], self.models, self.images, self.folder/"last-frame-only",
            [dict(after_frame=1, action="request")], kind="SYNTHETIC_ONLY")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("fixed_floor_shadow", rows[0])
        self.assertEqual(summary["load_event_counts"].get("accepted", 0), 0)
        self.assertEqual(summary["comparison_available_rows"], 0)
        self.assertFalse(summary["shutdown"]["model_load_running"])

    def test_wrong_session_cannot_be_rebound(self):
        other = copy.deepcopy(self.original[:25])
        for row in other:
            row["session"] = "other_SYNTHETIC_session"
        # Frame evidence includes its own session: leave this test focused on
        # the loader, not forging a real image identity.
        other = [{k:v for k,v in r.items() if k != "frame_evidence"} for r in other]
        rows, _, summary = run_case(other, self.models, self.images, self.folder/"other-session",
            [dict(after_frame=10, action="request")], kind="SYNTHETIC_ONLY_other_session")
        self.assertEqual(summary["comparison_available_rows"], 0)
        self.assertTrue(all("fixed_floor_shadow" not in row for row in rows))
        self.assertEqual(rows[-1]["fixed_floor_load"]["reason"], "load_failed:ValueError")


if __name__ == "__main__":
    unittest.main()
