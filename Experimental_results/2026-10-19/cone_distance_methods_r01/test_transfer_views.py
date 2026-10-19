"""Checks for the supplementary frozen-region image audit."""
from collections import Counter
import json
from pathlib import Path
import sys
import unittest

import cv2

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import audit_transfer_views as views
from cone_dataset import read_csv,sha256
from cone_view_consistency import assess_local_view


class TransferViewsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=HERE/"view_audit_r01"
        cls.rows=read_csv(cls.out/"local_matches.csv")
        cls.summary=read_csv(cls.out/"summary.csv")

    def test_all_fixed_regions_and_missing_texture_retained(self):
        self.assertEqual(len(self.rows),70)
        self.assertEqual(len(self.summary),14)
        self.assertEqual(set(Counter(r["case"] for r in self.rows).values()),{5})
        missing=[r for r in self.rows if r["evaluated"]=="False"]
        self.assertEqual(len(missing),14)
        for row in missing:
            self.assertEqual(row["delta_x_current_minus_reference_px"],"")
            self.assertEqual(row["delta_y_current_minus_reference_px"],"")
            self.assertEqual(row["reason"],"insufficient_reference_texture_no_offset_inferred")

    def test_each_local_measurement_reproduces_from_native_pixels(self):
        reference=cv2.imread(str(views.REFERENCE),cv2.IMREAD_GRAYSCALE)
        for identity,path in views.targets():
            views.verify_native_manifest(path)
            current=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
            for region in views.REGIONS:
                row=next(r for r in self.rows if r["case"]==identity and r["region"]==region[0])
                if row["evaluated"]=="False":
                    with self.assertRaisesRegex(ValueError,"insufficient texture"):
                        views.match_region(reference,current,region,margin=20)
                else:
                    result=views.match_region(reference,current,region,margin=20)
                    for key in ("delta_x_current_minus_reference_px","delta_y_current_minus_reference_px","ncc",
                                "separated_peak_margin","reverse_return_error_px"):
                        self.assertAlmostEqual(float(row[key]),result[key],places=7)

    def test_summary_recomputed_and_never_calibration_approval(self):
        for group in self.summary:
            selected=[r for r in self.rows if r["case"]==group["case"] and r["evaluated"]=="True"]
            result=assess_local_view(selected)
            self.assertEqual(result["state"],group["state"])
            self.assertEqual(result["reliable_regions"],int(group["reliable_regions"]))
            self.assertEqual(group["calibration_validated"],"False")
            self.assertEqual(group["usable_for_ffb"],"False")
        controls=[r for r in self.summary if r["case"].startswith("paper_control_")]
        self.assertEqual(len(controls),4)
        self.assertTrue(all(r["state"]=="LOCAL_APPEARANCE_MATCH" for r in controls))

    def test_hashes_and_nonmutation_flags(self):
        provenance=json.loads((self.out/"provenance.json").read_text())
        for path,digest in provenance["source_sha256"].items():
            self.assertEqual(sha256(Path(path)),digest,path)
        for name,digest in provenance["output_sha256"].items():
            self.assertEqual(sha256(self.out/name),digest,name)
        self.assertFalse(provenance["images_edited"])
        self.assertFalse(provenance["geometry_changed"])


if __name__=="__main__":unittest.main()
