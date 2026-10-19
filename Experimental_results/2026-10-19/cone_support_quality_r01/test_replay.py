import copy
import json
from pathlib import Path
import unittest

import replay as run
from cone_dataset import read_csv, sha256


def strings(rows):
    return [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows]


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.curves, cls.hashes = run.load_inputs()
        cls.rows = run.replay_frames(cls.source, cls.curves)
        cls.directory = run.HERE / "results_r02"

    def test_all_frames_and_exact_saved_replay_reproduced(self):
        self.assertEqual(len(self.rows), 5143)
        self.assertEqual(len({run.key(r) for r in self.rows}), 5143)
        self.assertEqual(strings(self.rows), read_csv(self.directory / "observations.csv"))

    def test_summaries_and_withheld_intervals_reproduced(self):
        self.assertEqual(strings(run.summarize(self.rows)), read_csv(self.directory / "summary.csv"))
        self.assertEqual(strings(run.withheld_runs(self.rows)), read_csv(self.directory / "withheld_runs.csv"))

    def test_no_prediction_fill_and_actual_observed_support_bounds_only(self):
        for r in self.rows:
            self.assertFalse(r["floor_contact_verified"])
            self.assertFalse(r["usable_for_ffb"])
            if not r["quality_accepted"]:
                self.assertEqual(r["observed_columns"], 0)
                self.assertIsNone(r["observed_x_lo"])
                self.assertIsNone(r["observed_x_hi"])
                self.assertIsNone(r["observed_y_min"])
                self.assertIsNone(r["observed_y_max"])
            else:
                curve = self.curves[run.key(r)]
                self.assertEqual(r["observed_columns"], len(curve))
                self.assertEqual(r["observed_x_lo"], min(x for x, _ in curve))
                self.assertEqual(r["observed_x_hi"], max(x for x, _ in curve))
                self.assertEqual(r["observed_y_min"], min(y for _, y in curve))
                self.assertEqual(r["observed_y_max"], max(y for _, y in curve))

    def test_existing_occlusion_rejected_and_recovery_count_restart_explained(self):
        group = {r["frame"]: r for r in self.rows if r["dataset"] == "sequence"}
        self.assertTrue(all(not group[i]["quality_accepted"] for i in range(1124, 1139)))
        self.assertTrue(group[1139]["quality_accepted"])
        for frame in (1133, 1134):
            self.assertIn("abrupt_support_width_change", json.loads(group[frame]["comparison_failures"]))
            self.assertIn("abrupt_lower_boundary_y_change", json.loads(group[frame]["comparison_failures"]))
        self.assertEqual(group[1137]["confirmation_count"], 1)
        self.assertEqual(json.loads(group[1137]["pending_comparison_failures"]), ["abrupt_support_endpoint_change"])
        self.assertEqual(group[1137]["pending_endpoint_change_px"], 7)
        self.assertEqual(group[1137]["pending_endpoint_limit_px"], 5)

    def test_non_linear_envelopes_can_be_accepted_but_missing_and_multiple_cannot(self):
        self.assertTrue(any(r["quality_accepted"] and not r["input_line_consistent"] for r in self.rows))
        for r in self.rows:
            if r["candidates"] != 1 or not r["input_envelope_available"]:
                self.assertFalse(r["quality_accepted"])
        no_target = [r for r in self.rows if r["dataset"] == "static" and r["condition"] == "none"]
        self.assertEqual(len(no_target), 332)
        self.assertTrue(all(r["observed_columns"] == 0 for r in no_target))

    def test_causal_prefix_source_immutable_and_line_labels_not_used_by_gate(self):
        source = copy.deepcopy(self.source[:100])
        curves = {run.key(r): self.curves[run.key(r)] for r in source if run.key(r) in self.curves}
        before = copy.deepcopy((source, curves))
        prefix = run.replay_frames(source, curves)
        self.assertEqual(prefix, self.rows[:100])
        self.assertEqual((source, curves), before)
        relabelled = [dict(r, condition="not_used", line_consistent=not r["line_consistent"], reference_z_m=99) for r in source]
        changed = run.replay_frames(relabelled, curves)
        for a, b in zip(prefix, changed):
            self.assertEqual({k: v for k, v in a.items() if k not in ("condition", "input_line_consistent")},
                             {k: v for k, v in b.items() if k not in ("condition", "input_line_consistent")})

    def test_incomplete_duplicate_orphan_curves_and_guard_mismatch_rejected(self):
        subset = self.source[:5]
        curves = {run.key(r): self.curves[run.key(r)] for r in subset}
        for source in (subset[1:], subset+[subset[-1]]):
            with self.assertRaises(ValueError):
                run.replay_frames(source, curves)
        with self.assertRaises(ValueError):
            run.replay_frames(subset, {**curves, ("orphan", "orphan", 1): [(1, 2)]})
        with self.assertRaises(ValueError):
            run.replay_frames([dict(subset[0], envelope_available=False)]+subset[1:], curves)

    def test_pending_telemetry_did_not_change_any_initial_decision_or_metric(self):
        initial = read_csv(run.HERE / "results_r01/observations.csv")
        updated = read_csv(self.directory / "observations.csv")
        self.assertEqual(len(initial), len(updated))
        for a, b in zip(initial, updated):
            self.assertEqual(a, {k: b[k] for k in a})
        self.assertEqual(sha256(run.HERE / "results_r01/summary.csv"), sha256(self.directory / "summary.csv"))

    def test_frozen_input_output_config_and_module_hashes_unchanged(self):
        provenance = json.loads((self.directory / "provenance.json").read_text())
        for path, digest in {**self.hashes, **provenance["source_sha256"]}.items():
            self.assertEqual(sha256(Path(path)), digest, path)
        for name, digest in provenance["output_sha256"].items():
            self.assertEqual(sha256(self.directory / name), digest, name)


if __name__ == "__main__":
    unittest.main()
