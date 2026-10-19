"""Saved-support equivalence and one-point calibration identifiability; no fit."""
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(HERE.parent/"cone_support_projection_r01"))
from cone_dataset import read_csv, sha256, write_csv
from fisheye_floor_geometry import intersect_floor, legacy_front_diagnostic_geometry
from metric_support import bounds, project_columns

PREVIOUS = HERE.parent/"paper_cone_2m_validation_r01/analysis_r01"
VARIABLES = ("front_cx_offset", "front_cy_offset", "radius_scale", "pitch_deg", "roll_deg", "yaw_deg")
SCALES = np.array([5., 5., .01, 1., 1., 1.])


def floor_xz(pixel, parameters):
    camera, transform = legacy_front_diagnostic_geometry(parameters)
    row = intersect_floor([pixel], camera, transform, image_size=(1280, 720))[0]
    if row["point_target_m"] is None:
        raise ValueError("no floor point; cannot substitute missing calibration information")
    point = row["point_target_m"]
    return np.array([-point[1], point[0]])


def sensitivity(pixel, parameters):
    derivatives = []
    for name, scale in zip(VARIABLES, SCALES):
        step = 1e-4*scale
        plus, minus = dict(parameters), dict(parameters)
        plus[name] += step
        minus[name] -= step
        derivatives.append((floor_xz(pixel, plus)-floor_xz(pixel, minus))/(2e-4))
    jacobian = np.column_stack(derivatives)
    _, singular, vh = np.linalg.svd(jacobian, full_matrices=True)
    rank = int(np.sum(singular > 1e-8))
    nullspace = vh[rank:]
    return dict(jacobian_scaled=jacobian.tolist(), singular_values=singular.tolist(), rank=rank,
                variables=list(VARIABLES), scales=SCALES.tolist(), nullity=len(VARIABLES)-rank,
                normalized_nullspace=nullspace.tolist(),
                nullspace_residual_abs_max=float(np.max(np.abs(jacobian @ nullspace.T))),
                finite_difference_normalized_step=1e-4, rank_absolute_tolerance=1e-8,
                calibration_fitted=False, interpretation="local first-order ambiguity, not physical noise covariance")


def main():
    output = HERE/"results_r01"
    if output.exists():
        raise ValueError("no overwrite")
    previous_summary = json.loads((PREVIOUS/"summary.json").read_text())
    sources = dict(previous_summary["source_sha256"])
    paths = [Path(__file__), HERE/"method.md", PREVIOUS/"summary.json", PREVIOUS/"support_quality.csv",
             PREVIOUS/"cone_support_extent_projection.csv", ROOT/"src/fisheye_floor_geometry.py",
             ROOT/"tests/test_fisheye_floor_geometry.py",
             ROOT/"Experimental_results/2026-10-15/paper_reference7_r01/analysis_r01/reference_points_primary170.csv"]
    sources.update({str(p): sha256(p) for p in paths})
    models = previous_summary["models"]
    supports = read_csv(PREVIOUS/"support_quality.csv")
    old_extent = {(int(r["frame"]), r["model"]): r for r in read_csv(PREVIOUS/"cone_support_extent_projection.csv")}
    rows, checked_keys, maximum, compared, reason_disagreements = [], set(), 0., 0, 0
    transforms = {}
    for name, p in models.items():
        camera, transform = legacy_front_diagnostic_geometry(p)
        transforms[name] = dict(target_frame="camera_ground_reference_diagnostic", source_frame="front_fisheye_optical_diagnostic",
            data_transform="p_target = R_target_from_optical * p_optical + t_target_from_optical",
            target_from_optical=transform.tolist(), camera=vars(camera), measured_extrinsics=False,
            base_link_transform=False, physical_output_permitted=False)
        for support in supports:
            common = dict(frame=int(support["frame"]), time_sec=float(support["time_sec"]), phase=support["phase"], model=name)
            points = json.loads(support["observed_support"])
            if points is None:
                rows.append(dict(**common, input_columns=0, legacy_complete=False, new_complete=False,
                                 max_coordinate_difference_m=None, input_withheld=True, usable_for_ffb=False))
                continue
            legacy = project_columns(points, p)
            new = intersect_floor(points, camera, transform, image_size=(1280, 720))
            converted = []
            maximum_row = 0.
            for pixel, old, row in zip(points, legacy, new):
                point = row["point_target_m"]
                if point is None:
                    reason = "not_downward_floor_ray" if row["reason"] == "not_downward_or_grazing_floor_ray" else "outside_front_lens_or_optical_centre"
                    x, z, radial = None, None, None
                else:
                    x, z = -point[1], point[0]
                    radial = float(np.hypot(x, z))
                    reason = ("invalid_or_nonforward_floor_intersection" if z <= 0 else
                              "outside_radial_diagnostic_range" if not .2 <= radial <= 4. else "valid")
                    if old["x_m"] is not None:
                        maximum_row = max(maximum_row, abs(x-old["x_m"]), abs(z-old["z_m"]))
                        compared += 1
                reason_disagreements += old["reason"] != reason
                converted.append(dict(pixel_x=pixel[0], pixel_y=pixel[1], x_m=x, z_m=z, radial_m=radial, reason=reason))
            result = bounds(converted)
            key = (common["frame"], name)
            saved = old_extent[key]
            complete = saved["projection_complete"] == "True"
            assert result["projection_complete"] == complete
            if complete:
                for field in ("x_min_m", "x_max_m", "z_min_m", "z_max_m", "x_median_m", "z_median_m"):
                    assert abs(result[field]-float(saved[field])) < 1e-9
            checked_keys.add(key)
            maximum = max(maximum, maximum_row)
            rows.append(dict(**common, input_columns=len(points), legacy_complete=complete,
                             new_complete=result["projection_complete"], max_coordinate_difference_m=maximum_row,
                             input_withheld=False, usable_for_ffb=False))
    assert checked_keys == set(old_extent)
    assert maximum < 1e-9 and reason_disagreements == 0
    pixel = previous_summary["paper_reference_native_xy"]
    diagnostic = sensitivity(pixel, models["height_only59"])
    old_points = read_csv(paths[-1])
    prior_2m = next(r for r in old_points if r["point_id"] == "C200")
    view_difference = dict(previous_paper2m_pixel=[float(prior_2m["pixel_x"]), float(prior_2m["pixel_y"])],
        current_paper2m_pixel=pixel, native_pixel_delta_current_minus_previous=[pixel[0]-float(prior_2m["pixel_x"]), pixel[1]-float(prior_2m["pixel_y"])],
        calibrated_translation=False, physical_cause_identified=False, same_session=False)
    assert diagnostic["rank"] == 2 and diagnostic["nullity"] == 4
    assert all(sha256(Path(p)) == digest for p, digest in sources.items())
    output.mkdir()
    write_csv(output/"all_frame_comparison.csv", rows)
    (output/"diagnostic_transforms.json").write_text(json.dumps(transforms, indent=2)+"\n")
    plot(diagnostic, output)
    summary = dict(status="PASS_TF_COMPATIBLE_MATH_NOT_CALIBRATION_APPROVAL", frames=len(supports),
        frame_model_rows=len(rows), observed_frame_model_rows=len(checked_keys), compared_columns=compared,
        max_coordinate_difference_m=maximum, reason_disagreements=reason_disagreements,
        independent_current_reference_points=1, sensitivity=diagnostic, previous_reference_comparison=view_difference,
        prior_seven_points_pooled=False, calibration_fitted=False, physical_output=False,
        live_tf_published=False, production_calls_changed=False, sources_unchanged=True, source_sha256=sources,
        output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({k:summary[k] for k in ("status", "frames", "frame_model_rows", "compared_columns",
          "max_coordinate_difference_m", "sensitivity", "previous_reference_comparison")}, indent=2))


def plot(diagnostic, output):
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axis = plt.subplots(figsize=(8, 3.5), layout="constrained")
    j = np.array(diagnostic["jacobian_scaled"])
    x = np.arange(len(VARIABLES))
    axis.bar(x-.18, j[0], width=.36, label="X-right response")
    axis.bar(x+.18, j[1], width=.36, label="Z-forward response")
    axis.set_xticks(x, ("centre X\n5 px", "centre Y\n5 px", "radius scale\n0.01", "pitch\n1 degree", "roll\n1 degree", "yaw\n1 degree"))
    axis.set_ylabel("Local floor response [m / normalized step]")
    axis.set_title("One 2D floor reference: Jacobian rank 2, 6 unknowns, nullity 4")
    axis.legend()
    axis.grid(axis="y", alpha=.25)
    fig.savefig(output/"one_point_identifiability.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
