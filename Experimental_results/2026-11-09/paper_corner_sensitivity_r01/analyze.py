"""Offline corner perturbation / contour audit. No fitting or live export."""
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
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from derive_fixed_floor_live_bundle import derive
from review_physical_reference import read_json, validate_queue, load_decisions, item_image

SPEC = importlib.util.spec_from_file_location(
    "reviewed_coordinate_audit", Path(__file__).resolve().parent.parent / "reviewed_coordinate_audit_r01/analyze.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def ordered_quad(points):
    """Image-only order for these predeclared ROIs, never a metric selector."""
    p = np.asarray(points, float)
    if p.shape != (4, 2) or not np.isfinite(p).all() or not cv2.isContourConvex(p.astype(np.float32)):
        raise ValueError("four finite convex contour vertices required")
    area = np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1))
    if area < 0:
        p = p[::-1]
    return np.roll(p, -int(np.argmin(p.sum(axis=1))), axis=0)


def perturbations():
    """Deterministic stress cases, NOT a noise law/confidence interval."""
    yield dict(id="baseline", kind="baseline", amplitude=0., corner=-1, axis="", delta=0., offsets=np.zeros((4, 2)))
    for amplitude in (.25, .5, 1.):
        for corner, axis, sign in itertools.product(range(4), range(2), (-1, 1)):
            offsets = np.zeros((4, 2)); offsets[corner, axis] = sign * amplitude
            yield dict(id=f"axis_{amplitude}_{corner}_{axis}_{sign}", kind="one_coordinate",
                       amplitude=amplitude, corner=corner, axis="xy"[axis], delta=sign * amplitude, offsets=offsets)
        for axis, sign in itertools.product(range(2), (-1, 1)):
            offsets = np.zeros((4, 2)); offsets[:, axis] = sign * amplitude
            yield dict(id=f"translate_{amplitude}_{axis}_{sign}", kind="translate_all_corners",
                       amplitude=amplitude, corner=-1, axis="xy"[axis], delta=sign * amplitude, offsets=offsets)
    for amplitude in (.5, 1.):
        for index, signs in enumerate(itertools.product((-1, 1), repeat=8)):
            yield dict(id=f"joint_{amplitude}_{index:03d}", kind="all_coordinates_box_vertices",
                       amplitude=amplitude, corner=-1, axis="", delta=0.,
                       offsets=amplitude * np.array(signs).reshape(4, 2))


def assignment_branch_map(models, baseline):
    """Track solution families by normal continuity, not height/range labels.

    IPPE's raw index may change as reprojection errors swap. Preserve raw
    indices AND match both solutions to the baseline normals, without
    selecting a physically correct solution or discarding either branch.
    """
    result = {}
    for assignment in ("as_listed", "swapped"):
        old = [m for m in baseline if f"_{assignment}_" in m["name"] and m["height_source"] == "image_plane_plus_thickness"]
        new = [m for m in models if f"_{assignment}_" in m["name"] and m["height_source"] == "image_plane_plus_thickness"]
        if len(old) != 2 or len(new) != 2:
            raise ValueError("both planar families required for local sensitivity audit")
        costs = [sum(np.arccos(np.clip(np.array(old[k]["normal_optical"]) @ new[p[k]]["normal_optical"], -1, 1))
                     for k in range(2)) for p in ((0, 1), (1, 0))]
        permutation = (0, 1) if costs[0] <= costs[1] else (1, 0)
        for k, j in enumerate(permutation):
            raw = new[j]["name"].split(f"_{assignment}_")[1].split("_")[0]
            family = old[k]["name"].split(f"_{assignment}_")[1].split("_")[0]
            result[(assignment, raw)] = family
    return result


def fit(points, item, settings, camera):
    refs = []
    for assignment, width, depth in (("as_listed", 296, 210), ("swapped", 210, 296)):
        refs.append(dict(assignment=assignment, pixels=np.asarray(points), dimensions_mm=[width, depth],
                         world=np.array([[0, 0, 0], [width, 0, 0], [width, depth, 0], [0, depth, 0]], float) / 1000,
                         coordinate_source="offline perturbation of explicit reviewed coordinates; NOT new observation"))
    bundle, _ = derive([dict(item, references=refs)], settings, camera,
                       board_thickness_mm=15, external_height_mm=590)
    if len(bundle["models"]) != 8:
        raise ValueError("eight hypotheses required; no silent dropping")
    return bundle["models"]


def contour_quad(image, roi, threshold, epsilon):
    x, y, width, height = roi
    gray = cv2.cvtColor(image[y:y+height, x:x+width], cv2.COLOR_BGR2GRAY)
    contours = cv2.findContours(cv2.inRange(gray, threshold, 255), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    contours = [c for c in contours if cv2.contourArea(c) >= 200]
    if len(contours) != 1:
        return None, dict(reason="not_one_contour", contour_count=len(contours))
    contour = contours[0]
    points = cv2.approxPolyDP(contour, epsilon * cv2.arcLength(contour, True), True)[:, 0, :] + [x, y]
    info = dict(contour_count=1, contour_area_px2=float(cv2.contourArea(contour)), vertices=len(points))
    if len(points) != 4:
        return None, dict(info, reason="not_four_vertices")
    try:
        return ordered_quad(points), dict(info, reason="quad_observed")
    except ValueError:
        return None, dict(info, reason="not_convex_quad")


def metrics(points, models, baseline, probes, camera, heading, session, bounds):
    mapping = assignment_branch_map(models, baseline)
    output = []
    for model in models:
        assignment = "as_listed" if "_as_listed_" in model["name"] else "swapped"
        raw_branch = model["name"].split(f"_{assignment}_")[1].split("_")[0]
        family = mapping[(assignment, raw_branch)]
        row = dict(assignment=assignment, raw_branch=raw_branch, tracked_branch=family,
                   branch_index_changed=raw_branch != family, height_source=model["height_source"],
                   height_mm=1000 * model["camera_to_floor_m"], reprojection_rmse_px=model["native_reprojection_rmse_px"])
        base = next(m for m in baseline if f"_{assignment}_{family}_" in m["name"] and m["height_source"] == model["height_source"])
        row["normal_change_deg"] = float(np.degrees(np.arccos(np.clip(
            np.array(base["normal_optical"]) @ model["normal_optical"], -1, 1))))
        for probe in probes:
            measured = audit.conditional_point(probe["point"], model, camera, heading, session, bounds)
            row[probe["id"] + "_range_m"] = measured["range_m"]
            row[probe["id"] + "_reason"] = measured["reason"]
        output.append(row)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    prep = Path(__file__).resolve().parent.parent / "physical_reference_review_r01/prepared_r01"
    queue_path = prep / "queue.json"
    queue = validate_queue(read_json(queue_path))
    decisions = load_decisions(prep / "decisions", queue, digest(queue_path))
    if len(decisions) != 6 or any(d["status"] != "reviewed" for d in decisions.values()):
        raise ValueError("all six explicit human visual decisions required")
    settings, camera, heading, _ = load_config()
    previous = Path(__file__).resolve().parent.parent / "reviewed_coordinate_audit_r01/results_r02"
    old_summary = read_json(previous / "summary.json")
    hashes = dict(old_summary["source_sha256"])
    paths = [Path(__file__), SPEC.origin, DEFAULT_CONFIG, ROOT / settings["camera_candidate"], ROOT / settings["floor_candidate"],
             previous / "summary.json", previous / "colour_pixel_vs_reviewed_edge.csv",
             previous / "b559e424_manual_visual_hypotheses_NOT_live.json",
             previous / "df33e833_manual_visual_hypotheses_NOT_live.json"]
    paths += [ROOT / "src" / name for name in ("derive_fixed_floor_live_bundle.py", "floor_reference_pose.py",
              "angular_fisheye_geometry.py", "cone_fixed_floor_candidate.py", "cone_distance_core.py", "review_physical_reference.py")]
    hashes.update({str(Path(p).relative_to(ROOT)): digest(p) for p in paths})
    if any(digest(ROOT / p) != sha for p, sha in hashes.items()):
        raise ValueError("reviewed analysis inputs changed")
    with (previous / "colour_pixel_vs_reviewed_edge.csv").open() as stream:
        offsets = list(csv.DictReader(stream))
    all_rows = []; scan_rows = []; jacobian = []; envelopes = []; baseline_rows = []; contours_json = []
    previous_models_checked = 0; primary_contours_reproduced = 0
    for paper in [i for i in queue["items"] if i["kind"] == "paper"]:
        session = paper["session"]; short = session[:8]
        item = item_image(paper); points = np.array(decisions[paper["id"]]["points_native_xy"])
        baseline = fit(points, item, settings, camera)
        stored = read_json(previous / (short + "_manual_visual_hypotheses_NOT_live.json"))["models"]
        for new, old in zip(baseline, stored):
            if new["name"] != old["name"] or abs(new["camera_to_floor_m"] - old["camera_to_floor_m"]) > 1e-12 or not np.allclose(new["normal_optical"], old["normal_optical"], atol=1e-12, rtol=0):
                raise ValueError("baseline differs from reviewed audit")
            previous_models_checked += 1
        probes = [dict(id="f" + r["frame"], point=[int(r["point_x"]), int(r["point_y"])], role=r["point_role"])
                  for r in offsets if r["session"] == session]
        # Rejected b559 f32654 stays explicitly hypothetical. No probes carry
        # a reported range label; all pixel probes are held fixed throughout.
        bounds = settings["diagnostic_range_m"]
        base_metrics = metrics(points, baseline, baseline, probes, camera, heading, session, bounds)
        baseline_rows += [dict(session=session, **r) for r in base_metrics]
        rows = []
        for case in perturbations():
            models = baseline if case["id"] == "baseline" else fit(points + case["offsets"], item, settings, camera)
            common = {k: v for k, v in case.items() if k != "offsets"}
            rows += [dict(session=session, **common, **r) for r in metrics(points + case["offsets"], models, baseline, probes, camera, heading, session, bounds)]
        all_rows += rows
        names = ["height_mm"] + [p["id"] + "_range_m" for p in probes]
        for base in base_metrics:
            same = [r for r in rows if all(r[k] == base[k] for k in ("assignment", "tracked_branch", "height_source"))]
            for corner, axis, step in itertools.product(range(4), "xy", (.25, .5, 1.)):
                pair = [next(r for r in same if r["kind"] == "one_coordinate" and r["corner"] == corner and r["axis"] == axis and r["delta"] == delta)
                        for delta in (-step, step)]
                for name in names:
                    derivative = None if any(r[name] is None for r in pair) else (pair[1][name] - pair[0][name]) / (2 * step)
                    jacobian.append(dict(session=session, assignment=base["assignment"], tracked_branch=base["tracked_branch"],
                                         height_source=base["height_source"], corner=corner, axis=axis, step_px=step,
                                         quantity=name, derivative_per_px=derivative, missing_pair=derivative is None))
            for amplitude in (.5, 1.):
                group = [r for r in same if r["kind"] == "all_coordinates_box_vertices" and r["amplitude"] == amplitude]
                for name in names:
                    vals = [r[name] for r in group if r[name] is not None]
                    envelopes.append(dict(session=session, assignment=base["assignment"], tracked_branch=base["tracked_branch"],
                                          height_source=base["height_source"], quantity=name, amplitude_px=amplitude,
                                          samples=len(group), available=len(vals), baseline_value=base[name],
                                          sampled_min=min(vals) if vals else None, sampled_max=max(vals) if vals else None,
                                          confidence_interval=False, global_bound=False))
        roi = (280, 395, 90, 50) if short == "b559e424" else (280, 390, 80, 40)
        old_ref = read_json(ROOT / f"Experimental_results/2026-11-04/floor_reference_{short}_r01/references.json")["frames"][0]
        primary_epsilon = .025 if short == "b559e424" else .02
        for threshold, epsilon in itertools.product((150, 170, 190), (.02, .025, .03, .04)):
            quad, info = contour_quad(item["image"], roi, threshold, epsilon)
            common = dict(session=session, threshold=threshold, epsilon=epsilon, **info)
            if quad is None:
                scan_rows.append(common); continue
            if threshold == 170 and epsilon == primary_epsilon:
                if not np.array_equal(quad, np.array(old_ref["corners_native_xy"])):
                    raise ValueError("primary contour no longer reproduces old corners")
                primary_contours_reproduced += 1
            common.update(max_corner_shift_from_manual_px=float(np.linalg.norm(quad - points, axis=1).max()),
                          mean_corner_shift_from_manual_px=float(np.linalg.norm(quad - points, axis=1).mean()))
            contours_json.append(dict(session=session, roi_xywh=roi, threshold=threshold, epsilon=epsilon, pixels=quad.tolist()))
            models = fit(quad, item, settings, camera)
            scan_rows += [dict(common, **r) for r in metrics(quad, models, baseline, probes, camera, heading, session, bounds)]
        print(f"Completed {short}: {len(rows)//8} perturbation cases; both dimensions and both branches retained", flush=True)
    # Avoid encoding perturbation corners/models as a loadable calibration.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for filename, rows in (("perturbation_metrics.csv", all_rows), ("baseline_metrics.csv", baseline_rows),
                           ("coordinate_derivatives.csv", jacobian), ("joint_stress_samples.csv", envelopes),
                           ("contour_scan.csv", scan_rows)):
        audit.write_csv(args.output_dir / filename, rows)
    audit.write_json(args.output_dir / "contour_coordinates.json", contours_json)
    # Graphs only, never export/annotate a camera image.
    fig, axes = audit.plt.subplots(2, 2, figsize=(11, 7), layout="constrained")
    for col, short in enumerate(("b559e424", "df33e833")):
        selection = [r for r in jacobian if r["session"].startswith(short) and r["assignment"] == "as_listed"
                     and r["tracked_branch"] == "s0" and r["height_source"] == "image_plane_plus_thickness" and r["step_px"] == .25]
        labels = [f"{c}{a}" for c in range(4) for a in "xy"]
        for row, quantity in enumerate(("height_mm", "f35562_range_m" if col == 0 else "f64232_range_m")):
            data = [r for r in selection if r["quantity"] == quantity]
            factor = 1. if row == 0 else 100.
            axes[row, col].bar(labels, [factor * r["derivative_per_px"] for r in data])
            axes[row, col].set_title(short + " / " + ("floor height" if row == 0 else "fixed colour-point range"))
            axes[row, col].set_ylabel("mm / native pixel" if row == 0 else "cm / native pixel")
            axes[row, col].axhline(0, color="k", lw=.6)
    fig.suptitle("Local central differences at +/-0.25 px / fixed first-listed family\nSensitivity, NOT a noise estimate or metric approval")
    fig.savefig(args.output_dir / "corner_sensitivity.png", dpi=150); audit.plt.close(fig)
    fig, axes = audit.plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for ax, short in zip(axes, ("b559e424", "df33e833")):
        for amplitude, color in ((.5, "tab:blue"), (1., "tab:orange")):
            vals = [r["height_mm"] for r in all_rows if r["session"].startswith(short) and r["assignment"] == "as_listed"
                    and r["tracked_branch"] == "s0" and r["height_source"] == "image_plane_plus_thickness"
                    and r["kind"] == "all_coordinates_box_vertices" and r["amplitude"] == amplitude]
            ax.plot(range(len(vals)), vals, ".", ms=3, label=f"Each x/y coordinate +/-{amplitude}px", color=color)
        ax.axhline(590., color="k", ls="--", label="Carried reported height (not fitted)")
        ax.set_title(short); ax.set_xlabel("Deterministic corner-offset combination"); ax.set_ylabel("Conditional floor height [mm]")
        ax.legend(fontsize=7)
    fig.suptitle("Sampled perturbation responses / NOT confidence intervals or global bounds")
    fig.savefig(args.output_dir / "height_stress_samples.png", dpi=150); audit.plt.close(fig)
    changed = [p for p, sha in hashes.items() if digest(ROOT / p) != sha]
    if changed:
        raise ValueError("source changed during audit: " + str(changed))
    summary = dict(status="COMPLETED_OFFLINE_SENSITIVITY_NOT_METRIC_APPROVAL", perturbation_rows=len(all_rows),
                   derivative_rows=len(jacobian), stress_summary_rows=len(envelopes), contour_scan_rows=len(scan_rows),
                   previous_models_reproduced=previous_models_checked, primary_contours_reproduced=primary_contours_reproduced,
                   branch_index_change_rows=sum(r["branch_index_changed"] for r in all_rows),
                   source_sha256=hashes, source_probes=offsets, all_eight_hypotheses_retained=True,
                   selected_model=None, statistical_uncertainty_estimated=False, global_error_bound_proven=False,
                   distances_used_to_fit_or_select=False, original_images_modified=False, runtime_changed=False,
                   physical_metric_verified=False, usable_for_ffb=False)
    audit.write_json(args.output_dir / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("source_sha256", "source_probes")}, indent=2))


if __name__ == "__main__":
    main()
