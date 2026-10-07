"""Offline decomposition only: frozen contacts, manual edge and ray geometry.

Never fits coefficients, changes runtime settings, or sends ROS/hardware output.
Manual edge estimates are nonblind illustration, not independent ground truth.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
from analyze_distance_reference import read, write_csv, CONDITIONS, REFERENCE
from diagnose_box_contact_calibration import (
    audit_rows, calibrated_position, project_pixel, sensitivity_rows, summarize_reference,
)
from evaluate_raw_velocity_confidence_replay import sha256
from ground_contact import detect_blue_ground_contact
from offline_box_contact_candidates import (
    BoxCandidateSettings, component_contact, seeded_components, select_component,
)

VARIANTS = ("baseline", "seeded_s130_nearest", "seeded_s130_bottom")


def nominal_pixel_y(x, expected_raw_z, parameters):
    """Solve ONE fixed-x floor ray, not a contour/contact estimator or calibration.

    Require exactly one decreasing, valid crossing in a predeclared image span.
    No extrapolation or treating invalid rays as zero distance.
    """
    samples = [(float(y), project_pixel((x, y), parameters)) for y in range(360, 601)]
    brackets = [(a[0], b[0]) for a, b in zip(samples, samples[1:])
                if a[1] is not None and b[1] is not None
                and a[1][1] >= expected_raw_z >= b[1][1]
                and a[1][1] > b[1][1]]
    if not brackets:
        return None
    # A target exactly on a grid value may give two adjacent brackets.
    if len(brackets) > 2 or (len(brackets) == 2 and brackets[0][1] != brackets[1][0]):
        raise ValueError("ambiguous inverse projection")
    low, high = brackets[0][0], brackets[-1][1]
    for _ in range(48):
        middle = (low + high) / 2
        point = project_pixel((x, middle), parameters)
        if point is None:
            raise ValueError("invalid projection inside bracket")
        if point[1] > expected_raw_z:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def edge_projection(edge, parameters, nominal):
    x, y, half = (float(edge[k]) for k in ("pixel_x", "pixel_y", "assumed_pixel_half_width"))
    if half < 0:
        raise ValueError("nonnegative pixel band required")
    # All integer pixels in a declared square, not a confidence interval.
    samples = [project_pixel((x + dx, y + dy), parameters)
               for dx in np.arange(-half, half + .01, 1.)
               for dy in np.arange(-half, half + .01, 1.)]
    if not samples or any(p is None for p in samples):
        raise ValueError("manual pixel band includes invalid floor ray")
    anchor = project_pixel((x, y), parameters)
    offset = float(parameters.get("blue_ground_contact_z_offset_m", 0.))
    zs = [p[1] + offset for p in samples]
    inverse = nominal_pixel_y(x, nominal - offset, parameters)
    return dict(manual_pixel_x=x, manual_pixel_y=y, assumed_pixel_half_width=half,
                manual_anchor_raw_z_m=anchor[1], manual_anchor_z_m=anchor[1] + offset,
                manual_band_z_min_m=min(zs), manual_band_z_max_m=max(zs),
                nominal_inside_assumed_pixel_band=int(min(zs) <= nominal <= max(zs)),
                model_pixel_y_for_nominal=inverse,
                model_y_minus_manual_y_px=inverse - y if inverse is not None else None,
                reference_quality=REFERENCE["reference_quality"],
                review_kind=edge["review_kind"])


def common_error_intervals(edge, nominal, parameters):
    """Inverse feasibility bounds, NOT fitted or recommended corrections.

    Floor Z is linear in camera height at fixed rays. These bounds assume the
    reported Z exactly and the illustrative manual pixel square, not true
    measurement uncertainty. Height and extra Z offset are tested separately.
    """
    height = float(parameters["camera_height"])
    offset = float(parameters.get("blue_ground_contact_z_offset_m", 0.))
    low, high = (float(edge[k]) for k in ("manual_band_z_min_m", "manual_band_z_max_m"))
    if height <= 0 or low <= offset or high < low or nominal <= offset:
        raise ValueError("positive forward raw Z and positive camera height required")
    return [dict(parameter="camera_height_m", lower=height*(nominal-offset)/(high-offset),
                 upper=height*(nominal-offset)/(low-offset)),
            dict(parameter="additional_z_offset_m", lower=nominal-high, upper=nominal-low)]


def intersect_intervals(rows):
    if not rows:
        raise ValueError("nonempty interval collection required")
    if len({r["parameter"] for r in rows}) != 1:
        raise ValueError("cannot mix parameters")
    if any(r["lower"] > r["upper"] for r in rows):
        raise ValueError("reversed input interval")
    low, high = max(r["lower"] for r in rows), min(r["upper"] for r in rows)
    return dict(parameter=rows[0]["parameter"], intersection_lower=low, intersection_upper=high,
                common_value_possible=low <= high, separation_gap=max(0., low-high))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", type=Path, required=True)
    args = parser.parse_args()
    comparison = HERE / "frozen_comparison"
    provenance = json.loads((comparison / "provenance.json").read_text())
    if not (provenance["frozen_candidate_check"]["settings_match"]
            and provenance["frozen_candidate_check"]["candidate_implementation_matches"]):
        raise ValueError("candidate comparison not frozen")
    settings = BoxCandidateSettings(**provenance["settings"])
    frozen_code = provenance["implementation_sha256"]["offline_box_contact_candidates.py"]
    if sha256(REPO / "src/offline_box_contact_candidates.py") != frozen_code:
        raise ValueError("candidate implementation changed")
    groups = defaultdict(list)
    for row in read(comparison / "frame_results.csv"):
        groups[row["session"], row["variant"]].append(row)
    sources = {s["session"]: s for s in provenance["sources"]}
    reviews = {(r["condition"], int(r["frame"])): r
               for r in read(HERE / "review_frame_manifest.csv")}
    manual = read(HERE / "manual_lower_edge.csv")
    audits, decomposed, sensitivities, edges, replay_checks, motion_checks = [], [], [], [], [], []
    input_hashes = {str(path.relative_to(REPO)): sha256(path) for path in (
        comparison / "frame_results.csv", comparison / "provenance.json",
        HERE / "manual_lower_edge.csv", HERE / "review_frame_manifest.csv",
        HERE / "reference_conditions.json")}
    representative = {}
    cv2.setNumThreads(1)
    for condition, nominal in CONDITIONS.items():
        matches = list((args.session_root / condition).rglob("metadata.json"))
        if len(matches) != 1:
            raise ValueError("exactly one session required per condition")
        session = matches[0].parent
        parameters = json.loads(matches[0].read_text())["parameters"]
        if parameters != sources[session.name]["parameters"]:
            raise ValueError("metadata differs from frozen comparison")
        before = json.dumps(parameters, sort_keys=True)
        for filename in ("metadata.json", "detections.csv", "raw.avi"):
            input_hashes[str(session / filename)] = sha256(session / filename)
        live = read(session / "detections.csv")
        maximum_error = 0.
        for row in live:
            if row["detected"] != "1":
                continue
            calculated = calibrated_position(float(row["raw_x_m"]), float(row["raw_z_m"]), parameters)
            error = max(abs(calculated[0] - float(row["x_m"])), abs(calculated[1] - float(row["z_m"])))
            maximum_error = max(maximum_error, error)
        # Live CSV rounds raw and calibrated positions independently to 4 decimals.
        if maximum_error > .00011:
            raise ValueError("live calibration mismatch exceeds rounding tolerance")
        after2 = [r for r in live if r["detected"] == "1" and float(r["time_sec"]) >= 2.]
        audits.append(dict(session=session.name, variant="live", frames=len(live),
            maximum_coordinate_difference_m=maximum_error, tolerance_m=.00011,
            live_norm_comparison_window="all_detections_after_2s",
            live_median_z_m=float(np.median([float(r["z_m"]) for r in after2])) if after2 else None,
            live_median_planar_distance_m=float(np.median([float(r["distance_m"]) for r in after2])) if after2 else None,
            live_planar_minus_forward_p95_m=float(np.percentile([
                float(r["distance_m"])-float(r["z_m"]) for r in after2],95)) if after2 else None))
        for variant in VARIANTS:
            rows = groups[session.name, variant]
            if [int(r["frame"]) for r in rows] != list(range(1, len(live) + 1)):
                raise ValueError("missing/reordered frozen frames")
            if [float(r["time_sec"]) for r in rows] != [float(r["time_sec"]) for r in live]:
                raise ValueError("frozen/live times differ")
            audits.append(dict(session=session.name, variant=variant, frames=len(rows),
                               **audit_rows(rows, parameters), tolerance_m=1e-10))
            if nominal is None:
                continue
            start = next(int(r["frame"]) for r in rows if float(r["time_sec"]) >= 2.)
            reference = dict(session=session.name, reference_kind="static_center_nominal",
                             start_frame=start, end_frame=len(rows), expected_x_m=0.,
                             expected_z_m=nominal, expected_distance_m="", reference_origin=REFERENCE["reference_origin"])
            summary = summarize_reference(rows, reference, parameters)
            summary["reference_quality"] = REFERENCE["reference_quality"]
            # summarize_reference's fallback is intended for historical initial-only layouts.
            summary["condition"] = condition
            decomposed.append(summary)
            sensitivities.extend(sensitivity_rows(summary, parameters))
        if nominal is not None:
            edge = next(r for r in manual if r["condition"] == condition)
            target = int(edge["frame"])
            cap = cv2.VideoCapture(str(session / "raw.avi"))
            try:
                frame = None
                for _ in range(target):
                    ok, frame = cap.read()
                    if not ok:
                        raise ValueError("video shorter than manual review frame")
            finally:
                cap.release()
            pixel_hash = hashlib.sha256(frame.tobytes()).hexdigest()
            if frame.shape != (720, 1280, 3) or pixel_hash != reviews[condition, target]["decoded_bgr_pixels_sha256"]:
                raise ValueError("manual review pixels differ from raw")
            representative[condition] = (frame, pixel_hash, target, session.name)
            edges.append(dict(condition=condition, session=session.name, frame=target,
                              **edge_projection(edge, parameters, nominal)))
            q = dict(parameters, blue_ground_contact_hsv_s_min=max(
                settings.body_s_min, parameters.get("blue_ground_contact_hsv_s_min", 70)))
            component = select_component(seeded_components(frame, q, settings), frame.shape, q)
            baseline, _ = detect_blue_ground_contact(frame, parameters,
                min_area_px=parameters.get("blue_ground_contact_min_area", 300),
                contact_fraction=parameters.get("blue_ground_contact_fraction", .08))
            contacts = dict(baseline=baseline,
                seeded_s130_nearest=component_contact(component, frame.shape, q, settings),
                seeded_s130_bottom=component_contact(component, frame.shape, q, settings, bottom=True))
            for variant, contact in contacts.items():
                row = groups[session.name, variant][target - 1]
                if contact is None:
                    raise ValueError("representative frame contact missing")
                difference = max(abs(contact[k] - float(row[column])) for k, column in (
                    ("x_m", "raw_contact_x_m"), ("z_m", "raw_contact_z_m"),
                    ("pixel_x", "contact_pixel_x"), ("pixel_y", "contact_pixel_y")))
                if difference > 1e-9:
                    raise ValueError("exact representative contact replay mismatch")
                replay_checks.append(dict(condition=condition, variant=variant, frame=target,
                    maximum_replay_difference=difference, raw_z_m=contact["z_m"],
                    contact_pixel_x=contact["pixel_x"], contact_pixel_y=contact["pixel_y"],
                    contact_y_minus_manual_y_px=contact["pixel_y"]-float(edge["pixel_y"])))
            # Fixed manual pixel, ONE predeclared parameter change at a time.
            # These are counterfactual illustrations, never fitted/adopted settings.
            for name, step in (("camera_height", .01), ("pitch_deg", 1.), ("front_cy_offset", 1.)):
                for sign in (-1, 1):
                    changed = dict(parameters, **{name: parameters.get(name, 0.) + sign * step})
                    point = project_pixel((float(edge["pixel_x"]), float(edge["pixel_y"])), changed)
                    motion_checks.append(dict(condition=condition, parameter=name, delta=sign*step,
                        projection_valid=int(point is not None),
                        changed_anchor_z_m=point[1] if point is not None else None,
                        nominal_bias_m=point[1]-nominal if point is not None else None,
                        kind="FIXED_PIXEL_COUNTERFACTUAL_NOT_FITTED_NOT_REPLAY"))
        if json.dumps(parameters, sort_keys=True) != before:
            raise ValueError("recorded parameters mutated")
    for name, rows in (("geometry_calibration_audit.csv", audits),
        ("geometry_coordinate_decomposition.csv", decomposed), ("geometry_sensitivity.csv", sensitivities),
        ("manual_edge_projection.csv", edges), ("representative_contact_replay.csv", replay_checks),
        ("common_parameter_counterfactual.csv", motion_checks)):
        write_csv(HERE / name, rows)
    bounds = []
    for edge in edges:
        for interval in common_error_intervals(edge, CONDITIONS[edge["condition"]], sources[edge["session"]]["parameters"]):
            bounds.append(dict(condition=edge["condition"], **interval,
                assumptions="exact_reported_Z_and_illustrative_manual_pixel_band_only",
                purpose="INVERSE_FEASIBILITY_NOT_FITTED_OR_RECOMMENDED"))
    intersections = [intersect_intervals([r for r in bounds if r["parameter"] == name])
                     for name in ("camera_height_m", "additional_z_offset_m")]
    write_csv(HERE / "common_error_intervals.csv", bounds)
    (HERE / "common_error_consistency.json").write_text(json.dumps(dict(
        reference_conditions=REFERENCE, separate_one_parameter_hypotheses=intersections,
        conditional_only=True, measurement_uncertainty_not_modelled=True,
        pixel_band_not_independent_ground_truth=True, parameter_search_or_fit=False,
        limits="Does not rule out joint pose/lens errors, endpoint effects or manual edge errors."), indent=2)+"\n")
    fig, axes = plt.subplots(1,2,figsize=(10,4))
    for ax, parameter, current in zip(axes, ("camera_height_m","additional_z_offset_m"), (.58,0.)):
        selected=[r for r in bounds if r["parameter"]==parameter]
        for i,row in enumerate(selected):
            ax.hlines(i, row["lower"]*100, row["upper"]*100, color=f"C{i}", linewidth=5)
        ax.axvline(current*100, color="black", linestyle="--", label="Recorded setting / no extra offset")
        ax.set_yticks(range(len(selected)),[r["condition"] for r in selected])
        ax.set_xlabel(parameter+f" [cm]; dashed = {current*100:g}")
        ax.set_title("Separate hypothesis: "+parameter)
        ax.grid(alpha=.25)
    fig.suptitle("Conditional compatibility: exact reported Z + visual edge +/-2 px; NOT fitted corrections",fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE/"common_error_consistency.png",dpi=150)
    plt.close(fig)
    # Keep new raw assets byte-for-pixel identical to sequentially decoded raw.
    assets = HERE.parent / "report_assets"
    manifest = []
    for condition in ("z0p90", "z1p30"):
        frame, pixel_hash, target, session = representative[condition]
        path = assets / f"distance_reference_{condition}_raw_frame_{target:04d}.png"
        if path.exists():
            saved = cv2.imread(str(path))
        else:
            if not cv2.imwrite(str(path), frame):
                raise ValueError("raw asset writing failed")
            saved = cv2.imread(str(path))
        if saved is None or saved.shape != frame.shape or not np.array_equal(saved, frame):
            raise ValueError("saved raw asset changed pixels")
        manifest.append(dict(condition=condition, session=session, frame=target,
            raw_png=str(path.relative_to(REPO)), decoded_bgr_pixels_sha256=pixel_hash))
    write_csv(HERE / "geometry_raw_asset_manifest.csv", manifest)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    xs = np.array([CONDITIONS[r["condition"]] for r in edges])
    medians = np.array([r["manual_anchor_z_m"] for r in edges])
    axes[0].errorbar(xs, medians, yerr=np.array([
        medians - np.array([r["manual_band_z_min_m"] for r in edges]),
        np.array([r["manual_band_z_max_m"] for r in edges]) - medians]), fmt="o", capsize=5,
        label="Visual edge +/-2 px: illustrative range")
    axes[0].plot(xs, xs, "k--", label="Reported distance (origin confirmed)")
    for variant, marker in zip(VARIANTS, ("s", "^", "x")):
        selected = [next(r for r in decomposed if r["condition"] == c and r["variant"] == variant)
                    for c in ("z0p90", "z1p10", "z1p30")]
        axes[0].plot(xs, [r["raw_z_median_m"] for r in selected], marker, label=variant)
    axes[0].set(xlabel="Filename nominal Z (m)", ylabel="Projected Z (m)", title="Edge / frozen contact / nominal")
    axes[0].legend(fontsize=7)
    labels = ["pixel_y +1 px", "height +1 cm", "pitch +1 degree", "lens_cy +1 px"]
    for edge in edges:
        row = next(r for r in decomposed if r["condition"] == edge["condition"]
                   and r["variant"] == "seeded_s130_bottom")
        choices = (("pixel_y", 1.), ("camera_height", .01), ("pitch_deg", 1.), ("front_cy_offset", 1.))
        changes = [next(r["raw_z_change_m"] for r in sensitivities if r["session"] == row["session"]
            and r["variant"] == "seeded_s130_bottom" and r["parameter"] == name and r["delta"] == delta)
            for name, delta in choices]
        axes[1].plot(labels, np.array(changes)*100, "o-", label=edge["condition"])
    axes[1].axhline(0, color="black", linewidth=.6)
    axes[1].set(ylabel="Fixed-anchor Z change (cm)", title="Sensitivity only: not a calibration fit")
    axes[1].tick_params(axis="x", labelrotation=20)
    axes[1].legend()
    for ax in axes:
        ax.grid(alpha=.25)
    fig.suptitle("2026-10-07: origin confirmed, height/tilt unchanged; absolute pose / uncertainty unmeasured", fontsize=10)
    fig.tight_layout()
    fig.savefig(HERE / "distance_geometry_diagnosis.png", dpi=150)
    plt.close(fig)
    code = (Path(__file__), REPO / "src/diagnose_box_contact_calibration.py",
        REPO / "src/ground_contact.py", REPO / "src/offline_box_contact_candidates.py",
        REPO / "src/bird_eye.py", HERE / "analyze_distance_reference.py")
    (HERE / "geometry_verification.json").write_text(json.dumps(dict(
        decision="PASS_OFFLINE_DIAGNOSTIC_CONSISTENCY_NOT_METRIC_ACCURACY",
        audit_groups=len(audits), decomposition_groups=len(decomposed),
        sensitivity_rows=len(sensitivities), representative_exact_replays=len(replay_checks),
        manual_points=len(edges), saved_raw_assets_pixel_equal=len(manifest),
        metadata_unchanged=True, coefficient_fitting=False, runtime_changed=False,
        ros_or_hardware_output=False, manual_review_blinded=False,
        physical_reference_confirmed=False, reference_conditions=REFERENCE,
        reference_origin_confirmed=REFERENCE["reference_origin_confirmed"],
        absolute_physical_pose_measured=False, pixel_band_is_confidence_interval=False,
        inputs_sha256=input_hashes, implementation_sha256={str(p.relative_to(REPO)):sha256(p) for p in code}),
        indent=2) + "\n")
    print(json.dumps(dict(audits=len(audits), exact_replays=len(replay_checks), edges=edges), indent=2))


if __name__ == "__main__":
    main()
