"""Independent decision/count checks; no pose or calibration approval."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
from cone_view_consistency import sha256


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    target = HERE/"verification.json"
    if target.exists():
        raise ValueError("no result overwrite")
    output = HERE/"results_r01"
    study = json.loads((output/"provenance.json").read_text())
    for path, digest in study["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    for name, digest in study["output_sha256"].items():
        assert sha256(output/name) == digest, name
    pairs, regions = 0, 0
    for directory in sorted(output.iterdir()):
        if not directory.is_dir() or not (directory/"summary.json").exists():
            continue
        summary = json.loads((directory/"summary.json").read_text())
        for path, digest in summary["source_sha256"].items():
            assert sha256(Path(path)) == digest
        for name, digest in summary["output_sha256"].items():
            assert sha256(directory/name) == digest
        source = next(Path(p) for p in summary["source_sha256"] if p.endswith(".csv"))
        grouped = defaultdict(list)
        for row in read(source):
            reference = row[summary["reference_column"]] if summary["reference_column"] else summary["reference_id"]
            grouped[reference, row[summary["case_column"]]].append(row)
        results = read(directory/"view_consistency.csv")
        assert len(grouped) == len(results) == summary["pairs"]
        for row in results:
            group = grouped[row["reference"], row["case"]]
            # Recompute without calling the implementation's classifier.
            good = [r for r in group if float(r["ncc"]) >= .8 and float(r["separated_peak_margin"]) >= .02
                    and float(r["reverse_return_error_px"]) <= 1
                    and abs(float(r["delta_x_current_minus_reference_px"])) < float(r["search_margin_px"])
                    and abs(float(r["delta_y_current_minus_reference_px"])) < float(r["search_margin_px"])]
            changed = [r for r in good if max(abs(float(r["delta_x_current_minus_reference_px"])),
                                             abs(float(r["delta_y_current_minus_reference_px"]))) > 2]
            expected = "LOCAL_CHANGE_OBSERVED" if changed else "LOCAL_APPEARANCE_MATCH" if len(good) >= 2 else "INSUFFICIENT_EVIDENCE"
            assert row["state"] == expected
            assert len(group) == int(row["supplied_regions"]) == 5
            assert len(good) == int(row["reliable_regions"])
            assert len(changed) == int(row["shifted_regions"])
            assert row["invalid_regions"] == "0"
            assert row["calibration_validated"] == row["floor_contact_verified"] == row["usable_for_ffb"] == "False"
        pairs += len(results)
        regions += sum(len(group) for group in grouped.values())
    assert pairs == 80 and regions == 400
    combined = read(output/"combined_summary.csv")
    assert len(combined) == 80 and dict(Counter(r["state"] for r in combined)) == study["state_counts"]
    current = [r for r in combined if r["dataset"] == "within_same_video"]
    assert len(current) == 15 and all(r["state"] == "LOCAL_APPEARANCE_MATCH" for r in current)
    assert all(float(r["max_reliable_local_offset_px"]) == 0 for r in current)
    wide = [r for r in combined if r["dataset"] == "cross_wide40" and r["reference"] == "new_floor"]
    selected = {r["case"]: r for r in wide}
    for case in ("old_floor", "old_cone080", "old_cone130", "old_cone200", "old_left130"):
        assert selected[case]["state"] == "LOCAL_CHANGE_OBSERVED"
    assert selected["old_right130"]["state"] == "INSUFFICIENT_EVIDENCE"
    previous = HERE.parent/"floor_cone_same_pose_analysis_r01/analysis_r01/summary.json"
    for path, digest in json.loads(previous.read_text())["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    report = dict(status="PASS_OFFLINE_DECISION_AND_FROZEN_INPUT_CHECKS_NOT_CALIBRATION_APPROVAL",
                  pairs_checked=pairs, region_rows_checked=regions, current_video_local_matches=15,
                  all_outputs_ineligible_for_ffb=True, old_input_camera_images_and_runtime_configs_unchanged=True,
                  physical_output=False, source_sha256={str(p): sha256(p)
                      for p in (Path(__file__), ROOT/"tests/test_cone_view_consistency.py")})
    target.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
