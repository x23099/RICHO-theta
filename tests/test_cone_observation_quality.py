import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from cone_observation_quality import ConeObservationQualityGate, ConeQualitySettings


class ProjectorStub:
    """Isolate temporal gate tests from already-tested camera projection math."""
    def project(self, row, **kwargs):
        return dict(projection_candidate=row.get("valid", True),
                    x_m=row.get("x", 0), z_m=row.get("z", 2),
                    reason="invalid_geometry")


def candidate(z=2, x=0, height=80, width=40, valid=True):
    return dict(x1=300, y1=400-height, x2=300+width, y2=400,
                z=z, x=x, valid=valid)


class ConeObservationQualityTest(unittest.TestCase):
    def setUp(self):
        self.gate = ConeObservationQualityGate(ProjectorStub())

    def update(self, frame, rows):
        return self.gate.update(frame/30, rows, frame_width=1280, frame_height=720)

    def initialize(self):
        for frame in range(1, 6):
            result = self.update(frame, [candidate()])
        return result

    def test_initial_confirmation_and_physical_flags(self):
        for frame in range(1, 6):
            r = self.update(frame, [candidate()])
            self.assertEqual(r["quality_accepted"], frame >= 3)
            self.assertFalse(r["floor_contact_verified"])
            self.assertFalse(r["usable_for_ffb"])

    def test_missing_never_returns_predicted_observation(self):
        self.initialize()
        r = self.update(6, [])
        self.assertTrue(r["internal_prediction"])
        self.assertIsNone(r["observed_z_m"])
        self.assertIsNone(r["filtered_z_m"])
        self.assertFalse(r["quality_accepted"])

    def test_recovery_needs_three_consecutive_frames(self):
        self.initialize()
        self.update(6, [])
        for frame in range(7, 10):
            r = self.update(frame, [candidate()])
            self.assertEqual(r["quality_accepted"], frame == 9)

    def test_interrupted_confirmation_restarts(self):
        self.update(1, [candidate()])
        self.update(2, [])
        for frame in range(3, 6):
            self.assertEqual(self.update(frame, [candidate()])["quality_accepted"], frame == 5)

    def test_abrupt_shape_change_does_not_poison_anchor(self):
        self.initialize()
        r = self.update(6, [candidate(height=20)])
        self.assertEqual(r["reason"], "abrupt_bbox_shape_change")
        for frame in range(7, 10):
            self.assertEqual(self.update(frame, [candidate()])["quality_accepted"], frame == 9)

    def test_in_range_distance_jump_rejected_without_correction(self):
        self.initialize()
        r = self.update(6, [candidate(z=3.5)])
        self.assertFalse(r["quality_accepted"])
        self.assertIn("nis_gate", r["reason"])
        self.assertGreater(r["nis"], 9.21)
        for frame in range(7, 10):
            r = self.update(frame, [candidate()])
        self.assertAlmostEqual(r["filtered_z_m"], 2, places=3)

    def test_ambiguity_fails_closed(self):
        self.initialize()
        r = self.update(6, [candidate(), candidate(x=.5)])
        self.assertEqual(r["reason"], "ambiguous_candidates")
        self.assertFalse(r["quality_accepted"])

    def test_invalid_projection_interrupts_confirmation(self):
        self.update(1, [candidate()])
        r = self.update(2, [candidate(valid=False)])
        self.assertEqual(r["reason"], "projection:invalid_geometry")
        self.assertFalse(self.update(3, [candidate()])["quality_accepted"])
        self.assertFalse(self.update(4, [candidate()])["quality_accepted"])
        self.assertTrue(self.update(5, [candidate()])["quality_accepted"])

    def test_long_missing_resets_track_and_shape(self):
        self.initialize()
        for frame in range(6, 40):
            self.update(frame, [])
        for frame in range(40, 43):
            r = self.update(frame, [candidate(z=1, height=200, width=100)])
            self.assertEqual(r["quality_accepted"], frame == 42)

    def test_sparse_frames_do_not_count_as_contiguous_confirmation(self):
        self.update(1, [candidate()])
        self.update(20, [candidate()])
        self.assertFalse(self.update(21, [candidate()])["quality_accepted"])
        self.assertTrue(self.update(22, [candidate()])["quality_accepted"])

    def test_sparse_frame_restarts_even_after_initialized(self):
        self.initialize()
        self.assertFalse(self.update(20, [candidate()])["quality_accepted"])

    def test_nonmonotonic_and_nonfinite_timestamps_reset(self):
        for bad in (5/30, 0, math.nan, math.inf):
            self.gate.reset()
            self.initialize()
            with self.assertRaises(ValueError):
                self.gate.update(bad, [], frame_width=1280, frame_height=720)
            self.assertFalse(self.update(1, [candidate()])["quality_accepted"])

    def test_smooth_approach_and_retreat(self):
        for speed in (-.25, .25):
            self.gate.reset()
            rows = []
            for frame in range(1, 121):
                z = 2+speed*frame/30
                rows.append(self.update(frame, [candidate(z=z, height=160/z, width=80/z)]))
            self.assertTrue(all(r["quality_accepted"] for r in rows[2:]))

    def test_repeated_outliers_require_reconfirmation_when_track_expires(self):
        self.initialize()
        for frame in range(6, 21):
            self.assertFalse(self.update(frame, [candidate(z=3.5)])["quality_accepted"])
        # A long stable incorrect hypothesis CAN eventually initialize. This is
        # a documented limitation, not proof that an occluded base is visible.
        accepted = [self.update(frame, [candidate(z=3.5)])["quality_accepted"]
                    for frame in range(21, 30)]
        self.assertTrue(any(accepted))

    def test_settings_validation(self):
        for kwargs in ({"max_nis": math.nan}, {"confirmation_frames": 1},
                       {"confirmation_frames": 2.5}, {"max_shape_factor": 1},
                       {"shape_memory_sec": .1}, {"max_frame_gap_sec": 0}):
            with self.assertRaises(ValueError):
                ConeQualitySettings(**kwargs)


if __name__ == "__main__":
    unittest.main()
