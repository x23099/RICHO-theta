"""Frozen-data bias decomposition, not camera pose fitting or calibration."""
from collections import defaultdict
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(HERE.parent/"cone_geometry_candidates_r01"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import CAMERA_KEYS
from geometry_models import project_floor_to_pixels, project_pixels_to_floor
from view_registration import REGIONS, match_region


def decompose(geometry, reference_z, floor, manual, bbox, half_width=2):
    """Exact algebraic partition. Inputs stay at their frozen original pixels."""
    pixels = np.asarray([floor, manual, bbox], dtype=float)
    z = project_pixels_to_floor(pixels, geometry)[:, 1]
    terms = (z[0]-reference_z, z[1]-z[0], z[2]-z[1])
    probes = []
    for pixel in pixels:
        samples = [pixel+[dx, dy] for dx in (-half_width, half_width)
                   for dy in (-half_width, half_width)]
        values = project_pixels_to_floor(samples, geometry)[:, 1]
        probes.append((float(values.min()), float(values.max())))
    return dict(floor_z_m=float(z[0]), manual_base_z_m=float(z[1]), bbox_z_m=float(z[2]),
                floor_minus_reference_m=float(terms[0]), manual_minus_floor_m=float(terms[1]),
                bbox_minus_manual_m=float(terms[2]), total_error_m=float(z[2]-reference_z),
                term_sum_m=float(sum(terms)),
                floor_error_hypothetical_min_m=probes[0][0]-reference_z,
                floor_error_hypothetical_max_m=probes[0][1]-reference_z,
                manual_minus_floor_hypothetical_min_m=probes[1][0]-probes[0][1],
                manual_minus_floor_hypothetical_max_m=probes[1][1]-probes[0][0],
                bbox_minus_manual_hypothetical_min_m=probes[2][0]-probes[1][1],
                bbox_minus_manual_hypothetical_max_m=probes[2][1]-probes[1][0])


def main():
    output = HERE/"results_r01"
    if output.exists():
        raise ValueError("no frozen result overwrite")
    floor = HERE.parent/"cone_floor_reference_real_r01"
    cone = HERE.parent/"cone_static_distance_r01"
    same = HERE.parent/"floor_cone_same_pose_analysis_r01"
    paths = [Path(__file__), HERE/"method.md", floor/"point_candidates.csv",
             cone/"manual_contact_candidates.csv", cone/"analysis_r01/positions.csv",
             same/"contact_candidates.csv", same/"analysis_r01/summary.json",
             same/"analysis_r01/observations.csv", same/"scope.json",
             floor/"intake_summary.json", cone/"intake_summary.json", same/"intake_summary.json",
             HERE.parent/"cone_geometry_candidates_r01/geometry_models.py",
             HERE.parent/"cone_geometry_candidates_r01/view_registration.py", ROOT/"src/ground_contact.py"]
    geometry = json.loads((same/"analysis_r01/summary.json").read_text())["models"]["measured59"]
    old_floor = {r["point_id"]: r for r in read_csv(floor/"point_candidates.csv")}
    old_manual = {r["condition"]: r for r in read_csv(cone/"manual_contact_candidates.csv")}
    old_positions = read_csv(cone/"analysis_r01/positions.csv")
    new_anchors = {(r["kind"], r["point_id"]): r for r in read_csv(same/"contact_candidates.csv")}
    new_positions = [r for r in read_csv(same/"analysis_r01/observations.csv") if r["model"] == "measured59"]
    decomposition = []
    comparison = []
    for point, condition, phase, ref_z in (("C130", "center_130", "cone_130", 1.3),
                                           ("C200", "center_200", "cone_200", 2.0)):
        endpoints = {}
        for dataset in ("previous_separate_sessions", "same_video"):
            f = old_floor[point] if dataset.startswith("previous") else new_anchors["floor", point]
            m = old_manual[condition] if dataset.startswith("previous") else new_anchors["cone", point]
            if dataset.startswith("previous"):
                rows = [r for r in old_positions if r["condition"] == condition and r["measurement_used"] == "True"]
                same_frame = next(r for r in rows if r["frame"] == m["frame"])
                bx, by = "bottom_pixel_x", "bottom_pixel_y"
            else:
                rows = [r for r in new_positions if r["phase"] == phase and r["target_hypothesis_used"] == "True"]
                same_frame = next(r for r in rows if r["frame"] == m["frame"])
                bx, by = "pixel_x", "pixel_y"
            fxy = [float(f[k]) for k in ("pixel_x", "pixel_y")]
            mxy = [float(m[k]) for k in ("pixel_x", "pixel_y")]
            # Median of per-frame Z is reported separately from projection of
            # median xy: nonlinear projection means they need not be identical.
            bbox_cases = (("manual_candidate_frame", [float(same_frame[k]) for k in (bx, by)]),
                          ("static_pixel_medians", [float(np.median([float(r[k]) for r in rows])) for k in (bx, by)]))
            for basis, bxy in bbox_cases:
                result = decompose(geometry, ref_z, fxy, mxy, bxy)
                expected = project_floor_to_pixels([[0, ref_z]], geometry)[0]
                decomposition.append(dict(dataset=dataset, point_id=point, reference_z_m=ref_z, basis=basis,
                    floor_frame=f["frame"], manual_frame=m["frame"], static_projection_count=len(rows),
                    floor_pixel_x=fxy[0], floor_pixel_y=fxy[1], manual_pixel_x=mxy[0], manual_pixel_y=mxy[1],
                    bbox_pixel_x=bxy[0], bbox_pixel_y=bxy[1],
                    bbox_minus_manual_y_px=bxy[1]-mxy[1],
                    expected_pixel_x_explanation_only=float(expected[0]), expected_pixel_y_explanation_only=float(expected[1]),
                    median_of_projected_frame_z_m=float(np.median([
                        project_pixels_to_floor([[float(r[bx]), float(r[by])]], geometry)[0, 1] for r in rows])),
                    floor_contact_verified=False, usable_for_ffb=False, **result))
                if basis == "manual_candidate_frame":
                    endpoints[dataset] = dict(floor=fxy, manual=mxy, bbox=bxy)
        for kind in ("floor", "manual", "bbox"):
            old = endpoints["previous_separate_sessions"][kind]
            new = endpoints["same_video"][kind]
            comparison.append(dict(point_id=point, kind=kind, old_pixel_x=old[0], old_pixel_y=old[1],
                                   new_pixel_x=new[0], new_pixel_y=new[1], new_minus_old_x_px=new[0]-old[0],
                                   new_minus_old_y_px=new[1]-old[1],
                                   hypothetical_independent_2px_difference_min_y_px=new[1]-old[1]-4,
                                   hypothetical_independent_2px_difference_max_y_px=new[1]-old[1]+4,
                                   uncertainty_is_assumed_not_measured=True))
    samples = [
        ("old_floor", floor/"raw_samples/floor_reference_f000187.png"),
        ("old_cone080", cone/"raw_samples/center_080_f000241.png"),
        ("old_cone130", cone/"raw_samples/center_130_f000217.png"),
        ("old_cone200", cone/"raw_samples/center_200_f000211.png"),
        ("old_left130", cone/"raw_samples/left_130_f000210.png"),
        ("old_right130", cone/"raw_samples/right_130_f000211.png"),
        ("new_floor", same/"raw_samples/same_pose_f000141.png"),
        ("new_cone130", same/"raw_samples/same_pose_f000563.png"),
        ("new_cone200", same/"raw_samples/same_pose_f001265.png")]
    refs = {"old_floor", "old_cone130", "new_floor"}
    paths.extend(p for _, p in samples)
    before = {str(p): sha256(p) for p in paths}
    images = {name: cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for name, p in samples}
    matches = []
    for ref, ref_file in samples:
        if ref not in refs:
            continue
        for name, image_file in samples:
            for region in REGIONS:
                matches.append(dict(reference_case=ref, current_case=name, reference_file=str(ref_file),
                                    current_file=str(image_file), **match_region(images[ref], images[name], region)))
    metadata = []
    historical_intake = json.loads((cone/"intake_summary.json").read_text())
    for item in historical_intake["inputs"]:
        p = Path(item["path"])/"metadata.json"
        paths.append(p)
        metadata.append((item["condition"], p, json.loads(p.read_text())))
    for label, directory in (("old_floor", floor), ("same_video", same)):
        intake = json.loads((directory/"intake_summary.json").read_text())
        p = Path(intake["session"])/"metadata.json"
        paths.append(p)
        metadata.append((label, p, json.loads(p.read_text())))
    settings = []
    for label, path, data in metadata:
        settings.append(dict(case=label, metadata=str(path),
                             **{k: data["parameters"][k] for k in CAMERA_KEYS},
                             requested_width=data["requested_camera_width"], requested_height=data["requested_camera_height"],
                             requested_fps=data["requested_camera_fps"],
                             device=str(data.get("device")), created_at=data.get("created_at")))
    output.mkdir(parents=True)
    write_csv(output/"distance_decomposition.csv", decomposition)
    write_csv(output/"pixel_comparison.csv", comparison)
    write_csv(output/"local_feature_matches.csv", matches)
    write_csv(output/"metadata_comparison.csv", settings)
    plot(decomposition, matches, output)
    assert all(sha256(Path(p)) == digest for p, digest in before.items())
    source_hashes = {str(p): sha256(p) for p in paths}
    counts = defaultdict(dict)
    for ref in refs:
        for name, _ in samples:
            group = [r for r in matches if r["reference_case"] == ref and r["current_case"] == name]
            counts[ref][name] = sum(r["reliable_for_local_feature_comparison"] for r in group)
    report = dict(status="COMPLETED_BIAS_DECOMPOSITION_NOT_UNIQUE_CAUSAL_DIAGNOSIS_OR_CALIBRATION_APPROVAL",
                  geometry=geometry, decomposition_rows=len(decomposition), feature_comparisons=len(matches),
                  metadata_rows=len(settings), local_match_counts=counts,
                  source_sha256=source_hashes, new_fit_points=0, threshold_search=False,
                  source_images_changed=False, new_camera_images_saved=False,
                  correction_applied=False, physical_output=False, production_settings_changed=False,
                  output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(dict(local_match_counts=counts), indent=2))


def plot(decomposition, matches, output):
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    chosen = [r for r in decomposition if r["basis"] == "manual_candidate_frame"]
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    xs = np.arange(len(chosen))
    for key, name, color in (("floor_minus_reference_m", "Floor hypothesis - nominal reference", "tab:blue"),
                              ("manual_minus_floor_m", "Manual base - floor (cross-session in OLD)", "tab:orange"),
                              ("bbox_minus_manual_m", "YOLO bottom - manual base", "tab:green")):
        ax.bar(xs, [100*r[key] for r in chosen], width=.22,
               label=name, color=color)
        xs = xs+.24
    ax.scatter(np.arange(len(chosen))+.24, [100*r["total_error_m"] for r in chosen],
               c="black", marker="D", label="Total signed Z residual", zorder=3)
    ax.set(xticks=np.arange(len(chosen))+.24,
           xticklabels=[("OLD separate" if r["dataset"].startswith("previous") else "NEW same video")+" "+r["point_id"] for r in chosen],
           ylabel="Signed Z difference [cm]", title="Fixed height 0.59 m; algebraic decomposition, NOT causal attribution")
    ax.axhline(0, color="black", linewidth=.8)
    ax.grid(axis="y", alpha=.3)
    ax.legend(fontsize=8)
    fig.savefig(output/"distance_decomposition.png", dpi=150)
    plt.close(fig)
    chosen = [r for r in matches if r["reference_case"] == "new_floor"]
    names = list(dict.fromkeys(r["current_case"] for r in chosen))
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for name, *_ in REGIONS:
        group = [next(r for r in chosen if r["current_case"] == case and r["region"] == name) for case in names]
        for axis, coord in zip(axes, ("x", "y")):
            axis.plot(range(len(names)), [r[f"delta_{coord}_current_minus_reference_px"]
                                         if r["reliable_for_local_feature_comparison"] else np.nan for r in group],
                      "o", label=name)
            axis.set_ylabel(coord.upper()+" local offset [px]")
            axis.grid(alpha=.3)
            axis.axhline(0, color="black", linewidth=.8)
    axes[0].set_title("Current image minus NEW floor reference; accepted local matches only, NOT global alignment")
    axes[0].legend(fontsize=8)
    axes[1].set(xticks=range(len(names)), xticklabels=names)
    fig.savefig(output/"local_offsets_vs_new_floor.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
