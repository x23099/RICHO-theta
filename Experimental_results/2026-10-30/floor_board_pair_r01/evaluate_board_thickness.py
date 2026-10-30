#!/usr/bin/env python3
"""Compare supplied approximate board thickness; no refit to reported height."""
import argparse
import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thickness-mm", type=float, required=True)
    parser.add_argument("--approximate", action="store_true", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.thickness_mm <= 100:
        raise ValueError("finite plausible thickness in 0..100mm required")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = HERE / "edge_refinement_r02/edge_refinement.json"
    data = json.loads(source.read_text())
    comparison = next(c for c in data["comparisons"] if c["threshold"] == 170
        and c["method"] == "intensity_crossings" and c["trim_fraction"] == .15 and c["seed_edge_gate_px"] == 4.)
    rows = []
    for frame in comparison["frames"]:
        paper = frame["height_m"]
        floor_if = paper+args.thickness_mm/1000
        rows.append(dict(frame=frame["frame"], printed_plane_height_m=paper,
            floor_height_if_supplied_thickness_m=floor_if,
            residual_from_reported_0p590m_mm=1000*(floor_if-.590),
            thickness_needed_to_match_0p590m_mm=1000*(.590-paper),
            expected_printed_plane_height_if_0p590m_and_thickness_m=.590-args.thickness_mm/1000))
    result = dict(schema="approximate_board_thickness_comparison_v1", status="METRIC_AGREEMENT_NOT_CONFIRMED",
        user_reported_approximate_thickness_mm=args.thickness_mm,
        thickness_uncertainty_mm=None, reported_camera_floor_height_m=.590,
        meaning="conditional comparison assuming a flat parallel board; user thickness is approximate, not a precision measurement",
        frames=rows, no_height_or_corner_refit=True, physical_metric_verified=False,
        live_integrated=False, usable_for_ffb=False,
        source_sha256={str(source): digest(source), str(Path(__file__).resolve()): digest(Path(__file__).resolve())})
    with (args.output_dir / "thickness_check.json").open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    with (args.output_dir / "thickness_check.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    x = [0, 1]
    ax.bar(x, [100*r["floor_height_if_supplied_thickness_m"] for r in rows], color=["tab:blue", "tab:orange"], width=.5)
    ax.axhline(59, color="black", linestyle="--", label="Reported lens-to-floor height: 59cm (not fitted)")
    for i, row in enumerate(rows):
        ax.text(i, 100*row["floor_height_if_supplied_thickness_m"]+.3,
                f"{100*row['floor_height_if_supplied_thickness_m']:.2f}cm\nresidual {row['residual_from_reported_0p590m_mm']:.1f}mm", ha="center")
    ax.set(xticks=x, xticklabels=[f"Frame {r['frame']}" for r in rows], ylim=(0, 65),
           ylabel="Lens-to-floor height IF board thickness is 15mm (cm)",
           title="Approximate board thickness does not remove the height discrepancy")
    ax.legend(loc="lower center", fontsize=9)
    fig.text(.5, .02, f"User supplied approximate thickness: {args.thickness_mm:g}mm; uncertainty not specified.\n"
             "No physical accuracy approval, calibration change, or live integration.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .09, 1, 1))
    fig.savefig(args.output_dir / "thickness_comparison.png", dpi=150)
    plt.close(fig)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
