"""Supplementary ALL-pair fixed-criteria search; not image registration."""
from collections import Counter
import json
from pathlib import Path

import cv2

from analyze import HERE, REGIONS, match_region, read_csv, sha256, write_csv


def main():
    output = HERE/"wide_search_r01"
    if output.exists():
        raise ValueError("no result overwrite")
    previous = HERE/"results_r01"
    provenance = json.loads((previous/"provenance.json").read_text())
    for path, digest in provenance["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    initial = read_csv(previous/"local_feature_matches.csv")
    files = {r[k] for r in initial for k in ("reference_file", "current_file")}
    images = {p: cv2.imread(p, cv2.IMREAD_GRAYSCALE) for p in files}
    regions = {r[0]: r for r in REGIONS}
    results = []
    for row in initial:
        result = match_region(images[row["reference_file"]], images[row["current_file"]],
                              regions[row["region"]], margin=40)
        results.append(dict(reference_case=row["reference_case"], current_case=row["current_case"],
                            reference_file=row["reference_file"], current_file=row["current_file"], **result))
    assert len(results) == len(initial) == 135
    output.mkdir()
    write_csv(output/"local_feature_matches.csv", results)
    transitions = Counter((old["reliable_for_local_feature_comparison"], str(new["reliable_for_local_feature_comparison"]))
                          for old, new in zip(initial, results))
    source_files = sorted(files)+[str(Path(__file__)), str(HERE/"wide_search_method.md"),
                                 str(previous/"provenance.json"), str(previous/"local_feature_matches.csv"),
                                 str(HERE.parent/"cone_geometry_candidates_r01/view_registration.py")]
    report = dict(status="COMPLETED_WIDE_LOCAL_SEARCH_NOT_POSE_OR_DISTANCE_CORRECTION", rows=len(results),
                  all_original_pairs_retained=True, search_margin_px=40, thresholds_changed=False,
                  transitions={f"{old}->{new}": count for (old, new), count in sorted(transitions.items())},
                  physical_output=False, correction_applied=False,
                  source_sha256={p: sha256(Path(p)) for p in source_files},
                  output_sha256={"local_feature_matches.csv": sha256(output/"local_feature_matches.csv")})
    (output/"provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report["transitions"], indent=2))
    for row in results:
        if (row["reference_case"] == "new_floor" and row["current_case"].startswith("old_")
                and row["reliable_for_local_feature_comparison"]):
            print(row["current_case"], row["region"], row["delta_x_current_minus_reference_px"],
                  row["delta_y_current_minus_reference_px"], row["ncc"])


if __name__ == "__main__":
    main()
