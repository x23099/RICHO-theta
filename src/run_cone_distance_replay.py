#!/usr/bin/env python3
"""Ordered native recording -> shared diagnostic distance core (no camera/ROS).

Saved YOLO runs are an explicit replay adapter, NOT fresh model inference.
Scene hypotheses and colour supports are recalculated from original pixels.
Functional replay virtual time includes measured scene-service delay, not a
reproduction of network/GPU latency or real-time throughput.
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import time

import cv2
import numpy as np

from cone_distance_core import DEFAULT_CONFIG, ConeDistanceEngine, digest, render_distance
from cone_scene_diagnostic import estimate_scene
from theta_rtc_frames import NativeFrame, native_frame


def read_rows(path):
    with Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def load_saved_run(session, directory, settings):
    original = read_rows(session / "detections.csv")
    frames = [r for r in read_rows(directory / "frames.csv") if r["session"] == session.name]
    proof = json.loads((directory / "provenance.json").read_text())
    candidate = proof["candidate"]
    if (candidate["sha256"] != settings["weights_sha256"] or candidate["confidence"] != settings["confidence"]
            or candidate["imgsz"] != settings["imgsz"] or candidate["nms_iou"] != settings["nms_iou"]
            or candidate["max_det"] != settings["max_det"]):
        raise ValueError("saved detector candidate / thresholds differ from diagnostic configuration")
    sources = [v for key, v in proof["source_sessions"].items() if Path(key).name == session.name]
    if len(sources) != 1:
        raise ValueError("one saved source-session identity required")
    for name in ("raw.avi", "metadata.json", "detections.csv"):
        if digest(session / name) != sources[0][name]:
            raise ValueError("saved inference was made from different original bytes: " + name)
    if not original or len(frames) != len(original):
        raise ValueError("complete saved frame ledger required")
    by_frame = defaultdict(list)
    for row in read_rows(directory / "predictions.csv"):
        if row["session"] != session.name:
            continue
        by_frame[int(row["frame"])].append(row)
    times, last = [], -1.0
    for index, (source, saved) in enumerate(zip(original, frames), 1):
        t = float(source["time_sec"])
        if (int(source["frame"]) != index or int(saved["frame"]) != index
                or not np.isfinite(t) or t <= last or t < 0 or t != float(saved["time_sec"])):
            raise ValueError("exact same-frame strictly increasing original time ledger required")
        predictions = by_frame[index]
        if len(predictions) != int(saved["detections"]) or any(float(p["time_sec"]) != t for p in predictions):
            raise ValueError("saved prediction coverage/time mismatch")
        last = t
        times.append(t)
    if any(n < 1 or n > len(times) for n in by_frame):
        raise ValueError("saved predictions outside original frame ledger")
    return times, by_frame


def save_example(output, frame, result):
    stem = f"f{frame.sequence:06d}"
    original = output / "originals" / (stem + ".png")
    derived = output / "visualizations" / (stem + "_recomputed.png")
    for path in (original, derived):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ValueError("example would overwrite an existing file")
    if not cv2.imwrite(str(original), frame.image) or not cv2.imwrite(str(derived), render_distance(frame.image, result, replay=True)):
        raise RuntimeError("example PNG write failed")
    return dict(frame=frame.sequence, source_time_sec=frame.received_at, reason=result["reason"],
                distance_available=result["distance_available"], distance_forward_m=result["distance_forward_m"],
                original=str(original.relative_to(output)), original_sha256=digest(original),
                visualization=str(derived.relative_to(output)), visualization_sha256=digest(derived),
                visualization_is_posthoc_recomputation=True, source_image_edited=False)


def replay(session, saved_run, output, config=DEFAULT_CONFIG, *, target_roi=None):
    session, saved_run, output = (Path(p).expanduser().resolve() for p in (session, saved_run, output))
    if output.exists() or output.is_relative_to(session) or session.is_relative_to(output):
        raise ValueError("new analysis output outside the original recording required")
    engine = ConeDistanceEngine(config, target_roi=target_roi)
    times, by_frame = load_saved_run(session, saved_run, engine.settings)
    source_paths = [session / name for name in ("raw.avi", "detections.csv", "metadata.json")]
    source_paths += [saved_run / name for name in ("frames.csv", "predictions.csv", "provenance.json")]
    source_paths += [Path(config).resolve(), Path(__file__), Path(__file__).with_name("cone_distance_core.py"),
                     Path(__file__).with_name("cone_scene_diagnostic.py"), Path(__file__).with_name("cone_support_quality.py"),
                     Path(__file__).with_name("scene_sampling_clock.py"),
                     Path(__file__).with_name("angular_fisheye_geometry.py"), Path(__file__).with_name("fisheye_floor_geometry.py")]
    source_paths += [Path(__file__).resolve().parents[1] / engine.settings[key + "_candidate"] for key in ("camera", "floor")]
    hashes = {str(p): digest(p) for p in source_paths}
    capture = cv2.VideoCapture(str(session / "raw.avi"))
    if not capture.isOpened():
        raise ValueError("cannot open original native recording")
    output.mkdir(parents=True, exist_ok=False)
    engine.reset(session.name)
    pending = None
    rows, jobs, examples, states = [], [], [], set()
    started = time.perf_counter()
    try:
        for number, source_time in enumerate(times, 1):
            decode_start = time.perf_counter()
            ok, image = capture.read()
            if not ok:
                raise ValueError("original video ended before ledger")
            native_frame(image)
            decode_ms = 1000 * (time.perf_counter()-decode_start)
            frame = NativeFrame(session.name, number, source_time, source_time, image)
            if pending is not None and pending[2] <= source_time:
                engine.complete_scene(pending[0], pending[1], pending[2])
                pending = None
            if pending is None and engine.scene_due(source_time):
                ticket = engine.begin_scene(frame)
                scene_start = time.perf_counter()
                scene = estimate_scene(image, engine.camera, engine.prior_up)
                service = time.perf_counter()-scene_start
                pending = ticket, scene, source_time + service
                jobs.append(dict(frame=number, source_time_sec=source_time, simulated_completion_sec=pending[2],
                                 target_time_sec=ticket.target_time_sec, skipped_targets=ticket.skipped_targets,
                                 measured_scene_service_ms=1000*service, accepted=scene["accepted"], reason=scene["reason"]))
            query_start = time.perf_counter()
            boxes = by_frame[number]
            result = engine.measure(frame, boxes, lambda: source_time + time.perf_counter()-query_start)
            support_ms = 1000*(time.perf_counter()-query_start)
            result.update(decode_ms=decode_ms, saved_detection_and_core_ms=support_ms,
                          inference_source="saved_yolo_predictions_NOT_fresh_inference")
            rows.append(result)
            state = "available" if result["distance_available"] else result["reason"]
            if state not in states and (len(examples) < 7 or state == "available"):
                states.add(state)
                examples.append(save_example(output, frame, result))
            if number % 300 == 0:
                print(f"[INFO] ordered replay {number}/{len(times)}", flush=True)
        if capture.read()[0]:
            raise ValueError("extra original video frames outside ledger")
    finally:
        capture.release()
    for path, expected in hashes.items():
        if digest(path) != expected:
            raise ValueError("source changed during replay: " + path)
    def write_csv(name, data):
        with (output / name).open("x", newline="") as stream:
            serialized = [{k: json.dumps(v) if isinstance(v, (list, dict, tuple)) else v for k, v in r.items()} for r in data]
            writer = csv.DictWriter(stream, fieldnames=list(serialized[0]))
            writer.writeheader()
            writer.writerows(serialized)
    write_csv("frame_results.csv", rows)
    write_csv("scene_jobs.csv", jobs)
    selected = [r for r in rows if r["distance_available"]]
    summary = dict(status="COMPLETED_ORDERED_FUNCTIONAL_REPLAY_NOT_LIVE_VALIDATION", session=session.name,
        frames=len(rows), diagnostic_frames=len(selected),
        target_roi_native_xyxy=engine.target_roi, scope_is_operator_choice_not_detection_validation=True,
        scene_cadence="source-origin anchored 1s grid; no queued catch-up images",
        first_diagnostic_source_time_sec=selected[0]["source_time_sec"] if selected else None,
        reason_counts=dict(Counter(r["reason"] for r in rows)),
        source_duration_sec=times[-1]-times[0], replay_wall_sec=time.perf_counter()-started,
        scene_jobs=len(jobs), scene_accepted=sum(j["accepted"] for j in jobs),
        scene_service_ms_median=float(np.median([j["measured_scene_service_ms"] for j in jobs])),
        core_ms_median=float(np.median([r["saved_detection_and_core_ms"] for r in rows])),
        source_sha256=hashes, examples=examples,
        saved_detector_predictions_reused=True, fresh_yolo_inference=False,
        scene_completion_clock="source timestamp plus measured local CPU scene cost; functional counterfactual only",
        end_to_end_latency_reproduced=False, realtime_throughput_verified=False,
        future_scene_images_used=False, reference_distances_used_by_engine=False,
        source_images_edited=False, physical_metric_verified=False, usable_for_ffb=False, physical_output=False,
        output_sha256={p.name: digest(p) for p in output.glob("*.csv")})
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("source_sha256", "output_sha256", "examples")}, indent=2))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--saved-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--target-roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                        help="optional explicit front-native bbox-centre scope; outside is NOT monitored")
    args = parser.parse_args(argv)
    replay(args.session, args.saved_run, args.output_dir, args.config, target_roi=args.target_roi)


if __name__ == "__main__":
    main()
