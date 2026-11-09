"""P0床姿勢を固定し、背景の相対回転だけで後続光線へ移す診断。

Eと後続A-Dは回転推定・補正・ゲートに入れない。並進や高さの補正なし。
鏡像は未確認の診断仮説。元画像・runtime・ROS/FFBを変更しない。
"""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
GEOMETRY = ROOT/"Experimental_results/2026-11-09/wide_floor_geometry_r01"
SPEC = importlib.util.spec_from_file_location("background_transfer_previous", GEOMETRY/"audit_same_frame_pose.py")
previous = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(previous)
original = previous.original
from angular_fisheye_geometry import project, unproject
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from fisheye_floor_geometry import checked_transform

# Predeclared diagnostic screens in pixel space, not chosen from E errors.
SCREENS = dict(min_matches=20, min_train=8, min_test=8, min_x_span_px=100.,
    min_y_span_px=50., max_test_median_px=.6, max_test_p90_px=1.5,
    max_rotation_deg=5., spatial_cell_px=48.)


def spatial_train_mask(source_pixels):
    p = np.asarray(source_pixels, float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        raise ValueError("finite Nx2 source coordinates required")
    return (np.floor(p/SCREENS["spatial_cell_px"]).sum(axis=1).astype(int) % 2) == 0


def checked_rotation(rotation):
    if np.iscomplexobj(rotation):
        raise ValueError("real proper rotation required")
    r = np.array(rotation, float, copy=True)
    if r.shape != (3, 3):
        raise ValueError("3x3 rotation required")
    transform = np.eye(4)
    transform[:3, :3] = r
    checked_transform(transform)
    return r


def estimate_background_rotation(source_pixels, target_pixels, camera):
    p, q = np.asarray(source_pixels, float), np.asarray(target_pixels, float)
    if (p.shape != q.shape or p.ndim != 2 or p.shape[1] != 2
            or not np.isfinite(p).all() or not np.isfinite(q).all()):
        raise ValueError("matching finite Nx2 background coordinates required")
    if (np.any(p[:, 0] < 0) or np.any(p[:, 0] >= 640) or np.any(p[:, 1] < 0)
            or np.any(p[:, 1] >= 245) or np.any(q[:, 1] >= 250)):
        raise ValueError("declared upper-lens background region only; no floor points")
    source, av = unproject(p, camera, image_size=(1280, 720))
    target, bv = unproject(q, camera, image_size=(1280, 720))
    if not (av & bv).all():
        raise ValueError("all rays must be in the calibration domain")
    train = spatial_train_mask(p)
    conditions = dict(enough_matches=len(p) >= SCREENS["min_matches"],
        enough_training=int(train.sum()) >= SCREENS["min_train"],
        enough_test=int((~train).sum()) >= SCREENS["min_test"],
        horizontal_span=len(p) > 0 and float(np.ptp(p[:, 0])) >= SCREENS["min_x_span_px"],
        vertical_span=len(p) > 0 and float(np.ptp(p[:, 1])) >= SCREENS["min_y_span_px"])
    base = dict(accepted_for_offline_diagnostic=False, conditions=conditions,
        matches=len(p), train_count=int(train.sum()), test_count=int((~train).sum()),
        rotation_current_from_reference=None, test_median_px=None, test_p90_px=None,
        rotation_deg=None, translation_estimated=False, physical_metric_verified=False,
        usable_for_ffb=False, model_selected=False)
    if not all(conditions.values()):
        return dict(base, reason="insufficient_background_geometry")
    # E and all current floor-point coordinates are absent from this API.
    rotation = checked_rotation(previous.proper_ray_rotation(source[train], target[train]))
    predicted, visible = project(source[~train] @ rotation.T, camera)
    if not visible.all():
        return dict(base, reason="test_rays_outside_calibration_domain")
    residual = np.linalg.norm(predicted - q[~train], axis=1)
    median, p90 = float(np.median(residual)), float(np.quantile(residual, .9))
    angle = float(np.degrees(np.arccos(np.clip((np.trace(rotation)-1)/2, -1, 1))))
    conditions.update(test_median=median <= SCREENS["max_test_median_px"],
                      test_p90=p90 <= SCREENS["max_test_p90_px"],
                      small_rotation=angle <= SCREENS["max_rotation_deg"])
    accepted = all(conditions.values())
    return dict(base, conditions=conditions, accepted_for_offline_diagnostic=accepted,
        reason="background_test_passed_NOT_metric_approval" if accepted else "background_test_rejected",
        rotation_current_from_reference=rotation.tolist(),
        test_median_px=median, test_p90_px=p90, rotation_deg=angle)


def rotation_for_hypothesis(rotation, hypothesis):
    r = checked_rotation(rotation)
    if hypothesis not in original.HYPOTHESES:
        raise ValueError("explicit hypothesis required")
    if hypothesis == original.HYPOTHESES[2]:
        # S alone is a reflection, not a TF. S R S is a proper rotation.
        s = np.diag([-1., 1., 1.])
        r = s @ r @ s
    return checked_rotation(r)


def transfer_floor_pose(source_candidate, current_from_reference_rotation):
    t = checked_transform(source_candidate["transform_floor_from_optical"])
    r = checked_rotation(current_from_reference_rotation)
    update = np.eye(4)
    update[:3, :3] = r.T
    result = checked_transform(t @ update)
    # Static-centre rotation hypothesis only. Do not refit/abs old height.
    np.testing.assert_array_equal(result[:3, 3], t[:3, 3])
    return dict(transform_floor_from_optical=result.tolist(),
        geometry_consistent=bool(source_candidate["geometry_consistent"] and result[2, 3] > 0),
        camera_height_above_floor_m=float(result[2, 3]),
        selected=False, physical_metric_verified=False, usable_for_ffb=False,
        camera_centre_translation_fixed=True, current_floor_points_used=False)


def floor_point_reprojection(pixel_points, target_transform, hypothesis, camera):
    transform = checked_transform(target_transform)
    world = original.vehicle_world(hypothesis)
    uv, valid = project((world-transform[:3, 3]) @ transform[:3, :3], camera)
    if not valid.all():
        return None
    if hypothesis == original.HYPOTHESES[2]:
        uv[:, 0] = 2 * camera.K[0, 2] - uv[:, 0]
    return float(np.sqrt(np.mean(np.sum((uv-pixel_points)**2, axis=1))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    provenance_path = GEOMETRY/"same_frame_pose_r01/input_provenance.json"
    for path, sha in json.loads(provenance_path.read_text()).items():
        if digest(path) != sha:
            raise ValueError("prior source/input changed: " + path)
    tracks_path = GEOMETRY/"same_frame_pose_r01/background_tracks.csv"
    points_path = GEOMETRY/"corner_identity_r01/corner_identity_comparison.csv"
    tracks = list(csv.DictReader(tracks_path.open()))
    points = list(csv.DictReader(points_path.open()))
    settings, camera, _, _ = load_config()
    inputs = {str(p): digest(p) for p in [Path(__file__), provenance_path, tracks_path,
        points_path, DEFAULT_CONFIG, ROOT/settings["camera_candidate"],
        ROOT/"src/angular_fisheye_geometry.py", ROOT/"src/fisheye_floor_geometry.py",
        GEOMETRY/"audit_same_frame_pose.py", GEOMETRY/"analyze.py"]}
    def frame_points(frame, threshold):
        return {row["point"]: np.array([float(row["convex_x"]), float(row["convex_y"])])
            for row in points if int(row["frame"]) == frame and int(row["threshold"]) == threshold
            and row["convex_available"] == "True"}
    frozen = {}
    for threshold in (90, 100, 110, 120):
        reference = frame_points(20063, threshold)
        for hypothesis in original.HYPOTHESES:
            frozen[threshold, hypothesis] = original.fit_fixed(
                np.array([reference[k] for k in original.FIXED]), hypothesis, camera)["candidates"]
    rotations, rotation_rows, evaluations = {}, [], []
    for group, frames, _, target in original.GROUPS[1:]:
        for frame in frames:
            if frame <= 20063:
                raise ValueError("reference must precede current observations")
            rows = [row for row in tracks if int(row["frame"]) == frame]
            source = np.array([[float(r["source_x"]), float(r["source_y"])] for r in rows])
            current = np.array([[float(r["target_x"]), float(r["target_y"])] for r in rows])
            estimate = estimate_background_rotation(source, current, camera)
            rotations[str(frame)] = estimate
            rotation_rows.append(dict(frame=frame, group=group,
                **{k: v for k, v in estimate.items() if k not in ("conditions", "rotation_current_from_reference")}))
            for threshold in (90, 100, 110, 120):
                observations = frame_points(frame, threshold)
                current_fixed = np.array([observations[k] for k in original.FIXED])
                for hypothesis in original.HYPOTHESES:
                    for candidate in frozen[threshold, hypothesis]:
                        for method in ("frozen_P0_no_update", "background_train_rotation_only"):
                            used = candidate
                            allowed = method == "frozen_P0_no_update" or estimate["accepted_for_offline_diagnostic"]
                            if allowed and method != "frozen_P0_no_update":
                                rotation = rotation_for_hypothesis(
                                    estimate["rotation_current_from_reference"], hypothesis)
                                used = transfer_floor_pose(candidate, rotation)
                            result = (original.evaluate_E(observations["E"], target, used, hypothesis, camera)
                                if allowed else dict(available=False, reason="background_screen_rejected",
                                    predicted_X_m=None, predicted_Z_m=None, error_X_m=None,
                                    error_Z_m=None, planar_error_m=None))
                            evaluations.append(dict(frame=frame, group=group, threshold=threshold,
                                method=method, hypothesis=hypothesis, solution_index=candidate["solution_index"],
                                source_fit_frame=20063, height_m=used["camera_height_above_floor_m"],
                                diagnostic_background_pass=estimate["accepted_for_offline_diagnostic"],
                                current_fixed_reprojection_rmse_px=None if not allowed else floor_point_reprojection(
                                    current_fixed, used["transform_floor_from_optical"], hypothesis, camera),
                                **result))
    metrics = []
    for group, _, _, _ in original.GROUPS[1:]:
        for method in ("frozen_P0_no_update", "background_train_rotation_only"):
            for hypothesis in original.HYPOTHESES:
                for branch in (0, 1):
                    rows = [r for r in evaluations if r["group"] == group and r["method"] == method
                            and r["hypothesis"] == hypothesis and r["solution_index"] == branch
                            and r["threshold"] == 110]
                    valid = [r for r in rows if r["available"]]
                    metrics.append(dict(group=group, method=method, hypothesis=hypothesis,
                        solution_index=branch, available=len(valid), total=len(rows),
                        median_X_m=None if not valid else float(np.median([r["predicted_X_m"] for r in valid])),
                        median_Z_m=None if not valid else float(np.median([r["predicted_Z_m"] for r in valid])),
                        median_error_m=None if not valid else float(np.median([r["planar_error_m"] for r in valid]))))
    summary = dict(status="ROTATION_TRANSFER_SUPPORTED_CONDITIONALLY_NOT_LIVE_APPROVED",
        reference_frame=20063, later_frames=8, background_passed=sum(r["accepted_for_offline_diagnostic"] for r in rotation_rows),
        screens=SCREENS, selected_hypothesis=None, selected_solution=None,
        background_rotation_uses_floor_markers=False, background_rotation_uses_E=False,
        background_rotation_uses_range_targets=False, background_test_spatially_held_out=True,
        independent_new_recording=False, translation_or_height_refitted=False,
        mirror_hypothesis_independently_verified=False, physical_metric_verified=False,
        usable_for_ffb=False, published_to_ros=False, camera_images_edited_or_exported=False,
        runtime_changed=False, metrics=metrics)
    args.output_dir.mkdir(parents=True)
    original.dump(args.output_dir/"input_provenance.json", inputs)
    original.dump(args.output_dir/"rotation_estimates.json", rotations)
    original.dump(args.output_dir/"summary.json", summary)
    original.table(args.output_dir/"background_quality.csv", rotation_rows)
    original.table(args.output_dir/"evaluation_metrics.csv", evaluations)
    original.table(args.output_dir/"group_metrics.csv", metrics)
    print(summary["status"], "background passed", summary["background_passed"], "/ 8")
    for row in metrics:
        if row["hypothesis"] == original.HYPOTHESES[2] and row["solution_index"] == 0:
            print(row)


if __name__ == "__main__":
    main()
