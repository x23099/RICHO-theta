"""Pure image-coordinate tests. No physical GT, media, model, ROS or hardware."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_self_body_shadow import checked_reference, compare_self_body

SESSION = "a" * 32


def reference():
    return dict(schema="offline_self_body_boundary_v1", image_size=[1280, 720],
        layout="dual_fisheye_front_left_unremapped", session=SESSION, source_frame=1,
        source_png_sha256="b" * 64, boundary_xy=[[280, 455], [320, 459], [360, 455]],
        independent_physical_measurement=False, cross_session_mount_verified=False,
        live_authorized=False, floor_contact_verified=False)


def observation(y=400):
    return dict(point=[320, y], support=[[x, y] for x in range(300, 341)],
        reason="unverified_test_observation", physical_metric_verified=False,
        floor_contact_verified=False, controlling_distance=False, usable_for_ffb=False)


def compare(obs=None, ref=None, **kwargs):
    return compare_self_body(observation() if obs is None else obs,
        reference() if ref is None else ref, session=kwargs.pop("session", SESSION),
        reference_matches=kwargs.pop("reference_matches", True), **kwargs)


class SelfBodyTests(unittest.TestCase):
    def test_clear_support_is_preserved_verbatim_without_contact_grant(self):
        old = observation()
        r = compare(old)
        self.assertFalse(r["revoked"])
        self.assertEqual(r["observation"], old)
        self.assertEqual(r["min_clearance_px"], 57.)
        self.assertFalse(r["floor_contact_verified"])

    def test_at_boundary_and_below_boundary_are_both_rejected(self):
        for y in (459, 460, 500):
            r = compare(observation(y), margin_px=0)
            self.assertTrue(r["revoked"])
            self.assertIsNone(r["observation"]["point"])
            self.assertEqual(r["reason"], "possible_self_body_occlusion")

    def test_any_support_column_can_revoke_even_if_chosen_point_is_clear(self):
        obs = observation()
        obs["support"][0][1] = 457
        r = compare(obs, margin_px=0)
        self.assertEqual(r["point_clearance_px"], 59.)
        self.assertEqual(r["affected_columns"], 1)
        self.assertTrue(r["revoked"])

    def test_margin_boundary_is_inclusive_and_monotone(self):
        obs = observation(450)
        self.assertFalse(compare(obs, margin_px=6)["revoked"])
        self.assertTrue(compare(obs, margin_px=7)["revoked"])
        self.assertTrue(compare(obs, margin_px=8)["revoked"])

    def test_no_rescue_of_unavailable_point_and_exact_original_reason_preserved(self):
        old = dict(point=None, support=None, reason="occluded")
        r = compare(old, session="c" * 32)
        self.assertFalse(r["revoked"])
        self.assertEqual(r["observation"], old)
        self.assertFalse(r["reference_usable"])

    def test_reference_hash_must_have_been_checked_by_caller(self):
        r = compare(reference_matches=False)
        self.assertTrue(r["revoked"])
        self.assertEqual(r["reason"], "self_body_reference_image_unchecked")

    def test_other_session_is_not_assumed_to_share_mount(self):
        r = compare(session="c" * 32)
        self.assertTrue(r["revoked"])
        self.assertEqual(r["reason"], "self_body_reference_session_mismatch")

    def test_one_outside_support_column_is_not_extrapolated_or_trimmed(self):
        obs = observation()
        obs["support"] = [[x, 400] for x in range(279, 341)]
        r = compare(obs)
        self.assertTrue(r["revoked"])
        self.assertEqual(r["reason"], "self_body_reference_does_not_cover_support")

    def test_invalid_support_or_point_cannot_gain_output(self):
        for mutate in (lambda o: o.update(point=[320, 401]),
                       lambda o: o["support"].reverse(),
                       lambda o: o.update(support=[[320, 400]])):
            obs = observation();mutate(obs)
            r = compare(obs)
            self.assertTrue(r["revoked"])
            self.assertIsNone(r["observation"]["point"])

    def test_reference_validation_rejects_wrong_geometry_authority_order_and_nan(self):
        for change in (dict(image_size=[640, 360]), dict(live_authorized=True),
                       dict(session="not-a-session"), dict(source_png_sha256="x" * 64),
                       dict(source_frame=True), dict(boundary_xy=[[320, 459], [280, 455]]),
                       dict(boundary_xy=[[280, 455], [360, float("nan")]]),
                       dict(boundary_xy=[[280, 455], [640, 455]])):
            ref = reference();ref.update(change)
            with self.assertRaises(ValueError):checked_reference(ref)

    def test_margin_rejects_boolean_nonfinite_negative_or_over_limit(self):
        for value in (True, float("nan"), float("inf"), -1, 17):
            with self.assertRaises(ValueError):compare(margin_px=value)

    def test_inputs_and_reference_are_not_mutated_or_aliased(self):
        obs, ref = observation(), reference()
        old_obs, old_ref = copy.deepcopy(obs), copy.deepcopy(ref)
        r = compare(obs, ref)
        r["observation"]["support"].clear()
        self.assertEqual(obs, old_obs)
        self.assertEqual(ref, old_ref)
        self.assertIsNot(checked_reference(ref), ref)

    def test_new_revocation_never_has_control_or_physical_authority(self):
        r = compare(observation(459))
        for k in ("floor_contact_verified", "physical_metric_verified", "controlling_distance",
                  "usable_for_ffb", "live_authorized"):
            self.assertIs(r[k], False)
            self.assertIs(r["observation"][k], False)

    def test_verified_or_authorized_observation_is_not_silently_relabelled(self):
        for name in ("floor_contact_verified", "physical_metric_verified",
                     "controlling_distance", "usable_for_ffb"):
            obs = observation();obs[name] = True
            with self.assertRaises(ValueError):compare(obs)

    def test_no_import_from_live_entry_points(self):
        for name in ("driver_motion_process.py", "driver_motion_bridge.py", "cone_motion_range.py",
                     "run_cone_motion_live.py"):
            import ast
            tree=ast.parse((ROOT/'src'/name).read_text())
            imported=[alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
            imported += [node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
            self.assertNotIn('cone_self_body_shadow',imported)


if __name__ == "__main__":
    unittest.main()
