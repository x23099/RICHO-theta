#!/usr/bin/env python3
"""同一録画の過去4姿勢で固定床を凍結し、その後の画像だけを比較する。

録画後の条件付き配線検証。実機性能・独立holdout・物理精度ではない。
既存成功sessionを開発例として使用し、設定/閾値/実行系は変更しない。
"""
import argparse
from collections import Counter
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import ConeDistanceEngine, digest, load_config
from cone_fixed_floor_candidate import COORDINATE_FRAME
from cone_fixed_floor_shadow import FixedFloorShadow, enforce_freshness
from cone_scene_diagnostic import estimate_scene
from run_cone_distance_replay import load_saved_run
from summarize_cone_distance_live import summarize
from theta_rtc_frames import NativeFrame, native_frame

SESSION = "floor_cone_same_pose_r01_20261015_160621_378"


def freeze_bundle(pose, session, settings, completion_time, query_frame, query_time, height_m=.59):
    """Never selects normals or heights by target distance or later frames."""
    if (not pose.ready or not pose.latest_accepted or len(pose.train) != 2 or len(pose.validation) != 2
            or query_frame <= pose.last_frame or query_time < completion_time or completion_time < pose.last_time):
        raise ValueError("two training/two later validation poses completed BEFORE the query required")
    normal = np.asarray(pose.candidate, float)
    if type(height_m) not in (int, float) or not .1 < height_m < 2. or not np.isfinite(height_m):
        raise ValueError("explicit external diagnostic height required")
    frames = [f for f, _ in pose.train] + list(pose.validation)
    if len(set(frames)) != 4 or frames != sorted(frames) or max(frames) >= query_frame:
        raise ValueError("four distinct ordered past pose frames required")
    heading = dict(path=settings["floor_candidate"], sha256=settings["floor_sha256"])
    model = dict(schema="explicit_floor_model_v1", name="first_past_only_up_external_height59",
        session=session, normal_optical=normal.tolist(), camera_to_floor_m=height_m,
        coordinate_frame=COORDINATE_FRAME, heading_reference=heading,
        evidence=["first existing PastOnlyPose readiness in this recording",
                  "training frames: "+str(frames[:2]), "later validation frames: "+str(frames[2:]),
                  "external user-reported height 0.59 m; not estimated from this recording"],
        assumptions=["static camera and same floor throughout the recording, not independently proved by this replay",
                     "architectural up direction is assumed normal to the floor",
                     "heading convention inherited only; camera foot range is not measured base_link distance"],
        invalidation_conditions=["different session or changed camera/capture/mount/floor geometry",
                                 "use before bootstrap completion", "use as an FFB or physical approval"],
        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False,
        controlling_distance=False, live_integrated=False, published_to_ros=False)
    bundle = dict(schema="explicit_floor_models_v1", session=session, heading_reference=heading, models=[model])
    seal = dict(training_frames=frames[:2], validation_frames=frames[2:],
                last_evidence_frame=pose.last_frame, completed_at_sec=completion_time,
                first_eligible_query_frame=query_frame, first_eligible_source_time_sec=query_time,
                height_is_external_input_m=height_m, distance_labels_used_for_bootstrap=False)
    return bundle, seal


def verify_releases(seal, rows):
    for row in rows:
        shadow = row.get("fixed_floor_shadow")
        if shadow is None:
            continue
        if row["frame"] <= seal["last_evidence_frame"] or row["source_time_sec"] < seal["completed_at_sec"]:
            raise ValueError("future bootstrap model leaked into its past")


def write_csv(path, rows):
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v
                         for k, v in row.items()} for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("new output directory required")
    session = ROOT / "recordings/2026-10-15_floor_cone_same_pose_intake_r01" / SESSION
    saved = ROOT / "Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/inference_r01"
    old = ROOT / "Experimental_results/2026-10-26/cone_distance_replay_r05/declared_central_scope"
    engine = ConeDistanceEngine(target_roi=(270, 0, 350, 720), support_completion_shadow=True, frame_evidence=True)
    engine.reset(SESSION)
    times, predictions = load_saved_run(session, saved, engine.settings)
    with (old / "scene_jobs.csv").open(newline="") as stream:
        jobs = {int(r["frame"]): r for r in csv.DictReader(stream)}
    for number, job in jobs.items():
        if float(job["source_time_sec"]) != times[number-1] or float(job["simulated_completion_sec"]) < times[number-1]:
            raise ValueError("saved scene schedule not aligned with original source ledger")
    sources = [session / n for n in ("raw.avi", "metadata.json", "detections.csv")]
    sources += [saved / n for n in ("frames.csv", "predictions.csv", "provenance.json")]
    sources += [old / "scene_jobs.csv", Path(__file__).resolve()]
    sources += [ROOT / "src" / n for n in ("cone_distance_core.py", "cone_scene_diagnostic.py",
        "cone_fixed_floor_shadow.py", "cone_fixed_floor_candidate.py", "cone_support_quality.py",
        "cone_support_completion_candidate.py", "cone_colour_support_candidate.py",
        "cone_distance_diagnostic_config.json", "angular_fisheye_geometry.py", "run_cone_distance_replay.py")]
    sources += [ROOT / engine.settings[k+"_candidate"] for k in ("camera", "floor")]
    before = {str(p): digest(p) for p in sources}
    output.mkdir(parents=True, exist_ok=False)
    rows, scene_rows, pending, adapter, seal = [], [], None, None, None
    baseline_adapter, baseline_control = None, {}
    cap = cv2.VideoCapture(str(session / "raw.avi"))
    if not cap.isOpened():
        raise ValueError("original recording cannot be decoded")
    unchanged, mismatched_schedule = 0, []
    try:
        for number, t in enumerate(times, 1):
            ok, image = cap.read()
            if not ok:
                raise ValueError("video shorter than saved detector ledger")
            native_frame(image)
            pixel_hash = hashlib.sha256(image.tobytes()).hexdigest()
            frame = NativeFrame(SESSION, number, t, t, image)
            if pending is not None and pending[2] <= t:
                ticket, result, released = pending
                engine.complete_scene(ticket, result, released)
                if adapter is None and engine.pose.ready and engine.pose.latest_accepted:
                    bundle, seal = freeze_bundle(engine.pose, SESSION, engine.settings, released, number, t)
                    bundle_path = output / "bootstrap_models.json"
                    bundle_path.write_text(json.dumps(bundle, indent=2)+"\n")
                    adapter = FixedFloorShadow(bundle_path, engine.settings, "support_completion_shadow")
                    baseline_adapter = FixedFloorShadow(bundle_path, engine.settings, "baseline")
                pending = None
            if number in jobs:
                if pending is not None:
                    raise ValueError("saved single-worker schedule overlaps")
                ticket = engine.begin_scene(frame)
                result = estimate_scene(image, engine.camera, engine.prior_up)
                job = jobs[number]
                if result["accepted"] != (job["accepted"] == "True") or result["reason"] != job["reason"]:
                    mismatched_schedule.append(number)
                scene_rows.append(dict(frame=number, source_time_sec=t,
                    completed_at_sec=float(job["simulated_completion_sec"]), **result))
                pending = ticket, result, float(job["simulated_completion_sec"])
            # Same explicit logical time throughout; NOT a measured GPU or live cost.
            row = engine.measure(frame, predictions[number], t+.01)
            baseline = copy.deepcopy(row)
            if adapter is not None:
                observation = row["support_completion_shadow"]["candidate"]
                row["fixed_floor_shadow"] = adapter.observe(frame, observation, engine.camera, engine.transform)
                enforce_freshness(row["fixed_floor_shadow"], row["frame_age_ms"])
                union_observation = row["frame_evidence"]["support_observation"]
                control = baseline_adapter.observe(frame, union_observation, engine.camera, engine.transform)
                enforce_freshness(control, row["frame_age_ms"])
                baseline_control[number] = control
            stripped = {k: v for k, v in row.items() if k != "fixed_floor_shadow"}
            unchanged += stripped == baseline
            row.update(predict_ms=0., support_geometry_ms=0., cone_service_ms=0.,
                       inference_source="saved_boxes_fixed_floor_bootstrap_NOT_live_inference")
            rows.append(row)
            if hashlib.sha256(image.tobytes()).hexdigest() != pixel_hash:
                raise ValueError("original native pixels modified")
            if number % 400 == 0:
                print(f"[INFO] {number}/{len(times)}", flush=True)
        if cap.read()[0]:
            raise ValueError("video longer than ledger")
    finally:
        cap.release()
    if seal is None or mismatched_schedule:
        raise ValueError(f"bootstrap unavailable or scene reconstruction differs: {mismatched_schedule}")
    verify_releases(seal, rows)
    if any(digest(path) != expected for path, expected in before.items()):
        raise ValueError("original source bytes changed during replay")
    log = output / "recorded_comparison"
    log.mkdir()
    with (log / "distance_frames.jsonl").open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False)+"\n")
    flat = []
    for row in rows:
        fixed = row.get("fixed_floor_shadow")
        control = baseline_control.get(row["frame"])
        flat.append(dict(frame=row["frame"], source_time_sec=row["source_time_sec"],
            baseline_distance_available=row["distance_available"], baseline_forward_m=row["distance_forward_m"],
            baseline_reason=row["reason"], support_pixel=(fixed or {}).get("support_pixel"),
            bootstrap_available=fixed is not None, fixed_reason=(fixed or {}).get("reason", "bootstrap_not_ready"),
            fixed_range_available=bool(fixed and fixed["models"][0]["range_available"]),
            fixed_horizontal_range_m=(fixed["models"][0]["horizontal_camera_foot_range_m"] if fixed else None),
            fixed_union_control_available=bool(control and control["models"][0]["range_available"]),
            fixed_union_control_range_m=(control["models"][0]["horizontal_camera_foot_range_m"] if control else None),
            fixed_union_control_reason=(control or {}).get("reason", "bootstrap_not_ready")))
    write_csv(output / "frame_comparison.csv", flat)
    write_csv(output / "scene_reconstruction.csv", scene_rows)
    report = summarize(log, output / "report", plots=False)
    control_log = output / "recorded_union_control"
    control_log.mkdir()
    with (control_log / "distance_frames.jsonl").open("x") as stream:
        for row in rows:
            control = copy.deepcopy(row)
            if row["frame"] in baseline_control:
                control["fixed_floor_shadow"] = baseline_control[row["frame"]]
            stream.write(json.dumps(control, separators=(",", ":"), allow_nan=False)+"\n")
    summarize(control_log, output / "union_control_report", plots=False)
    summary = dict(status="COMPLETED_SAME_SESSION_PAST_ONLY_DEVELOPMENT_REPLAY", session=SESSION,
        frames=len(rows), baseline_fields_unchanged=unchanged, bootstrap=seal,
        scene_checks=len(scene_rows), scene_acceptance_mismatches=mismatched_schedule,
        baseline_conditional_forward_frames=sum(r["distance_available"] for r in rows),
        fixed_horizontal_range_frames=sum(r["fixed_range_available"] for r in flat),
        fixed_union_control_frames=sum(r["fixed_union_control_available"] for r in flat),
        control_units_are_same_horizontal_range=True,
        union_control_also_never_changes_baseline_distance=True,
        fixed_reasons=dict(Counter(r["fixed_reason"] for r in flat)),
        timing="original r05 scene completion schedule; cone comparison logical +10ms; NOT current live timing",
        selected_known_success_recording=True, independent_holdout=False,
        fixed_model_holds_static_pose_assumption_not_verified=True,
        baseline_forward_and_fixed_horizontal_are_different_quantities=True,
        report_status=report["status"], no_live_summary_fabricated=True,
        fresh_detector_inference=False, new_capture=False, runtime_code_changed=False,
        physical_metric_verified=False, usable_for_ffb=False, physical_output=False, source_sha256=before)
    (output / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, layout="constrained")
    selected = [r for r in flat if r["fixed_range_available"]]
    axes[0].scatter([r["source_time_sec"] for r in selected], [r["fixed_horizontal_range_m"] for r in selected], s=5)
    axes[0].set(ylabel="Conditional camera-foot range [m]", title="Past-only fixed-floor replay: NOT live/physical accuracy")
    for label, level, predicate in (("baseline conditional forward", 1, lambda r:r["baseline_distance_available"]),
                                    ("fixed union-support control", 1.5, lambda r:r["fixed_union_control_available"]),
                                    ("fixed horizontal comparison", 2, lambda r:r["fixed_range_available"])):
        group = [r for r in flat if predicate(r)]
        axes[1].scatter([r["source_time_sec"] for r in group], [level]*len(group), s=5, label=label)
    for axis in axes:
        axis.axvline(seal["completed_at_sec"], color="grey", linestyle="--", label="bootstrap completion")
    axes[1].set(xlabel="Original source time [s]", yticks=[1, 1.5, 2], yticklabels=["Baseline", "Fixed union", "Fixed completion"])
    axes[1].legend()
    fig.savefig(output / "conditional_range_timeline.png", dpi=140)
    plt.close(fig)
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    main()
