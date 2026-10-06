#!/usr/bin/env python3
"""Summarize frozen OFFLINE contact candidates against historical position/phase labels.

Existing phase labels use zero-based video indices; comparison CSV uses one-based
recording frame IDs. Missing observations are never zero distance/error. All
position-error metrics include every detection, not just accepted measurements.
"""
import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path

import numpy as np

from evaluate_dynamic_ttc_conditions import evaluate_session as evaluate_dynamic_session, load_profile
from evaluate_observation_gates import load_phase_labels, phase_for_frame
from evaluate_raw_velocity_confidence_replay import sha256
from evaluate_velocity_confidence_replay import flag, number, write_csv


VALIDATION_VARIANTS = ("baseline", "seeded_s130_nearest", "seeded_s130_bottom")


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def statistic(values, kind):
    values = [v for v in values if v is not None and math.isfinite(v)]
    if not values:
        return None
    return float({"median": np.median, "mean": np.mean, "p95": lambda a: np.percentile(a, 95)}[kind](values))


def position_summary(rows, reference):
    start, end = int(reference["start_frame"]), int(reference["end_frame"])
    if start < 1 or end < start:
        raise ValueError("position reference requires inclusive one-based frame bounds")
    selected = [r for r in rows if start <= int(r["frame"]) <= end]
    if tuple(int(r["frame"]) for r in selected) != tuple(range(start, end + 1)):
        raise ValueError("position reference frames missing from comparison")
    detected = [r for r in selected if flag(r, "detected")]
    result = {"session": reference["session"], "variant": rows[0]["variant"], "reference_kind": reference["reference_kind"],
              "start_frame": start, "end_frame": end, "frames": len(selected), "detected": len(detected),
              "detection_rate": len(detected) / len(selected),
              "accepted": sum(flag(r, "measurement_accepted") for r in selected),
              "track_available": sum(flag(r, "track_available") for r in selected),
              "reference_source": reference["reference_source"]}
    for axis, key in [("x", "x_m"), ("z", "z_m"), ("distance", None)]:
        expected = number(reference, "expected_" + axis + "_m")
        values = [(math.hypot(number(r, "x_m"), number(r, "z_m")) if key is None else number(r, key)) for r in detected]
        if any(v is None or not math.isfinite(v) for v in values):
            raise ValueError("detected row has no finite calibrated position")
        errors = [v - expected for v in values] if expected is not None else []
        result.update({"expected_" + axis + "_m": expected, "estimated_" + axis + "_median_m": statistic(values, "median"),
                       axis + "_signed_error_median_m": statistic(errors, "median"),
                       axis + "_mae_m": statistic([abs(e) for e in errors], "mean"),
                       axis + "_abs_error_p95_m": statistic([abs(e) for e in errors], "p95")})
    return result


def label_rows(rows, intervals):
    result = []
    for index, row in enumerate(rows):
        if int(row["frame"]) != index + 1:
            raise ValueError("label alignment requires consecutive one-based frames")
        event, phase = phase_for_frame(intervals, index)
        if not phase:
            raise ValueError(f"phase label does not cover video index {index}")
        result.append(dict(row, video_index_zero_based=index, occlusion_event=event, phase_label=phase))
    if any(interval["end_frame"] >= len(rows) for interval in intervals):
        raise ValueError("phase label extends beyond video")
    return result


def phase_summary(rows, session, variant, phase):
    selected = [r for r in rows if r["phase_label"] == phase]
    velocities = [abs(v) for r in selected if (v := number(r, "relative_vz_mps")) is not None]
    return {"session": session, "variant": variant, "phase": phase, "frames": len(selected),
            "detected": sum(flag(r, "detected") for r in selected),
            "accepted": sum(flag(r, "measurement_accepted") for r in selected),
            "track_available": sum(flag(r, "track_available") for r in selected),
            "accepted_rate": sum(flag(r, "measurement_accepted") for r in selected) / len(selected) if selected else None,
            "max_abs_track_vz_mps": max(velocities) if velocities else None}


def occlusion_events(rows, intervals, *, grace_sec):
    if not math.isfinite(grace_sec) or grace_sec <= 0:
        raise ValueError("track grace must be positive and finite")
    result = []
    for hidden in [i for i in intervals if i["phase"] == "fully_occluded"]:
        event = hidden["event"]
        return_intervals = [i for i in intervals if i["event"] == event and i["phase"] == "reappearing"
                            and i["start_frame"] > hidden["end_frame"]]
        if len(return_intervals) != 1:
            raise ValueError("each fully_occluded interval needs one matching reappearing interval")
        recovery = return_intervals[0]
        next_occlusion = min([i["start_frame"] for i in intervals
                              if i["phase"] == "partial_occlusion" and i["start_frame"] > recovery["start_frame"]] or [len(rows)])
        hidden_rows = rows[hidden["start_frame"]:hidden["end_frame"] + 1]
        recover_rows = rows[recovery["start_frame"]:next_occlusion]
        start = number(hidden_rows[0], "time_sec")
        return_time = number(recover_rows[0], "time_sec")
        lost = next((r for r in hidden_rows if not flag(r, "track_available")), None)
        recovered = next((r for r in recover_rows if flag(r, "measurement_accepted") and flag(r, "track_available")), None)
        result.append({"session": rows[0]["session"], "variant": rows[0]["variant"], "event": event,
                       "fully_occluded_start_video_index": hidden["start_frame"], "fully_occluded_end_video_index": hidden["end_frame"],
                       "fully_occluded_frames": len(hidden_rows), "fully_occluded_detected": sum(flag(r, "detected") for r in hidden_rows),
                       "fully_occluded_accepted": sum(flag(r, "measurement_accepted") for r in hidden_rows),
                       "track_loss_observed": int(lost is not None),
                       "first_loss_delay_sec": number(lost, "time_sec") - start if lost else None,
                       "track_after_grace_frames": sum(flag(r, "track_available") and number(r, "time_sec") > start + grace_sec for r in hidden_rows),
                       "recovery_observed": int(recovered is not None),
                       "first_recovery_recording_frame": int(recovered["frame"]) if recovered else None,
                       "recovery_delay_sec": number(recovered, "time_sec") - return_time if recovered else None})
    return result


def warning_comparison(grouped, risk_summaries):
    result = []
    for session, by_variant in grouped.items():
        if not session.startswith("approach_"):
            continue
        baseline = risk_summaries[(session, "baseline")]
        base_time = number(baseline, "first_warning_sec")
        for variant, rows in by_variant.items():
            risk = risk_summaries[(session, variant)]
            onset = number(risk, "first_warning_sec")
            motion = [r for r in rows if flag(r, "odom_available") and (number(r, "odom_linear_mps") or 0) > .03]
            result.append({"session": session, "variant": variant, "frames": len(rows), "motion_frames": len(motion),
                           "motion_detected_rate": sum(flag(r, "detected") for r in motion) / len(motion) if motion else None,
                           "motion_track_rate": sum(flag(r, "track_available") for r in motion) / len(motion) if motion else None,
                           "motion_odom_median_mps": statistic([number(r, "odom_linear_mps") for r in motion], "median"),
                           "warning_frames": int(risk["warning_frames"]), "hold_frames": int(risk["hold_frames"]),
                           "critical_frames": int(risk["critical_frames"]), "unknown_frames": int(risk["unknown_frames"]),
                           "baseline_first_warning_sec": base_time, "first_warning_sec": onset,
                           "warning_onset_delta_sec": onset - base_time if onset is not None and base_time is not None else None,
                           "baseline_warning_lost": int(base_time is not None and onset is None),
                           "virtual_active_groups": int(risk["virtual_active_groups"]),
                           "final_risk": rows[-1]["risk"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-dir", type=Path, action="append", required=True)
    parser.add_argument("--position-labels", type=Path, required=True)
    parser.add_argument("--phase-labels", type=Path, required=True)
    parser.add_argument("--dynamic-profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    grouped = defaultdict(dict)
    risk_summaries, source_parameters, input_files = {}, {}, []
    frozen_settings = None
    candidate_hash = None
    detector_hash = None
    for directory in args.comparison_dir:
        provenance = json.loads((directory / "provenance.json").read_text())
        settings = provenance["settings"]
        implementation = provenance["implementation_sha256"]["offline_box_contact_candidates.py"]
        config = provenance["detector_config_sha256"]
        if frozen_settings is not None and (settings != frozen_settings or implementation != candidate_hash or config != detector_hash):
            raise ValueError("comparisons must use the same frozen detector candidate and configuration")
        frozen_settings, candidate_hash, detector_hash = settings, implementation, config
        selected_rows = defaultdict(list)
        for row in read_csv(directory / "frame_results.csv"):
            if row["variant"] in VALIDATION_VARIANTS:
                selected_rows[(row["session"], row["variant"])].append(row)
        for (session, variant), rows in selected_rows.items():
            if variant in grouped[session]:
                raise ValueError("duplicate session/variant across comparisons")
            grouped[session][variant] = rows
        for summary in read_csv(directory / "risk_summary.csv"):
            if summary["variant"] in VALIDATION_VARIANTS:
                risk_summaries[(summary["session"], summary["variant"])] = summary
        for source in provenance["sources"]:
            source_parameters[source["session"]] = source["parameters"]
        input_files.extend(directory / n for n in ("frame_results.csv", "risk_summary.csv", "provenance.json"))
    for session, variants in grouped.items():
        if set(variants) != set(VALIDATION_VARIANTS):
            raise ValueError(f"incomplete variants: {session}")
        frames = [tuple(r["frame"] for r in variants[v]) for v in VALIDATION_VARIANTS]
        if any(f != frames[0] for f in frames[1:]):
            raise ValueError("variant frame IDs differ")
    positions = []
    for reference in read_csv(args.position_labels):
        for rows in grouped[reference["session"]].values():
            positions.append(position_summary(rows, reference))
    phases, events, labelled_frames = [], [], []
    phase_labels = load_phase_labels(args.phase_labels)
    for session, intervals in phase_labels.items():
        for variant, rows in grouped[session].items():
            labelled = label_rows(rows, intervals)
            labelled_frames.extend({k: r[k] for k in ("session", "variant", "frame", "video_index_zero_based", "time_sec",
                                                      "occlusion_event", "phase_label", "detected", "measurement_accepted", "track_available",
                                                      "track_predicted", "x_m", "z_m", "relative_vz_mps")} for r in labelled)
            for phase in sorted({r["phase_label"] for r in labelled}):
                phases.append(phase_summary(labelled, session, variant, phase))
            events.extend(occlusion_events(labelled, intervals, grace_sec=source_parameters[session].get("blue_tracking_max_missing_sec", .25)))
    profile = load_profile(args.dynamic_profile)
    dynamic = []
    for session, variants in grouped.items():
        if not session.startswith("approach_"):
            continue
        for variant, rows in variants.items():
            result = evaluate_dynamic_session(session, session, {"parameters": source_parameters[session]}, rows, profile)
            result["variant"] = variant
            dynamic.append(result)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in [("position_accuracy.csv", positions), ("phase_results.csv", phases), ("occlusion_events.csv", events),
                       ("labelled_frames.csv", labelled_frames), ("warning_comparison.csv", warning_comparison(grouped, risk_summaries)),
                       ("fixed_dynamic_profile_results.csv", dynamic)]:
        if not rows:
            raise ValueError(f"no results for {name}")
        write_csv(args.output_dir / name, rows)
    inputs = input_files + [args.position_labels, args.phase_labels, args.dynamic_profile]
    (args.output_dir / "evaluation_provenance.json").write_text(json.dumps({
        "scope": "OFFLINE_VALIDATION_NOT_HARDWARE_APPROVAL", "variants": VALIDATION_VARIANTS,
        "settings": frozen_settings, "candidate_implementation_sha256": candidate_hash, "detector_config_sha256": detector_hash,
        "phase_label_indexing": "zero-based inclusive video indices = comparison recording frame minus one",
        "position_label_indexing": "one-based inclusive recording frames", "missing_error_is_zero": False,
        "inputs_sha256": {str(p.resolve()): sha256(p) for p in inputs},
        "implementation_sha256": {n: sha256(Path(__file__).with_name(n)) for n in
                                  (Path(__file__).name, "evaluate_dynamic_ttc_conditions.py", "evaluate_collision_hysteresis_replay.py",
                                   "evaluate_observation_gates.py")},
        "limits": ["historical data with previous use, not a blind prospectively collected holdout",
                   "distance labels have recorded placement accuracy, not metrology certification",
                   "dynamic profile keeps its own fixed decision conditions; no new nominal-speed rejection",
                   "risk_summary timing uses source metadata; fixed profile can produce a different state series",
                   "no runtime or ROS/network/physical timing validation"]}, indent=2) + "\n")
    print(f"Evaluated {len(positions)} position cases, {len(events)} occlusion events, {len(dynamic)} dynamic cases.")


if __name__ == "__main__":
    main()
