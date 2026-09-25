import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from publish_mock_odom_scenario import (  # noqa: E402
    build_scenario_schedule,
    validate_topic,
)


class MockOdomScenarioTest(unittest.TestCase):
    def test_builds_stop_move_stop_schedule(self):
        schedule = build_scenario_schedule(
            lead_in_sec=2.0,
            motion_sec=4.0,
            lead_out_sec=2.0,
            speed_mps=0.25,
            rate_hz=10.0,
        )

        self.assertEqual(len(schedule), 80)
        self.assertEqual(schedule[0].phase, "initial_stop")
        self.assertEqual(schedule[19].linear_mps, 0.0)
        self.assertEqual(schedule[20].phase, "forward_0p25")
        self.assertEqual(schedule[20].linear_mps, 0.25)
        self.assertEqual(schedule[59].linear_mps, 0.25)
        self.assertEqual(schedule[60].phase, "final_stop")
        self.assertEqual(schedule[-1].linear_mps, 0.0)
        self.assertEqual(
            [sample.sequence for sample in schedule], list(range(80))
        )

    def test_refuses_live_odom_and_non_phase5_topics(self):
        for topic in ("/odom", "odom", "/other/mock_odom", "/phase5/"):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                validate_topic(topic)
        self.assertEqual(validate_topic("/phase5/mock_odom"), "/phase5/mock_odom")

    def test_rejects_unsafe_scenario_limits(self):
        for kwargs in (
            {"motion_sec": 0.0},
            {"motion_sec": 121.0},
            {"speed_mps": 0.51},
            {"rate_hz": 9.0},
            {"rate_hz": 61.0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_scenario_schedule(**kwargs)


if __name__ == "__main__":
    unittest.main()
