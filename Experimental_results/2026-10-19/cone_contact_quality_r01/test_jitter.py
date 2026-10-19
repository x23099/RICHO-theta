import copy
import json
from pathlib import Path
import unittest

import audit_jitter as audit
from cone_dataset import read_csv, sha256


def row(frame, x, z=2, **extra):
    return dict(dict(dataset="test", session="s", condition="same", model="h59", method="colour",
                     frame=str(frame), candidate_x_m=str(x) if x is not None else "",
                     candidate_z_m=str(z) if x is not None else "", reason="confirmation_pending",
                     quality_accepted="False"), **extra)


class JitterTests(unittest.TestCase):
    def test_adjacent_pair_and_metrics(self):
        rows = [row(1, 0), row(2, .2, 2.01)]
        before = copy.deepcopy(rows)
        steps = audit.differences(rows)
        self.assertAlmostEqual(steps[0]["dx_m"], .2)
        summary = audit.summarize(steps)[0]
        self.assertEqual(summary["step_over_015m"], 1)
        self.assertEqual(summary["mostly_x_steps_over_015m"], 1)
        self.assertEqual(rows, before)

    def test_missing_projection_or_frame_gap_never_bridged(self):
        for rows in ([row(1, 0), row(2, None), row(3, 1)], [row(1, 0), row(3, 1)]):
            self.assertEqual(audit.differences(rows), [])

    def test_condition_session_model_method_boundaries_not_mixed(self):
        for field in ("condition", "session", "model", "method"):
            self.assertEqual(audit.differences([row(1, 0), row(2, 1, **{field: "other"})]), [])

    def test_saved_statistics_and_input_output_hashes_reproduce(self):
        base = Path(__file__).resolve().parent
        directory = base / "jitter_r01"
        data = read_csv(base / "results_r02/observations.csv")
        steps = audit.differences(data)
        self.assertEqual([{k: str(v) for k, v in r.items()} for r in steps], read_csv(directory / "consecutive_steps.csv"))
        self.assertEqual([{k: str(v) for k, v in r.items()} for r in audit.summarize(steps)], read_csv(directory / "jitter_summary.csv"))
        provenance = json.loads((directory / "provenance.json").read_text())
        for path, digest in provenance["source_sha256"].items():
            self.assertEqual(sha256(Path(path)), digest)
        for name, digest in provenance["output_sha256"].items():
            self.assertEqual(sha256(directory / name), digest)

    def test_rerun_after_correcting_test_expectation_changed_no_measurements(self):
        base = Path(__file__).resolve().parent
        for name in ("observations.csv", "summary.csv", "withheld_runs.csv", "occlusion_rows.csv",
                     "occlusion_quality_comparison.png", "coverage_and_remaining_bias.png"):
            self.assertEqual(sha256(base / "results_r01" / name), sha256(base / "results_r02" / name))


if __name__ == "__main__":
    unittest.main()
