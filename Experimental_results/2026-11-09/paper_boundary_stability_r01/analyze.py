"""Evaluate existing contour seeds + OpenCV subpixel refinement, offline only.

No seeds or parameter choice from human clicks or distance references. Human
clicks are comparison observations only. No image writes or live model export.
"""
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
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from angular_fisheye_geometry import project, unproject
from review_physical_reference import read_json, validate_queue, load_decisions, item_image

SPEC = importlib.util.spec_from_file_location(
    "paper_corner_sensitivity", Path(__file__).resolve().parent.parent / "paper_corner_sensitivity_r01/analyze.py")
sensitivity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sensitivity)
audit = sensitivity.audit


def checked_quad(points):
    p = np.asarray(points, float)
    if p.shape != (4, 2) or not np.isfinite(p).all() or np.any(p < [0, 0]) or np.any(p >= [640, 720]):
        raise ValueError("native front-left finite quadrilateral required")
    if not cv2.isContourConvex(p.astype(np.float32)):
        raise ValueError("convex quadrilateral required")
    area = np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1))
    if area <= 0:
        raise ValueError("positive image winding required; never silently reorder refined corners")
    return p


def refine(gray, points, window):
    if gray.dtype != np.uint8 or gray.shape != (720, 1280) or type(window) is not int or window not in (2, 3, 4):
        raise ValueError("native gray8 and predeclared half-window 2/3/4 required")
    p = checked_quad(points)
    if np.any(p < [window+2, window+2]) or np.any(p >= [640-window-2, 720-window-2]):
        raise ValueError("refinement window must remain within native front lens image rectangle")
    corners = p.astype(np.float32).reshape(-1, 1, 2).copy()
    cv2.cornerSubPix(gray, corners, (window, window), (-1, -1),
                     (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, .001))
    return checked_quad(corners[:, 0, :])


def seed_offsets():
    yield "base", np.zeros((4, 2))
    for corner in range(4):
        for axis in range(2):
            for sign in (-1, 1):
                delta = np.zeros((4, 2)); delta[corner, axis] = sign * .5
                yield f"c{corner}_{'xy'[axis]}_{sign}", delta


def edge_locus(endpoints, camera, count=33):
    """KB4 image locus of a straight physical edge under central-camera model."""
    rays, valid = unproject(endpoints, camera, image_size=(1280, 720))
    if len(rays) != 2 or not valid.all():
        raise ValueError("two valid edge endpoints required")
    t = np.linspace(.1, .9, count)[:, None]
    uv, ok = project((1-t)*rays[0] + t*rays[1], camera)
    if not ok.all():
        raise ValueError("edge outside calibrated domain")
    tangent = np.gradient(uv, axis=0)
    lengths = np.linalg.norm(tangent, axis=1)
    if np.any(lengths < 1e-8):
        raise ValueError("nonzero edge required")
    tangent /= lengths[:, None]
    inward = np.column_stack((-tangent[:, 1], tangent[:, 0]))
    return uv, inward


def sample_gray(gray, points):
    points = np.asarray(points, float)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("finite Nx2 sample coordinates required")
    if np.any(points < [0, 0]) or np.any(points > [639, 719]):
        raise ValueError("no border extrapolation allowed")
    return cv2.remap(gray, points[:, 0].astype(np.float32)[:, None],
                     points[:, 1].astype(np.float32)[:, None], cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT).reshape(-1).astype(float)


def boundary_evidence(gray, quad, camera):
    """Record raw local polarity/offset statistics, not a physical-paper gate.

    No line fitting to pixel chords: the proposed straight edge is evaluated
    through endpoint KB4 rays. 33 correlated samples per edge, no claim of
    independent evidence. Positive normal is inward for positive winding.
    """
    quad = checked_quad(quad)
    offsets = np.linspace(-3., 3., 25)
    records = []
    for edge in range(4):
        uv, inward = edge_locus(quad[[edge, (edge+1) % 4]], camera)
        contrasts = {d: sample_gray(gray, uv+d*inward) - sample_gray(gray, uv-d*inward) for d in (.5, 1., 2.)}
        profile = np.column_stack([sample_gray(gray, uv + d * inward) for d in offsets])
        derivative = np.diff(profile, axis=1) / .25
        peaks = np.argmax(derivative, axis=1)
        peak_value = derivative[np.arange(len(uv)), peaks]
        peak_offset = (offsets[:-1]+offsets[1:])[peaks] / 2
        positive_peaks = peak_value > 0
        records.append(dict(edge=edge, nominal_correlated_samples=len(uv),
                            contrast_halfpx_median=float(np.median(contrasts[.5])),
                            contrast_1px_median=float(np.median(contrasts[1.])),
                            contrast_2px_median=float(np.median(contrasts[2.])),
                            positive_1px_fraction=float(np.mean(contrasts[1.] > 0)),
                            contrast_1px_over20_fraction=float(np.mean(contrasts[1.] > 20)),
                            median_strongest_positive_gradient_offset_px=float(np.median(peak_offset[positive_peaks])) if positive_peaks.any() else None,
                            positive_peak_fraction=float(np.mean(positive_peaks)),
                            physical_edge_verified=False))
    return records


def covariance(gray, point, window):
    patch = cv2.getRectSubPix(gray.astype(np.float32), (2*window+3, 2*window+3), tuple(map(float, point)))
    dx = patch[1:-1, 2:] - patch[1:-1, :-2]
    dy = patch[2:, 1:-1] - patch[:-2, 1:-1]
    y, x = np.mgrid[-window:window+1, -window:window+1]
    weight = np.exp(-(x*x+y*y)/(window*window))
    matrix = np.array([[np.sum(weight*dx*dx), np.sum(weight*dx*dy)],
                       [np.sum(weight*dx*dy), np.sum(weight*dy*dy)]])
    values = np.linalg.eigvalsh(matrix)
    return dict(gradient_min_eigenvalue=float(values[0]), gradient_max_eigenvalue=float(values[1]),
                gradient_eigenvalue_ratio=float(values[0]/values[1]) if values[1] > 0 else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    day = Path(__file__).resolve().parent.parent
    prep = day / "physical_reference_review_r01/prepared_r01"
    queue = validate_queue(read_json(prep / "queue.json"))
    decisions = load_decisions(prep / "decisions", queue, digest(prep / "queue.json"))
    settings, camera, heading, _ = load_config()
    prev = day / "reviewed_coordinate_audit_r01/results_r02"
    paths = [Path(__file__), Path(SPEC.origin), day / "reviewed_coordinate_audit_r01/analyze.py",
             prep / "queue.json", prev / "colour_pixel_vs_reviewed_edge.csv", DEFAULT_CONFIG,
             ROOT / settings["camera_candidate"], ROOT / settings["floor_candidate"]]
    paths += [ROOT / "src" / name for name in ("angular_fisheye_geometry.py", "cone_distance_core.py",
              "cone_fixed_floor_candidate.py", "derive_fixed_floor_live_bundle.py", "floor_reference_pose.py",
              "review_physical_reference.py")]
    paths += [ROOT / item["image"] for item in queue["items"]]
    paths += [prep / "decisions" / (item["id"] + ".json") for item in queue["items"]]
    with (prev / "colour_pixel_vs_reviewed_edge.csv").open() as stream:
        probe_rows = list(csv.DictReader(stream))
    for short in ("b559e424", "df33e833"):
        paths.append(ROOT / f"Experimental_results/2026-11-04/floor_reference_{short}_r01/references.json")
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    candidates = []; corner_rows = []; evidence = []; geometry = []; seed_results = []; seed_summary = []; scan = []
    image_memory_unchanged = True; primary_reproduced = 0
    for paper in [i for i in queue["items"] if i["kind"] == "paper"]:
        session = paper["session"]; short = session[:8]
        if decisions[paper["id"]]["status"] != "reviewed":
            raise ValueError("explicit reviewed paper required")
        # Comparators are not passed into contour/refinement/evidence functions.
        human = np.array(decisions[paper["id"]]["points_native_xy"])
        item = item_image(paper); original = item["image"].copy()
        gray = cv2.cvtColor(item["image"], cv2.COLOR_BGR2GRAY)
        gray_before = gray.copy()
        roi = (280, 395, 90, 50) if short == "b559e424" else (280, 390, 80, 40)
        old = read_json(ROOT / f"Experimental_results/2026-11-04/floor_reference_{short}_r01/references.json")["frames"][0]
        primary_epsilon = .025 if short == "b559e424" else .02
        # Baseline families come from the old contour, not from human clicks.
        baseline = sensitivity.fit(np.array(old["corners_native_xy"]), item, settings, camera)
        probes = [dict(id="f"+r["frame"], point=[int(r["point_x"]), int(r["point_y"])]) for r in probe_rows if r["session"] == session]
        primary_refinements = {}
        for threshold in (150, 170, 190):
            for epsilon in (.02, .025, .03, .04):
                quad, info = sensitivity.contour_quad(item["image"], roi, threshold, epsilon)
                if quad is None:
                    scan.append(dict(session=session, threshold=threshold, epsilon=epsilon, **info)); continue
                is_primary = threshold == 170 and epsilon == primary_epsilon
                if is_primary:
                    if not np.array_equal(quad, old["corners_native_xy"]):
                        raise ValueError("old primary extraction mismatch")
                    primary_reproduced += 1
                for window in (0, 2, 3, 4):
                    candidate_id = f"{short}_t{threshold}_e{epsilon}_w{window}"
                    try:
                        refined = checked_quad(quad) if window == 0 else refine(gray, quad, window)
                    except ValueError as exc:
                        scan.append(dict(session=session, threshold=threshold, epsilon=epsilon, window=window, reason=str(exc))); continue
                    if is_primary and window:
                        primary_refinements[window] = refined
                    candidate = dict(id=candidate_id, session=session, threshold=threshold, epsilon=epsilon,
                                     window=window, primary_seed=is_primary,
                                     max_manual_difference_px=float(np.max(np.linalg.norm(refined-human, axis=1))),
                                     mean_manual_difference_px=float(np.mean(np.linalg.norm(refined-human, axis=1))))
                    candidates.append(candidate)
                    for k, point in enumerate(refined):
                        corner_rows.append(dict(candidate, corner=k, x=float(point[0]), y=float(point[1]),
                                                manual_difference_px=float(np.linalg.norm(point-human[k])),
                                                seed_movement_px=float(np.linalg.norm(point-quad[k])),
                                                returned_same_as_seed=bool(np.array_equal(point, quad[k])),
                                                **covariance(gray, point, window or 2)))
                    evidence += [dict(candidate_id=candidate_id, session=session, **r) for r in boundary_evidence(gray, refined, camera)]
                    models = sensitivity.fit(refined, item, settings, camera)
                    geometry += [dict(candidate, **r) for r in sensitivity.metrics(refined, models, baseline, probes, camera, heading, session, settings["diagnostic_range_m"])]
        # Initial-position stress of OLD primary contours, not human points.
        for window in (2, 3, 4):
            outputs = []
            for seed_id, delta in seed_offsets():
                seed = np.array(old["corners_native_xy"], float) + delta
                try:
                    result = refine(gray, seed, window)
                except ValueError as exc:
                    seed_results.append(dict(session=session, window=window, seed_id=seed_id, status="withheld", reason=str(exc))); continue
                outputs.append(result)
                for k in range(4):
                    seed_results.append(dict(session=session, window=window, seed_id=seed_id, corner=k,
                                             status="recorded_observation_only", x=float(result[k, 0]), y=float(result[k, 1]),
                                             movement_from_seed_px=float(np.linalg.norm(result[k]-seed[k])),
                                             deviation_from_unperturbed_output_px=float(np.linalg.norm(result[k]-primary_refinements[window][k]))))
            for k in range(4):
                points = np.array(outputs)[:, k, :]
                seed_summary.append(dict(session=session, window=window, corner=k, valid_trials=len(outputs), total_trials=17,
                                         x_span_px=float(np.ptp(points[:, 0])), y_span_px=float(np.ptp(points[:, 1])),
                                         max_distance_from_base_output_px=float(np.max(np.linalg.norm(points-primary_refinements[window][k], axis=1))),
                                         physical_corner_verified=False))
        image_memory_unchanged &= bool(np.array_equal(original, item["image"]) and np.array_equal(gray, gray_before))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for filename, rows in (("candidate_comparisons.csv", candidates), ("corner_observations.csv", corner_rows),
                           ("boundary_evidence.csv", evidence), ("conditional_geometry.csv", geometry),
                           ("initial_seed_trials.csv", seed_results), ("initial_seed_stability.csv", seed_summary),
                           ("withheld_contours.csv", scan)):
        audit.write_csv(args.output_dir / filename, rows)
    fig, axes = audit.plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for ax, short in zip(axes, ("b559e424", "df33e833")):
        rows = [r for r in corner_rows if r["session"].startswith(short) and r["primary_seed"]]
        for window in (0, 2, 3, 4):
            selected = [r for r in rows if r["window"] == window]
            ax.plot(range(4), [r["manual_difference_px"] for r in selected], "o-", label=f"half-window {window}" if window else "Old contour")
        ax.set_xticks(range(4), ["TL", "TR", "BR", "BL"]); ax.set_ylabel("Difference from manual click [native px]")
        ax.set_title(short); ax.legend(fontsize=8)
    fig.suptitle("Local refinement from OLD contour seeds / no method selected\nHuman visual comparison, NOT surveyed accuracy")
    fig.savefig(args.output_dir / "corner_refinement_comparison.png", dpi=150); audit.plt.close(fig)
    fig, axes = audit.plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for ax, short in zip(axes, ("b559e424", "df33e833")):
        rows = [r for r in geometry if r["session"].startswith(short) and r["assignment"] == "as_listed"
                and r["tracked_branch"] == "s0" and r["height_source"] == "image_plane_plus_thickness"]
        quantity = "f35562_range_m" if short == "b559e424" else "f64232_range_m"
        for window in (0, 2, 3, 4):
            vals = [r[quantity] for r in rows if r["window"] == window]
            ax.scatter(np.full(len(vals), window), vals, s=18, alpha=.6)
        ax.set_xticks([0, 2, 3, 4], ["none", "2", "3", "4"])
        ax.set_xlabel("Refinement half-window [px]"); ax.set_ylabel("Conditional fixed-point range [m]")
        ax.set_title(short + " / " + ("f35562" if short == "b559e424" else "f64232"))
    fig.suptitle("All successful old contour settings, same image / first-listed family\nTight clustering does NOT establish physical accuracy")
    fig.savefig(args.output_dir / "parameter_stability_ranges.png", dpi=150); audit.plt.close(fig)
    changed = [p for p, sha in hashes.items() if digest(ROOT / p) != sha]
    if changed or not image_memory_unchanged:
        raise ValueError("source image/decision/code changed: "+str(changed))
    summary = dict(status="COMPLETED_IMAGE_ONLY_REFINEMENT_NOT_APPROVED", candidates=len(candidates),
                   corners=len(corner_rows), boundary_edge_records=len(evidence), geometry_rows=len(geometry),
                   seed_corner_records=len(seed_results), seed_stability_records=len(seed_summary),
                   primary_extractors_reproduced=primary_reproduced, source_sha256=hashes,
                   opencv_version=cv2.__version__, fixed_windows_half_size=[2, 3, 4],
                   source_probes=probe_rows, reference_distances_used=False, manual_clicks_used_for_seeding=False,
                   original_image_memory_unchanged=image_memory_unchanged, original_images_modified=False,
                   selected_method=None, prepared_floor_exported=False, runtime_changed=False,
                   physical_metric_verified=False, usable_for_ffb=False,
                   method_references=["https://docs.opencv.org/4.13.0/dd/d1a/group__imgproc__feature.html",
                                      "https://raw.githubusercontent.com/opencv/opencv/4.5.5/modules/imgproc/src/cornersubpix.cpp"])
    audit.write_json(args.output_dir / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("source_sha256", "source_probes")}, indent=2))


if __name__ == "__main__":
    main()
