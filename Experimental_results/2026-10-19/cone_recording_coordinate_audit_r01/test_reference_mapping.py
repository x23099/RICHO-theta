import copy
import json
import unittest

import audit_reference_mapping as run
from cone_dataset import read_csv, sha256


class ReferenceMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = {k: read_csv(p) for k, p in run.inputs().items()}

    def test_corrected_cone_centre_and_paper_corner_not_conflated(self):
        rows = run.audit_tables(self.data)
        left = next(r for r in rows if r["identity"] == "left_130")
        paper = next(r for r in rows if r["identity"] == "L130")
        self.assertEqual(left["archival_nominal_x_m"], -.4)
        self.assertEqual(left["comparison_x_m"], -.5875)
        self.assertEqual(paper["comparison_x_m"], -.4)
        self.assertEqual(left["comparison_z_m"], paper["comparison_z_m"])
        self.assertTrue(all(not r["usable_for_ffb"] for r in rows))

    def test_stale_lateral_reference_in_latest_summary_rejected(self):
        data = copy.deepcopy(self.data)
        row = next(r for r in data["support_summary"] if r["condition"] == "left_130")
        row["reference_x_m"] = "-0.4"
        with self.assertRaises(ValueError):
            run.audit_tables(data)

    def test_saved_rows_recomputed_and_hashes_unchanged(self):
        root = run.HERE / "reference_mapping_r01"
        strings = [{k: "" if v is None else str(v) for k, v in r.items()} for r in run.audit_tables(self.data)]
        self.assertEqual(strings, read_csv(root / "reference_mapping.csv"))
        provenance = json.loads((root / "provenance.json").read_text())
        for name, digest in provenance["source_sha256"].items():
            self.assertEqual(sha256(name), digest)
        for name, digest in provenance["output_sha256"].items():
            self.assertEqual(sha256(root / name), digest)


if __name__ == "__main__":
    unittest.main()
