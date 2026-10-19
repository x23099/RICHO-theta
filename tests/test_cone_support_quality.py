import copy
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cone_support_quality import ConeSupportQualityGate, SupportQualitySettings


def sample(x=300, y=400, width=40):
    return dict(support=[(a, y) for a in range(x, x+width)])


class SupportQualityTests(unittest.TestCase):
    def setUp(self):
        self.gate = ConeSupportQualityGate()

    def update(self, frame, candidates=None, **kwargs):
        return self.gate.update(frame/30, [sample()] if candidates is None else candidates, **kwargs)

    def initialize(self):
        return [self.update(i) for i in range(1, 6)][-1]

    def test_first_three_frames_required_no_metric_or_ffb_permission(self):
        for frame in range(1, 7):
            r = self.update(frame)
            self.assertEqual(r["quality_accepted"], frame >= 3)
            self.assertFalse(r["floor_contact_verified"])
            self.assertFalse(r["usable_for_ffb"])
            if frame < 3:
                self.assertIsNone(r["observed_support"])

    def test_missing_never_returns_held_or_predicted_observation(self):
        self.initialize()
        r = self.update(6, [])
        self.assertTrue(r["anchor_present"])
        self.assertFalse(r["quality_accepted"])
        self.assertIsNone(r["observed_support"])
        self.assertIsNone(r["observed_x_lo"])

    def test_missing_recovery_requires_three_consecutive_frames(self):
        self.initialize()
        self.update(6, [])
        self.assertEqual([self.update(i)["quality_accepted"] for i in range(7, 10)], [False, False, True])

    def test_interrupted_pending_restarts(self):
        self.update(1)
        self.update(2, [])
        self.assertEqual([self.update(i)["quality_accepted"] for i in range(3, 6)], [False, False, True])

    def test_abrupt_shrink_rejected_anchor_is_not_poisoned(self):
        self.initialize()
        anchor = self.gate.anchor
        bad = self.update(6, [sample(x=310, y=370, width=15)])
        self.assertFalse(bad["quality_accepted"])
        self.assertIn("abrupt_support_width_change", bad["comparison_failures"])
        self.assertIn("abrupt_lower_boundary_y_change", bad["comparison_failures"])
        self.assertEqual(anchor, self.gate.anchor)
        self.assertEqual([self.update(i)["quality_accepted"] for i in range(7, 10)], [False, False, True])

    def test_y_jump_alone_rejected(self):
        self.initialize()
        r = self.update(6, [sample(y=360)])
        self.assertEqual(r["reason"], "abrupt_lower_boundary_y_change")
        self.assertEqual(r["median_abs_y_change_px"], 40)

    def test_endpoint_jump_and_no_shared_columns(self):
        self.initialize()
        r = self.update(6, [sample(x=400)])
        self.assertIn("abrupt_support_endpoint_change", r["comparison_failures"])
        self.assertIn("insufficient_shared_observed_columns", r["comparison_failures"])
        self.assertIsNone(r["median_abs_y_change_px"])

    def test_common_columns_only_not_matching_different_x(self):
        tilted = dict(support=[(x, 250+x//2) for x in range(300, 340)])
        for i in range(1, 6):
            self.update(i, [tilted])
        shifted = dict(support=[(x, 250+x//2) for x in range(302, 342)])
        r = self.update(6, [shifted])
        self.assertTrue(r["quality_accepted"])
        self.assertEqual(r["median_abs_y_change_px"], 0)
        self.assertEqual(r["common_columns"], 38)

    def test_local_y_damage_p90_can_reject_even_if_median_is_small(self):
        self.initialize()
        changed = dict(support=[(x, 385 if x < 312 else 400) for x in range(300, 340)])
        r = self.update(6, [changed])
        self.assertEqual(r["median_abs_y_change_px"], 0)
        self.assertEqual(r["p90_abs_y_change_px"], 15)
        self.assertFalse(r["quality_accepted"])

    def test_bent_boundary_does_not_need_a_single_line(self):
        bent = dict(support=[(x, 380+abs(x-320)) for x in range(300, 340)], line_consistent=False)
        for frame in range(1, 6):
            r = self.update(frame, [bent])
        self.assertTrue(r["quality_accepted"])

    def test_missing_color_and_ambiguity_interrupt_confirmation(self):
        for candidates in ([dict(support=None, unavailable_reason="colour_contour_reaches_roi_edge")], [sample(), sample(x=350)]):
            self.gate.reset()
            self.initialize()
            self.assertFalse(self.update(6, candidates)["quality_accepted"])
            self.assertEqual([self.update(i)["quality_accepted"] for i in range(7, 10)], [False, False, True])

    def test_resolution_and_native_columns_validation(self):
        invalid = [sample(width=2), dict(support=[(1, 400)]*40), dict(support=[(x, 400) for x in reversed(range(300, 340))]),
                   dict(support=[(x+.5, 400) for x in range(300, 340)]), sample(y=720), sample(x=-1),
                   dict(support=np.ones((10, 2), complex)), dict(support=[(x, math.nan) for x in range(300, 340)]), None]
        for bad in invalid:
            self.gate.reset()
            self.assertFalse(self.update(1, [bad])["quality_accepted"])
        self.gate.reset()
        self.assertEqual(self.update(1, frame_width=640)["reason"], "native_resolution_mismatch")

    def test_disconnected_columns_not_interpolated(self):
        row = dict(support=[(x, 400) for x in list(range(300, 315))+list(range(325, 340))])
        r = self.update(1, [row])
        self.assertEqual(r["reason"], "disconnected_support")

    def test_frame_gap_requires_reconfirmation(self):
        self.initialize()
        self.assertFalse(self.update(20)["quality_accepted"])
        self.assertFalse(self.update(21)["quality_accepted"])
        self.assertTrue(self.update(22)["quality_accepted"])

    def test_bad_time_resets_state(self):
        for timestamp in (5/30, -1, math.nan, math.inf, "not_a_time"):
            self.gate.reset()
            self.initialize()
            with self.assertRaises(ValueError):
                self.gate.update(timestamp, [sample()])
            self.assertIsNone(self.gate.anchor)
            self.assertFalse(self.update(1)["quality_accepted"])

    def test_long_absence_expires_anchor_but_stable_wrong_boundary_can_reinitialize(self):
        self.initialize()
        for i in range(6, 45):
            self.update(i, [])
        self.assertIsNone(self.gate.anchor)
        # Documented limit: image continuity alone does not verify a visible base.
        rows = [self.update(i, [sample(x=400, y=350, width=20)]) for i in range(45, 48)]
        self.assertTrue(rows[-1]["quality_accepted"])
        self.assertFalse(rows[-1]["floor_contact_verified"])

    def test_persistent_wrong_candidate_cannot_replace_live_anchor_but_can_after_expiry(self):
        self.initialize()
        for i in range(6, 25):
            self.assertFalse(self.update(i, [sample(y=350)])["quality_accepted"])
        rows = [self.update(i, [sample(y=350)]) for i in range(25, 45)]
        self.assertTrue(any(r["quality_accepted"] for r in rows))

    def test_slow_image_motion_and_width_change_synthetic_only(self):
        for frame in range(1, 100):
            r = self.update(frame, [sample(x=280+frame//3, y=370+frame//5, width=40+frame//10)])
            self.assertEqual(r["quality_accepted"], frame >= 3)

    def test_reference_labels_and_line_fit_flags_are_ignored(self):
        a, b = ConeSupportQualityGate(), ConeSupportQualityGate()
        for i in range(1, 20):
            self.assertEqual(a.update(i/30, [sample()]), b.update(i/30, [dict(sample(), reference_z_m=99, condition="occluded", line_consistent=False, frame=1134)]))

    def test_causal_prefix_replay_and_caller_mutation_cannot_change_anchor(self):
        def run(n):
            gate = ConeSupportQualityGate()
            return [gate.update(i/30, [sample()]) for i in range(1, n+1)]
        self.assertEqual(run(20)[:10], run(10))
        self.assertEqual(run(20), run(20))
        row = sample()
        before = copy.deepcopy(row)
        for frame in range(1, 4):
            self.update(frame, [row])
        self.assertEqual(row, before)
        row["support"][0] = (900, 900)
        self.assertEqual(self.gate.anchor[0], (300, 400))

    def test_settings_validation(self):
        for kwargs in (dict(confirmation_frames=1), dict(min_columns=2.5), dict(min_width_ratio=1),
                       dict(max_width_ratio=.5), dict(min_common_fraction=2), dict(anchor_memory_sec=.1),
                       dict(max_median_y_change_px=8, max_p90_y_change_px=6), dict(endpoint_floor_px=math.nan)):
            with self.assertRaises(ValueError):
                SupportQualitySettings(**kwargs)

    def test_pending_restart_has_separate_diagnostics_from_accepted_anchor_comparison(self):
        self.initialize()
        self.update(6, [])
        first = sample(x=305, width=35)
        second = sample(x=300, width=40)
        self.assertEqual(self.update(7, [first])["confirmation_count"], 1)
        # Use an endpoint jump > pending width*20% but still <= original anchor*20%.
        # Pending source x=307, width=33 is within the original anchor's 8px limit.
        self.gate.pending = tuple(sample(x=307, width=33)["support"])
        r = self.update(8, [second])
        self.assertEqual(r["comparison_failures"], ())
        self.assertEqual(r["confirmation_count"], 1)
        self.assertIn("abrupt_support_endpoint_change", r["pending_comparison_failures"])
        self.assertGreater(r["pending_endpoint_change_px"], r["pending_endpoint_limit_px"])


if __name__ == "__main__":
    unittest.main()
