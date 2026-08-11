import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from evaluate_ttc_replay import add_causal_velocity_and_ttc  # noqa: E402


class TtcReplayTest(unittest.TestCase):
    def test_ttc_is_only_computed_for_approaching_velocity_beyond_deadband(self):
        rows = [
            {
                "time_sec": 0.0,
                "track_available": 1,
                "filtered_z_m": 1.0,
                "relative_vz_mps": -0.10,
            },
            {
                "time_sec": 0.1,
                "track_available": 1,
                "filtered_z_m": 0.9,
                "relative_vz_mps": 0.0,
            },
        ]

        result = add_causal_velocity_and_ttc(rows, 0.2, 0.05)

        self.assertAlmostEqual(result[0]["ttc_sec"], 10.0)
        self.assertTrue(math.isnan(result[1]["ttc_sec"]))


if __name__ == "__main__":
    unittest.main()
