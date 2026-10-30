#!/usr/bin/env python3
"""Summarize completed read-only distance logs, never activate a receiver.

Counts refer to processed frames, NOT displayed-frame coverage, accuracy,
camera FPS, or cross-PC capture latency. Partial logs are never a live approval.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

AGE_LIMIT_MS = 500.
CONDITIONAL = "CONDITIONAL_DIAGNOSTIC_NOT_VERIFIED_CONTACT"
TIMINGS = ("frame_age_ms", "predict_ms", "support_geometry_ms", "cone_service_ms")


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def number(value, name, minimum=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and (minimum is None or value >= minimum)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("finite numeric " + name + " required")
    return float(value)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty " + name + " required")
    return value


def _pixel_point(value, name):
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) != 2
            or any(type(item) is not int for item in value)
            or not (0 <= value[0] < 1280 and 0 <= value[1] < 720)):
        raise ValueError("native image pixel point required: " + name)
    return value


def _sha256_text(value, name):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("sha256 text required: " + name)
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("sha256 text required: " + name) from exc


def validate_frame_evidence(row):
    evidence = row.get("frame_evidence")
    if evidence is None:
        return
    if not isinstance(evidence, dict) or evidence.get("schema") != "cone_frame_evidence_v1":
        raise ValueError("frame evidence schema required")
    source = evidence.get("input")
    if (not isinstance(source, dict) or source.get("session") != row["session"]
            or source.get("frame") != row["frame"]):
        raise ValueError("frame evidence must describe the same input frame")
    if source.get("width") != 1280 or source.get("height") != 720:
        raise ValueError("native frame size required in evidence")
    number(source.get("media_time_sec"), "evidence media time")
    number(source.get("received_time_sec"), "evidence received time", 0)
    if abs(source["received_time_sec"]-row["source_time_sec"]) > 1e-9:
        raise ValueError("evidence reception time must match the row")
    boxes = evidence.get("selected_detector_boxes")
    if not isinstance(boxes, list):
        raise ValueError("selected detector box list required")
    for box in boxes:
        if not isinstance(box, dict):
            raise ValueError("selected detector box object required")
        x1, y1, x2, y2 = (number(box.get(key), "selected box " + key)
                          for key in ("x1", "y1", "x2", "y2"))
        confidence = number(box.get("confidence"), "selected box confidence")
        if (not 0 <= x1 < x2 <= 1280 or not 0 <= y1 < y2 <= 720
                or not 0 <= confidence <= 1 or box.get("class_id") != 0):
            raise ValueError("bounded single-class selected box required")
    support = evidence.get("support_observation")
    if not isinstance(support, dict) or support.get("floor_contact_verified") is not False:
        raise ValueError("unverified baseline support observation required")
    support_rows = support.get("support")
    if support_rows is not None:
        if not isinstance(support_rows, list):
            raise ValueError("support column list required")
        for point in support_rows:
            _pixel_point(point, "support column")
    point = _pixel_point(support.get("point"), "support point")
    if point is not None and (support_rows is None or point not in support_rows):
        raise ValueError("support point must be an actual observed column")
    mask = support.get("mask_diagnostics")
    if mask is not None:
        if not isinstance(mask, dict):
            raise ValueError("mask diagnostics object required")
        crop, shape = mask.get("crop_bounds"), mask.get("mask_shape")
        if (not isinstance(crop, list) or len(crop) != 4
                or any(type(value) is not int for value in crop)
                or not (0 <= crop[0] < crop[2] <= 1280 and 0 <= crop[1] < crop[3] <= 720)):
            raise ValueError("bounded crop required in mask diagnostics")
        if (not isinstance(shape, list) or len(shape) != 2
                or any(type(value) is not int or value <= 0 for value in shape)
                or shape != [crop[2]-crop[0], crop[3]-crop[1]]):
            raise ValueError("mask shape must match crop bounds")
        count = mask.get("qualifying_contour_count")
        if type(count) is not int or count < 0:
            raise ValueError("nonnegative qualifying contour count required")
        areas = mask.get("contour_areas")
        if (not isinstance(areas, list)
                or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                       for value in areas)):
            raise ValueError("finite contour areas required")
        bounds = mask.get("selected_contour_bounds")
        if bounds is not None:
            if (not isinstance(bounds, list) or len(bounds) != 4
                    or any(type(value) is not int for value in bounds)
                    or not (0 <= bounds[0] <= bounds[2] < 1280
                            and 0 <= bounds[1] <= bounds[3] < 720)):
                raise ValueError("selected contour bounds required")
        touches = mask.get("touches")
        if (not isinstance(touches, dict) or set(touches) != {"left", "top", "right", "bottom"}
                or any(type(value) is not bool for value in touches.values())):
            raise ValueError("four boolean touch edges required")
        edges = mask.get("touching_edges")
        if (not isinstance(edges, list)
                or edges != [name for name in ("left", "top", "right", "bottom") if touches[name]]):
            raise ValueError("touching edge list must match touch flags")
        if bounds is not None:
            expected = dict(left=bounds[0] == crop[0], top=bounds[1] == crop[1],
                            right=bounds[2] == crop[2]-1, bottom=bounds[3] == crop[3]-1)
            if touches != expected:
                raise ValueError("touch flags must follow contour and crop bounds")
        if count == 0 and (bounds is not None or any(touches.values()) or areas):
            raise ValueError("no-contour diagnostics must be empty")
        if support["reason"] == "colour_contour_reaches_roi_edge" and not any(touches.values()):
            raise ValueError("edge rejection requires a touching contour")
        if support["reason"] == "unverified_visible_colour_support" and any(touches.values()):
            raise ValueError("accepted support cannot touch the crop edge")
    pose = evidence.get("pose")
    if not isinstance(pose, dict):
        raise ValueError("pose evidence object required")
    for key in ("initialized", "pose_available", "scene_pending"):
        if type(pose.get(key)) is not bool:
            raise ValueError("explicit bool pose evidence required: " + key)
    for key in ("physical_transform_verified", "usable_for_ffb"):
        if pose.get(key) is not False:
            raise ValueError("unverified pose evidence required: " + key)
    up = pose.get("up_optical")
    if up is not None and (not isinstance(up, list) or len(up) != 3
                           or any(type(value) not in (int, float) or not math.isfinite(value)
                                  for value in up)):
        raise ValueError("finite optical up vector or null required")
    floor = evidence.get("floor_model")
    if (not isinstance(floor, dict) or floor.get("target_frame") != "paper7_ground_reference"
            or floor.get("physical_metric_verified") is not False):
        raise ValueError("conditional paper-reference floor model required")
    for key in ("config_sha256", "camera_candidate_sha256", "floor_candidate_sha256"):
        _sha256_text(floor.get(key), "evidence " + key)
    fresh = evidence.get("freshness")
    if not isinstance(fresh, dict):
        raise ValueError("freshness evidence object required")
    # 1 ms tolerates the pre-resync engine/worker stamp offset (observed ~0.02 ms);
    # new logs are resynced to the final row age in the worker.
    if abs(number(fresh.get("age_ms"), "evidence age", 0)-row["frame_age_ms"]) > 1.:
        raise ValueError("evidence age must match the row")
    if fresh.get("limit_ms") != AGE_LIMIT_MS:
        raise ValueError("screened 500 ms freshness limit required")
    if (type(fresh.get("within_limit")) is not bool
            or fresh["within_limit"] != (row["frame_age_ms"] <= AGE_LIMIT_MS)):
        raise ValueError("freshness verdict must follow the age limit")
    if (not isinstance(fresh.get("blockers"), list)
            or any(not isinstance(item, str) or not item for item in fresh["blockers"])):
        raise ValueError("string freshness blockers required")
    text(fresh.get("primary_reason"), "freshness primary reason")


def validate_fixed_floor_shadow(row):
    shadow = row.get("fixed_floor_shadow")
    if shadow is None:
        return
    if (not isinstance(shadow, dict) or shadow.get("schema") != "fixed_floor_shadow_v1"
            or shadow.get("session") != row["session"] or shadow.get("frame") != row["frame"]):
        raise ValueError("same-frame fixed-floor shadow required")
    for key in ("controlling_distance", "physical_metric_verified", "floor_contact_verified", "usable_for_ffb", "yaw_measured"):
        if shadow.get(key) is not False:
            raise ValueError("fixed-floor shadow must deny physical/control authority")
    if shadow.get("coordinate_frame") != "paper7_heading_carryover_camera_foot" or shadow.get("frame_age_limit_ms") != 500.:
        raise ValueError("explicit conditional coordinate frame and 500 ms bound required")
    for key in ("model_bundle_sha256", "camera_candidate_sha256", "heading_reference_sha256"):
        _sha256_text(shadow.get(key), key)
    text(shadow.get("model_session"), "fixed-floor model session")
    text(shadow.get("reason"), "fixed-floor reason")
    if type(shadow.get("image_quality_accepted")) is not bool:
        raise ValueError("explicit image quality verdict required")
    point = _pixel_point(shadow.get("support_pixel"), "fixed-floor support")
    source = shadow.get("support_source")
    if source == "baseline":
        expected = row.get("base_pixel")
    elif source in ("colour_support_shadow", "support_completion_shadow") and source in row:
        expected = (row[source].get("candidate") or {}).get("point")
    else:
        raise ValueError("explicit logged fixed-floor support source required")
    if point != expected:
        raise ValueError("fixed-floor point must match its same-frame source")
    models = shadow.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("explicit fixed-floor model result list required")
    names = []
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("comparison model result object required")
        names.append(text(model.get("model_name"), "model name"))
        text(model.get("reason"), "model result reason")
        available = model.get("range_available")
        if type(available) is not bool:
            raise ValueError("explicit comparison range verdict required")
        if available:
            value = number(model.get("horizontal_camera_foot_range_m"), "comparison horizontal range", 0)
            if (not .2 <= value <= 4. or shadow["model_session"] != row["session"]
                    or point is None or not shadow["image_quality_accepted"] or row["frame_age_ms"] > 500.):
                raise ValueError("comparison range violates session/support/quality/freshness")
        elif model.get("horizontal_camera_foot_range_m") is not None:
            raise ValueError("withheld fixed-floor range must not contain a numeric result")
    if len(set(names)) != len(names):
        raise ValueError("unique comparison model names required")
    available = any(model["range_available"] for model in models)
    if shadow.get("status") != ("CONDITIONAL_FIXED_FLOOR_SHADOW" if available else "WITHHELD"):
        raise ValueError("fixed-floor status disagrees with comparison ranges")


def validate_row(row):
    if not isinstance(row, dict):
        raise ValueError("frame row must be an object")
    text(row.get("session"), "session")
    if type(row.get("frame")) is not int or row["frame"] < 1:
        raise ValueError("positive integer frame required")
    source = number(row.get("source_time_sec"), "source time", 0)
    completed = number(row.get("completed_time_sec"), "completion time", source)
    for key in TIMINGS:
        number(row.get(key), key, 0)
    if abs(row["frame_age_ms"]-1000*(completed-source)) > .001:
        raise ValueError("frame age inconsistent with local reception/completion times")
    for key in ("distance_available", "scene_initialized", "scene_pending", "quality_accepted"):
        if type(row.get(key)) is not bool:
            raise ValueError("explicit bool " + key + " required")
    for key in ("physical_metric_verified", "floor_contact_verified", "usable_for_ffb"):
        if row.get(key) is not False:
            raise ValueError("read-only unapproved diagnostic flag required: " + key)
    if row.get("target_frame") != "paper7_ground_reference":
        raise ValueError("unexpected target coordinate frame")
    if "target_roi_native_xyxy" not in row:
        raise ValueError("explicit target ROI or null full-front scope required")
    roi = row["target_roi_native_xyxy"]
    if roi is not None and (not isinstance(roi, list) or len(roi) != 4
        or any(type(value) is not int for value in roi)
        or not (0 <= roi[0] < roi[2] <= 640 and 0 <= roi[1] < roi[3] <= 720)):
        raise ValueError("native front-lens target ROI required")
    text(row.get("reason"), "reason")
    text(row.get("inference_source"), "inference source")
    blockers = row.get("blockers")
    if not isinstance(blockers, list) or any(not isinstance(item, str) or not item for item in blockers):
        raise ValueError("string blocker list required")
    if row["distance_available"]:
        forward = number(row.get("distance_forward_m"), "forward distance", 0)
        number(row.get("lateral_right_m"), "lateral distance")
        if (forward == 0 or blockers or row["reason"] != CONDITIONAL
                or not row["quality_accepted"] or not row["scene_initialized"] or row["scene_pending"]
                or row["frame_age_ms"] > AGE_LIMIT_MS):
            raise ValueError("inconsistent available diagnostic distance")
    elif (not blockers or blockers[0] != row["reason"]
          or row.get("distance_forward_m") is not None or row.get("lateral_right_m") is not None):
        raise ValueError("withheld distance must have blockers and no numeric distance")
    if "colour_support_shadow" in row:
        shadow = row["colour_support_shadow"]
        if (not isinstance(shadow, dict) or shadow.get("controlling_distance") is not False
                or shadow.get("usable_for_ffb") is not False):
            raise ValueError("colour shadow must never control distance or FFB")
        candidate = shadow.get("candidate")
        if candidate is not None:
            if (not isinstance(candidate, dict)
                    or any(candidate.get(key) is not False for key in
                           ("controlling_distance", "floor_contact_verified", "usable_for_ffb"))):
                raise ValueError("unverified colour shadow candidate required")
            point = candidate.get("point")
            if point is not None and (not isinstance(point, list) or len(point) != 2
                    or any(type(v) is not int for v in point)
                    or not (0 <= point[0] < 1280 and 0 <= point[1] < 720)
                    or not isinstance(candidate.get("support"), list) or point not in candidate["support"]):
                raise ValueError("shadow point must be an actual native support column")
    if "support_completion_shadow" in row:
        shadow = row["support_completion_shadow"]
        if (not isinstance(shadow, dict) or any(shadow.get(key) is not False for key in
                ("controlling_distance", "physical_metric_verified", "usable_for_ffb"))):
            raise ValueError("completion shadow must remain physically unverified and non-controlling")
        candidate = shadow.get("candidate")
        if candidate is not None:
            if (not isinstance(candidate, dict) or any(candidate.get(key) is not False for key in
                    ("controlling_distance", "physical_metric_verified", "floor_contact_verified", "usable_for_ffb"))
                    or any(type(candidate.get(key)) is not bool for key in ("completion_attempted", "completion_granted"))):
                raise ValueError("unverified completion candidate and explicit bool state required")
            point = candidate.get("point")
            if point is not None and (not isinstance(point, list) or len(point) != 2
                    or any(type(v) is not int for v in point)
                    or not (0 <= point[0] < 1280 and 0 <= point[1] < 720)
                    or not isinstance(candidate.get("support"), list) or point not in candidate["support"]):
                raise ValueError("completion point must be an actual native support column")
            if candidate["completion_granted"] and (point is None or not candidate["completion_attempted"]):
                raise ValueError("completion grant requires an attempted observation and support point")
    validate_frame_evidence(row)
    validate_fixed_floor_shadow(row)


def load_frames(path, allow_truncated_last_line=False):
    payload = path.read_bytes()
    lines, rows = payload.splitlines(), []
    truncated = False
    seen_sessions, last = set(), None
    for index, line in enumerate(lines):
        try:
            row = json.loads(line, parse_constant=reject_constant)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if allow_truncated_last_line and index == len(lines)-1 and not payload.endswith(b"\n"):
                truncated = True
                break
            raise ValueError(f"invalid JSON on frame line {index+1}") from exc
        try:
            validate_row(row)
            if last is not None:
                if (row["source_time_sec"] <= last["source_time_sec"]
                        or row["completed_time_sec"] < last["completed_time_sec"]):
                    raise ValueError("nonincreasing local timestamps")
                if row["session"] == last["session"]:
                    if row["frame"] <= last["frame"]:
                        raise ValueError("nonincreasing session frame")
                    if row["target_roi_native_xyxy"] != last["target_roi_native_xyxy"]:
                        raise ValueError("target ROI changed within one session")
                elif row["session"] in seen_sessions:
                    raise ValueError("retired session reappeared in log")
            seen_sessions.add(row["session"])
            rows.append(row)
            last = row
        except ValueError as exc:
            raise ValueError(f"frame line {index+1}: {exc}") from exc
    return rows, truncated, digest_bytes(payload)


def statistics(values):
    values = sorted(values)
    def quantile(fraction):
        position = (len(values)-1)*fraction
        lo, hi = math.floor(position), math.ceil(position)
        return values[lo]+(values[hi]-values[lo])*(position-lo)
    return dict(count=len(values), median=quantile(.5) if values else None,
                p95=quantile(.95) if values else None, maximum=values[-1] if values else None)


def session_statistics(session, rows):
    active = [r for r in rows if r["distance_available"]]
    span = rows[-1]["completed_time_sec"]-rows[0]["completed_time_sec"]
    return dict(session=session, processed_frames=len(rows), conditional_output_frames=len(active),
        target_roi_native_xyxy=rows[0]["target_roi_native_xyxy"],
        conditional_fraction_of_processed_frames=len(active)/len(rows),
        logged_completion_span_sec=span,
        processed_completion_hz=(len(rows)-1)/span if len(rows) > 1 and span > 0 else None,
        unlogged_sequence_numbers_between_logged_frames=sum(b["frame"]-a["frame"]-1 for a,b in zip(rows, rows[1:])),
        first_conditional_source_offset_sec=(active[0]["source_time_sec"]-rows[0]["source_time_sec"]) if active else None,
        reasons=dict(Counter(r["reason"] for r in rows)),
        blockers=dict(Counter(b for r in rows for b in set(r["blockers"]))),
        distance_forward_m=statistics([r["distance_forward_m"] for r in active]),
        timings_ms={key: statistics([r[key] for r in rows]) for key in TIMINGS})


def plot_rows(rows, output, synthetic):
    import os
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), layout="constrained")
    title = "INJECTED / UNVERIFIED PREDICTOR" if synthetic else "Processed distance diagnostic logs"
    fig.suptitle(title+" | NOT accuracy / camera FPS / capture latency")
    origin = rows[0]["source_time_sec"] if rows else 0.
    for session in dict.fromkeys(r["session"] for r in rows):
        group = [r for r in rows if r["session"] == session]
        active = [r for r in group if r["distance_available"]]
        axes[0].scatter([r["source_time_sec"]-origin for r in active],
                        [r["distance_forward_m"] for r in active], s=12, label=session)
        axes[1].scatter([r["source_time_sec"]-origin for r in group],
                        [r["frame_age_ms"] for r in group], s=10, label=session)
    axes[0].set(ylabel="Conditional forward [m]", xlabel="Local source reception offset [s]")
    axes[1].axhline(AGE_LIMIT_MS, color="red", linestyle="--", label="500 ms source-age limit")
    axes[1].set(ylabel="Reception to completion [ms]", xlabel="Local source reception offset [s]")
    reasons = Counter(r["reason"] for r in rows)
    names = list(reasons)
    axes[2].barh(range(len(names)), [reasons[n] for n in names])
    axes[2].set_yticks(range(len(names)), [n.replace(CONDITIONAL, "CONDITIONAL OUTPUT") for n in names], fontsize=8)
    axes[2].set(xlabel="Processed frame count (not display duration)")
    if not rows:
        axes[0].text(.5, .5, "NO FRAME LOGS", ha="center", transform=axes[0].transAxes)
    for axis in axes[:2]:
        if rows:
            axis.set_xlim(-.05, max(.05, rows[-1]["source_time_sec"]-origin+.05))
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize=7)
        axis.grid(alpha=.2)
    fig.savefig(output/"processing_diagnostics.png", dpi=130)
    plt.close(fig)


def summarize(input_dir, output_dir, *, allow_truncated_last_line=False, plots=True):
    root, output = Path(input_dir).expanduser().resolve(), Path(output_dir).expanduser().resolve()
    if output.exists():
        raise ValueError("new report output directory required")
    source = root/"distance_frames.jsonl"
    rows, truncated, sha = load_frames(source, allow_truncated_last_line)
    sources = {str(source): sha, str(Path(__file__).resolve()): digest_bytes(Path(__file__).read_bytes())}
    final_path, final = root/"live_summary.json", None
    if final_path.exists():
        payload = final_path.read_bytes()
        final = json.loads(payload, parse_constant=reject_constant)
        if not isinstance(final, dict):
            raise ValueError("live summary must be an object")
        for key in ("physical_metric_verified", "usable_for_ffb", "physical_output"):
            if final.get(key) is not False:
                raise ValueError("unapproved read-only live summary flag required: " + key)
        if "target_roi_native_xyxy" in final and any(r["target_roi_native_xyxy"] != final["target_roi_native_xyxy"] for r in rows):
            raise ValueError("frame ROI disagrees with live summary")
        sources[str(final_path)] = digest_bytes(payload)
    groups = {session: [r for r in rows if r["session"] == session]
              for session in dict.fromkeys(r["session"] for r in rows)}
    sessions = [session_statistics(name, group) for name, group in groups.items()]
    inference = dict(Counter(r["inference_source"] for r in rows))
    synthetic = any(name != "live_cuda_yolo" for name in inference)
    shutdown = final.get("shutdown") if final is not None else None
    finalized = (isinstance(shutdown, dict) and shutdown.get("shutdown_complete") is True
                 and shutdown.get("worker_stopped") is True and shutdown.get("scene_job_running") is False
                 and final.get("runtime_status") == "STOPPED" and final.get("run_error") is None
                 and final.get("worker_error") is None and final.get("cleanup_errors") == [])
    capture = "INCOMPLETE_CAPTURE" if truncated or not finalized else "FINALIZED_DIAGNOSTIC_LOG"
    if not rows:
        capture = "NO_FRAME_EVIDENCE"
    summary = dict(schema="cone_distance_live_log_report_v1", status=capture,
        processed_frames=len(rows), conditional_output_frames=sum(r["distance_available"] for r in rows),
        session_count=len(sessions), sessions=sessions, inference_sources=inference,
        contains_injected_or_unverified_predictor=synthetic,
        missing_live_summary=final is None, truncated_final_line_ignored=truncated,
        recorded_runtime_status=final.get("runtime_status") if final is not None else None,
        recorded_run_error=final.get("run_error") if final is not None else None,
        recorded_shutdown=shutdown, source_sha256=sources, plots_generated=plots,
        physical_metric_verified=False, usable_for_ffb=False, physical_output=False,
        display_availability_measured=False, camera_to_receiver_latency_measured=False,
        notes=["Counts include only processed/logged frames, not all received frames or actual GUI display.",
               "Sequence gaps are unlogged decoded frame numbers, not network packet loss.",
               "Completion frequency is not camera FPS. Frame age uses receiver-local reception time.",
               "No ground truth input: distance statistics are NOT accuracy measurements.",
               "Finalization does not mean distance estimation or hardware is approved."])
    shadow_rows = [r["colour_support_shadow"] for r in rows if "colour_support_shadow" in r]
    shadow_note = ""
    if shadow_rows:
        candidates = [r["candidate"] for r in shadow_rows if r.get("candidate") is not None]
        points = sum(c.get("point") is not None for c in candidates)
        summary["colour_support_shadow"] = dict(
            recorded_frames=len(shadow_rows), selected_candidate_frames=len(candidates),
            unverified_image_point_frames=points,
            selected_colours=dict(Counter(c.get("selected_colour") or "withheld" for c in candidates)),
            reasons=dict(Counter(c["reason"] for c in candidates)), controlling_distance=False,
            usable_for_ffb=False)
        shadow_note = (f"\n色分離の比較ログ：{len(shadow_rows)}処理frame、画像上の候補点あり{points}件。"
                       "この候補は距離出力・姿勢初期化・FFBの判定に使用していません。\n")
    completion_rows = [r["support_completion_shadow"] for r in rows if "support_completion_shadow" in r]
    if completion_rows:
        candidates = [r["candidate"] for r in completion_rows if r.get("candidate") is not None]
        points = sum(c.get("point") is not None for c in candidates)
        grants = sum(c["completion_granted"] for c in candidates)
        summary["support_completion_shadow"] = dict(recorded_frames=len(completion_rows),
            selected_candidate_frames=len(candidates), unverified_image_point_frames=points,
            completion_attempted_frames=sum(c["completion_attempted"] for c in candidates),
            completion_granted_frames=grants,
            previous_shadow_point_frames=sum(c.get("original_shadow_point") is not None for c in candidates),
            reasons=dict(Counter(c["reason"] for c in candidates)),
            completion_reasons=dict(Counter(c["completion_reason"] for c in candidates)),
            controlling_distance=False, physical_metric_verified=False, usable_for_ffb=False)
        shadow_note += (f"\n左右枠接触の比較ログ：{len(completion_rows)}処理frame、画像上の候補点あり{points}件、"
                        f"追加の候補点取得{grants}件。物理接地・距離精度の合格判定ではなく、距離・FFBへ使用していません。\n")
    evidence_rows = [r["frame_evidence"] for r in rows if "frame_evidence" in r]
    if evidence_rows:
        summary["frame_evidence"] = dict(
            recorded_frames=len(evidence_rows),
            frames_with_one_selected_box=sum(len(e["selected_detector_boxes"]) == 1
                                             for e in evidence_rows),
            frames_with_no_selected_box=sum(not e["selected_detector_boxes"]
                                            for e in evidence_rows),
            frames_with_support_point=sum(e["support_observation"]["point"] is not None
                                          for e in evidence_rows),
            frames_with_pose_available=sum(e["pose"]["pose_available"] for e in evidence_rows),
            frames_within_freshness_limit=sum(e["freshness"]["within_limit"]
                                              for e in evidence_rows),
            floor_model_config_sha256=sorted({e["floor_model"]["config_sha256"]
                                              for e in evidence_rows}),
            controlling_distance=False, physical_metric_verified=False,
            floor_contact_verified=False, usable_for_ffb=False)
        shadow_note += (f"\n同一フレーム証拠ログ：{len(evidence_rows)}処理frameに選択bbox・支持点・"
                        "姿勢・床モデル識別子・鮮度理由を記録。距離制御・接地判定には使用していません。\n")
    fixed_rows = [r["fixed_floor_shadow"] for r in rows if "fixed_floor_shadow" in r]
    if fixed_rows:
        summary["fixed_floor_shadow"] = dict(recorded_frames=len(fixed_rows),
            frames_with_comparison_range=sum(any(m["range_available"] for m in r["models"]) for r in fixed_rows),
            reasons=dict(Counter(r["reason"] for r in fixed_rows)),
            model_bundle_sha256=sorted({r["model_bundle_sha256"] for r in fixed_rows}),
            per_model=[dict(model_bundle_sha256=bundle, model_name=name,
                horizontal_range_m=statistics([m["horizontal_camera_foot_range_m"] for r in fixed_rows
                    if r["model_bundle_sha256"] == bundle for m in r["models"]
                    if m["model_name"] == name and m["range_available"]]))
                for bundle, name in sorted({(r["model_bundle_sha256"], m["model_name"])
                                            for r in fixed_rows for m in r["models"]})],
            controlling_distance=False, physical_metric_verified=False, usable_for_ffb=False)
        shadow_note += (f"\n固定床モデルの比較ログ：{len(fixed_rows)}処理frame。"
            "元の条件付き距離とは別集計。水平距離であり、接地・実測精度・車体座標・FFBの合格ではありません。\n")
    output.mkdir(parents=True, exist_ok=False)
    fields = ("session", "frame", "source_time_sec", "completed_time_sec", "distance_available",
              "distance_forward_m", "lateral_right_m", "reason", *TIMINGS, "inference_source")
    with (output/"processed_frames.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    if plots:
        plot_rows(rows, output, synthetic)
    metric_table = ["|Session|処理件数|条件付き出力|記録間の未処理番号数|", "|---|---:|---:|---:|"]
    metric_table += [f"|{s['session'].replace('|', '/')}|{s['processed_frames']}|{s['conditional_output_frames']}|{s['unlogged_sequence_numbers_between_logged_frames']}|" for s in sessions]
    details = []
    for session in sessions:
        name = session["session"].replace("|", "/")
        roi = session["target_roi_native_xyxy"]
        scope = f"指定ROI `{roi}`。この範囲の外は監視対象外。" if roi else "前方レンズ全体（複数コーンは保留）。"
        details += [f"\n## Session: {name}\n", scope+"\n",
                    "|処理結果の主理由|件数|", "|---|---:|"]
        details += [f"|{reason.replace('|', '/')}|{count}|" for reason, count in session["reasons"].items()]
        details += ["\n|処理時間項目 [ms]|中央値|p95|最大|", "|---|---:|---:|---:|"]
        for key, value in session["timings_ms"].items():
            details.append(f"|{key}|{value['median']:.3f}|{value['p95']:.3f}|{value['maximum']:.3f}|")
    (output/"report.md").write_text("# 測距処理ログの集計\n\n"
        + f"状態：`{capture}`。実機・距離精度の合格判定ではありません。\n\n"
        + ("**注入テストまたは未確認predictorを含むデータです。実GPUの結果と混同しないでください。**\n\n" if synthetic else "")
        + "\n".join(metric_table)+"\n\n処理・記録されたフレームだけの集計です。表示時間率、ネットワーク損失率、カメラFPSではありません。\n\n"
        + "距離はpaper7基準の条件付き推定値です。実測基準がないため精度・誤差は評価していません。\n\n"
        + "`summary.json`にsession別の保留理由、各blocker、受信後の処理時間の中央値・p95・最大値と入力SHA256を保存しています。\n"
        + shadow_note + "\n".join(details)+"\n")
    summary["output_sha256"] = {str(p.relative_to(output)): digest_bytes(p.read_bytes())
        for p in (output/"processed_frames.csv", output/"report.md", output/"processing_diagnostics.png") if p.is_file()}
    (output/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-truncated-last-line", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = summarize(args.input_dir, args.output_dir,
            allow_truncated_last_line=args.allow_truncated_last_line, plots=not args.no_plots)
    except (ValueError, OSError, ImportError) as exc:
        print("[ERROR] " + str(exc))
        return 1
    print(f"{result['status']}: processed={result['processed_frames']}, conditional={result['conditional_output_frames']}; NOT physical approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
