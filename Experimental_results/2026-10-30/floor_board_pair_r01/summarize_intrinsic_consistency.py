#!/usr/bin/env python3
"""Offline fixed-camera audit summaries, observability controls and plots."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
from audit_intrinsic_consistency import angular_project, load_config, plane_project
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest


def central_jacobian(function, parameters, relative_step):
    p = np.asarray(parameters, float)
    if p.ndim != 1 or not np.isfinite(p).all() or not np.isfinite(relative_step) or relative_step <= 0:
        raise ValueError("finite vector and positive finite differentiation step required")
    columns = []
    for i in range(len(p)):
        d = np.zeros_like(p)
        d[i] = relative_step*max(1, abs(p[i]))
        columns.append((np.asarray(function(p+d)).ravel()-np.asarray(function(p-d)).ravel())/(2*d[i]))
    result = np.asarray(columns).T
    if not np.isfinite(result).all():
        raise ValueError("finite Jacobian required")
    return result


def profile_intrinsics(pose_jacobian, intrinsic_jacobian):
    """Project out pose nuisance directions; descriptive local rank only."""
    a, b = np.asarray(pose_jacobian, float), np.asarray(intrinsic_jacobian, float)
    if (a.ndim != 2 or b.ndim != 2 or a.shape[0] != b.shape[0] or min(a.shape+b.shape) <= 0
            or not np.isfinite(a).all() or not np.isfinite(b).all()):
        raise ValueError("finite nonempty same-row Jacobians required")
    u, s, _ = np.linalg.svd(a, full_matrices=False)
    rank = int(np.count_nonzero(s > 1e-9*s[0])) if s[0] > 0 else 0
    q = u[:, :rank]
    residualized = b-q@(q.T@b)
    column_norms = np.linalg.norm(residualized, axis=0)
    scaled = residualized/np.maximum(column_norms, 1e-30)
    singular = np.linalg.svd(scaled, compute_uv=False)
    condition = float(singular[0]/singular[-1]) if singular[-1] > 0 else None
    return dict(pose_rank=rank, residual_coordinate_count=a.shape[0],
        intrinsic_parameter_count=b.shape[1], rank_ceiling_after_pose_elimination=min(a.shape[0]-rank, b.shape[1]),
        pose_jacobian_singular_values=s.tolist(), residualized_column_norms=column_norms.tolist(),
        normalized_profile_singular_values=singular.tolist(), normalized_profile_condition=condition,
        smallest_largest_ratio=float(singular[-1]/singular[0]) if singular[0] > 0 else 0.,
        note="Column-normalized local sensitivity; no pixel noise model, covariance, or accuracy certificate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = args.input_dir / "intrinsic_consistency.json"
    data = json.loads(source.read_text())
    _, camera, _, _ = load_config()
    primary = next(c for c in data["cases"] if c["threshold"] == 170)
    summaries = []
    for case in data["cases"]:
        free = case["shared_plane_best_local"]
        fixed = case["externally_anchored_printed_plane_0p575m"]
        shift = np.linalg.norm(np.asarray(free["native_predicted_xy"])-fixed["native_predicted_xy"], axis=2)
        summaries.append(dict(threshold=case["threshold"], free_printed_plane_height_m=free["camera_to_printed_plane_m"],
            free_rmse_px=free["native_point_rmse_px"], anchored_0p575_rmse_px=fixed["native_point_rmse_px"],
            anchored_max_error_px=fixed["max_native_point_error_px"],
            free_vs_anchored_prediction_rms_shift_px=float(np.sqrt(np.mean(shift**2))),
            free_vs_anchored_prediction_max_shift_px=float(shift.max())))
    observations = []
    for label, height, fit in (("free_height", None, primary["shared_plane_best_local"]),
            ("anchored_0p575m", .575, primary["externally_anchored_printed_plane_0p575m"])):
        p = np.asarray(fit["parameters"])
        _, points, theta, _, _ = plane_project(p, camera, height_m=height)
        intrinsic = angular_project(points.reshape(-1, 3), camera.K, camera.D)[2].reshape(-1, 8)
        for step in (1e-5, 1e-6, 1e-7):
            pose = central_jacobian(lambda x: plane_project(x, camera, height_m=height)[0], p, step)
            observation = profile_intrinsics(pose, intrinsic)
            observations.append(dict(mode=label, derivative_relative_step=step,
                intrinsic_coordinates=["log_fx", "log_fy", "cx", "cy", "d1", "d2", "d3", "d4"],
                ray_angle_min_deg=float(np.degrees(theta.min())), ray_angle_max_deg=float(np.degrees(theta.max())),
                **observation))
    edge_source = HERE / "edge_refinement_r02/edge_refinement.json"
    edges = json.loads(edge_source.read_text())
    threshold_shifts = []
    controls = [c for c in edges["all_controls"] if c["method"] == "intensity_crossings"
                and c["trim_fraction"] == .15 and c["seed_edge_gate_px"] == 4.]
    for frame in (1259, 1655):
        base = np.asarray(next(c for c in controls if c["frame"] == frame and c["threshold"] == 170)["refinement"]["corners_native_xy"])
        for threshold in (150, 190, 210):
            other = np.asarray(next(c for c in controls if c["frame"] == frame and c["threshold"] == threshold)["refinement"]["corners_native_xy"])
            change = np.linalg.norm(other-base, axis=1)
            threshold_shifts.append(dict(frame=frame, threshold=threshold, max_shift_px=float(change.max()),
                                        rms_shift_px=float(np.sqrt(np.mean(change**2)))))
    summary = dict(status="INTRINSIC_TRANSFER_CAUSE_UNRESOLVED_NO_RECALIBRATION",
        comparisons=summaries, local_intrinsic_observability=observations,
        observed_threshold_sensitivity=threshold_shifts, independent_accuracy_holdout=False,
        intrinsics_refitted=False, intrinsics_transfer_verified=False, physical_metric_verified=False,
        live_integrated=False, usable_for_ffb=False,
        source_sha256={str(p): digest(p) for p in (source, edge_source, Path(__file__).resolve())})
    with (args.output_dir / "audit_summary.json").open("x") as f:
        json.dump(summary, f, indent=2, allow_nan=False)
        f.write("\n")
    with (args.output_dir / "model_comparison.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    for threshold in (150, 170, 190, 210):
        rows = [r for r in data["profiles"] if r["threshold"] == threshold]
        ax.plot([100*r["height_m"] for r in rows], [r["fit"]["native_point_rmse_px"] for r in rows],
                label=f"Threshold {threshold}"+(" (primary)" if threshold == 170 else ""), lw=2 if threshold == 170 else 1)
    primary_free = primary["shared_plane_best_local"]
    ax.plot(100*primary_free["camera_to_printed_plane_m"], primary_free["native_point_rmse_px"], "ko", label="Primary local minimum")
    ax.axvline(57.5, color="black", linestyle="--", label="59cm lens height - approximate 1.5cm board")
    ax.set(xlabel="Assumed camera-to-printed-plane height (cm)", ylabel="Same-frame native point RMSE (pixels)",
           title="Frozen intrinsics: height profile after optimizing shared plane and board positions")
    ax.grid(alpha=.2)
    ax.legend(fontsize=8)
    fig.text(.5, .02, "Profile is not a confidence interval or independent accuracy test.\n"
             "Same 8 modelled corners; no calibration change or live use.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .09, 1, 1))
    fig.savefig(args.output_dir / "height_profile.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5))
    for mode in ("free_height", "anchored_0p575m"):
        row = next(r for r in observations if r["mode"] == mode and r["derivative_relative_step"] == 1e-6)
        values = np.asarray(row["normalized_profile_singular_values"])
        ax.semilogy(np.arange(1, len(values)+1), values/values[0], "o-", label=mode)
    ax.set(xticks=range(1, 9), xlabel="Singular value index (descending)",
           ylabel="Relative column-normalized intrinsic sensitivity",
           title="Local ability to distinguish 8 intrinsic parameters after eliminating pose")
    ax.grid(alpha=.2)
    ax.legend()
    fig.text(.5, .02, "Free height: at most 7 intrinsic directions remain (16 residual coordinates - 9 pose parameters).\n"
             "Fixed height improves rank, not independent evidence. No covariance or physical approval.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .09, 1, 1))
    fig.savefig(args.output_dir / "intrinsic_observability.png", dpi=150)
    plt.close(fig)
    tests = []
    for pattern in ("test_intrinsic_consistency.py", "test_intrinsic_audit_summary.py"):
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", pattern]
        run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
        tests.append(dict(command=cmd, returncode=run.returncode, stdout=run.stdout, stderr=run.stderr))
    fits = [r["fit"] for r in data["profiles"]]
    fits += [fit for c in data["cases"] for fit in c["shared_plane_free_runs"]]
    fits += [c["externally_anchored_printed_plane_0p575m"] for c in data["cases"]]
    checks = dict(all_input_hashes_unchanged=all(digest(Path(p)) == h for p, h in data["source_sha256"].items()),
        all_profiles_preserved=len(data["profiles"]) == 116,
        all_local_plane_fits_converged=all(f["success"] and f["scaled_stationarity"] < 1e-5 for f in fits),
        all_local_plane_fits_in_domain=all(f["all_positive_depth"] and f["all_within_calibrated_angular_domain"] for f in fits),
        no_local_bound_saturation=all(f["active_bound_count"] == 0 for f in fits),
        frozen_intrinsics=np.array_equal(data["K"], camera.K) and np.array_equal(data["D"], camera.D),
        no_intrinsic_refit_or_physical_approval=all(data[k] is False for k in ("intrinsics_refitted", "physical_metric_verified", "intrinsics_transfer_verified", "live_integrated", "usable_for_ffb")),
        unknown_height_rank_ceiling_seven=all(r["rank_ceiling_after_pose_elimination"] == 7 for r in observations if r["mode"] == "free_height"),
        focused_tests_passed=all(t["returncode"] == 0 and "Ran 0 tests" not in t["stderr"] for t in tests))
    verification = dict(status="PASS" if all(checks.values()) else "FAIL", checks=checks, test_runs=tests,
        meaning="Numerical/software audit checks only, not calibration approval",
        source_sha256={str(p): digest(p) for p in (Path(__file__).resolve(), HERE/"test_intrinsic_consistency.py", HERE/"test_intrinsic_audit_summary.py")})
    with (args.output_dir / "verification.json").open("x") as f:
        json.dump(verification, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(dict(status=verification["status"], checks=checks, comparisons=summaries), indent=2))
    return 0 if verification["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
