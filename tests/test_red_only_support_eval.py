"""Synthetic checks for the red-only shadow saved-data audit."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "Experimental_results/2026-10-30/red_only_support_eval_r01"
_spec = importlib.util.spec_from_file_location("red_only_analyze", EVAL / "analyze.py")
analyze = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyze)


def row(frame, point=(300, 398), reason="unverified_visible_colour_support",
        bbox=(280., 300., 320., 400.)):
    candidate = dict(point=list(point) if point else None,
                     reason=reason, selected_colour="red", seed_dominant_fraction=1.0,
                     support=[[295, 398], [296, 398], [300, 398], [305, 398]] if point else None)
    return dict(
        session="synthetic", frame=frame, distance_available=False,
        colour_support_shadow=dict(candidate=candidate, status="one_selected_candidate"),
        support_completion_shadow=dict(candidate=dict(point=list(point) if point else None)),
        frame_evidence=dict(
            selected_detector_boxes=[dict(x1=bbox[0], y1=bbox[1], x2=bbox[2], y2=bbox[3])],
            pose=dict(pose_available=False, scene_reason="synthetic_scene"),
            support_observation=dict(reason="colour_contour_reaches_roi_edge")))


class RedOnlyAuditTests(unittest.TestCase):
    def test_candidate_geometry_and_identity(self):
        item = analyze.candidate_row(row(1))
        self.assertEqual(item["point_x"], 300)
        self.assertEqual(item["support_columns"], 4)
        self.assertTrue(item["point_in_support"])
        self.assertTrue(item["point_inside_bbox_x"])
        self.assertAlmostEqual(item["y_above_bbox_bottom_px"], 2.0)
        self.assertTrue(item["completion_same_point"])

    def test_failed_candidate_keeps_reason_without_point(self):
        item = analyze.candidate_row(row(2, point=None, reason="ambiguous_upper_body_colour"))
        self.assertIsNone(item["point_x"])
        self.assertEqual(item["candidate_reason"], "ambiguous_upper_body_colour")
        self.assertIsNone(item["point_inside_bbox_x"])

    def test_adjacent_deltas_skip_frame_gaps(self):
        first = analyze.candidate_row(row(1, point=(300, 398)))
        second = analyze.candidate_row(row(2, point=(301, 398)))
        gap = analyze.candidate_row(row(5, point=(310, 400)))
        deltas = analyze.adjacent_deltas([first, second, gap])
        self.assertEqual(len(deltas), 1)
        self.assertEqual((deltas[0]["dx"], deltas[0]["dy"]), (1, 0))

    def test_summary_counts_and_denies_promotion(self):
        rows = [analyze.candidate_row(row(1)), analyze.candidate_row(row(2)),
                analyze.candidate_row(row(3, point=None, reason="colour_contour_reaches_roi_edge"))]
        summary = analyze.build_summary(rows, analyze.adjacent_deltas(rows), {"x": "0"*64})
        self.assertEqual(summary["processed_frames"], 3)
        self.assertEqual(summary["candidate_point_frames"], 2)
        self.assertEqual(summary["point_inside_bbox_x_frames"], 2)
        self.assertEqual(summary["point_in_support_frames"], 2)
        self.assertIs(summary["controlling_distance"], False)
        self.assertIs(summary["physical_metric_verified"], False)
        self.assertIs(summary["floor_contact_verified"], False)
        self.assertIs(summary["usable_for_ffb"], False)


if __name__ == "__main__":
    unittest.main()
