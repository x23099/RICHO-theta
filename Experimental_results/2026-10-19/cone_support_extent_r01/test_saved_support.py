from collections import defaultdict
import hashlib
import json
from pathlib import Path
import unittest

import cv2

import analyze_support as source
import extent_audit as ranges
from cone_dataset import read_csv, sha256
from support import SETTINGS, describe_support


def strings(rows):
    return [{k: "" if v is None else str(v) for k, v in row.items()} for row in rows]


class RangeAnalysisTests(unittest.TestCase):
    def fixture(self, frames, consistent=False):
        rows, points = [], []
        for frame, start in frames:
            available = start is not None
            rows.append(dict(dataset="d", session="s", frame=frame, condition="same", time_sec=frame/30,
                             envelope_available=available, line_consistent=consistent,
                             legacy_pixel_x=start, legacy_pixel_y=40 if available else None))
            if available:
                points.extend(dict(dataset="d", session="s", frame=str(frame), x=str(x), y="40",
                                   in_observed_support="True") for x in range(start, start+10))
        return rows, points

    def test_nonlinear_frames_are_included_without_line_filter(self):
        rows, points = self.fixture([(1, 0), (2, 1)], consistent=False)
        records, steps = ranges.audit_ranges(rows, points)
        self.assertEqual(len(records), 2)
        self.assertEqual(len(steps), 1)
        self.assertFalse(steps[0]["both_line_consistent"])
        self.assertEqual(steps[0]["shared_observed_columns"], 9)
        self.assertEqual(steps[0]["envelope_dy_abs_median_px"], 0)

    def test_missing_or_nonconsecutive_frames_never_bridged(self):
        for frames in ([(1, 0), (2, None), (3, 1)], [(1, 0), (3, 1)]):
            rows, points = self.fixture(frames)
            self.assertEqual(ranges.audit_ranges(rows, points)[1], [])

    def test_disjoint_observed_columns_not_extrapolated(self):
        rows, points = self.fixture([(1, 0), (2, 30)])
        step = ranges.audit_ranges(rows, points)[1][0]
        self.assertEqual(step["shared_observed_columns"], 0)
        self.assertIsNone(step["envelope_dy_abs_median_px"])
        self.assertEqual(step["support_column_iou"], 0)

    def test_duplicate_envelope_columns_refused(self):
        rows, points = self.fixture([(1, 0)])
        with self.assertRaises(ValueError):
            ranges.audit_ranges(rows, points+[points[0]])


class SavedSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = source.HERE / "results_r01"
        cls.extra = source.HERE / "extent_audit_r01"
        cls.raw_rows = read_csv(cls.directory / "observations.csv")
        cls.rows = [ranges.typed(r) for r in cls.raw_rows]
        cls.points = read_csv(cls.directory / "lower_envelopes.csv")
        cls.by_key = {ranges.key(r): r for r in cls.rows}
        cls.curves = defaultdict(list)
        for p in cls.points:
            cls.curves[ranges.key(p)].append((float(p["x"]), float(p["y"])))

    def test_every_frame_and_original_colour_guard_retained(self):
        self.assertEqual(len(self.rows), 5143)
        self.assertEqual(len(self.by_key), 5143)
        old = [r for r in read_csv(source.quality.CONTACT / "full_replay_r01/pixels.csv") if r["v_min"] == "30"]
        for p in old:
            r = self.by_key[ranges.key(p)]
            self.assertEqual(r["envelope_available"], source.quality.flag(p["colour_candidate"]))
            self.assertEqual(r["legacy_pixel_x"], float(p["pixel_x"]) if p["pixel_x"] else None)
            self.assertEqual(r["legacy_pixel_y"], float(p["pixel_y"]) if p["pixel_y"] else None)
        self.assertEqual(sum(r["envelope_available"] for r in self.rows), 4354)
        self.assertEqual(len(self.points), 231362)

    def test_all_saved_lines_and_support_ranges_recompute_from_retained_envelopes(self):
        count = 0
        for k, points in self.curves.items():
            result, envelope, selected = describe_support(points)
            saved = self.by_key[k]
            for field, value in result.items():
                self.assertEqual(value, saved[field], (k, field))
            count += 1
        self.assertEqual(count, 4354)

    def test_both_adjacency_scopes_and_summaries_reproduce(self):
        products = {"summary.csv": source.summarize(self.rows),
                    "adjacent_support.csv": source.adjacent(self.rows),
                    "adjacent_summary.csv": source.summarize_steps(source.adjacent(self.rows))}
        for name, rows in products.items():
            self.assertEqual(strings(rows), read_csv(self.directory / name))
        records, steps = ranges.audit_ranges(self.rows, self.points)
        for name, rows in (("observed_ranges.csv", records), ("adjacent_envelopes.csv", steps),
                           ("range_stability_summary.csv", ranges.summarize(steps))):
            self.assertEqual(strings(rows), read_csv(self.extra / name))

    def test_existing_native_pngs_match_raw_envelopes_and_no_image_mutation(self):
        _, selected, _, _ = source.quality.load_inputs()
        manifest = read_csv(source.quality.CONTACT / "results_r01/sample_manifest.csv")
        self.assertEqual(len(manifest), 41)
        for p in manifest:
            path = Path(p["path"])
            self.assertEqual(sha256(path), p["png_sha256"])
            image = cv2.imread(str(path))
            self.assertEqual(image.shape, (720, 1280, 3))
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), p["decoded_bgr_sha256"])
            before = image.tobytes()
            k = ranges.key(p)
            result, envelope, support = source.inspect_image(image, selected[k])
            self.assertEqual(image.tobytes(), before)
            saved = self.by_key[k]
            for field, value in result.items():
                self.assertEqual(value, saved[field], (k, field))
            self.assertEqual([tuple(point) for point in envelope], self.curves.get(k, []))

    def test_occlusion_edge_must_not_be_claimed_as_verified_base(self):
        for frame in (1133, 1134):
            r = next(r for r in self.rows if r["dataset"] == "sequence" and r["frame"] == frame)
            self.assertTrue(r["line_consistent"])
            self.assertFalse(r["floor_contact_verified"])
            self.assertFalse(r["usable_for_ffb"])
        for r in self.rows:
            self.assertFalse(r["floor_contact_verified"])
            self.assertFalse(r["usable_for_ffb"])

    def test_missing_and_ambiguous_frames_have_no_fabricated_envelope(self):
        for row in self.rows:
            if row["candidates"] != 1:
                self.assertFalse(row["envelope_available"])
                self.assertNotIn(ranges.key(row), self.curves)
        no_target = [r for r in self.rows if r["dataset"] == "static" and r["condition"] == "none"]
        self.assertEqual(len(no_target), 332)
        self.assertTrue(all(not r["envelope_available"] for r in no_target))

    def test_actual_shared_columns_compared_not_different_x_or_line_only_subset(self):
        records, steps = ranges.audit_ranges(self.rows, self.points)
        summary = ranges.summarize(steps)
        left = next(r for r in summary if (r["dataset"], r["condition"]) == ("static", "left_130"))
        self.assertEqual(left["adjacent_envelope_pairs"], 613)
        self.assertEqual(left["also_both_line_consistent"], 11)
        self.assertLess(left["dx_lo_px_p95"], left["legacy_dx_px_p95"])
        self.assertLess(left["dx_hi_px_p95"], left["legacy_dx_px_p95"])

    def test_all_frozen_source_raw_config_image_results_and_settings_hashes(self):
        for directory in (self.directory, self.extra):
            provenance = json.loads((directory / "provenance.json").read_text())
            for path, digest in provenance["source_sha256"].items():
                self.assertEqual(sha256(Path(path)), digest, path)
            for name, digest in provenance["output_sha256"].items():
                self.assertEqual(sha256(directory / name), digest, name)
        self.assertEqual(json.loads((self.directory / "provenance.json").read_text())["settings"], SETTINGS)


if __name__ == "__main__":
    unittest.main()
