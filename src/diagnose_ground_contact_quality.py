#!/usr/bin/env python3
"""OFFLINE contour/contact quality diagnostics. No measurement gate or ROS output.

Indicators describe the segmented contour, not ground-truth box boundaries or
calibrated distance uncertainty. Production detector/geometry are left unchanged.
"""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
import statistics

import cv2
import numpy as np

from evaluate_observation_gates import contour_shape_features, find_session_directories
from evaluate_raw_velocity_confidence_replay import sha256, validate_rows
from evaluate_velocity_confidence_replay import flag, number, write_csv
from ground_contact import (_lens_geometry, blue_preprocessed_hsv, detect_blue_ground_contact,
                            dual_fisheye_pixels_to_vehicle_rays, estimate_ground_contact)


DETECTOR_KEYS = {"blue_ground_contact_min_area", "blue_ground_contact_fraction", "blue_ground_contact_max_aspect_ratio",
                 "blue_ground_contact_illumination_mode", "blue_ground_contact_shades_of_gray_power",
                 "blue_ground_contact_clahe_clip_limit", "blue_ground_contact_clahe_tile_size"}


def percentile(values, q):
    return float(np.percentile(values, q)) if len(values) else None


def contact_distribution(contour, shape, parameters):
    """Recreate selected geometry samples ONLY to inspect their distribution."""
    pixels, rays = dual_fisheye_pixels_to_vehicle_rays(contour[:, 0, :], shape[1], shape[0], parameters)
    downward = rays[:, 1] < -.03
    pixels, rays = pixels[downward], rays[downward]
    if not len(rays):
        return None
    scale = -float(parameters["camera_height"]) / rays[:, 1]
    ground = np.column_stack((scale * rays[:, 0], scale * rays[:, 2]))
    distance = np.linalg.norm(ground, axis=1)
    valid = (scale > 0) & (ground[:, 1] > 0) & (distance >= .2) & (distance <= 4)
    ground, pixels, distance = ground[valid], pixels[valid], distance[valid]
    if len(ground) < 3:
        return None
    fraction = min(max(float(parameters.get("blue_ground_contact_fraction", .08)), .01), .5)
    count = max(3, math.ceil(len(ground) * fraction))
    indices = np.argpartition(distance, count - 1)[:count]
    selected, selected_pixels = ground[indices], pixels[indices]
    return {"contact_samples": count, "ground_valid_fraction": len(ground) / len(contour),
            "contact_x_m": float(np.median(selected[:, 0])), "contact_z_m": float(np.median(selected[:, 1])),
            "contact_pixel_x": float(np.median(selected_pixels[:, 0])), "contact_pixel_y": float(np.median(selected_pixels[:, 1])),
            "contact_z_iqr_m": percentile(selected[:, 1], 75) - percentile(selected[:, 1], 25),
            "contact_z_span_m": float(np.ptp(selected[:, 1])),
            "contact_y_span_px": float(np.ptp(selected_pixels[:, 1]))}


def box_iou(a, b):
    x = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    y = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    union = a[2] * a[3] + b[2] * b[3] - x * y
    return x * y / union if union else 0.0


def describe_frame(frame, parameters):
    p = parameters
    contact, mask = detect_blue_ground_contact(frame, p, min_area_px=p.get("blue_ground_contact_min_area", 300),
                                               contact_fraction=p.get("blue_ground_contact_fraction", .08))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cx, cy, radius, _ = _lens_geometry(frame.shape[1], frame.shape[0], p, "front")
    minimum = p.get("blue_ground_contact_min_area", 300)
    configured_aspect = p.get("blue_ground_contact_max_aspect_ratio")
    aspect_limit = math.inf if configured_aspect is None else float(configured_aspect)
    shape_candidates, eligible = [], []
    counts = Counter()
    for contour in contours:
        area = cv2.contourArea(contour)
        x, y, w, h = cv2.boundingRect(contour)
        if area < minimum:
            counts["small"] += 1
            continue
        if y + h / 2 < cy - .04 * radius or math.hypot(x + w / 2 - cx, y + h / 2 - cy) > .9 * radius:
            counts["outside_front_roi"] += 1
            continue
        shape_candidates.append(contour)
        if w / max(h, 1) > aspect_limit:
            counts["aspect"] += 1
        else:
            eligible.append(contour)
    selected = max(eligible, key=cv2.contourArea) if eligible else None
    feature_contour = selected if selected is not None else (max(shape_candidates, key=cv2.contourArea) if shape_candidates else None)
    reason = ("detected" if contact is not None else "ground_geometry_invalid" if selected is not None
              else "only_aspect_rejected" if shape_candidates else "no_front_roi_contour_above_area")
    result = {"video_detected": int(contact is not None), "detector_reason": reason,
              "contours_total": len(contours), "front_roi_contours_above_area": len(shape_candidates),
              "aspect_rejected_contours": counts["aspect"], "eligible_contours": len(eligible),
              "feature_contour_role": "selected" if selected is not None else "pre_aspect_reference" if feature_contour is not None else "none",
              "bbox_x": None, "bbox_y": None, "bbox_width_px": None, "bbox_height_px": None,
              "bbox_aspect_ratio": None, "bbox_fill_ratio": None, "contour_solidity": None,
              "area_px": None, "dark_blue_hs_fraction": None, "contact_samples": None,
              "ground_valid_fraction": None, "contact_x_m": None, "contact_z_m": None,
              "contact_pixel_x": None, "contact_pixel_y": None, "contact_z_iqr_m": None,
              "contact_z_span_m": None, "contact_y_span_px": None, "fraction_z_sensitivity_m": None}
    if feature_contour is not None:
        x, y, w, h = cv2.boundingRect(feature_contour)
        result.update(bbox_x=x, bbox_y=y, area_px=float(cv2.contourArea(feature_contour)), **contour_shape_features(feature_contour))
        hsv = blue_preprocessed_hsv(frame, p)[y:y + h, x:x + w]
        hs = ((hsv[:, :, 0] >= p.get("blue_ground_contact_hsv_h_min", 90))
              & (hsv[:, :, 0] <= p.get("blue_ground_contact_hsv_h_max", 140))
              & (hsv[:, :, 1] >= p.get("blue_ground_contact_hsv_s_min", 70))
              & (hsv[:, :, 1] <= p.get("blue_ground_contact_hsv_s_max", 255)))
        result["dark_blue_hs_fraction"] = float(np.mean(hsv[:, :, 2][hs] < p.get("blue_ground_contact_hsv_v_min", 30))) if hs.any() else None
    # A rejected contour can have shape features, but MUST NOT be assigned a
    # successful contact or hypothetical distance in the frame-result columns.
    if contact is not None:
        assert selected is not None
        distribution = contact_distribution(selected, frame.shape, p)
        if distribution is None:
            raise AssertionError("contact geometry reconstruction failed")
        if not all(math.isclose(distribution[k], contact[v], abs_tol=1e-10) for k, v in
                   [("contact_x_m", "x_m"), ("contact_z_m", "z_m"), ("contact_pixel_x", "pixel_x"), ("contact_pixel_y", "pixel_y")]):
            raise AssertionError("diagnostic and production contact selection differ")
        result.update(distribution)
        variants = [estimate_ground_contact(selected, frame.shape, p, contact_fraction=f) for f in (.02, .08, .16)]
        zs = [r["z_m"] for r in variants if r is not None]
        result["fraction_z_sensitivity_m"] = max(zs) - min(zs) if zs else None
    return result


def phase_intervals(rows):
    times = [number(r, "time_sec") for r in rows if flag(r, "odom_available") and (number(r, "odom_linear_mps") or 0) > .03]
    return (min(times), max(times)) if times else None


def phase_at(now, intervals):
    if intervals is None:
        return "no_forward_motion"
    start, stop = intervals
    return ("before_motion" if now < start else "moving" if now <= stop else
            "after_stop_transition" if now <= stop + .5 else "after_stop_plus_0p5")


def adjacent_features(previous, current):
    result = {"adjacent_motion_residual_m": None, "adjacent_contact_pixel_jump_px": None,
              "adjacent_bbox_iou": None, "adjacent_area_change_fraction": None}
    if previous is None or not previous["video_detected"] or not current["video_detected"]:
        return result
    dt = float(current["time_sec"]) - float(previous["time_sec"])
    if dt <= 0:
        raise ValueError("non-increasing frame times")
    if previous["odom_available"] and current["odom_available"]:
        travel = .5 * (previous["odom_linear_mps"] + current["odom_linear_mps"]) * dt
        result["adjacent_motion_residual_m"] = abs(current["contact_z_m"] - previous["contact_z_m"] + travel)
    result["adjacent_contact_pixel_jump_px"] = math.hypot(current["contact_pixel_x"] - previous["contact_pixel_x"],
                                                        current["contact_pixel_y"] - previous["contact_pixel_y"])
    result["adjacent_bbox_iou"] = box_iou(tuple(previous[k] for k in ("bbox_x", "bbox_y", "bbox_width_px", "bbox_height_px")),
                                        tuple(current[k] for k in ("bbox_x", "bbox_y", "bbox_width_px", "bbox_height_px")))
    result["adjacent_area_change_fraction"] = abs(current["area_px"] - previous["area_px"]) / previous["area_px"] if previous["area_px"] else None
    return result


QUALITY_KEYS = ("bbox_aspect_ratio", "bbox_fill_ratio", "contour_solidity", "dark_blue_hs_fraction",
                "contact_z_iqr_m", "contact_z_span_m", "fraction_z_sensitivity_m", "adjacent_bbox_iou",
                "adjacent_area_change_fraction", "adjacent_contact_pixel_jump_px", "adjacent_motion_residual_m")


def summarize(session, label, rows):
    result = {"session": session, "group": label, "frames": len(rows),
              "video_detected": sum(r["video_detected"] for r in rows),
              "aspect_only_missing": sum(r["detector_reason"] == "only_aspect_rejected" for r in rows),
              "no_roi_contour_missing": sum(r["detector_reason"] == "no_front_roi_contour_above_area" for r in rows),
              "geometry_missing": sum(r["detector_reason"] == "ground_geometry_invalid" for r in rows),
              "residual_pair_count": sum(r["adjacent_motion_residual_m"] is not None for r in rows),
              "residual_over_0p03m_count": sum((r["adjacent_motion_residual_m"] or 0) > .03 for r in rows)}
    for key in QUALITY_KEYS:
        values = [r[key] for r in rows if r[key] is not None and math.isfinite(r[key])]
        result.update({key + "_n": len(values), key + "_median": statistics.median(values) if values else None,
                       key + "_p95": percentile(values, 95), key + "_max": max(values) if values else None})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--detector-config", type=Path, help="override segmentation settings only; retain recorded camera geometry")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sessions = set()
    for source in args.input:
        found = find_session_directories([source])
        if not found:
            parser.error(f"no video sessions: {source}")
        sessions.update(found)
    if len({p.name for p in sessions}) != len(sessions):
        parser.error("duplicate session names")
    overrides = json.loads(args.detector_config.read_text()) if args.detector_config else {}
    overrides = {k: v for k, v in overrides.items() if k in DETECTOR_KEYS or k.startswith("blue_ground_contact_hsv_")}
    cv2.setNumThreads(1)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames, summaries, sources = [], [], []
    for session in sorted(sessions):
        metadata = json.loads((session / "metadata.json").read_text())
        p = dict(metadata["parameters"])
        p.update(overrides)
        with (session / "detections.csv").open(newline="") as stream:
            live = list(csv.DictReader(stream))
        validate_rows(live)
        intervals, previous = phase_intervals(live), None
        video = cv2.VideoCapture(str(session / "raw.avi"))
        if not video.isOpened():
            raise ValueError(f"cannot open video {session}")
        local = []
        print(f"Diagnosing {session.name} ...", flush=True)
        try:
            for motion in live:
                ok, image = video.read()
                if not ok:
                    raise ValueError("video shorter than CSV")
                expected_shape = (metadata.get("requested_camera_height"), metadata.get("requested_camera_width"))
                if all(expected_shape) and image.shape[:2] != expected_shape:
                    raise ValueError("video dimensions differ from recording metadata")
                row = {"session": session.name, "frame": motion["frame"], "time_sec": number(motion, "time_sec"),
                       "phase": phase_at(number(motion, "time_sec"), intervals),
                       "live_detected": int(flag(motion, "detected")), "live_raw_z_m": number(motion, "raw_z_m"),
                       "odom_available": int(flag(motion, "odom_available")),
                       "odom_linear_mps": number(motion, "odom_linear_mps"), "odom_angular_radps": number(motion, "odom_angular_radps")}
                row.update(describe_frame(image, p))
                row.update(adjacent_features(previous, row))
                local.append(row)
                previous = row
            if video.read()[0]:
                raise ValueError("video longer than CSV")
        finally:
            video.release()
        summaries.append(summarize(session.name, "all", local))
        for phase in sorted({r["phase"] for r in local}):
            summaries.append(summarize(session.name, phase, [r for r in local if r["phase"] == phase]))
        for name, selected in [
            ("detected_low_adjacent_residual", [r for r in local if r["adjacent_motion_residual_m"] is not None and r["adjacent_motion_residual_m"] <= .03]),
            ("detected_high_adjacent_residual", [r for r in local if (r["adjacent_motion_residual_m"] or 0) > .03]),
        ]:
            summaries.append(summarize(session.name, name, selected))
        frames.extend(local)
        sources.append({"session": session.name, "source": str(session), "parameters": p,
                        "sha256": {name: sha256(session / name) for name in ("raw.avi", "detections.csv", "metadata.json")}})
        print(f"  {Counter(r['detector_reason'] for r in local)}", flush=True)
    write_csv(args.output_dir / "frame_quality.csv", frames)
    write_csv(args.output_dir / "quality_summary.csv", summaries)
    (args.output_dir / "provenance.json").write_text(json.dumps({"scope": "OFFLINE_DIAGNOSIS_ONLY_NO_GATE_CHANGES",
        "sources": sources, "detector_overrides": overrides,
        "implementation_sha256": {name: sha256(Path(__file__).with_name(name)) for name in
                                  (Path(__file__).name, "ground_contact.py", "evaluate_observation_gates.py")},
        "limits": ["metrics are not distance-error ground truth", "adjacent motion reference assumes a fixed target and straight motion",
                   "no residual across missing frames", "selected contour bbox is not a ground-truth target ROI"]}, indent=2) + "\n")


if __name__ == "__main__":
    main()
