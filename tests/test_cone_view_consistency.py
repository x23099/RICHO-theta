import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from cone_view_consistency import (ViewConsistencySettings, assess_local_view, summarize_pairs, main)


def region(name, x=0, y=0, **extra):
    return dict(region=name, reference="r", case="c", delta_x_current_minus_reference_px=x,
                delta_y_current_minus_reference_px=y, ncc=.95, separated_peak_margin=.1,
                reverse_return_error_px=0, search_margin_px=20, **extra)


class ViewConsistencyTest(unittest.TestCase):
    def test_multiple_good_features_match_but_never_validate_calibration(self):
        r = assess_local_view([region("a"), region("b")])
        self.assertEqual(r["state"], "LOCAL_APPEARANCE_MATCH")
        self.assertTrue(r["appearance_consistent"])
        for field in ("calibration_validated", "floor_contact_verified", "usable_for_ffb"):
            self.assertFalse(r[field])

    def test_empty_and_single_match_are_unknown_not_zero_offset(self):
        self.assertEqual(assess_local_view([])["state"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(assess_local_view([])["max_reliable_local_offset_px"])
        self.assertEqual(assess_local_view([region("a")])["state"], "INSUFFICIENT_EVIDENCE")

    def test_one_changed_feature_blocks_other_matches(self):
        r = assess_local_view([region("a"), region("b"), region("c", x=10)])
        self.assertEqual(r["state"], "LOCAL_CHANGE_OBSERVED")
        self.assertEqual(r["shifted_region_names"], "c")

    def test_insufficient_match_cannot_claim_camera_change(self):
        r = assess_local_view([dict(region("a", x=10), ncc=.2)])
        self.assertEqual(r["state"], "INSUFFICIENT_EVIDENCE")

    def test_boundary_is_not_a_measured_shift(self):
        r = assess_local_view([region("a", x=20)])
        self.assertEqual(r["state"], "INSUFFICIENT_EVIDENCE")

    def test_reliable_flag_is_not_trusted(self):
        bad = dict(region("a"), ncc=.2, reliable_for_local_feature_comparison=True)
        self.assertEqual(assess_local_view([bad])["reliable_regions"], 0)

    def test_duplicates_and_blank_names_fail_closed(self):
        for invalid in (region("a"), region("")):
            r = assess_local_view([region("a"), region("b"), invalid])
            self.assertEqual(r["state"], "INSUFFICIENT_EVIDENCE")

    def test_invalid_diagnostics_fail_closed_even_with_two_good_regions(self):
        for field, value in (("ncc", float("nan")), ("separated_peak_margin", -.1),
                             ("delta_y_current_minus_reference_px", float("inf")),
                             ("delta_x_current_minus_reference_px", .5),
                             ("reverse_return_error_px", -1), ("search_margin_px", 3)):
            bad = dict(region("c"), **{field: value})
            self.assertEqual(assess_local_view([region("a"), region("b"), bad])["state"], "INSUFFICIENT_EVIDENCE")

    def test_missing_diagnostics_fail_closed(self):
        bad = region("a")
        del bad["ncc"]
        self.assertEqual(assess_local_view([bad])["invalid_regions"], 1)

    def test_development_bounds_are_inclusive(self):
        self.assertTrue(assess_local_view([region("a", 2, -2), region("b")])["appearance_consistent"])
        self.assertFalse(assess_local_view([region("a", 3), region("b")])["appearance_consistent"])

    def test_competing_peaks_and_bad_reverse_are_not_accepted(self):
        for overrides in (dict(separated_peak_margin=.001), dict(reverse_return_error_px=2)):
            self.assertEqual(assess_local_view([dict(region("a"), **overrides)])["reliable_regions"], 0)

    def test_settings_reject_invalid_thresholds(self):
        for kwargs in (dict(min_reliable_regions=1), dict(min_reliable_regions=2.5),
                       dict(max_local_offset_px=-1), dict(min_ncc=2), dict(min_peak_margin=0),
                       dict(max_reverse_error_px=float("nan")), dict(max_local_offset_px=True)):
            with self.assertRaises(ValueError):
                ViewConsistencySettings(**kwargs)

    def test_explicit_reference_identity_required(self):
        rows = [region("a"), region("b")]
        for kwargs in ({}, dict(reference_column="reference", reference_id="r")):
            with self.assertRaises(ValueError):
                summarize_pairs(rows, case_column="case", **kwargs)

    def test_pair_groups_do_not_share_evidence(self):
        rows = [region("a"), dict(region("b"), case="another")]
        groups = summarize_pairs(rows, reference_column="reference", case_column="case")
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(r["state"] == "INSUFFICIENT_EVIDENCE" for r in groups))

    def test_empty_identity_and_csv_rejected(self):
        for rows in ([], [dict(region("a"), case="")]):
            with self.assertRaises(ValueError):
                summarize_pairs(rows, reference_id="r", case_column="case")

    def test_cli_roundtrip_and_output_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            path = directory/"matches.csv"
            rows = [region("a"), region("b")]
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            args = ["--matches", str(path), "--reference-column", "reference", "--case-column", "case",
                    "--output-dir", str(directory/"result")]
            with redirect_stdout(io.StringIO()):
                main(args)
            report = json.loads((directory/"result/summary.json").read_text())
            self.assertEqual(report["pairs"], 1)
            self.assertFalse(report["calibration_selected"])
            before = (directory/"result/view_consistency.csv").read_bytes()
            with self.assertRaises(ValueError):
                main(args)
            self.assertEqual(before, (directory/"result/view_consistency.csv").read_bytes())


if __name__ == "__main__":
    unittest.main()
