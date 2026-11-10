"""Synthetic log evidence only; cannot grant live measurement permission."""
import copy
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1]/"Experimental_results/2026-11-10/support_boundary_audit_r01/audit.py"
spec = importlib.util.spec_from_file_location("support_boundary_log_audit", PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def record():
    obs = dict(point=[300, 447], support=[[299, 447], [300, 447], [301, 447]])
    component = dict(pixel_sha256="a"*64, touches=dict(left=False, right=False, top=False, bottom=False))
    return dict(frame=7, source_time_sec=1., distance_available=False,
        reason="colour_contour_reaches_roi_edge", selected_detector_boxes=[dict(x1=270., y1=294., x2=350., y2=446.4)],
        **{k: False for k in audit.FLAGS},
        support_observation=dict(completion_reason="completed_point_outside_original_bbox", contexts=[
            dict(component=dict(touches=dict(left=True, right=False, top=False, bottom=False))),
            dict(component=copy.deepcopy(component), observation=copy.deepcopy(obs), lateral_padding_px=16),
            dict(component=copy.deepcopy(component), observation=copy.deepcopy(obs), lateral_padding_px=32)]))


class BoundaryLogAuditTests(unittest.TestCase):
    def test_different_coordinate_conventions_remain_diagnostic(self):
        r = audit.candidate_audit(record())
        self.assertFalse(r["relation"]["inside_strict_float_bbox"])
        self.assertFalse(r["relation"]["pixel_cell_overlaps_bbox"])
        self.assertTrue(r["relation"]["inside_outward_rounded_inclusive_bbox"])
        self.assertFalse(r["adopted"])
        self.assertFalse(r["live_distance_available"])

    def test_half_pixel_tolerance_does_not_mean_one_pixel_tolerance(self):
        box = dict(x1=270., y1=294., x2=350., y2=446.7)
        self.assertTrue(audit.bbox_relation(box, [300, 447])["pixel_cell_overlaps_bbox"])
        self.assertFalse(audit.bbox_relation(box, [300, 448])["inside_outward_rounded_inclusive_bbox"])

    def test_mismatched_component_or_support_cannot_be_a_candidate(self):
        for key in ("component", "observation"):
            row = record()
            row["support_observation"]["contexts"][2][key] = {}
            self.assertNotIn("relation", audit.candidate_audit(row))

    def test_bottom_truncation_is_not_rescued_by_rounding(self):
        row = record()
        row["support_observation"]["completion_reason"] = "not_lateral_only_contact"
        self.assertNotIn("relation", audit.candidate_audit(row))

    def test_closed_pair_must_not_touch_new_boundary(self):
        row = record()
        row["support_observation"]["contexts"][1]["component"]["touches"]["bottom"] = True
        self.assertNotIn("relation", audit.candidate_audit(row))

    def test_granted_physical_permission_is_rejected(self):
        row = record()
        row["physical_metric_verified"] = True
        with self.assertRaises(ValueError):
            audit.candidate_audit(row)

    def test_inconsistent_logged_bbox_rejection_is_not_reinterpreted(self):
        row = record()
        row["selected_detector_boxes"][0]["y2"] = 450.
        with self.assertRaises(ValueError):
            audit.candidate_audit(row)

    def test_invalid_coordinates_and_booleans_rejected(self):
        for point in ([300, True], [300, float("nan")], [-1, 447], [700, 447]):
            with self.subTest(point=point), self.assertRaises(ValueError):
                audit.bbox_relation(record()["selected_detector_boxes"][0], point)

    def test_input_record_is_not_mutated(self):
        row = record()
        previous = copy.deepcopy(row)
        audit.candidate_audit(row)
        self.assertEqual(row, previous)


if __name__ == "__main__":
    unittest.main()
