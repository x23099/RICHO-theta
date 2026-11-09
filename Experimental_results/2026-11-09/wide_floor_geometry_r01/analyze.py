"""L字の暫定画像点・左右の整合性・床4点fitを分離するオフライン診断。

元PNGを変更せず、既存KB4内部校正を固定する。Eはfit/解選択に使わない。
鏡像仮説を診断するが、映像やruntimeを反転せず承認モデルも出力しない。
"""
import argparse
import csv
import itertools
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from angular_fisheye_geometry import floor_from_rays, unproject
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from floor_reference_pose import planar_floor_pose_candidates

SESSION = "159c37ad534a4ac0b96ca69791713567"
# Image-left/right labels are NOT vehicle-left/right. These are image-only
# analyst coarse estimates of the outer elbow, not human-approved coordinates.
FIXED = {"near_image_left": [253, 415], "near_image_right": [384, 410],
         "far_image_left": [275, 378], "far_image_right": [356, 375]}
GROUPS = [
    ("P0", [20063, 20493], None, None),
    ("P1", [38231, 38464], [320, 391], [0., 1.4]),
    ("P2", [43924, 44053], [318, 371], [0., 2.]),
    ("P3_vehicle_left", [51180, 51342], [344, 390], [-.2, 1.4]),
    ("P4_vehicle_right", [54907, 55094], [292, 392], [.2, 1.4]),
]
HYPOTHESES = ("image_left_is_vehicle_left_control",
              "vehicle_sides_follow_E_unmodified_rays",
              "vehicle_sides_follow_E_reflected_ray_x_control")


def dump(path, value):
    with path.open("x") as f:
        f.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def table(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def outer_corner_proposal(gray, seed, threshold):
    """Image-only nearby contour vertex; NOT proof of physical outer-corner ID.

    The seed nominates an outer elbow. Retain the closest local contour vertex,
    and report threshold spread rather than claiming subpixel edge accuracy.
    A local in-memory ROI is used, but no cropped/annotated image is saved.
    """
    seed = np.asarray(seed, float)
    if gray.shape != (720, 1280) or seed.shape != (2,) or not np.isfinite(seed).all():
        raise ValueError("native image and finite seed required")
    x, y = np.rint(seed).astype(int)
    if not (16 <= x < 624 and 12 <= y < 708):
        raise ValueError("front-lens seed away from ROI boundaries required")
    left, top = x - 16, y - 10
    mask = (gray[top:y+11, left:x+17] < threshold).astype(np.uint8)
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    vertices = []
    for contour in contours:
        if cv2.contourArea(contour) >= 2:
            vertices.extend((cv2.approxPolyDP(contour, .5, True)[:, 0, :]
                             + [left, top]).tolist())
    if not vertices:
        return None
    points = np.array(vertices, float)
    distances = np.linalg.norm(points - seed, axis=1)
    index = int(np.argmin(distances))
    return points[index] if distances[index] <= 4 else None


def vehicle_world(hypothesis):
    if hypothesis not in HYPOTHESES:
        raise ValueError("explicit hypothesis required")
    # x-forward, y-left, z-up; order follows FIXED image labels.
    world = np.array([[1., .4, 0], [1., -.4, 0],
                      [1.8, .4, 0], [1.8, -.4, 0]])
    if hypothesis != HYPOTHESES[0]:
        world[:, 1] *= -1
    return world


def hypothesis_pixels(pixels, hypothesis, camera):
    if hypothesis not in HYPOTHESES:
        raise ValueError("explicit hypothesis required")
    result = np.array(pixels, float, copy=True)
    if hypothesis == HYPOTHESES[2]:
        # Only point arrays change. Reflecting around K.cx negates the KB4
        # ray's optical x; this is NOT a measured image-orientation correction.
        result[:, 0] = 2 * camera.K[0, 2] - result[:, 0]
    return result


def fit_fixed(pixels, hypothesis, camera):
    if np.asarray(pixels).shape != (4, 2):
        raise ValueError("exactly the four fixed points, no E fitting")
    return planar_floor_pose_candidates(hypothesis_pixels(pixels, hypothesis, camera),
                                        vehicle_world(hypothesis), camera)


def evaluate_E(pixel, target_XZ, candidate, hypothesis, camera):
    result = dict(available=False, reason="physically_inconsistent_floor_pose",
                  predicted_X_m=None, predicted_Z_m=None, error_X_m=None,
                  error_Z_m=None, planar_error_m=None)
    if not candidate["geometry_consistent"]:
        return result
    rays, valid = unproject(hypothesis_pixels([pixel], hypothesis, camera),
                            camera, image_size=(1280, 720))
    points, accepted = floor_from_rays(rays, valid, candidate["transform_floor_from_optical"])
    if not accepted[0]:
        return dict(result, reason="no_forward_floor_intersection")
    X, Z = -float(points[0, 1]), float(points[0, 0])
    dx, dz = X - target_XZ[0], Z - target_XZ[1]
    return dict(available=True, reason="unapproved_hypothesis_only", predicted_X_m=X,
                predicted_Z_m=Z, error_X_m=dx, error_Z_m=dz,
                planar_error_m=float(np.hypot(dx, dz)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/home/robo25/Downloads"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    settings, camera, _, _ = load_config()
    inputs = {str(p): digest(p) for p in [Path(__file__), DEFAULT_CONFIG,
              ROOT/settings["camera_candidate"], ROOT/"src/floor_reference_pose.py",
              ROOT/"src/angular_fisheye_geometry.py"]}
    observations, points_by_frame, roles, targets = [], {}, {}, {}
    for group, frames, e_seed, target in GROUPS:
        for frame in frames:
            path = args.image_dir / f"decoded_{SESSION}_f{frame:06d}.png"
            inputs[str(path)] = digest(path)
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None or image.shape != (720, 1280):
                raise ValueError("unchanged native image required")
            seeds = dict(FIXED)
            if e_seed is not None:
                seeds["E"] = e_seed
            points_by_frame[frame] = {}
            roles[frame], targets[frame] = group, target
            for label, seed in seeds.items():
                for threshold in (90, 100, 110, 120):
                    proposal = outer_corner_proposal(image, seed, threshold)
                    observations.append(dict(frame=frame, group=group, point=label,
                        threshold=threshold, seed_x=seed[0], seed_y=seed[1],
                        observed=proposal is not None,
                        proposed_x=None if proposal is None else float(proposal[0]),
                        proposed_y=None if proposal is None else float(proposal[1]),
                        point_human_reviewed=False, physical_corner_identity_verified=False))
                    if threshold == 110:
                        if proposal is None:
                            raise ValueError(f"baseline point unavailable: {frame}/{label}")
                        points_by_frame[frame][label] = proposal
            if digest(path) != inputs[str(path)]:
                raise ValueError("image changed during analysis")
    poses, holdouts, pose_objects = [], [], {}
    # Fit ONLY P0's A-D; apply frozen poses to ALL eight E images.
    for frame in GROUPS[0][1]:
        fixed = np.array([points_by_frame[frame][key] for key in FIXED])
        for hypothesis in HYPOTHESES:
            fit = fit_fixed(fixed, hypothesis, camera)
            pose_objects[f"{frame}:{hypothesis}"] = fit
            for candidate in fit["candidates"]:
                identity = dict(fit_frame=frame, hypothesis=hypothesis,
                                solution_index=candidate["solution_index"])
                poses.append(dict(identity, fit_native_rmse_px=candidate["fit_native_rmse_px"],
                    camera_height_m=candidate["camera_height_above_floor_m"],
                    geometry_consistent=candidate["geometry_consistent"], selected=False))
                for e_frame, points in points_by_frame.items():
                    if "E" in points:
                        holdouts.append(dict(identity, group=roles[e_frame], frame=e_frame,
                            declared_X_m=targets[e_frame][0], declared_Z_m=targets[e_frame][1],
                            **evaluate_E(points["E"], targets[e_frame], candidate, hypothesis, camera)))
    # Stress each of 8 calibration coordinates, no tuning to E targets/height.
    stress = []
    baseline = np.array([points_by_frame[GROUPS[0][1][0]][key] for key in FIXED])
    for hypothesis, axis, sign, amplitude in itertools.product(HYPOTHESES, range(8), (-1, 1), (.5, 1.)):
        changed = baseline.copy()
        changed.flat[axis] += sign * amplitude
        for candidate in fit_fixed(changed, hypothesis, camera)["candidates"]:
            stress.append(dict(hypothesis=hypothesis, point=list(FIXED)[axis//2],
                axis="xy"[axis % 2], delta_px=sign*amplitude,
                solution_index=candidate["solution_index"],
                camera_height_m=candidate["camera_height_above_floor_m"],
                fit_native_rmse_px=candidate["fit_native_rmse_px"],
                geometry_consistent=candidate["geometry_consistent"],
                **evaluate_E(points_by_frame[43924]["E"], targets[43924], candidate, hypothesis, camera)))
    repeat = []
    for frame, points in points_by_frame.items():
        for label in FIXED:
            delta = points[label] - points_by_frame[20063][label]
            repeat.append(dict(frame=frame, group=roles[frame], point=label,
                dx_px=float(delta[0]), dy_px=float(delta[1]), norm_px=float(np.linalg.norm(delta))))
    metrics = []
    # Explicitly report both IPPE solutions, never rank by E error.
    for hypothesis, branch, group in itertools.product(HYPOTHESES, (0, 1), [g[0] for g in GROUPS[1:]]):
        rows = [r for r in holdouts if r["hypothesis"] == hypothesis
                and r["solution_index"] == branch and r["group"] == group]
        available = [r for r in rows if r["available"]]
        metrics.append(dict(hypothesis=hypothesis, solution_index=branch, group=group,
            available=len(available), total=len(rows),
            median_X_m=None if not available else float(np.median([r["predicted_X_m"] for r in available])),
            median_Z_m=None if not available else float(np.median([r["predicted_Z_m"] for r in available])),
            median_error_m=None if not available else float(np.median([r["planar_error_m"] for r in available]))))
    # Current local code audit only; not proof of the school PCs' deployed bytes.
    source_paths = [ROOT/"src/theta_rtc_diagnostic.py", ROOT/"src/theta_rtc_frames.py",
                    ROOT/"src/start_theta_stream_rtc.sh"]
    for p in source_paths:
        inputs[str(p)] = digest(p)
    summary = dict(status="WITHHELD_HANDEDNESS_AND_POINT_REVIEW_REQUIRED",
        session=SESSION, image_count=10, fixed_fit_frames=GROUPS[0][1], holdout_frames=8,
        declared_user_left_frames=[51180, 51342], declared_user_right_frames=[54907, 55094],
        vehicle_left_confirmed_facing_forward=True,
        fixed_point_ids_inferred_from_handedness_not_individually_verified=True,
        hypotheses=list(HYPOTHESES), selected_hypothesis=None, selected_solution=None,
        intrinsic_refit=False, height_fitted_to_reported_590mm=False, E_used_for_fit=False,
        camera_images_edited_or_exported=False, runtime_changed=False, physical_metric_verified=False,
        published_to_ros=False, usable_for_ffb=False, point_coordinates_human_reviewed=False,
        measurement_uncertainties_supplied=False, deployed_school_source_hashes_available=False,
        max_fixed_point_proposal_shift_px=max(r["norm_px"] for r in repeat),
        opencv_version=cv2.__version__, metrics=metrics)
    args.output_dir.mkdir(parents=True)
    dump(args.output_dir/"input_provenance.json", inputs)
    dump(args.output_dir/"pose_hypotheses.json", pose_objects)
    dump(args.output_dir/"summary.json", summary)
    for name, rows in [("point_proposals", observations), ("pose_metrics", poses),
                       ("holdout_metrics", holdouts), ("calibration_pixel_stress", stress),
                       ("fixed_point_repeatability", repeat), ("group_metrics", metrics)]:
        table(args.output_dir/f"{name}.csv", rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
