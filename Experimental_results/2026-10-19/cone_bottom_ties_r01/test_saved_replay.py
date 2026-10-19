from collections import Counter
import hashlib
import json
from pathlib import Path
import unittest

import cv2

import analyze as experiment
from cone_dataset import read_csv, sha256


class SavedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = experiment.HERE / "results_r01"
        cls.ledger, cls.old_candidates, cls.models, cls.hashes = experiment.quality.load_inputs()
        cls.pixels = read_csv(cls.directory / "pixels.csv")
        cls.index = {experiment.quality.key(r): r for r in cls.pixels}
        cls.new_candidates = {}
        for source in cls.ledger:
            k = experiment.quality.key(source)
            p = cls.index[k]
            evidence = dict(valid=experiment.quality.flag(p["colour_candidate"]), reason=p["reason"],
                            x=float(p["tie_inclusive_pixel_x"]) if p["tie_inclusive_pixel_x"] else None,
                            y=float(p["tie_inclusive_pixel_y"]) if p["tie_inclusive_pixel_y"] else None)
            cls.new_candidates[k] = [dict(b, _colour=evidence.copy()) for b in cls.old_candidates[k]]
        replay = experiment.quality.replay(cls.ledger, cls.new_candidates, cls.models)
        cls.new_rows = [dict(r, method="tie_inclusive") for r in replay if r["method"] == "colour"]
        cls.baseline = experiment.quality.replay(cls.ledger, cls.old_candidates, cls.models)
        cls.old_typed = [dict(r, method="legacy" if r["method"] == "colour" else r["method"]) for r in cls.baseline]
        cls.all_rows = cls.old_typed + cls.new_rows

    def test_all_frames_retained_with_legacy_pixels_exactly_unchanged(self):
        self.assertEqual(len(self.pixels), 5143)
        self.assertEqual(len(self.index), 5143)
        self.assertEqual(len(self.new_rows), 15429)
        original = [r for r in read_csv(experiment.quality.CONTACT / "full_replay_r01/pixels.csv") if r["v_min"] == "30"]
        for old in original:
            new = self.index[experiment.quality.key(old)]
            self.assertEqual(new["colour_candidate"], old["colour_candidate"])
            self.assertEqual(new["reason"], old["colour_reason"])
            self.assertEqual(new["legacy_pixel_x"], old["pixel_x"])
            self.assertEqual(new["legacy_pixel_y"], old["pixel_y"])

    def test_new_quality_replay_and_old_baselines_reproduce_exactly(self):
        self.assertEqual(experiment.csv_rows(self.new_rows), read_csv(self.directory / "observations.csv"))
        self.assertEqual(experiment.csv_rows(self.baseline), read_csv(experiment.QUALITY / "results_r02/observations.csv"))
        self.assertEqual(experiment.quality.bbox_regression(self.baseline, experiment.quality.PREVIOUS / "results_r01/observations.csv"), 15429)

    def test_all_summaries_common_frames_and_jitter_reproduce(self):
        pairs, common = experiment.compare_common(self.all_rows)
        products = {
            "summary.csv": experiment.quality.summarize(self.all_rows),
            "frame_pairs.csv": pairs,
            "common_frame_summary.csv": common,
            "jitter_summary.csv": experiment.jitter.summarize(experiment.jitter.differences(experiment.csv_rows(self.all_rows)))
        }
        for name, rows in products.items():
            self.assertEqual(experiment.csv_rows(rows), read_csv(self.directory / name))

    def test_guard_failures_missing_and_multiple_never_filled(self):
        for r in self.new_rows:
            self.assertFalse(r["floor_contact_verified"])
            self.assertFalse(r["usable_for_ffb"])
            if r["candidates"] != 1:
                self.assertFalse(r["quality_accepted"])
            if not r["quality_accepted"]:
                self.assertIsNone(r["observed_z_m"])
                self.assertIsNone(r["filtered_z_m"])
        no_target = [r for r in self.new_rows if r["dataset"] == "static" and r["reference_z_m"] is None]
        self.assertEqual(len(no_target), 332*3)
        self.assertTrue(all(not r["projection_candidate"] for r in no_target))

    def test_ties_all_included_and_point_changes_are_not_silently_hidden(self):
        good = [r for r in self.pixels if r["colour_candidate"] == "True"]
        self.assertEqual(len(good), 4354)
        for r in good:
            self.assertEqual(int(r["tie_inclusive_excluded_cutoff_ties"]), 0)
            self.assertGreaterEqual(int(r["tie_inclusive_selected_points"]), int(r["nominal_bottom_count"]))
        self.assertEqual(sum(int(r["legacy_excluded_cutoff_ties"]) > 0 for r in good), 4131)

    def test_existing_raw_samples_native_hash_and_both_point_selections(self):
        manifest = read_csv(experiment.quality.CONTACT / "results_r01/sample_manifest.csv")
        self.assertEqual(len(manifest), 41)
        for sample in manifest:
            path = Path(sample["path"])
            self.assertEqual(sha256(path), sample["png_sha256"])
            image = cv2.imread(str(path))
            self.assertEqual(image.shape, (720, 1280, 3))
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), sample["decoded_bgr_sha256"])
            k = experiment.quality.key(sample)
            candidates = self.old_candidates[k]
            if len(candidates) != 1:
                continue
            measured = experiment.extract_bottoms(image, candidates[0])
            saved = self.index[k]
            for mode, result in measured.items():
                self.assertEqual(result["colour_candidate"], experiment.quality.flag(saved["colour_candidate"]))
                for field in ("pixel_x", "pixel_y"):
                    expected = float(saved[mode+"_"+field]) if saved[mode+"_"+field] else None
                    self.assertEqual(result[field], expected)

    def test_known_occlusion_remains_withheld_and_recovery_is_reconfirmed(self):
        for model in self.models:
            rows = {r["frame"]: r for r in self.new_rows if r["dataset"] == "sequence" and r["model"] == model}
            self.assertTrue(all(not rows[f]["quality_accepted"] for f in range(1125, 1135)))
            self.assertFalse(rows[1135]["quality_accepted"])
            self.assertFalse(rows[1136]["quality_accepted"])
            self.assertTrue(rows[1137]["quality_accepted"])

    def test_causal_prefix_and_evaluation_reference_independence(self):
        ledger = self.ledger[:100]
        candidates = {experiment.quality.key(r): self.new_candidates[experiment.quality.key(r)] for r in ledger}
        prefix = experiment.quality.replay(ledger, candidates, self.models)
        expected = [dict(r, method="tie_inclusive") for r in prefix if r["method"] == "colour"]
        self.assertEqual(self.new_rows[:len(expected)], expected)
        relabelled = [dict(r, condition="not_used", reference_z_m=99, reference_x_m=-88) for r in ledger]
        other = experiment.quality.replay(relabelled, candidates, self.models)
        for a, b in zip(prefix, other):
            for field in ("quality_accepted", "reason", "observed_x_m", "observed_z_m", "nis", "confirmation_count"):
                self.assertEqual(a[field], b[field])

    def test_adverse_condition_and_metric_bias_are_preserved_not_tuned_away(self):
        summary = experiment.quality.summarize(self.all_rows)
        chosen = {r["method"]: r for r in summary if (r["dataset"], r["condition"], r["model"])
                  == ("static", "center_200", "height_only59")}
        self.assertLess(chosen["tie_inclusive"]["quality_accepted"], chosen["legacy"]["quality_accepted"])
        self.assertGreater(chosen["tie_inclusive"]["accepted_z_bias_m"], .5)

    def test_frozen_input_config_raw_and_output_hashes_unchanged(self):
        provenance = json.loads((self.directory / "provenance.json").read_text())
        for path, digest in {**self.hashes, **provenance["source_sha256"]}.items():
            self.assertEqual(sha256(Path(path)), digest, path)
        for name, digest in provenance["output_sha256"].items():
            self.assertEqual(sha256(self.directory / name), digest, name)
        previous = json.loads((experiment.QUALITY / "results_r02/provenance.json").read_text())
        self.assertEqual(provenance["settings"], previous["settings"])
        self.assertEqual(provenance["models"], previous["models"])


if __name__ == "__main__":
    unittest.main()
