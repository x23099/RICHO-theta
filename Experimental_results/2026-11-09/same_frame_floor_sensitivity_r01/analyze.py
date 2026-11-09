"""同一画像の床4点の画素摂動と、未反転の全点対応を分離する診断。

Eは姿勢fit・IPPE解の追跡に使わない。画素範囲は仮定した対照条件であり、
実測ノイズ分布や連続領域の保証上限ではない。元画像・runtimeを変更しない。
"""
import argparse
import csv
import importlib.util
import itertools
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
PRIOR = ROOT / "Experimental_results/2026-11-09/wide_floor_geometry_r01"
SPEC = importlib.util.spec_from_file_location("sensitivity_previous", PRIOR / "audit_same_frame_pose.py")
previous = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(previous)
original = previous.original
from angular_fisheye_geometry import floor_from_rays, unproject
from cone_distance_core import digest, load_config
from fisheye_floor_geometry import checked_transform
from floor_reference_pose import planar_floor_pose_candidates

FLAGS = dict(selected=False, physical_metric_verified=False, usable_for_ffb=False)
BRANCH_TRANSLATION_SCALE_M = .8  # 固定4点の辺長。E誤差・高さ申告で調整しない。


def fixed_variants():
    """8座標を個別に動かす32件と、全端点組合せ512件。基準1件も保持。"""
    yield "baseline", 0., "zero", np.zeros((4, 2))
    for amplitude in (.5, 1.):
        for axis, sign in itertools.product(range(8), (-1, 1)):
            delta = np.zeros((4, 2))
            delta.flat[axis] = sign * amplitude
            yield "single_coordinate", amplitude, f"{axis}:{sign:+d}", delta
        for signs in itertools.product((-1, 1), repeat=8):
            yield "all_corner_box_vertices", amplitude, "".join("+" if s > 0 else "-" for s in signs), \
                np.array(signs, float).reshape(4, 2) * amplitude


def branch_matches(reference, candidates):
    """姿勢だけで2解の対応を追う。解は削除・採用せずEも受け取らない。"""
    if len(reference) != 2 or len(candidates) != 2:
        return [None] * len(candidates), None
    cost = np.empty((2, 2))
    for i, base in enumerate(reference):
        a = checked_transform(base["transform_floor_from_optical"])
        for j, candidate in enumerate(candidates):
            b = checked_transform(candidate["transform_floor_from_optical"])
            angle = np.arccos(np.clip((np.trace(a[:3, :3] @ b[:3, :3].T)-1)/2, -1, 1))
            cost[i, j] = float(angle + np.linalg.norm(a[:3, 3]-b[:3, 3]) / BRANCH_TRANSLATION_SCALE_M)
    direct, swapped = cost[0, 0]+cost[1, 1], cost[0, 1]+cost[1, 0]
    margin = float(abs(direct-swapped))
    if margin < 1e-8:
        return [None, None], margin
    return ([0, 1] if direct < swapped else [1, 0]), margin


def evaluation_pixels(e_pixel, amplitude):
    p = np.asarray(e_pixel, float)
    if p.shape != (2,) or not np.isfinite(p).all() or amplitude < 0:
        raise ValueError("one finite E point and nonnegative amplitude required")
    offsets = [[0., 0.]]
    if amplitude:
        offsets.extend(np.array(signs, float) * amplitude for signs in itertools.product((-1, 1), repeat=2))
    return p + np.array(offsets)


def predict_e_pixels(pixels, candidate, hypothesis, camera):
    """評価点の座標だけを予測。目標距離は受け取らない。"""
    if not candidate["geometry_consistent"]:
        return [None] * len(pixels)
    rays, valid = unproject(original.hypothesis_pixels(pixels, hypothesis, camera),
                            camera, image_size=(1280, 720))
    points, accepted = floor_from_rays(rays, valid, candidate["transform_floor_from_optical"])
    return [[-float(p[1]), float(p[0])] if ok else None for p, ok in zip(points, accepted)]


def candidate_row(frame, group, hypothesis, case, amplitude, variant_id,
                  candidate, branch, margin, predicted, baseline, target):
    valid = np.array([p for p in predicted if p is not None], float)
    center = predicted[0]
    target = np.asarray(target, float)
    return dict(frame=frame, group=group, hypothesis=hypothesis, case=case, amplitude_px=amplitude,
        variant_id=variant_id, solver_solution_index=candidate["solution_index"],
        matched_reference_branch=branch, branch_match_margin=margin,
        height_m=candidate["camera_height_above_floor_m"], native_rmse_px=candidate["fit_native_rmse_px"],
        geometry_consistent=candidate["geometry_consistent"], E_evaluations=len(predicted),
        E_available=len(valid), predicted_X_m=None if center is None else center[0],
        predicted_Z_m=None if center is None else center[1],
        center_planar_error_m=None if center is None else float(np.linalg.norm(np.array(center)-target)),
        E_box_min_X_m=None if not len(valid) else float(min(valid[:, 0])),
        E_box_max_X_m=None if not len(valid) else float(max(valid[:, 0])),
        E_box_min_Z_m=None if not len(valid) else float(min(valid[:, 1])),
        E_box_max_Z_m=None if not len(valid) else float(max(valid[:, 1])),
        E_box_max_planar_error_m=None if not len(valid) else float(max(np.linalg.norm(valid-target, axis=1))),
        max_change_from_unperturbed_m=None if not len(valid) or baseline is None else
            float(max(np.linalg.norm(valid-np.asarray(baseline), axis=1))), **FLAGS)


def read_observations(path):
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    points = {}
    for r in rows:
        if int(r["threshold"]) == 110 and r["convex_available"] == "True":
            points.setdefault(int(r["frame"]), {})[r["point"]] = np.array(
                [float(r["convex_x"]), float(r["convex_y"])])
    for _, frames, _, _ in original.GROUPS[1:]:
        for frame in frames:
            if set(points.get(frame, {})) != set(original.FIXED) | {"E"}:
                raise ValueError("same-frame four fixed points plus E required")
    return points


def raw_assignment_rows(points, camera):
    """各画像で生光線の全24点対応・両解。対応を採用する関数ではない。"""
    rows = []
    world = original.vehicle_world(original.HYPOTHESES[0])
    for permutation in itertools.permutations(range(4)):
        for group, frames, _, target in original.GROUPS[1:]:
            for frame in frames:
                fixed = np.array([points[frame][k] for k in original.FIXED])
                fit = planar_floor_pose_candidates(fixed, world[list(permutation)], camera)
                for candidate in fit["candidates"]:
                    result = original.evaluate_E(points[frame]["E"], target, candidate,
                                                  original.HYPOTHESES[0], camera)
                    rows.append(dict(permutation="-".join(map(str, permutation)), frame=frame, group=group,
                        solution_index=candidate["solution_index"],
                        height_m=candidate["camera_height_above_floor_m"],
                        native_rmse_px=candidate["fit_native_rmse_px"],
                        mapping_adopted=False, E_used_for_diagnostic_only=True, **result))
    return rows


def permissive_assignment_summary(rows):
    """診断の下限：Eに最も近い解さえ画像ごとに許した場合。選択・承認には使わない。"""
    output = []
    frames = sorted({r["frame"] for r in rows})
    for mapping in sorted({r["permutation"] for r in rows}):
        for rms_limit in (None, 2.):
            best_each_frame = []
            for frame in frames:
                valid = [r for r in rows if r["permutation"] == mapping and r["frame"] == frame
                         and r["available"] and (rms_limit is None or
                         r["native_rmse_px"] is not None and r["native_rmse_px"] < rms_limit)]
                if valid:
                    best_each_frame.append(min(r["planar_error_m"] for r in valid))
            complete = len(best_each_frame) == len(frames)
            output.append(dict(permutation=mapping, native_rmse_limit_px=rms_limit,
                evaluated_frames=len(best_each_frame), total_frames=len(frames),
                best_possible_maximum_error_m=max(best_each_frame) if complete else None,
                E_used_to_choose_per_frame_solution_FOR_DIAGNOSTIC_ONLY=True,
                assignment_or_solution_adopted=False))
    return output


def grouped_metrics(rows):
    output = []
    keys = sorted({(r["group"], r["hypothesis"], r["case"], r["amplitude_px"],
                    r["matched_reference_branch"]) for r in rows if r["matched_reference_branch"] is not None})
    for group, h, case, amp, branch in keys:
        subset = [r for r in rows if (r["group"], r["hypothesis"], r["case"], r["amplitude_px"],
                  r["matched_reference_branch"]) == (group, h, case, amp, branch)]
        valid = [r for r in subset if r["E_available"] == r["E_evaluations"]]
        output.append(dict(group=group, hypothesis=h, case=case, amplitude_px=amp, branch=branch,
            pose_cases=len(subset), all_E_available_cases=len(valid),
            height_min_m=min(r["height_m"] for r in subset), height_max_m=max(r["height_m"] for r in subset),
            min_Z_m=None if not valid else min(r["E_box_min_Z_m"] for r in valid),
            max_Z_m=None if not valid else max(r["E_box_max_Z_m"] for r in valid),
            max_change_from_unperturbed_m=None if not valid else max(r["max_change_from_unperturbed_m"] for r in valid),
            max_error_to_declared_target_m=None if not valid else max(r["E_box_max_planar_error_m"] for r in valid),
            **FLAGS))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    inputs = {}
    manifests = [PRIOR / f"{folder}/input_provenance.json" for folder in (
        "results_r01", "corner_identity_r01", "same_frame_pose_r01")]
    for manifest in manifests:
        inputs.update(json.loads(manifest.read_text()))
        inputs[str(manifest)] = digest(manifest)
    for name, expected in inputs.items():
        if digest(name) != expected:
            raise ValueError("prior source/input changed: " + name)
    points_file = PRIOR / "corner_identity_r01/corner_identity_comparison.csv"
    inputs.update({str(p): digest(p) for p in (Path(__file__), points_file)})
    camera = load_config()[1]
    points = read_observations(points_file)
    rows, failures = [], []
    for group, frames, _, target in original.GROUPS[1:]:
        for frame in frames:
            fixed = np.array([points[frame][k] for k in original.FIXED])
            for h in original.HYPOTHESES:
                reference = original.fit_fixed(fixed, h, camera)["candidates"]
                reference_e = [predict_e_pixels([points[frame]["E"]], c, h, camera)[0] for c in reference]
                for case, amp, variant_id, delta in fixed_variants():
                    # 全座標の同時摂動は既に診断用としたH2のみ。採用を意味しない。
                    if case == "all_corner_box_vertices" and h != original.HYPOTHESES[2]:
                        continue
                    try:
                        candidates = original.fit_fixed(fixed+delta, h, camera)["candidates"]
                    except ValueError as error:
                        failures.append(dict(frame=frame, hypothesis=h, case=case, amplitude_px=amp,
                                             variant_id=variant_id, reason=str(error)))
                        continue
                    if len(candidates) != 2:
                        failures.append(dict(frame=frame, hypothesis=h, case=case, amplitude_px=amp,
                            variant_id=variant_id, reason="solution_count_not_two", solution_count=len(candidates)))
                    matches, margin = branch_matches(reference, candidates)
                    for c, branch in zip(candidates, matches):
                        predicted = predict_e_pixels(evaluation_pixels(points[frame]["E"], amp), c, h, camera)
                        rows.append(candidate_row(frame, group, h, case, amp, variant_id, c, branch, margin,
                            predicted, None if branch is None else reference_e[branch], target))
                # Eだけを動かす。床姿勢は同じ基準候補のまま。
                for amp in (.5, 1.):
                    for branch, c in enumerate(reference):
                        predicted = predict_e_pixels(evaluation_pixels(points[frame]["E"], amp), c, h, camera)
                        rows.append(candidate_row(frame, group, h, "E_only", amp, "Ebox", c, branch, None,
                                                  predicted, reference_e[branch], target))
            print(f"processed frame {frame:06d}", flush=True)
    assignments = raw_assignment_rows(points, camera)
    assignment_metrics = permissive_assignment_summary(assignments)
    metrics = grouped_metrics(rows)
    native_lower_bounds = [r["best_possible_maximum_error_m"] for r in assignment_metrics
        if r["native_rmse_limit_px"] is None and r["best_possible_maximum_error_m"] is not None]
    native_screened = [r["best_possible_maximum_error_m"] for r in assignment_metrics
        if r["native_rmse_limit_px"] == 2. and r["best_possible_maximum_error_m"] is not None]
    summary = dict(status="SAME_FRAME_PIXEL_SENSITIVITY_CONDITIONAL_PHYSICAL_MAPPING_WITHHELD",
        frames=8, threshold=110, pose_evaluation_rows=len(rows), raw_assignment_rows=len(assignments),
        branch_match_ambiguous_rows=sum(r["matched_reference_branch"] is None for r in rows),
        solver_index_differs_from_matched_branch_rows=sum(r["matched_reference_branch"] is not None and
            r["solver_solution_index"] != r["matched_reference_branch"] for r in rows),
        incomplete_variants=failures,
        minimum_possible_worst_E_error_raw_assignments_m=min(native_lower_bounds) if native_lower_bounds else None,
        minimum_possible_worst_E_error_raw_assignments_rms_below_2px_m=min(native_screened) if native_screened else None,
        E_used_for_pose_fit=False, E_used_for_branch_matching=False,
        point_order_search_used_E_for_diagnostic_not_adoption=True,
        pixel_amplitudes_are_measured_uncertainties=False, continuous_box_upper_bound_certified=False,
        confidence_interval=False, selected_hypothesis=None, selected_solution=None, selected_assignment=None,
        intrinsics_refitted=False, height_fitted_to_reported_590mm=False,
        mirror_verified=False, physical_corner_identity_verified=False,
        runtime_changed=False, camera_images_edited_or_exported=False, published_to_ros=False, **FLAGS,
        metrics=metrics)
    args.output_dir.mkdir(parents=True)
    original.dump(args.output_dir / "input_provenance.json", inputs)
    original.dump(args.output_dir / "summary.json", summary)
    original.table(args.output_dir / "pixel_stress.csv", rows)
    original.table(args.output_dir / "group_metrics.csv", metrics)
    original.table(args.output_dir / "all_raw_assignments.csv", assignments)
    original.table(args.output_dir / "raw_assignment_diagnostic.csv", assignment_metrics)
    print(summary["status"], "rows", len(rows), "incomplete", len(failures))
    print("best raw assignment worst error:", summary["minimum_possible_worst_E_error_raw_assignments_m"])
    for r in metrics:
        if r["hypothesis"] == original.HYPOTHESES[2] and r["branch"] == 0 and (
            r["case"] == "baseline" or r["amplitude_px"] == 1. and r["case"] != "single_coordinate"):
            print(r)


if __name__ == "__main__":
    main()
