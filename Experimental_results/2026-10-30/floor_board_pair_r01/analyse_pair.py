#!/usr/bin/env python3
"""Offline perimeter-pose consistency and deterministic pixel sensitivity.

No image writes, calibration refit, height fit, live integration, or approval.
The perturbations are numerical controls, NOT error bars or confidence bounds.
"""
import argparse
import csv
import itertools
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from floor_reference_pose import planar_floor_pose_candidates


def canonical(candidate):
    signed = candidate["camera_height_above_floor_m"]
    if not np.isfinite(signed) or signed == 0:
        raise ValueError("nonzero finite plane offset required")
    return (np.asarray(candidate["up_optical"]) * np.sign(signed), abs(signed))


def angle(a, b):
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b), -1, 1))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = HERE / "white_paper_quad_measured_r01.json"
    data = json.loads(source.read_text())
    config, camera, _, _ = load_config()
    primary = {row["frame"]: row["quads"][0] for row in data["rows"]
               if row["threshold"] == data["primary_threshold"] and len(row["quads"]) == 1}
    if set(primary) != {1259, 1655}:
        raise ValueError("exactly two unambiguous primary quads required")
    long_m, short_m = np.asarray(data["paper_size_mm"]) / 1000
    hypotheses = []
    for name in ("image_far_edge_long", "image_far_edge_short"):
        for branch in (0, 1):
            pair = [primary[f]["poses"][name]["candidates"][branch] for f in (1259, 1655)]
            (n1, h1), (n2, h2) = map(canonical, pair)
            hypotheses.append(dict(orientation_hypothesis=name, solution_index=branch,
                plane_normal_difference_deg=angle(n1, n2), height_difference_mm=1000*abs(h1-h2),
                frames=[dict(frame=f, height_to_printed_plane_m=h, normal_optical=n.tolist(),
                             fit_native_rmse_px=c["fit_native_rmse_px"],
                             required_floor_to_printed_plane_mm_if_camera_height_590mm=590-1000*h)
                        for f, c, n, h in zip((1259, 1655), pair, (n1, n2), (h1, h2))]))
    # These controls describe the lowest-reprojection-error long-edge branch;
    # this is an analysis branch, not an automatically approved transform.
    world = [[0, 0, 0], [long_m, 0, 0], [long_m, short_m, 0], [0, short_m, 0]]
    controls, summaries = [], []
    for frame, quad in primary.items():
        native = np.asarray(quad["quad_xy"], float)
        base_n, base_h = canonical(quad["poses"]["image_far_edge_long"]["candidates"][0])
        for amplitude in (.5, 1.):
            # All 2^8 combinations, not a random sample or measured noise model.
            rows = []
            for signs in itertools.product((-1, 1), repeat=8):
                delta = amplitude * np.asarray(signs).reshape(4, 2)
                candidates = planar_floor_pose_candidates(native+delta, world, camera)["candidates"]
                if not candidates:
                    raise ValueError("perturbation lost all planar solutions")
                distances = [angle(base_n, canonical(c)[0]) for c in candidates]
                selected = int(np.argmin(distances))  # branch correspondence, not height matching
                candidate = candidates[selected]
                n, height = canonical(candidate)
                row = dict(frame=frame, amplitude_px=amplitude,
                    corner_signs="".join("+" if s > 0 else "-" for s in signs),
                    matched_solution_index=candidate["solution_index"],
                    height_to_printed_plane_m=height, normal_shift_deg=angle(base_n, n),
                    fit_native_rmse_px=candidate["fit_native_rmse_px"],
                    all_positive_depth=candidate["all_reference_points_positive_depth"],
                    all_projected=candidate["all_projected_in_calibrated_domain"])
                rows.append(row)
                controls.append(row)
            heights = [r["height_to_printed_plane_m"] for r in rows]
            summaries.append(dict(frame=frame, amplitude_px=amplitude, count=len(rows),
                baseline_height_m=base_h, min_height_m=min(heights), max_height_m=max(heights),
                camera_590mm_with_zero_thickness_within_sampled_range=min(heights) <= .59 <= max(heights),
                max_normal_shift_deg=max(r["normal_shift_deg"] for r in rows),
                all_positive_depth=all(r["all_positive_depth"] for r in rows),
                all_projected=all(r["all_projected"] for r in rows)))
    # Threshold variation retains detection failures and both metric hypotheses.
    threshold_controls = []
    for row in data["rows"]:
        out = dict(frame=row["frame"], threshold=row["threshold"], quad_count=len(row["quads"]))
        if len(row["quads"]) == 1:
            q = row["quads"][0]
            candidate = q["poses"]["image_far_edge_long"]["candidates"][0]
            n, h = canonical(candidate)
            out.update(quad_xy=q["quad_xy"], height_m=h, normal_optical=n.tolist(),
                       fit_native_rmse_px=candidate["fit_native_rmse_px"])
        threshold_controls.append(out)
    with (args.output_dir / "pixel_sensitivity.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(controls[0]))
        writer.writeheader()
        writer.writerows(controls)
    report = dict(status="FLOOR_ORIENTATION_CANDIDATE_METRIC_WITHHELD",
        paper_size_mm=data["paper_size_mm"], measured_camera_height_m=.59,
        printed_plane_thickness_m=None, primary_threshold=data["primary_threshold"],
        hypotheses=hypotheses, threshold_controls=threshold_controls,
        pixel_sensitivity=summaries,
        sensitivity_definition="all 256 independent corner-coordinate signs at each amplitude; nearest canonical normal branch; NOT confidence intervals or measured pixel errors",
        input_source_sha256={**data["source_sha256"], str(source): digest(source),
                             str(Path(__file__).resolve()): digest(Path(__file__).resolve()),
                             str(DEFAULT_CONFIG): digest(DEFAULT_CONFIG),
                             str(ROOT / config["camera_candidate"]): digest(ROOT / config["camera_candidate"]),
                             str(ROOT / config["floor_candidate"]): digest(ROOT / config["floor_candidate"]),
                             str(ROOT / "src/floor_reference_pose.py"): digest(ROOT / "src/floor_reference_pose.py"),
                             str(ROOT / "src/angular_fisheye_geometry.py"): digest(ROOT / "src/angular_fisheye_geometry.py")},
        physical_metric_verified=False, base_link_transform_verified=False,
        distance_accuracy_evaluated=False, live_integrated=False, usable_for_ffb=False)
    with (args.output_dir / "pair_summary.json").open("x") as f:
        json.dump(report, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "hypotheses", "pixel_sensitivity")}, indent=2))


if __name__ == "__main__":
    main()
