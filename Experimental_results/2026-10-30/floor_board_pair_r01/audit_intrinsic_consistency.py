#!/usr/bin/env python3
"""Fixed-intrinsic native-pixel pose/profile audit, NOT a recalibration.

The same two corners/edge observations are fitted, not held-out evaluation.
Known height is used only in labelled counterfactual constrained controls.
No camera model replacement, source-photo writes, ROS, GPU, or live output.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from scipy.optimize import least_squares

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from fisheye_angular_bundle_diagnostic import angular_project, pose_projection


def tangent_basis(slopes):
    s = np.asarray(slopes, float)
    if s.shape != (2,) or not np.isfinite(s).all():
        raise ValueError("finite two normal slopes required")
    n = np.array([s[0], -1., s[1]])
    n /= np.linalg.norm(n)
    u = np.array([1., 0., 0.])-n[0]*n
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return n, u, v


def plane_project(parameters, camera, *, height_m=None, paper_size=(.296, .210)):
    """Shared near-nominal plane + two freely positioned in-plane rectangles.

    Normal points to camera. Parameters are two slopes, optional log(height),
    then each rectangle's in-plane a,b,yaw. This is not a vehicle frame.
    """
    p = np.asarray(parameters, float)
    size = np.asarray(paper_size, float)
    if (p.shape != ((9,) if height_m is None else (8,)) or not np.isfinite(p).all()
            or size.shape != (2,) or not np.isfinite(size).all() or np.any(size <= 0)):
        raise ValueError("finite parameters and positive measured rectangle required")
    n, u, v = tangent_basis(p[:2])
    h = np.exp(p[2]) if height_m is None else float(height_m)
    if not np.isfinite(h) or h <= 0:
        raise ValueError("finite positive plane height required")
    local = np.array([[-.5, -.5], [.5, -.5], [.5, .5], [-.5, .5]])*size
    uv, optical, angles = [], [], []
    start = 3 if height_m is None else 2
    for a, b, theta in p[start:].reshape(2, 3):
        width = np.cos(theta)*u+np.sin(theta)*v
        depth = np.sin(theta)*u-np.cos(theta)*v
        points = -h*n+a*u+b*v+local[:, 0, None]*width+local[:, 1, None]*depth
        pixels, _, _, theta_cam = angular_project(points, camera.K, camera.D)
        uv.append(pixels)
        optical.append(points)
        angles.append(theta_cam)
    return np.asarray(uv), np.asarray(optical), np.asarray(angles), n, h


def initial_parameters(controls):
    candidates = [r["poses"]["image_far_edge_long"]["candidates"][0] for r in controls]
    normals, centres, widths, heights = [], [], [], []
    for c in candidates:
        transform = np.asarray(c["transform_floor_from_optical"])
        rotation = transform[:3, :3].T
        translation = -rotation@transform[:3, 3]
        heights.append(abs(transform[2, 3]))
        normals.append(np.asarray(c["up_optical"])*np.sign(transform[2, 3]))
        centres.append(translation+rotation@np.array([.148, .105, 0.]))
        widths.append(rotation[:, 0])
    n = np.mean(normals, axis=0)
    slopes = n[[0, 2]] / -n[1]
    _, u, v = tangent_basis(slopes)
    boards = [[centre@u, centre@v, np.arctan2(width@v, width@u)]
              for centre, width in zip(centres, widths)]
    return np.r_[slopes, np.log(np.mean(heights)), np.asarray(boards).ravel()]


def fit_plane(pixels, camera, initial, *, height_m=None, max_nfev=300):
    pixels = np.asarray(pixels, float)
    if pixels.shape != (2, 4, 2) or not np.isfinite(pixels).all():
        raise ValueError("two finite native quadrilaterals required")
    start = np.asarray(initial, float)
    if start.shape != (9,):
        raise ValueError("nine-parameter initializer required")
    x0 = start.copy() if height_m is None else np.r_[start[:2], start[3:]]
    lower = [-.5, -.5]+([np.log(.3)] if height_m is None else [])+[-3., .3, -np.pi]*2
    upper = [.5, .5]+([np.log(.9)] if height_m is None else [])+[3., 3., np.pi]*2
    def fun(p):
        return (plane_project(p, camera, height_m=height_m)[0]-pixels).ravel()
    result = least_squares(fun, x0, jac="3-point", bounds=(lower, upper), x_scale="jac",
        ftol=1e-11, xtol=1e-11, gtol=1e-10, max_nfev=max_nfev, loss="linear")
    uv, points, theta, normal, h = plane_project(result.x, camera, height_m=height_m)
    error = uv-pixels
    norms = np.linalg.norm(result.jac, axis=0)
    gradient = float(np.max(abs(result.jac.T@result.fun)/np.maximum(norms, 1e-12)))
    singular = np.linalg.svd(result.jac/np.maximum(norms, 1e-12), compute_uv=False)
    return dict(success=bool(result.success), height_is_fixed_input=height_m is not None,
        camera_to_printed_plane_m=float(h), normal_optical=normal.tolist(),
        parameters=result.x.tolist(), solver_status=int(result.status), evaluations=result.nfev,
        native_point_rmse_px=float(np.sqrt(np.mean(np.sum(error**2, axis=2)))),
        max_native_point_error_px=float(np.max(np.linalg.norm(error, axis=2))),
        per_frame_rmse_px=np.sqrt(np.mean(np.sum(error**2, axis=2), axis=1)).tolist(),
        native_predicted_xy=uv.tolist(), native_error_xy=error.tolist(),
        all_positive_depth=bool(np.all(points[:, :, 2] > 0)),
        all_within_calibrated_angular_domain=bool(np.all(theta <= camera.max_theta_rad)),
        active_bound_count=int(np.count_nonzero(result.active_mask)),
        scaled_stationarity=gradient, normalized_jacobian_singular_values=singular.tolist(),
        normalized_jacobian_condition=float(singular[0]/singular[-1]),
        physical_metric_verified=False, usable_for_ffb=False)


def refine_individual(control, camera):
    world = np.array([[0., 0., 0.], [.296, 0., 0.], [.296, .210, 0.], [0., .210, 0.]])
    pixels = np.asarray(control["refinement"]["corners_native_xy"])
    results = []
    for c in control["poses"]["image_far_edge_long"]["candidates"]:
        transform = np.asarray(c["transform_floor_from_optical"])
        rotation = transform[:3, :3].T
        t = -rotation@transform[:3, 3]
        x0 = np.r_[cv2.Rodrigues(rotation)[0].ravel(), t[:2], np.log(t[2])]
        def fun(p):
            return (pose_projection(world, p, camera.K, camera.D)[0]-pixels).ravel()
        def jac(p):
            return pose_projection(world, p, camera.K, camera.D)[2].reshape(-1, 6)
        result = least_squares(fun, x0, jac=jac, x_scale="jac", loss="linear",
            max_nfev=300, ftol=1e-11, xtol=1e-11, gtol=1e-10)
        uv, _, _, theta, points, rotation = pose_projection(world, result.x, camera.K, camera.D)
        t = np.r_[result.x[3:5], np.exp(result.x[5])]
        signed = float((-rotation.T@t)[2])
        error = uv-pixels
        results.append(dict(initial_ippe_solution_index=c["solution_index"],
            initial_height_m=abs(transform[2, 3]), initial_native_rmse_px=c["fit_native_rmse_px"],
            refined_height_m=abs(signed), refined_normal_optical=(rotation[:, 2]*np.sign(signed)).tolist(),
            native_point_rmse_px=float(np.sqrt(np.mean(np.sum(error**2, axis=1)))),
            success=bool(result.success), all_positive_depth=bool(np.all(points[:, 2] > 0)),
            all_in_angular_domain=bool(np.all(theta <= camera.max_theta_rad)),
            physical_metric_verified=False, usable_for_ffb=False))
    return dict(frame=control["frame"], branches=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    config, camera, _, _ = load_config()
    source = HERE / "edge_refinement_r02/edge_refinement.json"
    data = json.loads(source.read_text())
    if data["paper_size_mm"] != [296., 210.]:
        raise ValueError("this audit requires the confirmed 296x210mm paper")
    cases, profiles, raw_profiles = [], [], []
    for threshold in (150, 170, 190, 210):
        controls = sorted([r for r in data["all_controls"] if r["threshold"] == threshold
            and r["method"] == "intensity_crossings" and r["trim_fraction"] == .15
            and r["seed_edge_gate_px"] == 4.], key=lambda r: r["frame"])
        if len(controls) != 2 or not all("poses" in c for c in controls):
            raise ValueError("both frozen image controls required")
        pixels = np.asarray([c["refinement"]["corners_native_xy"] for c in controls])
        initial = initial_parameters(controls)
        # Two different height initializers: local robustness check, not global proof.
        starts = [initial, np.r_[initial[:2], np.log(.575), initial[3:]]]
        free_runs = [fit_plane(pixels, camera, s) for s in starts]
        best = min(free_runs, key=lambda r: r["native_point_rmse_px"])
        fixed = fit_plane(pixels, camera, np.asarray(best["parameters"]), height_m=.575)
        case = dict(threshold=threshold, frames=[c["frame"] for c in controls],
            pixels_native_xy=pixels.tolist(), initial_parameters=initial.tolist(),
            individual_native_refinement=[refine_individual(c, camera) for c in controls],
            shared_plane_free_runs=free_runs, shared_plane_best_local=best,
            externally_anchored_printed_plane_0p575m=fixed)
        cases.append(case)
        # The grid is a profile diagnostic, not a confidence interval or noise model.
        for height in sorted(set(np.round(np.r_[np.arange(.49, .631, .005), .575], 6))):
            fit = fit_plane(pixels, camera, np.asarray(best["parameters"]), height_m=float(height))
            profiles.append(dict(threshold=threshold, printed_plane_height_m=float(height),
                native_point_rmse_px=fit["native_point_rmse_px"], max_error_px=fit["max_native_point_error_px"],
                success=fit["success"], scaled_stationarity=fit["scaled_stationarity"],
                active_bound_count=fit["active_bound_count"],
                all_valid=fit["all_positive_depth"] and fit["all_within_calibrated_angular_domain"]))
            raw_profiles.append(dict(threshold=threshold, height_m=float(height), fit=fit))
    sources = {str(p): digest(p) for p in (source, Path(__file__).resolve(), DEFAULT_CONFIG,
        ROOT/config["camera_candidate"], ROOT/config["floor_candidate"],
        ROOT/"src/fisheye_angular_bundle_diagnostic.py", ROOT/"src/fisheye_bundle_diagnostic.py",
        ROOT/"src/angular_fisheye_geometry.py", ROOT/"src/floor_reference_pose.py")}
    result = dict(schema="fixed_intrinsic_floor_plane_native_audit_v1", cases=cases, profiles=raw_profiles,
        primary_threshold=170, K=camera.K.tolist(), D=camera.D.tolist(), source_sha256=sources,
        local_plane_parameterization="normal=(s0,-1,s1)/norm; near-nominal local audit, not global ambiguity enumeration",
        independent_inputs=dict(camera_floor_height_m=.590, approximate_board_thickness_m=.015,
                                printed_plane_height_for_control_m=.575, paper_size_m=[.296, .210]),
        limitations=["same-frame fitting, not holdout accuracy", "corner estimates depend on the frozen KB4 model",
                     "local pose solutions do not prove global optimum", "thickness approximate; no supplied uncertainty"],
        intrinsics_refitted=False, physical_metric_verified=False, intrinsics_transfer_verified=False,
        live_integrated=False, usable_for_ffb=False)
    with (args.output_dir / "intrinsic_consistency.json").open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    with (args.output_dir / "height_profile.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(profiles[0]))
        writer.writeheader()
        writer.writerows(profiles)
    for case in cases:
        free, fixed = case["shared_plane_best_local"], case["externally_anchored_printed_plane_0p575m"]
        print(case["threshold"], "free height", free["camera_to_printed_plane_m"], "free rms", free["native_point_rmse_px"],
              "fixed rms", fixed["native_point_rmse_px"], "max", fixed["max_native_point_error_px"])


if __name__ == "__main__":
    main()
