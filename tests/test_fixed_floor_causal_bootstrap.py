"""Past-only fixed-floor bootstrap accounting; synthetic pose evidence."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_scene_diagnostic import PastOnlyPose
from cone_distance_core import load_config
from cone_fixed_floor_shadow import load_bundle

SPEC = importlib.util.spec_from_file_location("causal_fixed_replay", ROOT / "Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/run.py")
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class CausalFixedBootstrapTests(unittest.TestCase):
    def pose(self, count=4):
        p = PastOnlyPose()
        for number in range(1, count+1):
            p.ingest(number, float(number), True, [0., -1., 0.])
        return p

    def freeze(self, pose=None, **kwargs):
        options = dict(completion_time=4.1, query_frame=5, query_time=4.2)
        options.update(kwargs)
        return replay.freeze_bundle(pose or self.pose(), "synthetic", load_config()[0], **options)

    def test_first_two_training_two_validation_are_explicit(self):
        bundle, seal = self.freeze()
        self.assertEqual(seal["training_frames"], [1, 2])
        self.assertEqual(seal["validation_frames"], [3, 4])
        self.assertEqual(bundle["models"][0]["camera_to_floor_m"], .59)
        self.assertFalse(seal["distance_labels_used_for_bootstrap"])

    def test_three_poses_cannot_bootstrap(self):
        with self.assertRaises(ValueError):
            self.freeze(self.pose(3))

    def test_same_or_earlier_frame_cannot_query_model(self):
        for number in (3, 4):
            with self.subTest(number=number), self.assertRaises(ValueError):
                self.freeze(query_frame=number)

    def test_query_before_computation_completion_refused(self):
        with self.assertRaises(ValueError):
            self.freeze(query_time=4.05)

    def test_completion_before_source_image_refused(self):
        with self.assertRaises(ValueError):
            self.freeze(completion_time=3.9)

    def test_latest_rejected_scene_cannot_be_used_for_initial_freeze(self):
        pose = self.pose()
        pose.ingest(5, 5., False)
        with self.assertRaises(ValueError):
            self.freeze(pose, query_frame=6, query_time=6., completion_time=5.1)

    def test_duplicate_evidence_frames_refused(self):
        pose = self.pose()
        pose.validation = [3, 3]
        with self.assertRaises(ValueError):
            self.freeze(pose)

    def test_later_direction_change_does_not_rewrite_frozen_bundle(self):
        pose = self.pose()
        bundle, _ = self.freeze(pose)
        before = copy.deepcopy(bundle)
        pose.ingest(6, 6., True, [.6, -.8, 0.])
        self.assertEqual(bundle, before)

    def test_bool_or_nonfinite_height_is_not_a_measurement(self):
        for h in (True, 0., float("nan"), float("inf")):
            with self.subTest(h=h), self.assertRaises(ValueError):
                self.freeze(height_m=h)

    def test_generated_bundle_loads_with_existing_diagnostic_contract(self):
        bundle, _ = self.freeze()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"bundle.json"
            path.write_text(json.dumps(bundle))
            loaded, _ = load_bundle(path, load_config()[0])
        self.assertEqual(loaded["session"], "synthetic")
        self.assertTrue(all(loaded["models"][0][k] is False for k in
                           ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb")))

    def test_release_audit_rejects_model_leaking_to_past(self):
        _, seal = self.freeze()
        with self.assertRaises(ValueError):
            replay.verify_releases(seal, [dict(frame=4, source_time_sec=4.2, fixed_floor_shadow={})])
        with self.assertRaises(ValueError):
            replay.verify_releases(seal, [dict(frame=5, source_time_sec=4.0, fixed_floor_shadow={})])

    def test_prefix_can_be_missing_model_without_fabricated_measurements(self):
        _, seal = self.freeze()
        replay.verify_releases(seal, [dict(frame=1, source_time_sec=1.),
            dict(frame=5, source_time_sec=4.2, fixed_floor_shadow={})])


if __name__ == "__main__":
    unittest.main()
