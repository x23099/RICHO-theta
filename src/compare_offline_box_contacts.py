#!/usr/bin/env python3
"""Replay fixed box/contact candidates on video. OFFLINE: no ROS/hardware output.

Colour/shape overrides only; recorded camera calibration, motion, frame times,
tracking/TTC/risk settings remain fixed. No velocity-confidence candidate mixed in.
"""
import argparse
from dataclasses import asdict
import csv
import json
from pathlib import Path
import time

import cv2
import numpy as np

from diagnose_ground_contact_quality import DETECTOR_KEYS, phase_at, phase_intervals
from evaluate_observation_gates import find_session_directories
from evaluate_raw_velocity_confidence_replay import OfflineBluePipeline, sha256, validate_rows
from evaluate_velocity_confidence_replay import evaluate_rows, flag, number, write_csv
from ground_contact import detect_blue_ground_contact
from offline_box_contact_candidates import (BoxCandidateSettings, component_contact,
                                           seeded_components, select_component)


VARIANTS = ("baseline", "weak_v10_reference", "seeded_open5_nearest", "seeded_open5_bottom",
            "seeded_s130_nearest", "seeded_s130_bottom")


def contact_metrics(contact):
    keys = ("raw_contact_x_m", "raw_contact_z_m", "contact_pixel_x", "contact_pixel_y", "area_px",
            "bbox_x", "bbox_y", "bbox_width", "bbox_height", "fill_ratio", "seed_fraction")
    result = dict.fromkeys(keys)
    if contact is None:
        return result
    x, y, w, h = cv2.boundingRect(contact["contour"])
    result.update(raw_contact_x_m=contact["x_m"], raw_contact_z_m=contact["z_m"],
                  contact_pixel_x=contact["pixel_x"], contact_pixel_y=contact["pixel_y"], area_px=contact["area_px"],
                  bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
                  fill_ratio=contact["area_px"] / (w * h), seed_fraction=contact.get("seed_fraction"))
    return result


def adjacent_residual(previous, current):
    if previous is None or not flag(previous, "detected") or not flag(current, "detected"):
        return None
    if not flag(previous, "odom_available") or not flag(current, "odom_available"):
        return None
    dt = float(current["time_sec"]) - float(previous["time_sec"])
    if dt <= 0:
        raise ValueError("time_sec must increase for temporal distance comparison")
    travel = .5 * (number(previous, "odom_linear_mps") + number(current, "odom_linear_mps")) * dt
    return abs(current["raw_contact_z_m"] - previous["raw_contact_z_m"] + travel)


def summary_group(session, variant, group, rows):
    detected = [r for r in rows if flag(r, "detected")]
    residuals = [r["adjacent_motion_residual_m"] for r in rows if r["adjacent_motion_residual_m"] is not None]
    zs = [r["raw_contact_z_m"] for r in detected]
    return {"session": session, "variant": variant, "group": group, "frames": len(rows), "detected": len(detected),
            "calibration_valid": sum(flag(r, "calibration_valid") for r in rows),
            "measurement_accepted": sum(flag(r, "measurement_accepted") for r in rows),
            "residual_pairs": len(residuals), "residual_over_0p03m": sum(r > .03 for r in residuals),
            "residual_p95_m": float(np.percentile(residuals, 95)) if residuals else None,
            "residual_max_m": max(residuals) if residuals else None,
            "raw_z_median_m": float(np.median(zs)) if zs else None,
            "raw_z_iqr_m": float(np.percentile(zs, 75) - np.percentile(zs, 25)) if zs else None,
            "segmentation_ms_median": float(np.median([r["segmentation_ms"] for r in rows])) if rows else None}


def validate_variants(variants):
    variants = tuple(variants)
    if not variants or len(set(variants)) != len(variants) or any(v not in VARIANTS for v in variants):
        raise ValueError("variants must be nonempty, unique, and supported")
    return variants


def verify_frozen_candidate(path, settings):
    frozen = json.loads(path.read_text())
    if frozen["settings"] != asdict(settings):
        raise ValueError("candidate thresholds differ from the frozen comparison")
    name = "offline_box_contact_candidates.py"
    if frozen["implementation_sha256"][name] != sha256(Path(__file__).with_name(name)):
        raise ValueError("candidate implementation differs from frozen comparison")
    return {"reference": str(path.resolve()), "sha256": sha256(path),
            "settings_match": True, "candidate_implementation_matches": True}


def compare_session(session, overrides, settings, variants=VARIANTS):
    variants = validate_variants(variants)
    metadata = json.loads((session / "metadata.json").read_text())
    metadata["parameters"] = dict(metadata["parameters"], **overrides)
    with (session / "detections.csv").open(newline="") as stream:
        live = list(csv.DictReader(stream))
    validate_rows(live)
    # validate both clocks: production may use monotonic time while plots use elapsed time.
    elapsed = [number(r, "time_sec") for r in live]
    if any(t is None for t in elapsed) or any(b <= a for a, b in zip(elapsed, elapsed[1:])):
        raise ValueError("finite increasing time_sec required")
    pipelines = {name: OfflineBluePipeline(metadata["parameters"]) for name in variants}
    output = {name: [] for name in variants}
    p = metadata["parameters"]
    intervals = phase_intervals(live)
    video = cv2.VideoCapture(str(session / "raw.avi"))
    if not video.isOpened():
        raise ValueError(f"cannot open {session / 'raw.avi'}")
    try:
        for motion in live:
            ok, frame = video.read()
            if not ok:
                raise ValueError("video shorter than CSV")
            expected = (metadata.get("requested_camera_height"), metadata.get("requested_camera_width"))
            if all(expected) and frame.shape[:2] != expected:
                raise ValueError("video geometry differs from metadata")
            contacts, timings = {}, {}
            for name, q in [("baseline", p), ("weak_v10_reference", dict(p, blue_ground_contact_hsv_v_min=settings.weak_v_min))]:
                if name not in variants:
                    continue
                start = time.perf_counter()
                contacts[name], _ = detect_blue_ground_contact(frame, q, min_area_px=q.get("blue_ground_contact_min_area", 300),
                                                               contact_fraction=q.get("blue_ground_contact_fraction", .08))
                timings[name] = 1000 * (time.perf_counter() - start)
            for prefix, q in [("seeded_open5", p), ("seeded_s130", dict(p, blue_ground_contact_hsv_s_min=
                                                                      max(settings.body_s_min, p.get("blue_ground_contact_hsv_s_min", 70))))]:
                if not any(prefix + "_" + suffix in variants for suffix in ("nearest", "bottom")):
                    continue
                start = time.perf_counter()
                component = select_component(seeded_components(frame, q, settings), frame.shape, q)
                shared_ms = 1000 * (time.perf_counter() - start)
                for suffix, bottom in [("nearest", False), ("bottom", True)]:
                    name = prefix + "_" + suffix
                    if name not in variants:
                        continue
                    start = time.perf_counter()
                    contacts[name] = component_contact(component, frame.shape, q, settings, bottom=bottom)
                    timings[name] = shared_ms + 1000 * (time.perf_counter() - start)
            for name in variants:
                pipeline = pipelines[name]
                row = pipeline.update_observation(pipeline.calibrate_contact(contacts[name]), motion)
                row.update(contact_metrics(contacts[name]), session=session.name, variant=name,
                           phase=phase_at(float(motion["time_sec"]), intervals), segmentation_ms=timings[name])
                row["adjacent_motion_residual_m"] = adjacent_residual(output[name][-1] if output[name] else None, row)
                output[name].append(row)
        if video.read()[0]:
            raise ValueError("video longer than CSV")
    finally:
        video.release()
    return metadata, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--detector-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=VARIANTS)
    parser.add_argument("--freeze-from", type=Path, help="verify candidate settings/code match an earlier provenance.json")
    args = parser.parse_args()
    sessions = set()
    for source in args.input:
        found = find_session_directories([source])
        if not found:
            parser.error(f"no video sessions in {source}")
        sessions.update(found)
    if len({p.name for p in sessions}) != len(sessions):
        parser.error("duplicate session names")
    configured = json.loads(args.detector_config.read_text())
    overrides = {k: v for k, v in configured.items() if k in DETECTOR_KEYS or k.startswith("blue_ground_contact_hsv_")}
    settings = BoxCandidateSettings()
    variants = validate_variants(args.variants)
    frozen = verify_frozen_candidate(args.freeze_from, settings) if args.freeze_from else None
    cv2.setNumThreads(1)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames, summaries, risks, sources = [], [], [], []
    for session in sorted(sessions):
        print(f"Comparing {session.name} ...", flush=True)
        metadata, output = compare_session(session, overrides, settings, variants=variants)
        for variant, rows in output.items():
            risk, details = evaluate_rows(session.name, metadata, rows, candidate=False)
            risk["variant"] = variant
            risks.append(risk)
            for row, detail in zip(rows, details):
                row.update(risk=detail["risk"], virtual_active=detail["virtual_active"], virtual_reason=detail["virtual_reason"],
                           virtual_requested_magnitude=detail["virtual_requested_magnitude"])
            frames.extend(rows)
            summaries.append(summary_group(session.name, variant, "all", rows))
            for phase in sorted({r["phase"] for r in rows}):
                summaries.append(summary_group(session.name, variant, phase, [r for r in rows if r["phase"] == phase]))
            print(f"  {variant}: detected={sum(flag(r, 'detected') for r in rows)}/{len(rows)} "
                  f"WARNING={risk['warning_frames']} CRITICAL={risk['critical_frames']} UNKNOWN={risk['unknown_frames']}", flush=True)
        sources.append({"session": session.name, "path": str(session.resolve()), "parameters": metadata["parameters"],
                        "sha256": {n: sha256(session / n) for n in ("raw.avi", "detections.csv", "metadata.json")}})
    write_csv(args.output_dir / "frame_results.csv", frames)
    write_csv(args.output_dir / "contact_summary.csv", summaries)
    write_csv(args.output_dir / "risk_summary.csv", risks)
    code = (Path(__file__).name, "offline_box_contact_candidates.py", "ground_contact.py",
            "evaluate_raw_velocity_confidence_replay.py", "evaluate_velocity_confidence_replay.py",
            "diagnose_ground_contact_quality.py", "evaluate_observation_gates.py", "obstacle_tracking.py",
            "collision_risk.py", "collision_ffb_publisher.py", "virtual_ffb.py", "offline_velocity_confidence.py")
    (args.output_dir / "provenance.json").write_text(json.dumps({
        "scope": "OFFLINE_ONLY_NO_RUNTIME_OR_HARDWARE_APPROVAL", "sources": sources, "variants": variants,
        "frozen_candidate_check": frozen,
        "settings": asdict(settings), "detector_overrides": overrides,
        "detector_config_sha256": sha256(args.detector_config),
        "implementation_sha256": {n: sha256(Path(__file__).with_name(n)) for n in code},
        "limits": ["exploration on development recordings, not independent holdout",
                   "fixed target straight-motion residual is not absolute distance truth",
                   "MJPG differs from live pixels; no ROS/network/physical replay",
                   "timing on analysis PC, single thread, sequential variants, not live FPS",
                   "seed and morphology do not prove semantic object identity",
                   "no new velocity-confidence gate combined with this comparison"]}, indent=2) + "\n")


if __name__ == "__main__":
    main()
