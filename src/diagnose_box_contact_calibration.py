#!/usr/bin/env python3
"""OFFLINE audit of contact coordinates, affine calibration and fixed-pixel geometry.

No coefficient fitting, runtime configuration writing, ROS or hardware output.
Historical nominal layouts are diagnostics, not trusted calibration targets.
Median selected pixels are approximate anchors, not actual recomputed contours.
"""
import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path

import numpy as np

from evaluate_raw_velocity_confidence_replay import sha256
from evaluate_velocity_confidence_replay import flag, number, write_csv
from ground_contact import dual_fisheye_pixels_to_vehicle_rays

VARIANTS = ("baseline", "seeded_s130_nearest", "seeded_s130_bottom")


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def calibrated_position(x, z, parameters):
    """Ground-contact branch only; legacy BEV scale and UI offsets are ignored."""
    if parameters.get("blue_position_method", "ground_contact") != "ground_contact":
        raise ValueError("ground_contact metadata required")
    return (x * parameters.get("blue_ground_contact_x_scale", 1.) + parameters.get("blue_ground_contact_x_offset_m", 0.),
            z + parameters.get("blue_ground_contact_z_offset_m", 0.))


def range_valid(x, z, p):
    return (abs(x) <= p.get("blue_calibration_input_x_max_m", .5)
            and p.get("blue_calibration_input_z_min_m", .65) <= z <= p.get("blue_calibration_input_z_max_m", 1.35))


def project_pixel(pixel, p, width=1280, height=720):
    """Same ray/plane projection and distance bounds as production, one pixel."""
    _, rays = dual_fisheye_pixels_to_vehicle_rays(np.asarray([pixel]), width, height, p)
    if len(rays) != 1 or rays[0, 1] >= -.03:
        return None
    h = float(p["camera_height"])
    if not math.isfinite(h) or h <= 0:
        raise ValueError("positive finite camera_height required")
    scale = -h / rays[0, 1]
    x, z = float(scale * rays[0, 0]), float(scale * rays[0, 2])
    if z <= 0 or not .20 <= math.hypot(x, z) <= 4.0:
        return None
    return x, z


def audit_rows(rows, p):
    errors = []
    valid_mismatches = 0
    for row in rows:
        if not flag(row, "detected"):
            continue
        raw_x, raw_z = number(row, "raw_contact_x_m"), number(row, "raw_contact_z_m")
        if raw_x is None or raw_z is None:
            raise ValueError("detected row missing raw geometry")
        x, z = calibrated_position(raw_x, raw_z, p)
        stored = number(row, "x_m"), number(row, "z_m")
        if None in stored:
            raise ValueError("detected row missing calibrated geometry")
        errors.append(max(abs(x - stored[0]), abs(z - stored[1])))
        valid_mismatches += range_valid(x, z, p) != flag(row, "calibration_valid")
    if any(e > 1e-10 for e in errors) or valid_mismatches:
        raise ValueError("stored result differs from recorded ground-contact calibration")
    return {"detected_audited": len(errors), "maximum_coordinate_difference_m": max(errors) if errors else None,
            "range_valid_mismatches": valid_mismatches}


def summarize_reference(rows, reference, p):
    start, end = int(reference["start_frame"]), int(reference["end_frame"])
    if start < 1 or end < start:
        raise ValueError("inclusive one-based reference bounds required")
    selected = [r for r in rows if start <= int(r["frame"]) <= end]
    if [int(r["frame"]) for r in selected] != list(range(start, end + 1)):
        raise ValueError("reference has missing frames")
    detected = [r for r in selected if flag(r, "detected")]
    result = {"session": reference["session"], "variant": rows[0]["variant"],
              "reference_kind": reference["reference_kind"], "frames": len(selected), "detected": len(detected),
              "accepted": sum(flag(r, "measurement_accepted") for r in selected),
              "reference_quality": "nominal_layout_not_for_fitting" if reference["reference_kind"] == "static_layout" else "user_initial_distance_only",
              "reference_origin": reference.get("reference_origin", "unconfirmed"),
              "x_scale": p.get("blue_ground_contact_x_scale", 1.), "x_offset_m": p.get("blue_ground_contact_x_offset_m", 0.),
              "z_offset_m": p.get("blue_ground_contact_z_offset_m", 0.)}
    for axis in ("x", "z", "distance"):
        expected = number(reference, "expected_" + axis + "_m")
        result["expected_" + axis + "_m"] = expected
        for stage in ("raw", "current"):
            values = []
            for row in detected:
                prefix = "raw_contact_" if stage == "raw" else ""
                if axis == "distance":
                    value = math.hypot(number(row, prefix + "x_m"), number(row, prefix + "z_m"))
                else:
                    value = number(row, prefix + axis + "_m")
                values.append(value)
            result[f"{stage}_{axis}_median_m"] = float(np.median(values)) if values else None
            result[f"{stage}_{axis}_mae_m"] = float(np.mean([abs(v - expected) for v in values])) if values and expected is not None else None
        result[f"calibration_{axis}_median_shift_m"] = (result[f"current_{axis}_median_m"] - result[f"raw_{axis}_median_m"]) if detected else None
    for axis in ("x", "y"):
        values = [number(r, "contact_pixel_" + axis) for r in detected]
        result["anchor_pixel_" + axis] = float(np.median(values)) if values else None
    if detected:
        anchor = project_pixel((result["anchor_pixel_x"], result["anchor_pixel_y"]), p)
        result["anchor_projection_x_m"] = anchor[0] if anchor else None
        result["anchor_projection_z_m"] = anchor[1] if anchor else None
        result["anchor_minus_actual_raw_x_m"] = anchor[0] - result["raw_x_median_m"] if anchor else None
        result["anchor_minus_actual_raw_z_m"] = anchor[1] - result["raw_z_median_m"] if anchor else None
    return result


def paired_spans(summaries):
    result = []
    groups = defaultdict(list)
    for row in summaries:
        if row["reference_kind"] == "static_layout":
            groups[row["variant"], row["expected_z_m"]].append(row)
    for (variant, depth), rows in groups.items():
        left = [r for r in rows if r["expected_x_m"] < 0]
        right = [r for r in rows if r["expected_x_m"] > 0]
        if len(left) != 1 or len(right) != 1:
            raise ValueError("exactly one left/right nominal point needed per depth")
        a, b = left[0], right[0]
        expected = b["expected_x_m"] - a["expected_x_m"]
        raw_span = b["raw_x_median_m"] - a["raw_x_median_m"]
        current_span = b["current_x_median_m"] - a["current_x_median_m"]
        if raw_span <= 0 or expected <= 0:
            raise ValueError("positive span needed")
        if a["x_scale"] != b["x_scale"] or a["x_offset_m"] != b["x_offset_m"]:
            raise ValueError("paired spans require common recorded lateral calibration")
        result.append({"variant": variant, "expected_z_m": depth, "nominal_span_m": expected,
                       "raw_span_m": raw_span, "current_span_m": current_span,
                       "current_span_over_nominal": current_span / expected,
                       "pair_midpoint_bias_m": (b["current_x_median_m"] + a["current_x_median_m"] - b["expected_x_m"] - a["expected_x_m"]) / 2,
                       "nominal_implied_x_scale_not_fitted_or_approved": expected / raw_span})
    return result


def sensitivity_rows(summary, p):
    if summary["anchor_pixel_x"] is None:
        return []
    pixel = (summary["anchor_pixel_x"], summary["anchor_pixel_y"])
    base = project_pixel(pixel, p)
    if base is None:
        return []
    changes = [("pixel_y", d) for d in (-5., -1., 1., 5.)]
    changes += [(name, d) for name, step in (("camera_height", .01), ("pitch_deg", 1.), ("roll_deg", 1.), ("front_cy_offset", 1.)) for d in (-step, step)]
    result = []
    for parameter, delta in changes:
        q = dict(p)
        point = pixel
        if parameter == "pixel_y":
            point = pixel[0], pixel[1] + delta
        else:
            q[parameter] = p.get(parameter, 0.) + delta
        projected = project_pixel(point, q)
        result.append({"session": summary["session"], "variant": summary["variant"], "parameter": parameter,
                       "delta": delta, "anchor_pixel_x": pixel[0], "anchor_pixel_y": pixel[1],
                       "base_raw_x_m": base[0], "base_raw_z_m": base[1], "projection_valid": int(projected is not None),
                       "raw_x_change_m": projected[0] - base[0] if projected else None,
                       "raw_z_change_m": projected[1] - base[1] if projected else None,
                       "kind": "FIXED_PIXEL_SENSITIVITY_NOT_REPLAY_OR_CALIBRATION_FIT"})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-dir", action="append", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--trusted-points", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    groups, parameters, inputs = defaultdict(list), {}, [args.references, args.trusted_points]
    frozen_settings = frozen_hash = None
    for root in args.comparison_dir:
        prov = json.loads((root / "provenance.json").read_text())
        settings, code_hash = prov["settings"], prov["implementation_sha256"]["offline_box_contact_candidates.py"]
        if frozen_settings is not None and (settings != frozen_settings or code_hash != frozen_hash):
            raise ValueError("frozen contact candidates differ across comparisons")
        frozen_settings, frozen_hash = settings, code_hash
        for source in prov["sources"]:
            if source["session"] in parameters:
                raise ValueError("duplicate source session")
            parameters[source["session"]] = source["parameters"]
        for row in read(root / "frame_results.csv"):
            if row["variant"] in VARIANTS:
                groups[row["session"], row["variant"]].append(row)
        inputs += [root / "provenance.json", root / "frame_results.csv"]
    audits = [dict(session=s, variant=v, **audit_rows(rows, parameters[s])) for (s, v), rows in groups.items()]
    summaries, sensitivities = [], []
    for reference in read(args.references):
        for variant in VARIANTS:
            s = reference["session"]
            summary = summarize_reference(groups[s, variant], reference, parameters[s])
            summaries.append(summary)
            sensitivities.extend(sensitivity_rows(summary, parameters[s]))
    trusted = []
    by_dataset = defaultdict(list)
    for row in read(args.trusted_points):
        if row["role"] == "trusted":
            by_dataset[row["dataset"]].append(row)
    for dataset, rows in by_dataset.items():
        trusted.append({"dataset": dataset, "points": len(rows), "source_kind": "historical_baseline_points_not_candidate_replay",
                        "x_mae_m": float(np.mean([abs(float(r["median_current_x_m"]) - float(r["expected_x_m"])) for r in rows])),
                        "z_mae_m": float(np.mean([abs(float(r["median_current_z_m"]) - float(r["expected_z_m"])) for r in rows]))})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("calibration_audit.csv", audits), ("coordinate_decomposition.csv", summaries),
                       ("paired_lateral_spans.csv", paired_spans(summaries)), ("geometry_sensitivity.csv", sensitivities),
                       ("trusted_baseline_reference.csv", trusted)):
        write_csv(args.output_dir / name, rows)
    code = (Path(__file__).name, "ground_contact.py", "evaluate_raw_velocity_confidence_replay.py", "bird_eye.py")
    (args.output_dir / "provenance.json").write_text(json.dumps({
        "scope": "OFFLINE_CALIBRATION_DIAGNOSIS_NO_FITTING", "frame_shape": [720, 1280],
        "inputs_sha256": {str(p.resolve()): sha256(p) for p in inputs},
        "implementation_sha256": {n: sha256(Path(__file__).with_name(n)) for n in code},
        "candidate_settings": frozen_settings, "candidate_implementation_sha256": frozen_hash,
        "nominal_layouts_used_to_fit": False, "runtime_changed": False,
        "limits": ["nominal placement labels not independent calibration ground truth",
                   "initial 1.3m origin confirmed as camera-under/Kobuki centre; x/z components and exact box endpoint unconfirmed",
                   "geometry sensitivity freezes a median pixel, not the mask or contour algorithm",
                   "historical trusted points have no raw-video candidate replay here",
                   "camera/robot rigid translation unknown; UI offsets not physical extrinsics"]}, indent=2) + "\n")
    print(f"Audited {len(audits)} session/variant groups; decomposed {len(summaries)} intervals; no fitting or runtime changes.")


if __name__ == "__main__":
    main()
