import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from virtual_ffb import VirtualFfbPolicy, summarize_rows  # noqa: E402


class VirtualFfbPolicyTest(unittest.TestCase):
    def test_clear_and_path_do_not_request_feedback(self):
        policy = VirtualFfbPolicy()

        self.assertFalse(policy.command("CLEAR").active)
        self.assertFalse(policy.command("PATH").active)

    def test_warning_hold_preserves_warning_magnitude(self):
        policy = VirtualFfbPolicy()

        warning = policy.command("WARNING")
        held = policy.command("WARNING_HOLD")

        self.assertTrue(warning.active)
        self.assertEqual(held.normalized_magnitude, warning.normalized_magnitude)
        self.assertEqual(held.pattern, "steady_hold")

    def test_unknown_input_does_not_fail_silent(self):
        command = VirtualFfbPolicy().command("")

        self.assertTrue(command.active)
        self.assertEqual(command.risk_level, "UNKNOWN")
        self.assertEqual(command.pattern, "pulse")

    def test_rejects_unsafe_magnitude_order(self):
        with self.assertRaises(ValueError):
            VirtualFfbPolicy(warning_magnitude=0.5, critical_magnitude=0.4)

    def test_summary_counts_activations_and_levels(self):
        rows = [
            {"collision_risk_level": "CLEAR"},
            {"collision_risk_level": "WARNING"},
            {"collision_risk_level": "WARNING_HOLD"},
            {"collision_risk_level": "CLEAR"},
            {"collision_risk_level": "UNKNOWN"},
        ]

        result = summarize_rows("trial", "label", rows)

        self.assertEqual(result["active_frames"], 3)
        self.assertEqual(result["warning_frames"], 1)
        self.assertEqual(result["warning_hold_frames"], 1)
        self.assertEqual(result["unknown_frames"], 1)
        self.assertEqual(result["activation_events"], 2)


if __name__ == "__main__":
    unittest.main()
