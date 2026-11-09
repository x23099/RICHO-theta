"""外角候補の凸性と全24点順を調べる診断。runtime・元PNGは変更しない。"""
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
SPEC = importlib.util.spec_from_file_location("wide_floor_original", Path(__file__).with_name("analyze.py"))
original = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(original)
from cone_distance_core import digest, load_config
from floor_reference_pose import planar_floor_pose_candidates


def signed_area(polygon):
    p = np.asarray(polygon, float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.isfinite(p).all():
        raise ValueError("finite polygon required")
    return float(.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1)
                              - p[:, 1] * np.roll(p[:, 0], -1)))


def polygon_vertices(polygon):
    """Polygon winding-independent convexity. Convex != verified physical ID."""
    p = np.asarray(polygon, float)
    area = signed_area(p)
    if abs(area) < 1e-9:
        return []
    result = []
    for i, xy in enumerate(p):
        before, after = xy - p[i - 1], p[(i + 1) % len(p)] - xy
        turn = float(before[0] * after[1] - before[1] * after[0])
        kind = "convex" if turn * area > 0 else "concave" if turn * area < 0 else "flat"
        result.append(dict(x=float(xy[0]), y=float(xy[1]), kind=kind))
    return result


def nearby_vertices(gray, seed, threshold):
    if gray.shape != (720, 1280):
        raise ValueError("unchanged native image required")
    point = np.asarray(seed, float)
    if point.shape != (2,) or not np.isfinite(point).all():
        raise ValueError("finite seed required")
    x, y = np.rint(point).astype(int)
    if not (16 <= x < 624 and 12 <= y < 708):
        raise ValueError("front seed away from image/ROI boundaries required")
    if not 0 < threshold < 256:
        raise ValueError("explicit intensity threshold required")
    left, top = x - 16, y - 10
    mask = (gray[top:y + 11, left:x + 17] < threshold).astype(np.uint8)
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    result = []
    for contour_index, contour in enumerate(contours):
        if cv2.contourArea(contour) < 2:
            continue
        polygon = cv2.approxPolyDP(contour, .5, True)[:, 0, :].astype(float) + [left, top]
        for row in polygon_vertices(polygon):
            distance = float(np.linalg.norm(np.array([row["x"], row["y"]]) - point))
            if distance <= 4:
                result.append(dict(row, distance_px=distance, contour_index=contour_index))
    return result


def convex_proposal(vertices):
    candidates = [r for r in vertices if r["kind"] == "convex"]
    if not candidates:
        return None
    return min(candidates, key=lambda r: (r["distance_px"], r["contour_index"]))


def evaluate_permutations(pixels, E_records, camera):
    """Keep ALL assignments; E errors are diagnostic, NOT holdout selection.

    Fixed physical IDs are not changed/adopted based on these errors. The
    rows merely test whether another raw, proper pose could explain the data.
    """
    result = []
    world = original.vehicle_world(original.HYPOTHESES[0])
    for permutation in itertools.permutations(range(4)):
        fit = planar_floor_pose_candidates(pixels, world[list(permutation)], camera)
        for candidate in fit["candidates"]:
            records = [original.evaluate_E(pixel, target, candidate,
                        original.HYPOTHESES[0], camera) for pixel, target in E_records]
            available = [r for r in records if r["available"]]
            result.append(dict(permutation="-".join(map(str, permutation)),
                solution_index=candidate["solution_index"],
                geometry_consistent=candidate["geometry_consistent"],
                camera_height_m=candidate["camera_height_above_floor_m"],
                native_rmse_px=candidate["fit_native_rmse_px"],
                available=len(available), total=len(records),
                maximum_E_error_m=None if len(available) != len(records)
                    else max(r["planar_error_m"] for r in available),
                mapping_adopted=False, holdout_used_for_diagnostic_rejection_only=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/home/robo25/Downloads"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    camera = load_config()[1]
    earlier = Path(__file__).parent / "results_r01"
    prior_inputs = json.loads((earlier / "input_provenance.json").read_text())
    for path, sha in prior_inputs.items():
        if digest(path) != sha:
            raise ValueError("earlier source/input changed: " + path)
    inputs = {str(path): digest(path) for path in [Path(__file__),
        Path(__file__).with_name("analyze.py"), earlier/"input_provenance.json",
        earlier/"point_proposals.csv"]}
    prior_rows = list(csv.DictReader((earlier / "point_proposals.csv").open()))
    all_candidates, comparisons, proposals, group_by_frame, target_by_frame = [], [], {}, {}, {}
    for group, frames, E_seed, target in original.GROUPS:
        for frame in frames:
            path = args.image_dir / f"decoded_{original.SESSION}_f{frame:06d}.png"
            inputs[str(path)] = digest(path)
            gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if gray is None or gray.shape != (720, 1280):
                raise ValueError("unchanged native PNG required")
            group_by_frame[frame], target_by_frame[frame] = group, target
            seeds = dict(original.FIXED)
            if E_seed is not None:
                seeds["E"] = E_seed
            for threshold in (90, 100, 110, 120):
                proposals[frame, threshold] = {}
                for label, seed in seeds.items():
                    vertices = nearby_vertices(gray, seed, threshold)
                    prior = next(r for r in prior_rows if int(r["frame"]) == frame
                        and r["point"] == label and int(r["threshold"]) == threshold)
                    prior_xy = [float(prior["proposed_x"]), float(prior["proposed_y"])]
                    matches = [r for r in vertices if [r["x"], r["y"]] == prior_xy]
                    selected = convex_proposal(vertices)
                    proposals[frame, threshold][label] = (None if selected is None
                        else np.array([selected["x"], selected["y"]]))
                    comparisons.append(dict(frame=frame, group=group, point=label, threshold=threshold,
                        prior_x=prior_xy[0], prior_y=prior_xy[1],
                        prior_convex=any(r["kind"] == "convex" for r in matches),
                        prior_concave=any(r["kind"] == "concave" for r in matches),
                        convex_available=selected is not None,
                        convex_x=None if selected is None else selected["x"],
                        convex_y=None if selected is None else selected["y"],
                        displacement_px=None if selected is None else float(np.linalg.norm(
                            np.array([selected["x"], selected["y"]]) - prior_xy)),
                        physical_outer_corner_identity_verified=False))
                    all_candidates.extend(dict(r, frame=frame, point=label, threshold=threshold)
                                          for r in vertices)
            if digest(path) != inputs[str(path)]:
                raise ValueError("PNG changed")
    poses, holdouts, permutations, winding, outcomes = [], [], [], [], []
    for frame, threshold in itertools.product(original.GROUPS[0][1], (90, 100, 110, 120)):
        fixed = [proposals[frame, threshold][label] for label in original.FIXED]
        if any(p is None for p in fixed):
            outcomes.append(dict(frame=frame, threshold=threshold, reason="fixed_corner_unavailable"))
            continue
        pixels = np.array(fixed)
        winding.append(dict(frame=frame, threshold=threshold,
            image_quad_signed_area_px2=signed_area(pixels[[0, 1, 3, 2]])))
        E_records = [(points["E"], target_by_frame[e_frame])
            for (e_frame, t), points in proposals.items()
            if t == threshold and "E" in points and points["E"] is not None]
        if len(E_records) != 8:
            outcomes.append(dict(frame=frame, threshold=threshold, reason="E_corner_unavailable"))
            continue
        for hypothesis in original.HYPOTHESES:
            fit = original.fit_fixed(pixels, hypothesis, camera)
            for candidate in fit["candidates"]:
                identity = dict(fit_frame=frame, threshold=threshold, hypothesis=hypothesis,
                                solution_index=candidate["solution_index"])
                poses.append(dict(identity, height_m=candidate["camera_height_above_floor_m"],
                    native_rmse_px=candidate["fit_native_rmse_px"],
                    geometry_consistent=candidate["geometry_consistent"], selected=False))
                for (e_frame, t), points in proposals.items():
                    if t == threshold and "E" in points and points["E"] is not None:
                        holdouts.append(dict(identity, frame=e_frame, group=group_by_frame[e_frame],
                            **original.evaluate_E(points["E"], target_by_frame[e_frame], candidate,
                                                  hypothesis, camera)))
        permutations.extend(dict(r, fit_frame=frame, threshold=threshold)
                            for r in evaluate_permutations(pixels, E_records, camera))
    above_rows = [r for r in permutations if r["geometry_consistent"]
                  and r["available"] == r["total"]]
    low_rmse_rows = [r for r in above_rows if r["native_rmse_px"] is not None
                    and r["native_rmse_px"] < 2.]
    primary = [r for r in poses if r["hypothesis"] == original.HYPOTHESES[1]]
    summary = dict(status="WITHHELD_HANDEDNESS_NOT_RESOLVED_BY_CORNER_CONVEXITY_OR_ASSIGNMENT",
        session=original.SESSION, images=10, compared_proposals=len(comparisons),
        prior_concave_proposal_count=sum(r["prior_concave"] for r in comparisons),
        prior_not_convex_proposal_count=sum(not r["prior_convex"] for r in comparisons),
        convex_unavailable_count=sum(not r["convex_available"] for r in comparisons),
        maximum_candidate_change_px=max(r["displacement_px"] for r in comparisons
                                        if r["displacement_px"] is not None),
        primary_height_range_m=[min(r["height_m"] for r in primary), max(r["height_m"] for r in primary)],
        primary_physically_consistent_count=sum(r["geometry_consistent"] for r in primary),
        primary_pose_count=len(primary), permutation_rows=len(permutations),
        valid_above_floor_assignment_rows=len(above_rows),
        minimum_of_maximum_E_error_across_all_raw_assignments_m=min(r["maximum_E_error_m"] for r in above_rows),
        minimum_of_maximum_E_error_for_native_rmse_below_2px_m=min(r["maximum_E_error_m"] for r in low_rmse_rows),
        comparisons_are_not_independent_physical_trials=True,
        all_vehicle_sides_user_confirmed_facing_forward=True, selected_hypothesis=None,
        selected_solution=None, selected_assignment=None, physical_metric_verified=False,
        physical_corner_identity_verified=False, camera_images_edited_or_exported=False,
        runtime_changed=False, usable_for_ffb=False, calibration_used_E_points=False,
        E_used_to_diagnose_assignments_but_not_adopt_one=True,
        incomplete_variants=outcomes, winding=winding, opencv_version=cv2.__version__)
    args.output_dir.mkdir(parents=True)
    original.dump(args.output_dir/"input_provenance.json", inputs)
    original.dump(args.output_dir/"summary.json", summary)
    for name, rows in [("corner_candidates", all_candidates), ("corner_identity_comparison", comparisons),
                       ("pose_metrics", poses), ("holdout_metrics", holdouts),
                       ("all_raw_assignments", permutations)]:
        original.table(args.output_dir/f"{name}.csv", rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
