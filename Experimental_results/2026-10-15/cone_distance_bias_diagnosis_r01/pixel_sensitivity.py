"""Diagnostic uniform pixel shifts ONLY; never edit inputs or fit corrections."""
import json
from pathlib import Path

from analyze import HERE, project_pixels_to_floor, read_csv, sha256, write_csv


def main():
    output = HERE/"sensitivity_r01"
    if output.exists():
        raise ValueError("no result overwrite")
    original = HERE/"results_r01"
    source = original/"distance_decomposition.csv"
    provenance_file = original/"provenance.json"
    provenance = json.loads(provenance_file.read_text())
    geometry = provenance["geometry"]
    cases = read_csv(source)
    results = []
    # Fixed symmetric illustration, NOT threshold search or calibrated error CI.
    for case in cases:
        x, y = float(case["bbox_pixel_x"]), float(case["bbox_pixel_y"])
        for dy in (-2, 0, 2):
            _, z = project_pixels_to_floor([[x, y+dy]], geometry)[0]
            results.append(dict(dataset=case["dataset"], point_id=case["point_id"], basis=case["basis"],
                                reference_z_m=case["reference_z_m"], hypothetical_bbox_y_shift_px=dy,
                                original_bbox_x=x, original_bbox_y=y, hypothetical_z_m=float(z),
                                hypothetical_error_z_m=float(z)-float(case["reference_z_m"]),
                                used_in_production=False, original_pixel_changed=False, usable_for_ffb=False))
    output.mkdir()
    write_csv(output/"uniform_pixel_shift.csv", results)
    report = dict(status="DIAGNOSTIC_SYMMETRIC_PIXEL_SENSITIVITY_NOT_PROPOSED_CORRECTION", rows=len(results),
                  chosen_shift_or_calibration=None, correction_applied=False, physical_output=False,
                  source_sha256={str(p): sha256(p) for p in (Path(__file__), source, provenance_file,
                      HERE.parent/"cone_geometry_candidates_r01/geometry_models.py")},
                  output_sha256={"uniform_pixel_shift.csv": sha256(output/"uniform_pixel_shift.csv")})
    (output/"provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    for row in results:
        if row["basis"] == "manual_candidate_frame" and row["point_id"] == "C200":
            print(row["dataset"], row["hypothetical_bbox_y_shift_px"], row["hypothetical_z_m"])


if __name__ == "__main__":
    main()
