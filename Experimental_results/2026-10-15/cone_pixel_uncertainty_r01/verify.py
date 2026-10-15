"""Independent vector-ray re-evaluation; never approval of calibration/FFB."""
import json
from pathlib import Path

import numpy as np

from analyze import HERE, ROOT, read_csv, sha256
from ground_contact import dual_fisheye_pixels_to_vehicle_rays


def main():
    target = HERE/"verification.json"
    if target.exists():
        raise ValueError("no verification overwrite")
    directory = HERE/"results_r01"
    provenance = json.loads((directory/"provenance.json").read_text())
    for path, digest in provenance["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    for name, digest in provenance["output_sha256"].items():
        assert sha256(directory/name) == digest, name
    bands = read_csv(directory/"pixel_band_sensitivity.csv")
    residuals = read_csv(directory/"fixed_model_residuals.csv")
    summaries = read_csv(directory/"fixed_model_summary.csv")
    overlaps = read_csv(directory/"point_overlap.csv")
    assert len(residuals) == 84 and len(bands) == 504 and len(overlaps) == 4
    for row in bands:
        b = int(row["assumed_pixel_half_width_px"])
        points = np.asarray([[float(row["pixel_x"])+dx, float(row["pixel_y"])+dy]
                             for dx in range(-b, b+1) for dy in range(-b, b+1)])
        p = provenance["models"][row["model"]]
        _, rays = dual_fisheye_pixels_to_vehicle_rays(points, 1280, 720, p)
        down = rays[rays[:, 1] < -.03]
        scale = -p["camera_height"]/down[:, 1]
        ground = down[:, [0, 2]]*scale[:, None]
        ranges = np.linalg.norm(ground, axis=1)
        valid = ground[(ground[:, 1] > 0) & (ranges >= .2) & (ranges <= 4)]
        assert (2*b+1)**2 == int(row["attempted_samples"])
        assert len(valid) == int(row["valid_samples"])
        assert len(valid)+int(row["invalid_samples"]) == len(points)
        if len(valid):
            for index, axis in enumerate(("x", "z")):
                assert abs(valid[:, index].min()-float(row[f"sampled_{axis}_min_m"])) < 1e-12
                assert abs(valid[:, index].max()-float(row[f"sampled_{axis}_max_m"])) < 1e-12
        assert row["floor_contact_verified"] == row["usable_for_ffb"] == "False"
    for row in residuals:
        required = max(abs(float(row["expected_minus_candidate_x_px"])),
                       abs(float(row["expected_minus_candidate_y_px"])))
        assert abs(required-float(row["required_joint_xy_half_width_px"])) < 1e-12
        assert row["floor_contact_verified"] == row["usable_for_ffb"] == "False"
    for row in summaries:
        group = [r for r in residuals if r["model"] == row["model"] and r["group"] == row["group"]]
        assert len(group) == int(row["points"])
        maximum = max(float(r["required_joint_xy_half_width_px"]) for r in group)
        assert abs(maximum-float(row["required_joint_xy_half_width_max_px"])) < 1e-12
        for b in (1, 2, 3, 4, 6, 8):
            assert sum(float(r["required_joint_xy_half_width_px"]) <= b for r in group) == int(row[f"compatible_points_at_assumed_{b}px"])
    for row in overlaps:
        dx, dy = float(row["dx_new_minus_old_px"]), float(row["dy_new_minus_old_px"])
        b = max(abs(dx), abs(dy))/2
        assert float(row["minimum_equal_half_width_for_overlap_px"]) == b
        for width in (1, 2, 3, 4, 6, 8):
            # Intersection of two centred closed squares exists iff each
            # coordinate's separation is no greater than the sum of widths.
            intersects = abs(dx) <= 2*width and abs(dy) <= 2*width
            assert row[f"overlap_at_assumed_half_width_{width}px"] == str(intersects)
    previous = HERE.parent/"floor_cone_same_pose_analysis_r01/analysis_r01/summary.json"
    for path, digest in json.loads(previous.read_text())["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    report = dict(status="PASS_FROZEN_SOURCE_AND_SENSITIVITY_EQUATIONS_NOT_METRIC_ACCURACY_APPROVAL",
                  fixed_models=6, fixed_point_candidates=14, model_point_residuals=84,
                  band_rows_recomputed=504, pair_overlap_checks=4,
                  point_candidates_and_frozen_models_unchanged=True,
                  original_images_and_runtime_configs_unchanged=True,
                  parameters_fitted=False, model_selected=False, physical_output=False,
                  source_sha256={str(p): sha256(p) for p in (Path(__file__), HERE/"test_pixel_uncertainty.py")})
    target.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
