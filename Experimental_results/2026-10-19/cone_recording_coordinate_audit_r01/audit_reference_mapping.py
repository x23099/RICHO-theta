"""Check archived nominal labels vs later confirmed references, without rewriting either."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "Experimental_results/2026-10-15"
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv


def inputs():
    return dict(nominal=OLD / "cone_static_distance_r01/session_conditions.csv",
                confirmed=OLD / "cone_geometry_candidates_r01/reference_update_r01/reference_conditions.csv",
                paper=OLD / "paper_reference7_r01/analysis_r01/reference_points_primary170.csv",
                point_summary=HERE.parent / "cone_distance_methods_r01/results_r01/summary.csv",
                support_summary=HERE.parent / "cone_support_projection_r01/results_r01/summary.csv")


def audit_tables(data):
    nominal = {r["condition"]: r for r in data["nominal"]}
    result = []
    for r in data["confirmed"]:
        condition = r["condition"]
        x, z = float(r["reference_x_m"]), float(r["reference_z_m"])
        for group in ("point_summary", "support_summary"):
            rows = [s for s in data[group] if s["dataset"] == "static" and s["condition"] == condition]
            if not rows or any(float(s["reference_x_m"]) != x or float(s["reference_z_m"]) != z for s in rows):
                raise ValueError("latest analysis uses stale nominal instead of confirmed physical reference")
        n = nominal[condition]
        if float(n["reference_z_m"]) != z:
            raise ValueError("Z reference must remain vehicle-side base edge, not base centre")
        result.append(dict(kind="cone", identity=condition, archival_nominal_x_m=float(n["reference_x_m"]),
                           comparison_x_m=x, comparison_z_m=z, physical_point=r["physical_point"],
                           orientation_assumption=r["orientation_assumption"],
                           current_point_and_support_references_consistent=True,
                           reference_kind="user_confirmation_with_axis_parallel_conversion_assumption",
                           pixel_gt_verified=False, usable_for_ffb=False))
    for r in data["paper"]:
        result.append(dict(kind="paper", identity=r["point_id"], archival_nominal_x_m=None,
                           comparison_x_m=float(r["reference_x_m"]), comparison_z_m=float(r["reference_z_m"]),
                           physical_point="vehicle-side paper edge left corner", orientation_assumption="not equated to cone base centre",
                           current_point_and_support_references_consistent=None,
                           reference_kind="user confirmed paper corner placement; same-recording provisional calibration",
                           pixel_gt_verified=False, usable_for_ffb=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    paths = inputs()
    hashes = {str(p): sha256(p) for p in [*paths.values(), Path(__file__), HERE / "test_reference_mapping.py"]}
    rows = audit_tables({k: read_csv(p) for k, p in paths.items()})
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "reference_mapping.csv", rows)
    if not all(sha256(p) == h for p, h in hashes.items()):
        raise ValueError("input changed during read-only reference audit")
    (args.output_dir / "provenance.json").write_text(json.dumps(dict(
        status="REFERENCE_MAPPING_AUDIT_NO_COORDINATE_OR_PREDICTION_CHANGES", rows=len(rows),
        source_sha256=hashes, output_sha256={"reference_mapping.csv": sha256(args.output_dir / "reference_mapping.csv")},
        physical_output=False, usable_for_ffb=False), indent=2)+"\n")
    print("Confirmed reference mapping:", len(rows), "rows; no stale lateral reference in current analyses")


if __name__ == "__main__":
    main()
