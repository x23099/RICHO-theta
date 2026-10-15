"""Fixed candidate pixels/models only; no fit, image editing, ROS or FFB."""
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(HERE.parent/"cone_geometry_candidates_r01"))
from cone_dataset import read_csv, sha256, write_csv
from diagnose_box_contact_calibration import project_pixel
from geometry_models import project_floor_to_pixels

BANDS = (1, 2, 3, 4, 6, 8)


def required_common_band(first, second):
    a, b = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if a.shape != (2,) or b.shape != (2,) or not np.isfinite([a, b]).all():
        raise ValueError("two finite 2D pixels required")
    return float(np.max(np.abs(a-b))/2)


def sampled_band(pixel, parameters, half_width):
    if type(half_width) is not int or half_width < 0:
        raise ValueError("nonnegative integer half width required")
    if len(pixel) != 2 or not all(math.isfinite(v) for v in pixel):
        raise ValueError("finite pixel required")
    if not (half_width <= pixel[0] < 1280-half_width and half_width <= pixel[1] < 720-half_width):
        raise ValueError("whole sampled band must stay inside native image")
    samples = [project_pixel((pixel[0]+dx, pixel[1]+dy), parameters)
               for dx in range(-half_width, half_width+1) for dy in range(-half_width, half_width+1)]
    valid = [value for value in samples if value is not None]
    return dict(attempted_samples=len(samples), valid_samples=len(valid),
                invalid_samples=len(samples)-len(valid),
                sampled_x_min_m=min(v[0] for v in valid) if valid else None,
                sampled_x_max_m=max(v[0] for v in valid) if valid else None,
                sampled_z_min_m=min(v[1] for v in valid) if valid else None,
                sampled_z_max_m=max(v[1] for v in valid) if valid else None)


def load_points(day):
    floor = day/"cone_floor_reference_real_r01"
    cone = day/"cone_static_distance_r01"
    same = day/"floor_cone_same_pose_analysis_r01"
    points = []
    for row in read_csv(floor/"point_candidates.csv"):
        group = "old_floor_check2" if row["point_id"] in ("H100", "H160") else "old_floor_fit5"
        points.append(dict(group=group, source="old_floor", point_id=row["point_id"], frame=row["frame"],
                           pixel_x=float(row["pixel_x"]), pixel_y=float(row["pixel_y"]),
                           reference_x_m=float(row["reference_x_m"]), reference_z_m=float(row["reference_z_m"])))
    for row in read_csv(same/"contact_candidates.csv"):
        points.append(dict(group="new_floor_check2" if row["kind"] == "floor" else "new_cone_illustration2",
                           source="new_"+row["kind"], point_id=row["point_id"], frame=row["frame"],
                           pixel_x=float(row["pixel_x"]), pixel_y=float(row["pixel_y"]),
                           reference_x_m=float(row["reference_x_m"]), reference_z_m=float(row["reference_z_m"])))
    for row in read_csv(cone/"manual_contact_candidates.csv"):
        if not row["condition"].startswith("center_"):
            continue
        point = {"center_080": "C080", "center_130": "C130", "center_200": "C200"}[row["condition"]]
        points.append(dict(group="old_cone_illustration3", source="old_cone", point_id=point, frame=row["frame"],
                           pixel_x=float(row["pixel_x"]), pixel_y=float(row["pixel_y"]),
                           reference_x_m=0., reference_z_m={"C080": .8, "C130": 1.3, "C200": 2.}[point]))
    assert len(points) == 14
    return points


def main():
    output = HERE/"results_r01"
    if output.exists():
        raise ValueError("no frozen result overwrite")
    day = HERE.parent
    parameters_file = day/"cone_geometry_candidates_r01/results_r01/candidate_parameters.json"
    model_records = json.loads(parameters_file.read_text())["models"]
    models = {name: row["parameters"] for name, row in model_records.items()}
    assert len(models) == 6
    points = load_points(day)
    paths = [Path(__file__), HERE/"method.md", parameters_file,
             day/"cone_floor_reference_real_r01/point_candidates.csv",
             day/"cone_static_distance_r01/manual_contact_candidates.csv",
             day/"floor_cone_same_pose_analysis_r01/contact_candidates.csv",
             day/"capture_path_review_r01/audit.json",
             day/"cone_geometry_candidates_r01/geometry_models.py",
             ROOT/"src/ground_contact.py", ROOT/"src/diagnose_box_contact_calibration.py"]
    paths.extend([day/"cone_floor_reference_real_r01/raw_samples/floor_reference_f000187.png",
                  day/"floor_cone_same_pose_analysis_r01/raw_samples/same_pose_f000141.png"])
    paths.extend(day/"cone_static_distance_r01"/r["file"] for r in
                 read_csv(day/"cone_static_distance_r01/manual_contact_candidates.csv")
                 if r["condition"].startswith("center_"))
    paths.extend(day/"floor_cone_same_pose_analysis_r01/raw_samples"/f"same_pose_f{frame:06d}.png" for frame in (563,1265))
    before = {str(p): sha256(p) for p in paths}
    comparison = []
    for kind in ("floor", "cone"):
        for point in ("C130", "C200"):
            old = next(r for r in points if r["source"] == "old_"+kind and r["point_id"] == point)
            new = next(r for r in points if r["source"] == "new_"+kind and r["point_id"] == point)
            width = required_common_band([old["pixel_x"], old["pixel_y"]], [new["pixel_x"], new["pixel_y"]])
            comparison.append(dict(kind=kind, point_id=point, dx_new_minus_old_px=new["pixel_x"]-old["pixel_x"],
                                   dy_new_minus_old_px=new["pixel_y"]-old["pixel_y"],
                                   minimum_equal_half_width_for_overlap_px=width,
                                   **{f"overlap_at_assumed_half_width_{b}px": b >= width for b in BANDS},
                                   source_pixels_changed=False, reading_error_measured=False,
                                   placement_error_measured=False))
    residuals, sensitivity = [], []
    for model, parameters in models.items():
        for point in points:
            pixel = (point["pixel_x"], point["pixel_y"])
            expected = project_floor_to_pixels([[point["reference_x_m"], point["reference_z_m"]]], parameters)[0]
            baseline = project_pixel(pixel, parameters)
            required = max(abs(expected[0]-pixel[0]), abs(expected[1]-pixel[1]))
            residuals.append(dict(model=model, **point, expected_pixel_x_explanation_only=float(expected[0]),
                                  expected_pixel_y_explanation_only=float(expected[1]),
                                  expected_minus_candidate_x_px=float(expected[0]-pixel[0]),
                                  expected_minus_candidate_y_px=float(expected[1]-pixel[1]),
                                  required_joint_xy_half_width_px=float(required),
                                  x_m=baseline[0] if baseline else None, z_m=baseline[1] if baseline else None,
                                  floor_contact_verified=False, usable_for_ffb=False))
            for b in BANDS:
                samples = sampled_band(pixel, parameters, b)
                sensitivity.append(dict(model=model, **point, assumed_pixel_half_width_px=b, **samples,
                    reference_xy_compatible_with_pixel_band=bool(required <= b),
                    reference_z_inside_sampled_z_envelope=bool(samples["valid_samples"] and
                        samples["sampled_z_min_m"] <= point["reference_z_m"] <= samples["sampled_z_max_m"]),
                    floor_contact_verified=False, usable_for_ffb=False))
    grouped = defaultdict(list)
    for row in residuals:
        grouped[row["model"], row["group"]].append(row)
    summaries = [dict(model=model, group=group, points=len(rows),
                      required_joint_xy_half_width_max_px=max(r["required_joint_xy_half_width_px"] for r in rows),
                      **{f"compatible_points_at_assumed_{b}px": sum(r["required_joint_xy_half_width_px"] <= b for r in rows) for b in BANDS})
                 for (model, group), rows in grouped.items()]
    output.mkdir(parents=True)
    write_csv(output/"point_overlap.csv", comparison)
    write_csv(output/"fixed_model_residuals.csv", residuals)
    write_csv(output/"pixel_band_sensitivity.csv", sensitivity)
    write_csv(output/"fixed_model_summary.csv", summaries)
    plot(summaries, sensitivity, output)
    assert all(sha256(Path(p)) == digest for p, digest in before.items())
    provenance = dict(status="COMPLETED_PIXEL_ASSUMPTION_AND_FIXED_MODEL_DIAGNOSIS_NOT_CALIBRATION_APPROVAL",
                      source_sha256=before, models=models, point_count=len(points), models_count=len(models),
                      band_half_widths_px=BANDS, overlap_pairs=len(comparison), residual_rows=len(residuals),
                      sensitivity_rows=len(sensitivity), parameters_fitted=False, candidate_pixels_changed=False,
                      model_selected=False, physical_output=False, production_settings_changed=False,
                      output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"provenance.json").write_text(json.dumps(provenance, indent=2)+"\n")
    print(json.dumps(dict(overlaps=comparison, residual_rows=len(residuals), sensitivity_rows=len(sensitivity)), indent=2))


def plot(summary, sensitivity, output):
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    models = list(dict.fromkeys(r["model"] for r in summary))
    fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
    for i, group in enumerate(("old_floor_fit5", "old_floor_check2", "new_floor_check2")):
        values = [next(r["required_joint_xy_half_width_max_px"] for r in summary if r["model"] == m and r["group"] == group) for m in models]
        ax.bar(np.arange(6)+i*.25, values, width=.24, label=group)
    ax.set(xticks=np.arange(6)+.25, xticklabels=models, ylabel="Required joint X/Y pixel half-width [px]",
           title="Frozen models: candidate-pixel compatibility, NOT measured annotation accuracy")
    ax.axhline(2, color="black", linestyle="--", linewidth=1, label="Previously assumed +/-2 px")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=.3)
    fig.savefig(output/"fixed_model_pixel_requirements.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True, layout="constrained")
    for axis, kind in zip(axes, ("floor", "cone")):
        for source in ("old_"+kind, "new_"+kind):
            rows = [r for r in sensitivity if r["source"] == source and r["point_id"] == "C200" and r["model"] == "measured59"]
            axis.fill_between([r["assumed_pixel_half_width_px"] for r in rows],
                              [r["sampled_z_min_m"] for r in rows], [r["sampled_z_max_m"] for r in rows],
                              alpha=.25, label=source+" sampled envelope")
        axis.axhline(2, color="black", linestyle="--", label="Nominal Z=2m (not a fitted target)")
        axis.set(xlabel="Assumed pixel half-width [px] (not measured)", title=kind+" candidate, fixed height 0.59m")
        axis.grid(alpha=.3)
        axis.legend(fontsize=8)
    axes[0].set_ylabel("Sampled Z [m]; not a confidence interval")
    fig.savefig(output/"c200_pixel_band_sensitivity.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
