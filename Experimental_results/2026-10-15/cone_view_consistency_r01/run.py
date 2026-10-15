"""Replay diagnostic CSVs through the offline local-view consistency check."""
from collections import Counter
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
from cone_view_consistency import main as check_main, sha256
from cone_dataset import read_csv, write_csv


def main():
    output = HERE/"results_r01"
    if output.exists():
        raise ValueError("no frozen artifact overwrite")
    bias = HERE.parent/"cone_distance_bias_diagnosis_r01"
    entries = [
        ("cross_primary20", bias/"results_r01/local_feature_matches.csv", "reference_case", None, "current_case"),
        ("cross_wide40", bias/"wide_search_r01/local_feature_matches.csv", "reference_case", None, "current_case"),
        ("within_same_video", HERE.parent/"floor_cone_same_pose_analysis_r01/analysis_r01/within_video_vehicle_features.csv",
         None, "same_pose_frame141", "frame"),
        ("previous_controls_and_transfer", HERE.parent/"cone_geometry_candidates_r01/view_audit_r01/local_feature_matches.csv",
         "reference", None, "case")]
    sources = [Path(__file__), HERE/"method.md", ROOT/"src/cone_view_consistency.py",
               ROOT/"tests/test_cone_view_consistency.py"]+[e[1] for e in entries]
    before = {str(p): sha256(p) for p in sources}
    combined = []
    for name, source, reference_column, reference_id, case_column in entries:
        arguments = ["--matches", str(source), "--case-column", case_column,
                     "--output-dir", str(output/name)]
        arguments.extend(["--reference-column", reference_column] if reference_column
                         else ["--reference-id", reference_id])
        check_main(arguments)
        combined.extend(dict(dataset=name, **row) for row in read_csv(output/name/"view_consistency.csv"))
    assert len(combined) == 80
    assert sum(int(r["supplied_regions"]) for r in combined) == 400
    assert all(r["calibration_validated"] == r["floor_contact_verified"] == r["usable_for_ffb"] == "False" for r in combined)
    write_csv(output/"combined_summary.csv", combined)
    plot(combined, output/"local_appearance_matrix.png")
    assert all(sha256(Path(p)) == digest for p, digest in before.items())
    report = dict(status="COMPLETED_DIAGNOSTIC_APPEARANCE_CHECK_NOT_CALIBRATION_OR_FFB_APPROVAL",
                  cases=len(combined), region_rows=400, state_counts=dict(Counter(r["state"] for r in combined)),
                  source_sha256=before, output_sha256={str(p.relative_to(output)): sha256(p)
                      for p in output.rglob("*") if p.is_file() and "matplotlib_config" not in p.parts},
                  thresholds_optimized=False, input_images_changed=False, parameters_fitted=False,
                  production_settings_changed=False, physical_output=False)
    (output/"provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report["state_counts"], indent=2))


def plot(rows, path):
    os.environ.setdefault("MPLCONFIGDIR", str(path.parent/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    import numpy as np
    references = ("old_floor", "old_cone130", "new_floor")
    cases = ("old_floor", "old_cone080", "old_cone130", "old_cone200", "old_left130", "old_right130",
             "new_floor", "new_cone130", "new_cone200")
    codes = dict(LOCAL_APPEARANCE_MATCH=0, LOCAL_CHANGE_OBSERVED=1, INSUFFICIENT_EVIDENCE=2)
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), layout="constrained")
    for dataset, axis in zip(("cross_primary20", "cross_wide40"), axes):
        matrix = np.empty((3, 9))
        for i, reference in enumerate(references):
            for j, case in enumerate(cases):
                match = [r for r in rows if r["dataset"] == dataset and r["reference"] == reference and r["case"] == case]
                assert len(match) == 1
                matrix[i, j] = codes[match[0]["state"]]
                axis.text(j, i, ("LOCAL MATCH", "CHANGE", "UNKNOWN")[int(matrix[i, j])], ha="center", va="center", fontsize=7)
        axis.imshow(matrix, cmap=ListedColormap(["#a8d5ba", "#efb77f", "#d2d5d8"]), vmin=0, vmax=2, aspect="auto")
        axis.set(yticks=range(3), yticklabels=references, xticks=range(9), xticklabels=cases,
                 title=dataset+": local appearance only; NO cell approves distance calibration")
        axis.set_ylabel("Reference image")
        axis.tick_params(axis="x", rotation=20)
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
