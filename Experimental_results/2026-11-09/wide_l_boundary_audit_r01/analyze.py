"""L字の外角候補を、元輪郭・辺の光線平面・局所角補正で比較する。

画像だけで抽出し、距離の真値で候補や条件を選ばない。元画像の書出しなし。
補正点が安定しても、物理的な外角や測量対応を確認したことにはならない。
"""
import argparse
import csv
import importlib.util
import itertools
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
PRIOR = ROOT / "Experimental_results/2026-11-09/wide_floor_geometry_r01"
SPEC = importlib.util.spec_from_file_location("l_boundary_prior", PRIOR / "audit_corner_identity.py")
corners = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corners)
original = corners.original
from angular_fisheye_geometry import project, unproject
from cone_distance_core import digest, load_config

SCREENS = dict(min_arm_samples=3, min_arm_span_px=1.8, max_line_rms_px=.65,
    min_intersection_sine=.2, max_corner_shift_px=3., min_positive_gradient=20.,
    profile_offsets_px=[-.75, -.5, -.25, 0., .25, .5, .75, 1., 1.25, 1.5])
FLAGS = dict(physical_outer_corner_identity_verified=False, physical_metric_verified=False,
              usable_for_ffb=False, selected=False)


def native_gray(gray):
    if gray.shape != (720, 1280) or gray.dtype != np.uint8:
        raise ValueError("unchanged native gray8 image required")


def sample_gray(gray, points):
    native_gray(gray)
    p = np.asarray(points, float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        raise ValueError("finite native Nx2 sample points required")
    if np.any(p < [0, 0]) or np.any(p > [639, 719]):
        raise ValueError("front-lens sampling only; no border extrapolation")
    return cv2.remap(gray, p[:, 0].astype(np.float32)[:, None],
        p[:, 1].astype(np.float32)[:, None], cv2.INTER_LINEAR).reshape(-1).astype(float)


def contour_and_corner(gray, seed, threshold):
    native_gray(gray)
    selected = corners.convex_proposal(corners.nearby_vertices(gray, seed, threshold))
    if selected is None:
        return None, None, "convex_corner_unavailable"
    x, y = np.rint(seed).astype(int)
    left, top = x-16, y-10
    mask = (gray[top:y+11, left:x+17] < threshold).astype(np.uint8)
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    contour = contours[selected["contour_index"]][:, 0].astype(float) + [left, top]
    if np.any(contour[:, 0] <= left) or np.any(contour[:, 0] >= left+32) or np.any(contour[:, 1] <= top) or np.any(contour[:, 1] >= top+20):
        return contour, selected, "contour_reaches_local_roi_edge"
    return contour, selected, None


def arm_samples(contour, corner, step, length):
    """角から輪郭の両側へ進む。端点で折り返す支持は使わない。"""
    c, q = np.asarray(contour, float), np.asarray(corner, float)
    indices = np.flatnonzero(np.linalg.norm(c-q, axis=1) < 1e-8)
    if len(indices) != 1:
        return None, "nonunique_contour_corner"
    index, arc, last = int(indices[0]), 0., q
    samples = []
    initial_direction = None
    previous_projection = 0.
    for k in range(1, len(c)//2):
        p = c[(index+step*k) % len(c)]
        arc += float(np.linalg.norm(p-last))
        last = p
        if arc > length+.01:
            break
        if arc < 1.:
            continue
        if initial_direction is None:
            initial_direction = (p-q)/np.linalg.norm(p-q)
        along = float((p-q) @ initial_direction)
        # Local monotonicity is conservative: no fitting around tape end caps.
        if along <= previous_projection+.1:
            break
        previous_projection = along
        samples.append(p)
    if len(samples) < SCREENS["min_arm_samples"]:
        return None, "insufficient_distinct_arm_samples"
    samples = np.asarray(samples)
    if np.linalg.norm(samples[-1]-samples[0]) < SCREENS["min_arm_span_px"]:
        return None, "insufficient_arm_span"
    return samples, None


def threshold_crossings(gray, points, normal, threshold):
    """外向きの暗→明の交点。複数交点・弱い勾配は位置を発明せず保留。"""
    offsets = np.asarray(SCREENS["profile_offsets_px"])
    records, evidence = [], []
    for point in points:
        profile = sample_gray(gray, point + offsets[:, None]*normal)
        crossing = np.flatnonzero((profile[:-1] < threshold) & (profile[1:] >= threshold))
        if len(crossing) != 1:
            return None, evidence, "threshold_crossing_not_unique"
        i = int(crossing[0])
        gradient = (profile[i+1]-profile[i])/(offsets[i+1]-offsets[i])
        if gradient < SCREENS["min_positive_gradient"]:
            return None, evidence, "weak_outward_gradient"
        offset = float(offsets[i] + (threshold-profile[i]) / gradient)
        records.append(point+offset*normal)
        evidence.append(dict(offset_px=offset, positive_gradient=float(gradient)))
    return np.array(records), evidence, None


def ray_plane(points, camera):
    p = np.asarray(points, float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.isfinite(p).all():
        raise ValueError("at least three finite edge coordinates required")
    if len(np.unique(p, axis=0)) != len(p) or np.linalg.norm(np.ptp(p, axis=0)) < 1.8:
        raise ValueError("distinct extended edge support required")
    rays, valid = unproject(p, camera, image_size=(1280, 720))
    if not valid.all():
        raise ValueError("edge outside calibrated domain")
    _, singular, vt = np.linalg.svd(rays)
    if singular[1] < 1e-6:
        raise ValueError("edge ray spread insufficient")
    normal = vt[-1]
    corrected = rays - (rays @ normal)[:, None]*normal
    projected, valid = project(corrected, camera)
    if not valid.all():
        raise ValueError("edge projection outside domain")
    rms = float(np.sqrt(np.mean(np.sum((projected-p)**2, axis=1))))
    return normal, rms


def intersect_planes(first, second, seed, camera):
    direction = np.cross(first, second)
    sine = float(np.linalg.norm(direction))
    if sine < SCREENS["min_intersection_sine"]:
        return None, sine, "near_parallel_edge_planes"
    direction /= sine
    if direction[2] < 0:
        direction = -direction
    point, valid = project([direction], camera)
    if not valid[0] or not 0 <= point[0, 0] < 640 or not 0 <= point[0, 1] < 720:
        return None, sine, "intersection_outside_domain"
    if np.linalg.norm(point[0]-seed) > SCREENS["max_corner_shift_px"]:
        return None, sine, "intersection_moved_outside_local_corner"
    return point[0], sine, None


def edge_corner(gray, contour, selected, length, refine, threshold, camera):
    native_gray(gray)
    if length not in (3, 4, 5) or type(refine) is not bool:
        raise ValueError("predeclared arc length and explicit refinement required")
    q = np.array([selected["x"], selected["y"]])
    area = corners.signed_area(contour)
    if abs(area) < 1e-8:
        return dict(available=False, reason="zero_contour_area", **FLAGS)
    planes, arms = [], []
    for step in (-1, 1):
        samples, reason = arm_samples(contour, q, step, length)
        if samples is None:
            return dict(available=False, reason=reason, arms=arms, **FLAGS)
        # cv.fitLine is used for the local outward sampling direction only.
        line = cv2.fitLine(samples.astype(np.float32), cv2.DIST_L2, 0, .001, .001).reshape(-1)
        tangent = line[:2].astype(float)
        if tangent @ (samples[-1]-samples[0]) < 0:
            tangent = -tangent
        forward_tangent = tangent*step
        outward = np.array([forward_tangent[1], -forward_tangent[0]])*np.sign(area)
        evidence = []
        if refine:
            refined, evidence, reason = threshold_crossings(gray, samples, outward, threshold)
            if refined is None:
                return dict(available=False, reason=reason, arms=arms, **FLAGS)
            samples = refined
        try:
            normal, rms = ray_plane(samples, camera)
        except ValueError as error:
            return dict(available=False, reason=str(error), arms=arms, **FLAGS)
        arms.append(dict(step=step, samples=len(samples), rms_px=rms,
                         edge_samples_native_xy=samples.tolist(), crossings=evidence))
        if rms > SCREENS["max_line_rms_px"]:
            return dict(available=False, reason="edge_not_straight_enough", arms=arms, **FLAGS)
        planes.append(normal)
    point, sine, reason = intersect_planes(*planes, q, camera)
    return dict(available=point is not None, reason=reason or "unverified_edge_intersection",
        point=None if point is None else point.tolist(), intersection_sine=sine,
        shift_px=None if point is None else float(np.linalg.norm(point-q)), arms=arms, **FLAGS)


def local_subpixel(gray, selected, window):
    native_gray(gray)
    if window not in (2, 3):
        raise ValueError("predeclared half-window 2 or 3 required")
    seed = np.array([selected["x"], selected["y"]], np.float32)
    point = seed.reshape(1, 1, 2).copy()
    cv2.cornerSubPix(gray, point, (window, window), (-1, -1),
                     (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, .001))
    q = point[0, 0].astype(float)
    shift = float(np.linalg.norm(q-seed))
    valid = np.isfinite(q).all() and shift <= SCREENS["max_corner_shift_px"]
    return dict(available=bool(valid), reason="unverified_subpixel_corner" if valid else "subpixel_moved_outside_local_corner",
        point=q.tolist() if valid else None, shift_px=shift, **FLAGS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/home/robo25/Downloads"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    manifest = PRIOR / "corner_identity_r01/input_provenance.json"
    inputs = dict(json.loads(manifest.read_text()))
    for p in (PRIOR / "results_r01/input_provenance.json",):
        inputs.update(json.loads(p.read_text()))
        inputs[str(p)] = digest(p)
    for name, sha in inputs.items():
        if digest(name) != sha:
            raise ValueError("prior source/input changed: " + name)
    inputs.update({str(p): digest(p) for p in (Path(__file__), manifest,
        PRIOR / "audit_corner_identity.py", ROOT / "src/floor_reference_pose.py")})
    with (PRIOR / "corner_identity_r01/corner_identity_comparison.csv").open() as stream:
        prior_points = list(csv.DictReader(stream))
    inputs[str(PRIOR / "corner_identity_r01/corner_identity_comparison.csv")] = digest(
        PRIOR / "corner_identity_r01/corner_identity_comparison.csv")
    camera = load_config()[1]
    observations, proposals, evaluations, failures = [], {}, [], []
    for group, frames, E_seed, target in original.GROUPS:
        for frame in frames:
            image_path = args.image_dir / f"decoded_{original.SESSION}_f{frame:06d}.png"
            image_sha = digest(image_path)
            inputs[str(image_path)] = image_sha
            gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            native_gray(gray)
            before = gray.copy()
            seeds = dict(original.FIXED)
            if E_seed is not None:
                seeds["E"] = E_seed
            for label, threshold in itertools.product(seeds, (90, 100, 110, 120)):
                contour, selected, contour_error = contour_and_corner(gray, seeds[label], threshold)
                expected = next(r for r in prior_points if int(r["frame"]) == frame and
                    r["point"] == label and int(r["threshold"]) == threshold)
                if selected is None or [selected["x"], selected["y"]] != [float(expected["convex_x"]), float(expected["convex_y"])]:
                    raise ValueError("old convex proposal not reproduced")
                base_point = [selected["x"], selected["y"]]
                outcomes = [("integer_convex", dict(available=True, point=base_point,
                    shift_px=0., reason="unverified_convex_proposal", **FLAGS))]
                for length, refine in itertools.product((3, 4, 5), (False, True)):
                    result = (dict(available=False, reason=contour_error, **FLAGS) if contour_error else
                        edge_corner(gray, contour, selected, length, refine, threshold, camera))
                    outcomes.append((f"{'isocross' if refine else 'raster'}_rayplane_arc{length}", result))
                for window in (2, 3):
                    outcomes.append((f"cornerSubPix_w{window}", local_subpixel(gray, selected, window)))
                for method, result in outcomes:
                    point = result.get("point")
                    record = dict(frame=frame, group=group, label=label, threshold=threshold, method=method,
                        seed_native_xy=seeds[label], integer_native_xy=base_point, **result)
                    observations.append(record)
                    proposals.setdefault((frame, threshold, method), {})[label] = point if result["available"] else None
            if not np.array_equal(gray, before) or digest(image_path) != image_sha:
                raise ValueError("source image was modified")
            print(f"read-only extraction frame {frame:06d}", flush=True)
    for (frame, threshold, method), points in proposals.items():
        if "E" not in points:
            continue
        missing = [key for key in list(original.FIXED)+["E"] if points.get(key) is None]
        if missing:
            failures.append(dict(frame=frame, threshold=threshold, method=method,
                                 reason="missing_marker_no_fallback", missing=missing))
            continue
        group, target = next((g, t) for g, frames, _, t in original.GROUPS if frame in frames)
        fixed = np.array([points[k] for k in original.FIXED])
        for h in original.HYPOTHESES:
            fit = original.fit_fixed(fixed, h, camera)
            for candidate in fit["candidates"]:
                result = original.evaluate_E(points["E"], target, candidate, h, camera)
                evaluations.append(dict(frame=frame, group=group, threshold=threshold, method=method,
                    hypothesis=h, solution_index=candidate["solution_index"],
                    height_m=candidate["camera_height_above_floor_m"],
                    native_rmse_px=candidate["fit_native_rmse_px"], **result, selected=False))
    coverage = []
    for method in sorted({r["method"] for r in observations}):
        rows = [r for r in observations if r["method"] == method]
        valid = [r for r in rows if r["available"]]
        coverage.append(dict(method=method, available=len(valid), total=len(rows),
            maximum_shift_px=max(r["shift_px"] for r in valid) if valid else None,
            reasons={reason: sum(r["reason"] == reason for r in rows if not r["available"])
                     for reason in sorted({r["reason"] for r in rows if not r["available"]})}))
    summary = dict(status="BOUNDARY_REFINEMENT_COMPARISON_ONLY_NO_PHYSICAL_ADOPTION",
        session=original.SESSION, image_count=10, observations=len(observations), pose_rows=len(evaluations),
        incomplete_frame_methods=len(failures), coverage=coverage, screens=SCREENS,
        E_used_for_extraction=False, E_targets_used_to_choose_parameters=False,
        selected_method=None, selected_hypothesis=None, selected_solution=None,
        camera_images_edited_or_exported=False, runtime_changed=False, **FLAGS)
    args.output_dir.mkdir(parents=True)
    original.dump(args.output_dir / "input_provenance.json", inputs)
    original.dump(args.output_dir / "summary.json", summary)
    original.dump(args.output_dir / "boundary_observations.json", observations)
    original.dump(args.output_dir / "withheld_methods.json", failures)
    original.table(args.output_dir / "point_coordinates.csv", [dict(
        frame=r["frame"], group=r["group"], label=r["label"], threshold=r["threshold"], method=r["method"],
        available=r["available"], reason=r["reason"], x=None if r.get("point") is None else r["point"][0],
        y=None if r.get("point") is None else r["point"][1], shift_px=r.get("shift_px"), **FLAGS) for r in observations])
    original.table(args.output_dir / "pose_evaluation.csv", evaluations)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
