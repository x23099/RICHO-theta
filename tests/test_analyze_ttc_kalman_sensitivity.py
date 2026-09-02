import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from analyze_ttc_kalman_sensitivity import (  # noqa: E402
    classify_motion,
    replay_candidate,
    summarize_candidates,
    summarize_session,
)


def recorded_row(timestamp, z_m, odom=0.0, accepted=True):
    return {
        "time_sec": timestamp,
        "monotonic_time_sec": timestamp,
        "x_m": 0.0,
        "z_m": z_m,
        "measurement_accepted": int(accepted),
        "odom_linear_mps": odom,
    }


class TtcKalmanSensitivityTest(unittest.TestCase):
    def test_classifies_labelled_motion_and_stationary_odom(self):
        rows = [recorded_row(0.0, 1.0), recorded_row(0.1, 1.0)]
        self.assertEqual(classify_motion("approach_center_v0p10_r01", rows, 0.05), "approach")
        self.assertEqual(classify_motion("retreat_center_v0p10_r01", rows, 0.05), "retreat")
        self.assertEqual(classify_motion("static_center", rows, 0.05), "static")

    def test_replay_produces_causal_ttc_for_accepted_approach_measurements(self):
        rows = [recorded_row(index * 0.1, 1.2 - index * 0.02, 0.2) for index in range(20)]
        replayed = replay_candidate(rows, 1.5, 0.05, velocity_window_sec=0.3)
        self.assertEqual(len(replayed), len(rows))
        self.assertTrue(any(row["ttc_sec"] is not None for row in replayed))
        self.assertTrue(all(row["ttc_sec"] is None or row["ttc_sec"] > 0.0 for row in replayed))

    def test_static_summary_reports_no_false_ttc(self):
        rows = [recorded_row(index * 0.1, 1.0, 0.0) for index in range(20)]
        replayed = replay_candidate(rows, 1.5, 0.05)
        detail = summarize_session("static_center", "test", rows, replayed, 1.5, 0.05)
        self.assertEqual(detail["motion"], "static")
        self.assertEqual(detail["false_ttc_rate"], 0.0)
        summaries = summarize_candidates([detail])
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["max_static_false_ttc_rate"], 0.0)
        self.assertTrue(math.isnan(summaries[0]["max_approach_speed_mae_mps"]))


if __name__ == "__main__":
    unittest.main()
