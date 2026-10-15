import unittest

from replay import replay_frames, scoped_candidates, ConeGroundProjector, ConeQualitySettings


class ReplayBookkeepingTest(unittest.TestCase):
    def setUp(self):
        self.projector = ConeGroundProjector(dict(
            camera_height=.59, pitch_deg=1, roll_deg=2, yaw_deg=0, radius_scale=.86,
            front_cx_offset=-80, front_cy_offset=-21, back_cx_offset=82, back_cy_offset=-18),
            width=1280, height=720, front_lens="left", confidence_threshold=.5)
        self.box = dict(session="s", frame="1", class_id="0", confidence=".9",
                        x1="290", y1="320", x2="330", y2="400")
        self.frame = dict(session="s", frame="1", time_sec=".03", detections="1")

    def run_rows(self, frames, predictions):
        return replay_frames(frames, predictions, self.projector, True, ConeQualitySettings())

    def test_all_missing_frames_retained(self):
        rows = self.run_rows([dict(self.frame, detections="0")], [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "no_candidate")

    def test_duplicate_frame_rejected(self):
        with self.assertRaises(ValueError):
            self.run_rows([self.frame, self.frame], [self.box])

    def test_omitted_frame_rejected(self):
        with self.assertRaises(ValueError):
            self.run_rows([dict(self.frame, frame="2")], [])

    def test_orphan_prediction_rejected(self):
        with self.assertRaises(ValueError):
            self.run_rows([], [self.box])

    def test_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            self.run_rows([self.frame], [])

    def test_scope_only_selects_experiment_target(self):
        other = dict(self.box, x1="180", x2="210", y1="330", y2="380")
        self.assertEqual(len(scoped_candidates([self.box, other], self.projector, True)), 1)
        self.assertEqual(len(scoped_candidates([self.box, other], self.projector, False)), 2)

    def test_invalid_bbox_not_silently_filtered(self):
        bad = dict(self.box, x1="nan")
        self.assertEqual(len(scoped_candidates([bad], self.projector, True)), 1)
        rows = self.run_rows([self.frame], [bad])
        self.assertEqual(rows[0]["reason"], "projection:invalid_detection")

    def test_prefix_is_causal_and_repeated_replay_deterministic(self):
        frames = [dict(self.frame, frame=str(i), time_sec=str(i/30)) for i in range(1, 20)]
        predictions = [dict(self.box, frame=str(i)) for i in range(1, 20)]
        full = self.run_rows(frames, predictions)
        self.assertEqual(full, self.run_rows(frames, predictions))
        self.assertEqual(full[:10], self.run_rows(frames[:10], predictions[:10]))


if __name__ == "__main__":
    unittest.main()
