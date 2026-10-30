"""Offline review accounting, no hardware, inference, or distance calculation."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("support_live_review", ROOT / "Experimental_results/2026-10-30/cone_support_live_review_r01/analyze.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def candidate(point=True):
    return dict(point=[110, 400] if point else None,
        support=[[x, 400] for x in range(100, 121)] if point else None,
        controlling_distance=False, floor_contact_verified=False, usable_for_ffb=False,
        completion_granted=False, completion_attempted=False, selected_colour="red" if point else None,
        reason="unverified_visible_colour_support" if point else "ambiguous_upper_body_colour",
        completion_reason="existing_shadow_point_preserved" if point else "not_eligible",
        seed_red_pixels=90, seed_yellow_pixels=0, seed_dominant_fraction=1., seed_xyxy=[110, 210, 114, 225])


def row(number, point=True):
    c = candidate(point)
    return dict(frame=number, session="test", source_time_sec=number/30,
        colour_support_shadow=dict(candidate=copy.deepcopy(c)), support_completion_shadow=dict(candidate=c),
        selected_detector_boxes=[dict(x1=100., y1=200., x2=130., y2=410.)],
        frame_age_ms=10., distance_available=False, scene_initialized=False)


def completion():
    box = dict(x1=100., y1=200., x2=130., y2=410.)
    c = candidate()
    c.update(completion_granted=True, completion_attempted=True)
    observation = dict(point=c["point"], support=c["support"])
    c["contexts"] = [dict(crop_xyxy=[100-p, 196, 130+p, 414],
        component=dict(touches=dict(left=i == 0, right=False, top=False, bottom=False),
                       pixel_sha256="a"*64, pixel_count=100), observation=copy.deepcopy(observation))
        for i, p in enumerate((4, 8, 16))]
    return c, box


class LiveSupportReviewTests(unittest.TestCase):
    def test_preserved_requires_identical_support_and_point(self):
        old, new = candidate(), candidate()
        self.assertEqual(review.partition(old, new), "preserved")
        new["support"][0][1] += 1
        with self.assertRaises(ValueError):
            review.partition(old, new)

    def test_lost_existing_point_is_not_silently_withheld(self):
        with self.assertRaises(ValueError):
            review.partition(candidate(), candidate(False))

    def test_completion_is_separate_category(self):
        c, _ = completion()
        self.assertEqual(review.partition(candidate(False), c), "completed")
        c["completion_attempted"] = False
        with self.assertRaises(ValueError):
            review.partition(candidate(False), c)

    def test_missing_is_withheld_not_zero_distance(self):
        self.assertEqual(review.partition(candidate(False), candidate(False)), "withheld")

    def test_control_authority_rejected(self):
        for key in review.FLAGS:
            c = candidate()
            c[key] = True
            with self.assertRaises(ValueError):
                review.partition(candidate(), c)

    def test_logged_closed_contexts_accepted_as_consistency_only(self):
        c, box = completion()
        checks = review.check_completion(c, box)
        self.assertEqual(checks["original_touches"], ["left"])
        self.assertTrue(checks["original_and_expanded_component_hash_equal"])

    def test_original_bottom_contact_rejected(self):
        c, box = completion()
        c["contexts"][0]["component"]["touches"]["bottom"] = True
        with self.assertRaises(ValueError):
            review.check_completion(c, box)

    def test_different_closed_context_pixel_sets_rejected(self):
        c, box = completion()
        c["contexts"][2]["component"]["pixel_sha256"] = "b"*64
        with self.assertRaises(ValueError):
            review.check_completion(c, box)

    def test_changed_crop_rule_rejected(self):
        c, box = completion()
        c["contexts"][1]["crop_xyxy"][0] -= 1
        with self.assertRaises(ValueError):
            review.check_completion(c, box)

    def test_point_outside_box_rejected(self):
        c, box = completion()
        box["y2"] = 399.
        # Keep the expected crop consistent so point containment is exercised.
        for context in c["contexts"]:
            context["crop_xyxy"][3] = 403
        with self.assertRaises(ValueError):
            review.check_completion(c, box)

    def test_run_empty_and_last_missing(self):
        self.assertEqual(review.runs([], lambda _: True), [])
        s = review.runs([row(1), row(2)], lambda _: True)
        self.assertEqual((s[0]["first_frame"], s[0]["last_frame"]), (1, 2))

    def test_sequence_gap_breaks_run_without_inventing_rows(self):
        s = review.runs([row(1), row(3), row(4)], lambda _: True)
        self.assertEqual([r["logged_frames"] for r in s], [1, 2])

    def test_adjacent_metrics_never_bridge_missing_or_sequence_gap(self):
        rows = [dict(frame=i, source_time_sec=i/30, new_point=p)
                for i, p in ((1, [100, 400]), (2, None), (3, [110, 400]), (5, [120, 400]), (6, [121, 400]))]
        metrics = review.adjacent_metrics(rows, "new")
        self.assertEqual(metrics["step_px"]["count"], 1)
        self.assertEqual(metrics["step_px"]["maximum"], 1.)

    def test_time_gap_excluded_even_if_frame_numbers_consecutive(self):
        metrics = review.adjacent_metrics([dict(frame=1, source_time_sec=0., new_point=[1, 2]),
            dict(frame=2, source_time_sec=.3, new_point=[101, 2])], "new")
        self.assertEqual(metrics["step_px"]["count"], 0)

    def test_quality_reconfirms_after_missing_without_mutating_inputs(self):
        rows = [row(i, i != 4) for i in range(1, 8)]
        before = copy.deepcopy(rows)
        flat, summary = review.summarize_rows(rows)
        self.assertEqual(summary["new"]["point_frames"], 6)
        self.assertEqual(summary["new"]["offline_quality_accepted"], 2)
        self.assertEqual(summary["category_counts"], {"preserved": 6, "withheld": 1})
        self.assertFalse(flat[4]["new_offline_quality"])
        self.assertEqual(rows, before)

    def test_existing_point_outside_bbox_is_recorded_not_called_physical_error(self):
        rows = [row(1)]
        rows[0]["selected_detector_boxes"][0]["y2"] = 399.5
        _, summary = review.summarize_rows(rows)
        self.assertEqual(summary["new"]["point_outside_bbox_frames"], [1])
        self.assertEqual(summary["new"]["point_bbox_excess_px"]["maximum"], .5)
        self.assertEqual(summary["category_counts"], {"preserved": 1})
        self.assertFalse(summary["floor_contact_verified"])


if __name__ == "__main__":
    unittest.main()
