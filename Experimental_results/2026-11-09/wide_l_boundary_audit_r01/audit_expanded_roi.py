"""小ROIで端が切れる問題を、同じ元画像の大きい探索ROIで分離する。

既存の凸角の物理IDは再選択しない。その点を含む連結成分だけを追う。
ROI・辺長条件は全て保持し、距離の真値に近い条件を採用しない。
"""
import argparse
import csv
import importlib.util
import itertools
import json
from pathlib import Path

import cv2
import numpy as np

SPEC = importlib.util.spec_from_file_location("l_boundary_base", Path(__file__).with_name("analyze.py"))
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
original = base.original


def expanded_contour(gray, seed, threshold, half_size):
    base.native_gray(gray)
    if half_size not in ((24, 16), (32, 20)):
        raise ValueError("predeclared expanded ROI required")
    # Locate the same original convex proposal; no new physical-point selection.
    _, selected, _ = base.contour_and_corner(gray, seed, threshold)
    if selected is None:
        return None, None, "original_convex_corner_unavailable"
    x, y = np.rint(seed).astype(int)
    w, h = half_size
    if x-w < 0 or y-h < 0 or x+w >= 640 or y+h >= 720:
        return None, selected, "expanded_roi_outside_front_lens"
    mask = (gray[y-h:y+h+1, x-w:x+w+1] < threshold).astype(np.uint8)
    _, labels = cv2.connectedComponents(mask, connectivity=8)
    px, py = int(selected["x"])-x+w, int(selected["y"])-y+h
    label = int(labels[py, px])
    if label == 0:
        return None, selected, "old_corner_not_in_dark_component"
    component = (labels == label).astype(np.uint8)
    if component[0].any() or component[-1].any() or component[:, 0].any() or component[:, -1].any():
        return None, selected, "component_reaches_expanded_roi_edge"
    contours = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    if len(contours) != 1 or cv2.contourArea(contours[0]) < 2:
        return None, selected, "ambiguous_or_degenerate_component"
    contour = contours[0][:, 0].astype(float) + [x-w, y-h]
    return contour, selected, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/home/robo25/Downloads"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    folder = Path(__file__).parent
    manifest = folder / "results_r01/input_provenance.json"
    inputs = json.loads(manifest.read_text())
    for name, sha in inputs.items():
        if base.digest(name) != sha:
            raise ValueError("fixed source/input changed: " + name)
    inputs.update({str(p): base.digest(p) for p in (Path(__file__), manifest,
        folder / "results_r01/point_coordinates.csv", folder / "results_r01/pose_evaluation.csv")})
    camera = base.load_config()[1]
    points, records, pose_rows, withheld = {}, [], [], []
    seed_stress = []
    for group, frames, E_seed, target in original.GROUPS:
        for frame in frames:
            path = args.image_dir / f"decoded_{original.SESSION}_f{frame:06d}.png"
            sha = base.digest(path)
            inputs[str(path)] = sha
            gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            base.native_gray(gray)
            before = gray.copy()
            seeds = dict(original.FIXED)
            if E_seed is not None:
                seeds["E"] = E_seed
            for label, threshold, roi in itertools.product(seeds, (90, 100, 110, 120), ((24, 16), (32, 20))):
                contour, selected, reason = expanded_contour(gray, seeds[label], threshold, roi)
                for length, refine in itertools.product((4, 5), (False, True)):
                    method = f"{'isocross' if refine else 'raster'}_rayplane_arc{length}_roi{roi[0]}x{roi[1]}"
                    result = (dict(available=False, reason=reason, **base.FLAGS) if reason else
                              base.edge_corner(gray, contour, selected, length, refine, threshold, camera))
                    records.append(dict(frame=frame, group=group, label=label, threshold=threshold,
                                        method=method, **result))
                    points.setdefault((frame, threshold, method), {})[label] = result.get("point") if result["available"] else None
                # Seed stability control, not distance-based refinement selection.
                if threshold == 110 and roi == (24, 16) and selected:
                    for window, delta in itertools.product((2, 3), ([0., 0.], [.5, 0.], [-.5, 0.], [0., .5], [0., -.5])):
                        shifted = dict(selected, x=selected["x"]+delta[0], y=selected["y"]+delta[1])
                        result = base.local_subpixel(gray, shifted, window)
                        seed_stress.append(dict(frame=frame, label=label, window=window,
                                                seed_offset=delta, **result))
            if not np.array_equal(gray, before) or base.digest(path) != sha:
                raise ValueError("source image was modified")
            print(f"expanded read-only frame {frame:06d}", flush=True)
    for (frame, threshold, method), observed in points.items():
        if "E" not in observed:
            continue
        missing = [k for k in list(original.FIXED)+["E"] if observed.get(k) is None]
        if missing:
            withheld.append(dict(frame=frame, threshold=threshold, method=method, missing=missing))
            continue
        group, target = next((g, t) for g, frames, _, t in original.GROUPS if frame in frames)
        fixed = np.array([observed[k] for k in original.FIXED])
        for h in original.HYPOTHESES:
            for c in original.fit_fixed(fixed, h, camera)["candidates"]:
                pose_rows.append(dict(frame=frame, group=group, threshold=threshold, method=method, hypothesis=h,
                    solution_index=c["solution_index"], height_m=c["camera_height_above_floor_m"],
                    native_rmse_px=c["fit_native_rmse_px"],
                    **original.evaluate_E(observed["E"], target, c, h, camera), selected=False))
    with (folder / "results_r01/pose_evaluation.csv").open() as stream:
        old_poses = list(csv.DictReader(stream))
    all_poses = old_poses + pose_rows
    def number(v):
        return None if v in (None, "") else float(v)
    metrics = []
    for group, _, _, _ in original.GROUPS[1:]:
        for method in sorted({r["method"] for r in all_poses} | {r["method"] for r in records}):
            for h, branch in itertools.product(original.HYPOTHESES, (0, 1)):
                rows = [r for r in all_poses if r["group"] == group and r["method"] == method
                        and r["hypothesis"] == h and int(r["solution_index"]) == branch]
                valid = [r for r in rows if r["available"] in (True, "True")]
                zs = [number(r["predicted_Z_m"]) for r in valid]
                metrics.append(dict(group=group, method=method, hypothesis=h, solution_index=branch,
                    available_evaluations=len(valid), expected_evaluations=8,
                    min_Z_m=min(zs) if zs else None, max_Z_m=max(zs) if zs else None,
                    max_planar_error_m=max(number(r["planar_error_m"]) for r in valid) if valid else None,
                    median_Z_at_threshold110=None if not (central := [number(r["predicted_Z_m"]) for r in valid if int(r["threshold"]) == 110]) else float(np.median(central)),
                    selected=False, physical_metric_verified=False, usable_for_ffb=False))
    seed_summary = []
    for frame, label, window in sorted({(r["frame"], r["label"], r["window"]) for r in seed_stress}):
        rows = [r for r in seed_stress if (r["frame"], r["label"], r["window"]) == (frame, label, window)]
        valid = [r for r in rows if r["available"]]
        p = np.array([r["point"] for r in valid])
        seed_summary.append(dict(frame=frame, label=label, window=window, available=len(valid), total=len(rows),
            x_span_px=float(np.ptp(p[:, 0])) if len(p) else None,
            y_span_px=float(np.ptp(p[:, 1])) if len(p) else None,
            maximum_pair_distance_px=float(np.linalg.norm(p[:, None]-p[None, :], axis=2).max()) if len(p) else None,
            physical_outer_corner_identity_verified=False))
    coverage = []
    for method in sorted({r["method"] for r in records}):
        rows = [r for r in records if r["method"] == method]
        coverage.append(dict(method=method, available=sum(r["available"] for r in rows), total=len(rows),
            complete_E_frames_at_threshold110=sum(all(v is not None for v in p.values()) and "E" in p
                for (f, t, m), p in points.items() if t == 110 and m == method),
            reasons={reason: sum(r["reason"] == reason for r in rows if not r["available"])
                for reason in sorted({r["reason"] for r in rows if not r["available"]})}))
    summary = dict(status="EXPANDED_ROI_DIAGNOSTIC_ONLY_NOT_DISTANCE_SELECTED", observations=len(records),
        pose_rows=len(pose_rows), coverage=coverage, withheld_frame_methods=len(withheld),
        seed_stress_cases=len(seed_stress), seed_stress_max_pair_distance_px=max(
            r["maximum_pair_distance_px"] for r in seed_summary if r["maximum_pair_distance_px"] is not None),
        selected_method=None, E_targets_used_to_choose_parameters=False, old_point_identity_reselected=False,
        camera_images_edited_or_exported=False, runtime_changed=False, **base.FLAGS)
    args.output_dir.mkdir(parents=True)
    original.dump(args.output_dir / "input_provenance.json", inputs)
    original.dump(args.output_dir / "summary.json", summary)
    original.dump(args.output_dir / "boundary_observations.json", records)
    original.dump(args.output_dir / "seed_stress.json", seed_stress)
    original.dump(args.output_dir / "withheld_methods.json", withheld)
    original.table(args.output_dir / "pose_evaluation.csv", pose_rows)
    original.table(args.output_dir / "comparison_metrics.csv", metrics)
    original.table(args.output_dir / "seed_stress_summary.csv", seed_summary)
    print(json.dumps(summary, indent=2))
    for r in metrics:
        if r["group"] == "P2" and r["hypothesis"] == original.HYPOTHESES[2] and r["solution_index"] == 0:
            print(r)


if __name__ == "__main__":
    main()
