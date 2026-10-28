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
        + "\n".join(details)+"\n")
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
