"""L字保留の局所原因：色付き連結と最初の輪郭stepへの依存を分離する。

既存外角・灰度経路・数値検査を維持した対照と比較する。色差は連結の補助だけ。
閾値・方向推定は全条件を保持し、距離の真値で採用しない。画像出力/runtimeなし。
"""
import argparse
import csv
import importlib.util
import itertools
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / "Experimental_results/2026-11-09/wide_l_boundary_audit_r01"
SPEC = importlib.util.spec_from_file_location("local_support_expanded", PRIOR / "audit_expanded_roi.py")
expanded = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(expanded)
base, original = expanded.base, expanded.original
CHROMA_LIMITS = (None, 60, 80, 100)


def selected_component(bgr, gray, seed, threshold, chroma_limit):
    """色を理由に別の点へ移らない。元の凸頂点が消えれば保留。"""
    base.native_gray(gray)
    if bgr.shape != (720, 1280, 3) or bgr.dtype != np.uint8 or chroma_limit not in CHROMA_LIMITS:
        raise ValueError("native BGR8 and predeclared absolute chroma limit required")
    _, selected, _ = base.contour_and_corner(gray, seed, threshold)
    if selected is None:
        return None, None, {}, "old_convex_corner_unavailable"
    x, y = np.rint(seed).astype(int)
    w, h = 24, 16
    if x-w < 0 or y-h < 0 or x+w >= 640 or y+h >= 720:
        raise ValueError("local support must remain inside native front lens")
    roi = bgr[y-h:y+h+1, x-w:x+w+1]
    # Convert before subtracting: no uint8 wraparound, no saturation/hue claim.
    chroma = roi.max(axis=2).astype(int)-roi.min(axis=2).astype(int)
    mask = gray[y-h:y+h+1, x-w:x+w+1] < threshold
    _, gray_labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    px, py = int(selected["x"])-x+w, int(selected["y"])-y+h
    component = gray_labels == gray_labels[py, px]
    evidence = dict(grayscale_component_area=int(component.sum()),
        grayscale_component_chroma_median=float(np.median(chroma[component])),
        grayscale_component_chroma_max=int(chroma[component].max()),
        original_corner_chroma=int(chroma[py, px]),
        grayscale_component_touches_border=bool(component[0].any() or component[-1].any() or
            component[:, 0].any() or component[:, -1].any()))
    if chroma_limit is not None:
        mask = mask & (chroma <= chroma_limit)
    if not mask[py, px]:
        return None, selected, evidence, "chroma_filter_removed_original_corner"
    _, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    component = (labels == labels[py, px]).astype(np.uint8)
    evidence["filtered_component_area"] = int(component.sum())
    if component[0].any() or component[-1].any() or component[:, 0].any() or component[:, -1].any():
        return None, selected, evidence, "component_reaches_roi_edge"
    contours = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    if len(contours) != 1 or cv2.contourArea(contours[0]) < 2:
        return None, selected, evidence, "ambiguous_or_degenerate_component"
    contour = contours[0][:, 0].astype(float)+[x-w, y-h]
    # Keep the exact original point, never nearest replacement after filtering.
    if not np.any(np.linalg.norm(contour-[selected["x"], selected["y"]], axis=1) < 1e-8):
        return None, selected, evidence, "original_corner_no_longer_on_contour"
    return contour, selected, evidence, None


def principal_arm_samples(contour, corner, step, length):
    """最初の1stepでなく支持点全体の主軸を使う。点数・範囲・逆走検査は残す。"""
    c, q = np.asarray(contour, float), np.asarray(corner, float)
    if c.ndim != 2 or c.shape[1] != 2 or q.shape != (2,) or step not in (-1, 1) or length not in (4, 5):
        raise ValueError("finite contour, one corner and declared traversal required")
    if not np.isfinite(c).all() or not np.isfinite(q).all():
        raise ValueError("finite contour required")
    indices = np.flatnonzero(np.linalg.norm(c-q, axis=1) < 1e-8)
    if len(indices) != 1:
        return None, "nonunique_contour_corner"
    index, arc, last, samples = int(indices[0]), 0., q, []
    for k in range(1, len(c)//2):
        point = c[(index+step*k) % len(c)]
        arc += float(np.linalg.norm(point-last))
        last = point
        if arc > length+.01:
            break
        if arc >= 1.:
            samples.append(point)
    if len(samples) < base.SCREENS["min_arm_samples"]:
        return None, "insufficient_distinct_arm_samples"
    samples = np.asarray(samples)
    if len(np.unique(samples, axis=0)) != len(samples):
        return None, "repeated_arm_samples"
    if np.linalg.norm(samples[-1]-samples[0]) < base.SCREENS["min_arm_span_px"]:
        return None, "insufficient_arm_span"
    _, _, vt = np.linalg.svd(samples-samples.mean(axis=0))
    direction = vt[0]
    if direction @ (samples.mean(axis=0)-q) < 0:
        direction = -direction
    projected = (samples-q) @ direction
    if projected[0] <= 0 or np.any(np.diff(projected) < -.25):
        return None, "backtracking_principal_arm_support"
    return samples, None


def edge_intersection(gray, contour, selected, length, arm_method, threshold, camera):
    if arm_method not in ("first_step_control", "principal_axis"):
        raise ValueError("explicit arm method required")
    sampler = base.arm_samples if arm_method == "first_step_control" else principal_arm_samples
    q = np.array([selected["x"], selected["y"]])
    area = base.corners.signed_area(contour)
    if abs(area) < 1e-8:
        return dict(available=False, reason="zero_contour_area", **base.FLAGS)
    planes, support = [], []
    for step in (-1, 1):
        samples, reason = sampler(contour, q, step, length)
        if samples is None:
            return dict(available=False, reason=reason, support=support, **base.FLAGS)
        line = cv2.fitLine(samples.astype(np.float32), cv2.DIST_L2, 0, .001, .001).reshape(-1)
        tangent = line[:2].astype(float)
        if tangent @ (samples[-1]-samples[0]) < 0:
            tangent = -tangent
        outward = np.array([(tangent*step)[1], -(tangent*step)[0]])*np.sign(area)
        refined, crossings, reason = base.threshold_crossings(gray, samples, outward, threshold)
        if refined is None:
            return dict(available=False, reason=reason, support=support, **base.FLAGS)
        try:
            normal, rms = base.ray_plane(refined, camera)
        except ValueError as error:
            return dict(available=False, reason=str(error), support=support, **base.FLAGS)
        support.append(dict(step=step, count=len(samples), raw_samples_native_xy=samples.tolist(),
            refined_samples_native_xy=refined.tolist(), rms_px=rms, crossings=crossings))
        if rms > base.SCREENS["max_line_rms_px"]:
            return dict(available=False, reason="edge_not_straight_enough", support=support, **base.FLAGS)
        planes.append(normal)
    point, sine, reason = base.intersect_planes(*planes, q, camera)
    return dict(available=point is not None, reason=reason or "unverified_local_support_intersection",
        point=None if point is None else point.tolist(), intersection_sine=sine,
        shift_px=None if point is None else float(np.linalg.norm(point-q)), support=support, **base.FLAGS)


def evaluate_proposals(proposals, camera):
    """Eの抽出後にのみ呼ぶ。姿勢fitには同じ画像の固定4点だけを渡す。"""
    evaluations, withheld = [], []
    for (frame, threshold, chroma, arm, length), observed in proposals.items():
        if "E" not in observed:
            continue
        identity = dict(frame=frame, threshold=threshold, chroma_limit=chroma, arm_method=arm, arc_px=length)
        missing = [k for k in list(original.FIXED)+["E"] if observed.get(k) is None]
        if missing:
            withheld.append(dict(identity, missing=missing))
            continue
        group, target = next((g, t) for g, frames, _, t in original.GROUPS if frame in frames)
        fixed = np.array([observed[k] for k in original.FIXED])
        for h in original.HYPOTHESES:
            for candidate in original.fit_fixed(fixed, h, camera)["candidates"]:
                evaluations.append(dict(identity, group=group, hypothesis=h,
                    solution_index=candidate["solution_index"], height_m=candidate["camera_height_above_floor_m"],
                    native_rmse_px=candidate["fit_native_rmse_px"],
                    **original.evaluate_E(observed["E"], target, candidate, h, camera), selected=False))
    return evaluations, withheld


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/home/robo25/Downloads"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    manifest = PRIOR/"expanded_roi_r01/input_provenance.json"
    inputs = json.loads(manifest.read_text())
    for name, sha in inputs.items():
        if base.digest(name) != sha:
            raise ValueError("fixed prior source/input changed: " + name)
    old_path = PRIOR/"expanded_roi_r01/boundary_observations.json"
    old_rows = json.loads(old_path.read_text())
    inputs.update({str(p): base.digest(p) for p in (Path(__file__), manifest, old_path)})
    camera = base.load_config()[1]
    observations, proposals, components, grayscale_checks, control_checks = [], {}, [], [], []
    for group, frames, E_seed, target in original.GROUPS:
        for frame in frames:
            path = args.image_dir/f"decoded_{original.SESSION}_f{frame:06d}.png"
            sha = base.digest(path)
            inputs[str(path)] = sha
            bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
            gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)  # Preserve historical route exactly.
            base.native_gray(gray)
            bgr_before, gray_before = bgr.copy(), gray.copy()
            alternate = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            delta = gray.astype(int)-alternate.astype(int)
            grayscale_checks.append(dict(frame=frame, canonical_route="imread_IMREAD_GRAYSCALE",
                comparison_route="cvtColor_BGR2GRAY", differing_pixels=int(np.count_nonzero(delta)),
                difference_min=int(delta.min()), difference_max=int(delta.max()),
                floor_region_difference_pixels=int(np.count_nonzero(delta[360:430, 230:410])),
                comparison_route_used_for_fitting=False))
            seeds = dict(original.FIXED)
            if E_seed is not None:
                seeds["E"] = E_seed
            for label, threshold, chroma in itertools.product(seeds, (90, 100, 110, 120), CHROMA_LIMITS):
                contour, selected, evidence, reason = selected_component(bgr, gray, seeds[label], threshold, chroma)
                components.append(dict(frame=frame, label=label, threshold=threshold, chroma_limit=chroma,
                    reason=reason or "local_component_available", **evidence))
                for arm, length in itertools.product(("first_step_control", "principal_axis"), (4, 5)):
                    result = (dict(available=False, reason=reason, **base.FLAGS) if reason else
                              edge_intersection(gray, contour, selected, length, arm, threshold, camera))
                    row = dict(frame=frame, group=group, label=label, threshold=threshold,
                        chroma_limit=chroma, arm_method=arm, arc_px=length, **result)
                    observations.append(row)
                    proposals.setdefault((frame, threshold, chroma, arm, length), {})[label] = result.get("point") if result["available"] else None
                    if chroma is None and arm == "first_step_control":
                        old = next(r for r in old_rows if r["frame"] == frame and r["label"] == label
                            and r["threshold"] == threshold and r["method"] == f"isocross_rayplane_arc{length}_roi24x16")
                        equal = result["available"] == old["available"]
                        if result["available"] and old["available"]:
                            equal = equal and np.allclose(result["point"], old["point"], rtol=0, atol=1e-9)
                        control_checks.append(dict(frame=frame, label=label, threshold=threshold,
                            arc_px=length, availability_and_coordinates_reproduced=bool(equal)))
            if not np.array_equal(gray, gray_before) or not np.array_equal(bgr, bgr_before) or base.digest(path) != sha:
                raise ValueError("source image changed")
            print(f"local support frame {frame:06d}", flush=True)
    if not all(r["availability_and_coordinates_reproduced"] for r in control_checks):
        raise ValueError("historical control did not reproduce; do not compare mixed grayscale routes")
    evaluations, withheld = evaluate_proposals(proposals, camera)
    coverage = []
    for chroma, arm, length in itertools.product(CHROMA_LIMITS, ("first_step_control", "principal_axis"), (4, 5)):
        rows = [r for r in observations if (r["chroma_limit"], r["arm_method"], r["arc_px"]) == (chroma, arm, length)]
        coverage.append(dict(chroma_limit=chroma, arm_method=arm, arc_px=length,
            available=sum(r["available"] for r in rows), total=len(rows),
            complete_later_frames_at_threshold110=sum("E" in p and all(v is not None for v in p.values())
                for (f, t, c, a, length_key), p in proposals.items() if (t, c, a, length_key) == (110, chroma, arm, length)),
            reasons={reason: sum(r["reason"] == reason for r in rows if not r["available"])
                for reason in sorted({r["reason"] for r in rows if not r["available"]})}))
    metrics = []
    for group, _, _, _ in original.GROUPS[1:]:
        for chroma, arm, length, h, branch in itertools.product(CHROMA_LIMITS,
                ("first_step_control", "principal_axis"), (4, 5), original.HYPOTHESES, (0, 1)):
            rows = [r for r in evaluations if (r["group"], r["chroma_limit"], r["arm_method"], r["arc_px"],
                r["hypothesis"], r["solution_index"]) == (group, chroma, arm, length, h, branch)]
            valid = [r for r in rows if r["available"]]
            central = [r for r in valid if r["threshold"] == 110]
            metrics.append(dict(group=group, chroma_limit=chroma, arm_method=arm, arc_px=length,
                hypothesis=h, solution_index=branch, available=len(valid), expected=8,
                min_Z_m=min(r["predicted_Z_m"] for r in valid) if valid else None,
                max_Z_m=max(r["predicted_Z_m"] for r in valid) if valid else None,
                median_Z_at_threshold110=float(np.median([r["predicted_Z_m"] for r in central])) if central else None,
                max_planar_error_m=max(r["planar_error_m"] for r in valid) if valid else None,
                selected=False, physical_metric_verified=False, usable_for_ffb=False))
    summary = dict(status="LOCAL_EXTRACTION_CAUSES_SEPARATED_NOT_PHYSICAL_ADOPTION", observations=len(observations),
        historical_controls=len(control_checks), historical_controls_reproduced=sum(
            r["availability_and_coordinates_reproduced"] for r in control_checks),
        coverage=coverage, pose_rows=len(evaluations), withheld_frame_methods=len(withheld),
        selected_chroma_limit=None, selected_arm_method=None, selected_hypothesis=None,
        selected_solution=None, E_used_for_extraction=False, E_target_used_for_parameter_selection=False,
        grayscale_route_changed=False, mask_used_to_fake_grayscale_crossings=False,
        original_corner_relocated_after_color_filter=False, runtime_changed=False,
        camera_images_edited_or_exported=False, **base.FLAGS)
    args.output_dir.mkdir(parents=True)
    original.dump(args.output_dir/"input_provenance.json", inputs)
    original.dump(args.output_dir/"summary.json", summary)
    original.dump(args.output_dir/"observations.json", observations)
    original.dump(args.output_dir/"withheld_methods.json", withheld)
    original.table(args.output_dir/"components.csv", components)
    original.table(args.output_dir/"grayscale_route_audit.csv", grayscale_checks)
    original.table(args.output_dir/"historical_controls.csv", control_checks)
    original.table(args.output_dir/"pose_evaluation.csv", evaluations)
    original.table(args.output_dir/"group_metrics.csv", metrics)
    print(json.dumps(summary, indent=2))
    for r in metrics:
        if r["group"] == "P2" and r["hypothesis"] == original.HYPOTHESES[2] and r["solution_index"] == 0 and r["arm_method"] == "principal_axis":
            print(r)


if __name__ == "__main__":
    main()
