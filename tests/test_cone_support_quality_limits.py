"""Regression of LIMITATIONS: image continuity is never physical-base proof."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cone_support_quality import ConeSupportQualityGate


class ImageContinuityLimitTests(unittest.TestCase):
    def test_stable_initial_upper_fragment_is_accepted_but_remains_unverified(self):
        gate = ConeSupportQualityGate()
        fragment = dict(support=[(x, 350) for x in range(300, 320)])
        results = [gate.update(i/30, [fragment]) for i in range(1, 5)]
        self.assertTrue(results[-1]["quality_accepted"])
        self.assertFalse(results[-1]["floor_contact_verified"])
        self.assertFalse(results[-1]["usable_for_ffb"])

    def test_slowly_shrinking_and_rising_edge_can_be_followed_not_claimed_as_detected_occlusion(self):
        gate = ConeSupportQualityGate()
        # Simulated gradually lost base: every image change fits the local
        # continuity model. No hidden physical label is supplied to the gate.
        results = []
        for frame in range(1, 31):
            changed = max(0, frame-5)
            sample = dict(support=[(x, 400-changed) for x in range(300, 340-changed)])
            results.append(gate.update(frame/30, [sample]))
        self.assertTrue(all(r["quality_accepted"] for r in results[2:]))
        self.assertLess(results[-1]["observed_x_hi"], results[4]["observed_x_hi"])
        self.assertLess(results[-1]["observed_y_max"], results[4]["observed_y_max"])
        self.assertTrue(all(not r["floor_contact_verified"] and not r["usable_for_ffb"] for r in results))


if __name__ == "__main__":
    unittest.main()
