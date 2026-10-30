#!/usr/bin/env python3
"""床の5校正点だけでPnP、未使用2点と別録画1点は評価だけに使う。"""
import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest, load_config
from angular_fisheye_geometry import floor_from_rays, project, unproject
from floor_reference_pose import planar_floor_pose_candidates

FIT_IDS = ("C080", "C130", "C200", "L130", "R130")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    source = ROOT / "Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_reference_results.csv"
    with source.open(newline="") as f:
        points = [r for r in csv.DictReader(f) if r["model"] == "angular_paper5_rotation"]
    by_id = {r["point_id"]: r for r in points}
    fit = [by_id[name] for name in FIT_IDS]
    pixel = lambda r: [float(r["pixel_x"]), float(r["pixel_y"])]
    world = lambda r: [float(r["reference_z_m"]), -float(r["reference_x_m"]), 0.]
    _, camera, _, _ = load_config()
    result = planar_floor_pose_candidates([pixel(r) for r in fit], [world(r) for r in fit], camera)
    rows = []
    for candidate in result["candidates"]:
        transform = np.asarray(candidate["transform_floor_from_optical"])
        uv, valid = project((np.asarray([world(r) for r in points])-transform[:3, 3]) @ transform[:3, :3], camera)
        rays, ok = unproject([pixel(r) for r in points], camera, image_size=(1280, 720))
        intersections, ok = floor_from_rays(rays, ok, transform)
        for index, point in enumerate(points):
            xy = intersections[index]
            row = dict(solution_index=candidate["solution_index"], point_id=point["point_id"],
                       role=point["role"], source_recording=point["session"],
                       reprojected_x_px=float(uv[index, 0]) if valid[index] else None,
                       reprojected_y_px=float(uv[index, 1]) if valid[index] else None,
                       reprojection_error_px=float(np.linalg.norm(uv[index]-pixel(point))) if valid[index] else None,
                       forward_m=float(xy[0]) if ok[index] else None,
                       right_m=float(-xy[1]) if ok[index] else None,
                       forward_error_m=float(xy[0]-world(point)[0]) if ok[index] else None,
                       planar_error_m=float(np.linalg.norm(xy-np.asarray(world(point)))) if ok[index] else None,
                       physical_metric_verified=False, usable_for_ffb=False)
            rows.append(row)
        candidate["height_minus_independent_0p59m_measurement"] = candidate["camera_height_above_floor_m"]-.59
        selected = [r for r in rows if r["solution_index"] == candidate["solution_index"]]
        candidate["same_recording_holdout_planar_rmse_m"] = float(np.sqrt(np.mean([
            r["planar_error_m"]**2 for r in selected if r["point_id"] in ("H100", "H160")])))
        candidate["cross_recording_2m_forward_m"] = next(r["forward_m"] for r in selected if r["point_id"] == "paper_cone_2m")
    paths = [source, Path(__file__).resolve(), ROOT / "src/floor_reference_pose.py",
             ROOT / "src/angular_fisheye_geometry.py", ROOT / "src/cone_distance_diagnostic_config.json"]
    paths += [ROOT / "src/cone_distance_core.py"]
    result.update(fit_ids=list(FIT_IDS), evaluation_ids=["H100", "H160", "paper_cone_2m"],
                  camera_height_constrained=False, camera_xy_constrained=False, physical_floor_points_independently_surveyed=False,
                  current_live_application_allowed=False, source_sha256={str(x): digest(x) for x in paths})
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "point_evaluation.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
