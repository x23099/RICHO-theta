"""Native synthetic pixels and fixed rules; no camera/model/ROS or contact GT."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import load_config
from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge, lower_half_pixel_only

SESSION = "a" * 32
BOX = dict(x1=301., y1=305., x2=339., y2=399.6, confidence=.95, class_id=0)


def pixels(colour=(0, 0, 255)):
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], colour)
    image.flags.writeable = False
    return image


def reference(edge=458):
    return dict(schema="offline_self_body_boundary_v1", image_size=[1280, 720],
        layout="dual_fisheye_front_left_unremapped", session=SESSION, source_frame=1,
        source_png_sha256="b" * 64, boundary_xy=[[280, edge], [360, edge]],
        independent_physical_measurement=False, cross_session_mount_verified=False,
        live_authorized=False, floor_contact_verified=False)


class GuardedLowerEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.camera = load_config()[1]

    def compare(self, *, box=BOX, ref=None, image=None, session=SESSION, verified=True):
        return compare_guarded_lower_edge(pixels() if image is None else image, box, self.camera,
            reference() if ref is None else ref, session=session, reference_matches=verified)

    def test_clear_closed_current_support_can_be_proposed_without_moving_point(self):
        r = self.compare()
        self.assertIsNone(r["baseline"]["point"])
        self.assertTrue(r["lower_half_pixel_eligible"])
        self.assertTrue(r["new_point_proposed"])
        self.assertEqual(r["proposed_observation"]["point"], [320, 400])

    def test_body_boundary_veto_takes_precedence_over_pixel_overlap(self):
        r = self.compare(ref=reference(400))
        self.assertTrue(r["lower_half_pixel_eligible"])
        self.assertFalse(r["new_point_proposed"])
        self.assertIsNone(r["proposed_observation"]["point"])
        self.assertEqual(r["proposed_body_review"]["reason"], "possible_self_body_occlusion")

    def test_more_than_half_pixel_does_not_fallback_to_integer_rounding(self):
        r = self.compare(box=dict(BOX, y2=399.4))
        self.assertFalse(r["lower_half_pixel_eligible"])
        self.assertFalse(r["new_point_proposed"])

    def test_exact_half_pixel_inclusive_and_no_relaxation_when_already_inside(self):
        self.assertTrue(lower_half_pixel_only(dict(BOX, y2=399.5), [320, 400]))
        self.assertFalse(lower_half_pixel_only(dict(BOX, y2=399.499), [320, 400]))
        self.assertFalse(lower_half_pixel_only(dict(BOX, y2=400.), [320, 400]))

    def test_left_right_and_top_shortfalls_are_never_relaxed(self):
        for b, point in ((dict(BOX, x1=320.1), [320, 400]),
                         (dict(BOX, x2=319.9), [320, 400]),
                         (dict(BOX, y1=310.1, y2=410.), [320, 310])):
            self.assertFalse(lower_half_pixel_only(b, point))

    def test_existing_clear_baseline_is_kept_verbatim(self):
        r = self.compare(box=dict(BOX, y2=405.))
        self.assertIsNotNone(r["baseline"]["point"])
        self.assertEqual(r["baseline"], r["proposed_observation"])
        self.assertFalse(r["new_point_proposed"])
        self.assertFalse(r["baseline_point_revoked"])

    def test_existing_baseline_can_be_revoked_but_cannot_grant_contact(self):
        r = self.compare(box=dict(BOX, y2=405.), ref=reference(400))
        self.assertIsNotNone(r["baseline"]["point"])
        self.assertTrue(r["baseline_point_revoked"])
        self.assertIsNone(r["proposed_observation"]["point"])
        self.assertFalse(r["floor_contact_verified"])

    def test_session_mismatch_unchecked_hash_and_partial_scope_never_rescue(self):
        ref = reference();ref["boundary_xy"] = [[319, 458], [321, 458]]
        for options in (dict(session="c" * 32), dict(verified=False), dict(ref=ref)):
            r = self.compare(**options)
            self.assertFalse(r["new_point_proposed"])
            self.assertIsNone(r["proposed_observation"]["point"])

    def test_missing_component_or_open_bottom_stays_unavailable(self):
        blank = np.zeros((720, 1280, 3), np.uint8)
        connected = pixels().copy();cv2.rectangle(connected, (280, 395), (360, 430), (0, 0, 255), -1)
        for image in (blank, connected):
            image.flags.writeable = False
            r = self.compare(image=image)
            self.assertIsNone(r["proposed_observation"]["point"])
            self.assertFalse(r["new_point_proposed"])

    def test_yellow_seed_is_not_relabelled_as_red(self):
        r = self.compare(image=pixels((0, 255, 255)))
        self.assertEqual(r["proposed_observation"]["selected_colour"], "yellow")
        self.assertTrue(r["new_point_proposed"])

    def test_side_only_half_overlap_proposal_is_discarded(self):
        # Isolate composition from the already-tested raw component generator.
        from cone_bbox_boundary_shadow import compare_boundary_observations
        base = compare_boundary_observations(pixels(), BOX, self.camera)
        with patch("cone_guarded_lower_edge_shadow.compare_boundary_observations", return_value=base):
            r = self.compare(box=dict(BOX, x1=320.1))
        self.assertFalse(r["lower_half_pixel_eligible"])
        self.assertIsNone(r["proposed_observation"]["point"])

    def test_original_pixels_box_reference_and_separate_baseline_not_mutated(self):
        image, box, ref = pixels(), copy.deepcopy(BOX), reference()
        before = image.copy();old_ref = copy.deepcopy(ref)
        r = self.compare(image=image, box=box, ref=ref)
        r["proposed_observation"]["support"].clear()
        np.testing.assert_array_equal(image, before)
        self.assertEqual(box, BOX);self.assertEqual(ref, old_ref)
        self.assertIsNone(r["baseline"]["support"])

    def test_invalid_geometry_noninteger_points_or_policy_parameters_raise(self):
        for point in ([320, True], [320.1, 400], [640, 400]):
            with self.assertRaises(ValueError):lower_half_pixel_only(BOX, point)
        with self.assertRaises(ValueError):
            self.compare(image=np.zeros((360, 640, 3), np.uint8))

    def test_proposed_point_never_has_physical_or_control_authority(self):
        r = self.compare()
        for name in ("live_authorized", "floor_contact_verified", "physical_metric_verified",
                     "controlling_distance", "usable_for_ffb"):
            self.assertIs(r[name], False)
        for name in ("floor_contact_verified", "physical_metric_verified", "controlling_distance", "usable_for_ffb"):
            self.assertIs(r["proposed_observation"][name], False)

    def test_live_entry_points_do_not_import_comparator(self):
        for name in ("driver_motion_process.py", "driver_motion_bridge.py", "cone_motion_range.py",
                     "run_cone_motion_live.py"):
            self.assertNotIn("cone_guarded_lower_edge_shadow", (ROOT / "src" / name).read_text())


if __name__ == "__main__":
    unittest.main()
