from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate_reviewed_occlusion import join_reviews, review_summary


VARIANTS = ("baseline", "candidate")


def fixture():
    reviews = [dict(session="s", frame_one_based=str(f), reviewed_phase="partial_occlusion",
                    visible_evidence="blue_box_below_panel", review_method="whole_raw_frame_visual_review")
               for f in (2, 3)]
    labelled, results = [], []
    for variant in VARIANTS:
        for frame in (2, 3):
            row = dict(session="s", variant=variant, frame=str(frame), time_sec=str(frame / 10),
                       detected="1" if frame == 2 else "0", measurement_accepted="0",
                       track_available="0", track_predicted="0")
            results.append(row)
            labelled.append(dict(row, video_index_zero_based=str(frame - 1),
                                 phase_label="fully_occluded", occlusion_event="1"))
    return reviews, labelled, results


class ReviewedOcclusionTests(unittest.TestCase):
    def test_covers_all_frames_including_nondetections(self):
        joined = join_reviews(*fixture(), VARIANTS)
        self.assertEqual(len(joined), 4)
        self.assertEqual([r["video_index_zero_based"] for r in joined], [1, 1, 2, 2])
        self.assertTrue(all(r["original_phase"] == "fully_occluded" for r in joined))
        self.assertTrue(all(r["reviewed_phase"] == "partial_occlusion" for r in joined))

    def test_no_fully_hidden_frames_is_not_evaluated_not_zero_rate_or_pass(self):
        phases, events = review_summary(join_reviews(*fixture(), VARIANTS), VARIANTS)
        fully = [r for r in phases if r["reviewed_phase"] == "fully_occluded"]
        for row in fully:
            self.assertEqual(row["assessment"], "NOT_EVALUATED")
            self.assertIsNone(row["detected_rate"])
            self.assertIsNone(row["measurement_accepted"])
        self.assertEqual(events[0]["partial_occlusion_frames"], 2)

    def test_review_is_not_selected_by_detector_output(self):
        reviews, labelled, results = fixture()
        with self.assertRaises(ValueError):
            join_reviews(reviews[:1], labelled, results, VARIANTS)

    def test_missing_duplicate_and_extraneous_reviews_fail(self):
        reviews, labelled, results = fixture()
        for manual in (reviews[:1], reviews + reviews[:1],
                       reviews + [dict(reviews[0], frame_one_based="4")]):
            with self.assertRaises(ValueError):
                join_reviews(manual, labelled, results, VARIANTS)

    def test_zero_based_manual_number_and_unknown_phase_fail(self):
        for update in (dict(frame_one_based="0"), dict(reviewed_phase="visible"),
                       dict(review_method="detector_inferred"), dict(visible_evidence="")):
            reviews, labelled, results = fixture()
            reviews[0].update(update)
            with self.assertRaises(ValueError):
                join_reviews(reviews, labelled, results, VARIANTS)

    def test_uncertain_is_separate_not_fully_hidden(self):
        reviews, labelled, results = fixture()
        reviews[0]["reviewed_phase"] = "uncertain"
        phases, _ = review_summary(join_reviews(reviews, labelled, results, VARIANTS), VARIANTS)
        self.assertEqual(phases[0]["frames"], 1)
        self.assertEqual(phases[1]["assessment"], "NOT_EVALUATED")
        self.assertEqual(phases[2]["frames"], 1)

    def test_actual_fully_hidden_metrics_use_only_reviewed_full_frames(self):
        reviews, labelled, results = fixture()
        reviews[1].update(reviewed_phase="fully_occluded", visible_evidence="no_box_part_visible")
        phases, _ = review_summary(join_reviews(reviews, labelled, results, VARIANTS), VARIANTS)
        self.assertEqual(phases[1]["frames"], 1)
        self.assertEqual(phases[1]["detected_rate"], 0)
        self.assertEqual(phases[1]["assessment"], "OBSERVED_NOT_CERTIFIED")

    def test_missing_duplicate_or_changed_frozen_result_fail(self):
        reviews, labelled, results = fixture()
        modified = deepcopy(results)
        modified[0]["detected"] = "0"
        changed_time = deepcopy(results)
        changed_time[0]["time_sec"] = "100"
        for rows in (results[:-1], results + results[:1], modified, changed_time):
            with self.assertRaises(ValueError):
                join_reviews(reviews, labelled, rows, VARIANTS)

    def test_variant_coverage_and_old_frame_index_fail(self):
        reviews, labelled, results = fixture()
        with self.assertRaises(ValueError):
            join_reviews(reviews, labelled[:-1], results, VARIANTS)
        labelled[0]["video_index_zero_based"] = "2"
        with self.assertRaises(ValueError):
            join_reviews(reviews, labelled, results, VARIANTS)

    def test_inputs_are_not_modified(self):
        inputs = fixture()
        before = deepcopy(inputs)
        review_summary(join_reviews(*inputs, VARIANTS), VARIANTS)
        self.assertEqual(inputs, before)


if __name__ == "__main__":
    unittest.main()
