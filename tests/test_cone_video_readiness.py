"""Alignment/zero-run semantics; synthetic inputs, no GPU or real cone claims."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cone_observation import ConeGroundProjector
from cone_video_readiness import summarize_stream


def frames(counts):
    return [dict(session="synthetic", frame=i+1, time_sec=(i+1)/30, detections=count)
            for i, count in enumerate(counts)]


def prediction(frame=1, index=0, **changes):
    return dict(dict(session="synthetic", frame=frame, time_sec=frame/30,
                     prediction_index=index, class_id=0, confidence=.8,
                     x1=300, y1=340, x2=340, y2=430), **changes)


class ConeVideoReadinessTest(unittest.TestCase):
    def setUp(self):
        self.projector = ConeGroundProjector(dict(camera_height=.58, pitch_deg=0, roll_deg=0,
                yaw_deg=0, radius_scale=.86, front_cx_offset=-80, front_cy_offset=-21,
                back_cx_offset=82, back_cy_offset=-18), width=1280, height=720,
                front_lens="left", confidence_threshold=.5)

    def summarize(self, ff, pp):
        return summarize_stream(ff, pp, self.projector)

    def test_preserve_zeros_and_unknown_truth(self):
        ff = frames([1, 0, 1]); pp = [prediction(), prediction(3)]
        counts, candidates, summary, runs = self.summarize(ff, pp)
        self.assertEqual([r["front_detections"] for r in counts], [1, 0, 1])
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(r["zero_frames"] == 1 and r["sample_span_sec"] == 0 for r in runs))
        self.assertTrue(all("NOT" in r["truth"] for r in runs))
        self.assertTrue(all(not r["usable_for_ffb"] for r in candidates))
        self.assertEqual(ff, frames([1, 0, 1])); self.assertEqual(pp, [prediction(), prediction(3)])

    def test_rear_detection_does_not_hide_front_zero(self):
        counts, _, _, _ = self.summarize(frames([1]), [prediction(x1=900, x2=940)])
        self.assertEqual((counts[0]["all_detections"], counts[0]["front_detections"]), (1, 0))

    def test_second_cone_is_not_collapsed_or_assigned_identity(self):
        counts, candidates, _, _ = self.summarize(frames([2]), [prediction(), prediction(index=1, x1=340, x2=380)])
        self.assertEqual(counts[0]["projection_candidates"], 2)
        self.assertEqual(len(candidates), 2)

    def test_empty_predictions_on_negative_stream_are_valid(self):
        _, _, summary, runs = self.summarize(frames([0, 0]), [])
        self.assertTrue(all(r["zero_frames"] == 2 for r in summary))
        self.assertTrue(all(r["bounded_by_detection"] == 0 for r in runs))

    def test_unknown_duplicate_misaligned_predictions_refused(self):
        for pp in ([prediction(frame=2)], [prediction(), prediction()],
                   [prediction(time_sec=.9)], [prediction(time_sec=float("nan"))]):
            with self.subTest(pp=pp), self.assertRaises(ValueError):
                self.summarize(frames([1]), pp)

    def test_inconsistent_count_or_index_refused(self):
        for ff, pp in ((frames([1]), []), (frames([0]), [prediction()]),
                       (frames([1]), [prediction(index=1)])):
            with self.subTest(ff=ff, pp=pp), self.assertRaises(ValueError):
                self.summarize(ff, pp)

    def test_invalid_frames_refused(self):
        for ff in ([], [dict(frames([0])[0], frame=2)],
                   [dict(frames([0])[0], detections=-1)],
                   [dict(frames([0])[0], time_sec=float("inf"))],
                   frames([0])+[dict(frames([0])[0], frame=2)]):
            with self.subTest(ff=ff), self.assertRaises(ValueError):
                self.summarize(ff, [])

    def test_invalid_class_score_or_geometry_refused(self):
        for changes in (dict(confidence=.49), dict(confidence=float("nan")),
                        dict(class_id=1), dict(class_id=float("nan")), dict(x1=-1),
                        dict(y2=float("inf"))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.summarize(frames([1]), [prediction(**changes)])


if __name__ == "__main__":
    unittest.main()
