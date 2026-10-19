import copy
import json
from pathlib import Path
import unittest

import x_only_replay as candidate
from cone_dataset import read_csv, sha256


class XOnlyInputTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(dataset="s", session="s", frame=1, time_sec=.03)
        self.k = candidate.first.quality.key(self.source)
        self.box = dict(x1=300, y1=300, x2=340, y2=400, confidence=.9, class_id=0,
                        _colour=dict(valid=True, x=313.5, y=396, reason="unverified_visible_colour_bottom"))
        self.selected = {self.k: [self.box]}
        self.pixel = dict(dataset="s", session="s", frame="1", time_sec=".03", candidates="1",
                          colour_candidate="True", reason="unverified_visible_colour_bottom",
                          legacy_pixel_y="396", tie_inclusive_pixel_x="320", tie_inclusive_pixel_y="395")

    def join(self, pixels=None, selected=None):
        return candidate.candidates_from_pixels([self.source], selected or self.selected, pixels or [self.pixel])

    def test_x_changes_but_y_is_exactly_original_without_mutation(self):
        before = copy.deepcopy(self.selected)
        result = self.join()[self.k][0]["_colour"]
        self.assertEqual(result["x"], 320)
        self.assertEqual(result["y"], 396)
        self.assertEqual(self.selected, before)

    def test_labels_and_inclusive_y_do_not_affect_x_only_point(self):
        altered = dict(self.pixel, tie_inclusive_pixel_y="999", reference_z_m="999", condition="test")
        self.assertEqual(self.join([altered]), self.join())

    def test_duplicate_missing_time_count_nonfinite_and_wrong_legacy_y_rejected(self):
        for pixels in ([self.pixel, self.pixel], [dict(self.pixel, frame="2")],
                       [dict(self.pixel, time_sec="1")], [dict(self.pixel, candidates="2")],
                       [dict(self.pixel, tie_inclusive_pixel_x="nan")], [dict(self.pixel, legacy_pixel_y="395")]):
            with self.assertRaises(ValueError):
                self.join(pixels)

    def test_missing_evidence_is_not_filled(self):
        selected = {self.k: [dict(self.box, _colour=dict(valid=False, x=None, y=None, reason="no_supported_colour_contour"))]}
        p = dict(self.pixel, colour_candidate="False", reason="no_supported_colour_contour", legacy_pixel_y="", tie_inclusive_pixel_x="")
        result = self.join([p], selected)[self.k][0]["_colour"]
        self.assertFalse(result["valid"])
        self.assertIsNone(result["x"])
        self.assertIsNone(result["y"])


class XOnlyReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger, cls.pixels, cls.models, cls.rows, cls.new, cls.hashes = candidate.run()
        cls.directory = candidate.HERE / "x_only_r01"

    def test_all_saved_observations_summaries_and_pairs_reproduce(self):
        products = {"observations.csv": self.new,
                    "summary.csv": candidate.first.quality.summarize(self.rows),
                    "frame_pairs.csv": candidate.common_comparison(self.rows),
                    "jitter_summary.csv": candidate.first.jitter.summarize(candidate.first.jitter.differences(candidate.first.csv_rows(self.rows)))}
        for name, values in products.items():
            self.assertEqual(candidate.first.csv_rows(values), read_csv(self.directory / name))

    def test_all_source_frames_y_is_legacy_not_reestimated(self):
        _, selected, _, _ = candidate.first.quality.load_inputs()
        joined = candidate.candidates_from_pixels(self.ledger, selected, self.pixels)
        self.assertEqual(len(joined), 5143)
        for k, rows in joined.items():
            self.assertEqual(len(rows), len(selected[k]))
            for row, old in zip(rows, selected[k]):
                self.assertEqual(row["_colour"]["y"], old["_colour"]["y"])

    def test_full_retention_flags_no_predicted_observations_and_occlusion(self):
        self.assertEqual(len(self.new), 5143*3)
        self.assertEqual(len({(candidate.first.quality.key(r), r["model"]) for r in self.new}), len(self.new))
        for row in self.new:
            self.assertFalse(row["usable_for_ffb"])
            self.assertFalse(row["floor_contact_verified"])
            if not row["quality_accepted"]:
                self.assertIsNone(row["observed_z_m"])
                self.assertIsNone(row["filtered_z_m"])
            if row["dataset"] == "sequence" and 1125 <= row["frame"] <= 1134:
                self.assertFalse(row["quality_accepted"])

    def test_inputs_outputs_and_both_prior_candidates_unchanged(self):
        saved = json.loads((self.directory / "provenance.json").read_text())
        for path, digest in {**self.hashes, **saved["source_sha256"]}.items():
            self.assertEqual(sha256(Path(path)), digest)
        for name, digest in saved["output_sha256"].items():
            self.assertEqual(sha256(self.directory / name), digest)


if __name__ == "__main__":
    unittest.main()
