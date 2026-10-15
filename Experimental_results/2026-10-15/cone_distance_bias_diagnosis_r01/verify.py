"""Independent pixel-ray equations, conservation and source integrity checks."""
import json
from pathlib import Path

import numpy as np

from analyze import HERE, CAMERA_KEYS, read_csv, sha256
from ground_contact import dual_fisheye_pixels_to_vehicle_rays


def direct_z(pixel, geometry):
    _, ray = dual_fisheye_pixels_to_vehicle_rays(np.asarray([pixel], dtype=float), 1280, 720,
                                                geometry, lens="front", front_lens="left")
    return float(-geometry["camera_height"]*ray[0, 2]/ray[0, 1])


def main():
    target = HERE/"verification.json"
    if target.exists():
        raise ValueError("no verification overwrite")
    for directory in ("results_r01", "wide_search_r01", "sensitivity_r01"):
        p = HERE/directory
        provenance = json.loads((p/"provenance.json").read_text())
        for name, digest in provenance["source_sha256"].items():
            assert sha256(Path(name)) == digest, name
        for name, digest in provenance["output_sha256"].items():
            assert sha256(p/name) == digest, name
    provenance = json.loads((HERE/"results_r01/provenance.json").read_text())
    geometry = provenance["geometry"]
    rows = read_csv(HERE/"results_r01/distance_decomposition.csv")
    assert len(rows) == 8
    assert len({(r["dataset"], r["point_id"], r["basis"]) for r in rows}) == 8
    for row in rows:
        f, m, b = [direct_z([float(row[k+"_pixel_x"]), float(row[k+"_pixel_y"])], geometry)
                   for k in ("floor", "manual", "bbox")]
        reference = float(row["reference_z_m"])
        for column, expected in (("floor_z_m", f), ("manual_base_z_m", m), ("bbox_z_m", b),
                                 ("floor_minus_reference_m", f-reference), ("manual_minus_floor_m", m-f),
                                 ("bbox_minus_manual_m", b-m), ("total_error_m", b-reference),
                                 ("term_sum_m", b-reference)):
            assert abs(float(row[column])-expected) < 1e-12, column
        assert row["floor_contact_verified"] == row["usable_for_ffb"] == "False"
    metadata = read_csv(HERE/"results_r01/metadata_comparison.csv")
    keys = list(CAMERA_KEYS)+["requested_width", "requested_height", "requested_fps", "device"]
    assert len(metadata) == 8
    assert len({tuple(r[k] for k in keys) for r in metadata}) == 1
    initial = read_csv(HERE/"results_r01/local_feature_matches.csv")
    wide = read_csv(HERE/"wide_search_r01/local_feature_matches.csv")
    assert len(initial) == len(wide) == 135
    for old, new in zip(initial, wide):
        assert all(old[k] == new[k] for k in ("reference_case", "current_case", "region", "reference_file", "current_file"))
        assert old["search_margin_px"] == "20" and new["search_margin_px"] == "40"
        if old["reliable_for_local_feature_comparison"] == "True":
            assert new["reliable_for_local_feature_comparison"] == "True"
            assert all(old[k] == new[k] for k in ("delta_x_current_minus_reference_px", "delta_y_current_minus_reference_px"))
    sensitivity = read_csv(HERE/"sensitivity_r01/uniform_pixel_shift.csv")
    assert len(sensitivity) == 24
    for row in sensitivity:
        z = direct_z([float(row["original_bbox_x"]), float(row["original_bbox_y"])
                      +float(row["hypothetical_bbox_y_shift_px"])], geometry)
        assert abs(z-float(row["hypothetical_z_m"])) < 1e-12
        assert row["original_pixel_changed"] == row["usable_for_ffb"] == row["used_in_production"] == "False"
    # Check previous frozen runtime/source/image snapshots as well, without
    # rewriting any prior verification artifact.
    previous = HERE.parent/"floor_cone_same_pose_analysis_r01/analysis_r01/summary.json"
    for path, digest in json.loads(previous.read_text())["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    report = dict(status="PASS_BOOKKEEPING_EQUATIONS_AND_FROZEN_INPUTS_NOT_CALIBRATION_APPROVAL",
                  decompositions=8, metadata_sessions=8, matched_metadata_settings=True,
                  local_feature_checks=270, sensitivity_rows=24,
                  old_accepted_local_offsets_preserved_under_wider_search=True,
                  original_camera_images_and_runtime_configs_unchanged=True,
                  physical_output=False, parameters_fitted=False,
                  source_sha256={str(p): sha256(p) for p in (Path(__file__), HERE/"test_bias_decomposition.py")})
    target.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
