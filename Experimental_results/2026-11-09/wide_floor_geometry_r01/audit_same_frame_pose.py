"""背景の画像間変化と、同じ画像の固定4点による姿勢再推定を分離する。"""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("wide_floor_corner_audit", Path(__file__).with_name("audit_corner_identity.py"))
corners = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corners)
original = corners.original
from angular_fisheye_geometry import project, unproject
from cone_distance_core import digest, load_config


def proper_ray_rotation(source, target):
    """Diagnostic least-squares ray rotation, not a measured motion/TF."""
    a, b = np.asarray(source, float), np.asarray(target, float)
    if (a.shape != b.shape or a.ndim != 2 or a.shape[1] != 3 or len(a) < 3
            or not np.isfinite(a).all() or not np.isfinite(b).all()
            or not np.allclose(np.linalg.norm(a, axis=1), 1)
            or not np.allclose(np.linalg.norm(b, axis=1), 1)):
        raise ValueError("matching finite unit rays required")
    u, _, vt = np.linalg.svd(b.T @ a)
    return u @ np.diag([1., 1., np.linalg.det(u @ vt)]) @ vt


def background_motion(reference, current, camera):
    if reference.shape != (720, 1280) or current.shape != reference.shape:
        raise ValueError("native grayscale images required")
    mask = np.zeros_like(reference)
    cv2.ellipse(mask, (320, 300), (270, 265), 0, 0, 360, 255, -1)
    mask[245:] = 0  # Ceiling/building only; no floor markers or E.
    seeds = cv2.goodFeaturesToTrack(reference, maxCorners=350, qualityLevel=.015,
                                   minDistance=9, mask=mask, blockSize=5)
    if seeds is None:
        return dict(status="no_background_features", matches=0), []
    tracked, status, error = cv2.calcOpticalFlowPyrLK(reference, current, seeds, None,
                                                    winSize=(15, 15), maxLevel=2)
    if tracked is None:
        return dict(status="tracking_unavailable", matches=0), []
    backward, reverse_status, _ = cv2.calcOpticalFlowPyrLK(current, reference, tracked, None,
                                                         winSize=(15, 15), maxLevel=2)
    if backward is None:
        return dict(status="reverse_tracking_unavailable", matches=0), []
    fb = np.linalg.norm(backward[:, 0] - seeds[:, 0], axis=1)
    accepted = (status[:, 0] > 0) & (reverse_status[:, 0] > 0) & (fb < .5) & (error[:, 0] < 20)
    p, q = seeds[:, 0][accepted], tracked[:, 0][accepted]
    if len(p) < 8:
        return dict(status="insufficient_background_matches", matches=len(p)), []
    flow = q - p
    median = np.median(flow, axis=0)
    source_rays, av = unproject(p, camera, image_size=(1280, 720))
    target_rays, bv = unproject(q, camera, image_size=(1280, 720))
    valid = av & bv
    rotation = proper_ray_rotation(source_rays[valid], target_rays[valid])
    predicted, projected = project(source_rays[valid] @ rotation.T, camera)
    residual = np.linalg.norm(predicted[projected] - q[valid][projected], axis=1)
    records = [dict(source_x=float(a[0]), source_y=float(a[1]),
                    target_x=float(b[0]), target_y=float(b[1]),
                    dx_px=float(d[0]), dy_px=float(d[1])) for a, b, d in zip(p, q, flow)]
    return dict(status="image_motion_observed_NOT_physical_motion_proof", matches=len(p),
        median_dx_px=float(median[0]), median_dy_px=float(median[1]),
        mad_dx_px=float(np.median(np.abs(flow[:, 0] - median[0]))),
        mad_dy_px=float(np.median(np.abs(flow[:, 1] - median[1]))),
        apparent_ray_rotation_deg=float(np.degrees(np.arccos(np.clip((np.trace(rotation)-1)/2, -1, 1)))),
        rotation_only_pixel_residual_median=float(np.median(residual)),
        rotation_only_pixel_residual_p90=float(np.quantile(residual, .9)),
        physical_motion_measured=False, scene_points_used_for_floor_fit=False), records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/home/robo25/Downloads"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    folder = Path(__file__).parent
    identity_file = folder/"corner_identity_r01/corner_identity_comparison.csv"
    prior_provenance = folder/"corner_identity_r01/input_provenance.json"
    for path, sha in json.loads(prior_provenance.read_text()).items():
        if digest(path) != sha:
            raise ValueError("prior input changed: " + path)
    inputs = {str(p): digest(p) for p in [Path(__file__), identity_file, prior_provenance,
        folder/"audit_corner_identity.py", folder/"analyze.py"]}
    proposals = list(csv.DictReader(identity_file.open()))
    _, camera, _, _ = load_config()
    reference_path = args.image_dir/f"decoded_{original.SESSION}_f020063.png"
    reference = cv2.imread(str(reference_path), cv2.IMREAD_GRAYSCALE)
    images, flow_rows, tracks, pose_rows, metrics = [], [], [], [], []
    for group, frames, _, target in original.GROUPS:
        for frame in frames:
            path = args.image_dir/f"decoded_{original.SESSION}_f{frame:06d}.png"
            inputs[str(path)] = digest(path)
            current = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            motion, detail = background_motion(reference, current, camera)
            flow_rows.append(dict(frame=frame, group=group, **motion))
            tracks.extend(dict(r, frame=frame) for r in detail)
            images.append(dict(frame=frame, group=group, sha256=inputs[str(path)]))
            if target is None:
                continue
            for threshold in (90, 100, 110, 120):
                selected = [r for r in proposals if int(r["frame"]) == frame
                            and int(r["threshold"]) == threshold]
                points = {r["point"]: np.array([float(r["convex_x"]), float(r["convex_y"])])
                          for r in selected if r["convex_available"] == "True"}
                if set(points) != set(original.FIXED) | {"E"}:
                    raise ValueError("all four fixed points and independent E required")
                fixed = np.array([points[label] for label in original.FIXED])
                for hypothesis in original.HYPOTHESES:
                    # E isn't passed to this function; no target-dependent fit.
                    fit = original.fit_fixed(fixed, hypothesis, camera)
                    for candidate in fit["candidates"]:
                        identity = dict(frame=frame, group=group, threshold=threshold,
                            hypothesis=hypothesis, solution_index=candidate["solution_index"])
                        pose_rows.append(dict(identity, height_m=candidate["camera_height_above_floor_m"],
                            native_rmse_px=candidate["fit_native_rmse_px"],
                            geometry_consistent=candidate["geometry_consistent"], selected=False))
                        metrics.append(dict(identity, **original.evaluate_E(points["E"], target,
                                                               candidate, hypothesis, camera)))
            if digest(path) != inputs[str(path)]:
                raise ValueError("image changed")
    group_metrics = []
    for group, _, _, _ in original.GROUPS[1:]:
        for hypothesis in original.HYPOTHESES:
            for branch in (0, 1):
                subset = [r for r in metrics if r["group"] == group and r["hypothesis"] == hypothesis
                          and r["solution_index"] == branch and r["threshold"] == 110]
                valid = [r for r in subset if r["available"]]
                group_metrics.append(dict(group=group, hypothesis=hypothesis, solution_index=branch,
                    available=len(valid), total=len(subset),
                    median_X_m=None if not valid else float(np.median([r["predicted_X_m"] for r in valid])),
                    median_Z_m=None if not valid else float(np.median([r["predicted_Z_m"] for r in valid])),
                    median_planar_error_m=None if not valid else float(np.median([r["planar_error_m"] for r in valid]))))
    summary = dict(status="WITHHELD_HANDEDNESS_DESPITE_BETTER_PAIRED_FRAME_DIAGNOSTIC",
        session=original.SESSION, image_count=len(images), input_images=images,
        fixed_pose_fit_uses_same_frame_A_to_D_only=True, E_in_pose_fit=False,
        background_used_for_floor_fit=False, mirror_hypothesis_independently_verified=False,
        physical_corner_identity_verified=False, camera_images_edited_or_exported=False,
        runtime_changed=False, usable_for_ffb=False, physical_metric_verified=False,
        selected_hypothesis=None, selected_solution=None, group_metrics=group_metrics,
        opencv_version=cv2.__version__)
    args.output_dir.mkdir(parents=True)
    original.dump(args.output_dir/"input_provenance.json", inputs)
    original.dump(args.output_dir/"summary.json", summary)
    for name, rows in [("background_motion", flow_rows), ("background_tracks", tracks),
                       ("pose_metrics", pose_rows), ("holdout_metrics", metrics),
                       ("group_metrics", group_metrics)]:
        original.table(args.output_dir/f"{name}.csv", rows)
    print(summary["status"])
    for r in group_metrics:
        if r["hypothesis"] == original.HYPOTHESES[2] and r["solution_index"] == 0:
            print(r)


if __name__ == "__main__":
    main()
