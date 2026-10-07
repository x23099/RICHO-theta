"""Read-only offline analysis of the supplied 2026-10-07 trial.

Inputs must already be safely extracted with analyze_field_recording.safe_extract_archive.
No ROS node, network publishing, hardware access, or detector tuning is performed.
"""
import argparse
import csv
import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "Experimental_results/2026-09-17"))
sys.path.insert(0, str(REPO / "src"))
import analyze_phase5_bag_r02 as decoder
from analyze_field_recording import summarize_session_integrity

DECODERS = {
    "/collision/ffb_intent": decoder.decode_command,
    "/collision/ffb_command": decoder.decode_command,
    "/collision/ffb_status": decoder.decode_status,
    "/collision/ffb_challenge": decoder.decode_challenge,
    "/collision/ffb_relay_diagnostics": decoder.decode_relay_diagnostic,
    "/phase5/mock_odom": decoder.decode_odom,
}


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def stats(values):
    values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return dict(n=len(values), min=min(values), median=float(np.median(values)),
                p95=float(np.percentile(values, 95)), max=max(values)) if values else None


def runs(rows, key, time_key):
    result = []
    for row in rows:
        value = row[key]
        if not result or result[-1]["value"] != value:
            result.append(dict(value=value, first_sec=float(row[time_key]),
                               last_sec=float(row[time_key]), samples=0))
        result[-1]["last_sec"] = float(row[time_key])
        result[-1]["samples"] += 1
    for index, run in enumerate(result):
        run["elapsed_first_to_last_sec"] = run["last_sec"] - run["first_sec"]
        run["next_sample_sec"] = result[index + 1]["first_sec"] if index + 1 < len(result) else None
    return result


def command_identity(row):
    return (row["source"], row["sequence"], row["receiver_session_id"], row["receiver_token"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--kobuki-db", type=Path, required=True)
    parser.add_argument("--hsr-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--plot-title", default="2026-10-07 r01: partial occlusion samples; full occlusion NOT confirmed")
    parser.add_argument("--recovery-window", nargs=2, type=float, default=(26.5, 29.0))
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    camera = read_csv(args.session / "detections.csv")
    metadata = json.loads((args.session / "metadata.json").read_text())
    start_ns, end_ns = decoder.camera_recording_window(args.session.name, camera)
    summary = {"session": args.session.name, "time_alignment_limit":
               "Camera start is inferred from session name. Cross-PC wall times are for plotting/windowing only, not one-way latency.",
               "camera_window_jst": [decoder.clock(start_ns), decoder.clock(end_ns)],
               "integrity": summarize_session_integrity(args.session, "provided_archive"),
               "source_sha256": {n: hashlib.sha256((args.session / n).read_bytes()).hexdigest()
                                 for n in ("metadata.json", "detections.csv", "raw.avi")}}
    expected = json.loads((REPO / "src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json").read_text())
    summary["v12_parameter_differences"] = {
        k: {"expected": v, "recorded": metadata["parameters"].get(k)}
        for k, v in expected.items() if metadata["parameters"].get(k) != v}
    summary["publisher_metadata"] = metadata["collision_ffb_publisher"]
    summary["camera_capture_properties"] = metadata["camera_capture_properties"]
    bags = {}
    for pc, db in (("kobuki", args.kobuki_db), ("hsr", args.hsr_db)):
        events = {topic: [] for topic in DECODERS}
        with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            topics = dict(connection.execute("SELECT id,name FROM topics"))
            unknown = sorted(set(topics.values()) - set(DECODERS))
            for topic_id, ns, data in connection.execute("SELECT topic_id,timestamp,data FROM messages ORDER BY timestamp"):
                topic = topics[topic_id]
                if topic not in DECODERS:
                    continue
                row = DECODERS[topic](data)
                row.update(bag_ns=ns, camera_relative_sec=(ns - start_ns) / 1e9,
                           in_camera_window=start_ns <= ns <= end_ns)
                events[topic].append(row)
        bags[pc] = events
        detail = {"unparsed_topics": unknown, "database_sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
                  "counts_full_bag": {k: len(v) for k, v in events.items()},
                  "counts_camera_window": {k: sum(r["in_camera_window"] for r in v) for k, v in events.items()},
                  "spans_jst": {k: [decoder.clock(v[0]["bag_ns"]), decoder.clock(v[-1]["bag_ns"])] if v else None for k, v in events.items()}}
        for topic, rows in events.items():
            write_csv(out / f"{pc}_{topic.rsplit('/', 1)[-1]}.csv", rows)
        statuses = events["/collision/ffb_status"]
        diagnostics = events["/collision/ffb_relay_diagnostics"]
        detail.update(output_modes=dict(Counter(r["output_mode"] for r in statuses)),
                      faults_full_bag=[r for r in statuses if r["fault"]],
                      max_applied_magnitude=max((r["applied_magnitude"] for r in statuses), default=None),
                      active_statuses_full_bag=sum(r["output_active"] for r in statuses),
                      last_status=statuses[-1] if statuses else None,
                      relay_outcomes_full_bag=dict(Counter(r["outcome"] for r in diagnostics)),
                      relay_rejections=[r for r in diagnostics if r["outcome"] != "forwarded"],
                      relay_active_rejections=[r for r in diagnostics if r["intent_active"] and r["outcome"] != "forwarded"],
                      relay_camera_window_outcomes=dict(Counter(r["outcome"] for r in diagnostics if r["in_camera_window"])),
                      relay_challenge_age_forwarded_sec=stats(r.get("challenge_age_sec") for r in diagnostics if r["outcome"] == "forwarded"),
                      relay_stream_restart_counts=sorted({r.get("challenge_stream_restart_count") for r in diagnostics}),
                      relay_stream_timeouts=sorted({r.get("challenge_stream_timeout_sec") for r in diagnostics}))
        challenge = events["/collision/ffb_challenge"]
        detail["challenge_bag_interarrival_ms"] = stats((b["bag_ns"] - a["bag_ns"]) / 1e6 for a, b in zip(challenge, challenge[1:]))
        detail["challenge_bag_gaps_over_60ms"] = sum(b["bag_ns"] - a["bag_ns"] > 60_000_000 for a, b in zip(challenge, challenge[1:]))
        odom_runs = runs(events["/phase5/mock_odom"], "linear_x", "camera_relative_sec")
        write_csv(out / f"{pc}_mock_odom_runs.csv", odom_runs)
        detail["mock_odom_runs"] = odom_runs
        summary[pc] = detail
    for key in ("odom_linear_mps", "collision_risk_level", "detected", "measurement_accepted", "collision_ffb_active"):
        write_csv(out / f"camera_{key}_runs.csv", runs(camera, key, "time_sec"))
    summary["camera_counts"] = {key: dict(Counter(r[key] for r in camera)) for key in (
        "detected", "measurement_accepted", "collision_risk_level", "collision_ffb_active", "rejection_reason", "odom_available", "collision_ffb_publish_success")}
    summary["frame_interarrival_ms"] = stats((float(b["time_sec"]) - float(a["time_sec"])) * 1000 for a, b in zip(camera, camera[1:]))
    summary["capture_elapsed_fps"] = (len(camera) - 1) / (float(camera[-1]["time_sec"]) - float(camera[0]["time_sec"]))
    summary["processing_total_before_csv_ms"] = stats(r["processing_total_before_csv_ms"] for r in camera)
    active = [r for r in camera if r["collision_ffb_active"] == "1"]
    delivery = []
    for r in active:
        seq = int(r["collision_ffb_sequence"])
        record = dict(frame=r["frame"], time_sec=r["time_sec"], sequence=seq,
                      risk=r["collision_risk_level"], camera_reason=r["collision_ffb_reason"])
        for pc, ev in bags.items():
            intents = [x for x in ev["/collision/ffb_intent"] if x["sequence"] == seq and x["source"] == "bird_eye" and x["active"]]
            commands = [x for x in ev["/collision/ffb_command"] if x["sequence"] == seq and x["source"] == "bird_eye" and x["active"]]
            statuses = [x for x in ev["/collision/ffb_status"] if x["sequence"] == seq and x["source"] == "bird_eye" and x["output_active"] and not x["fault"]]
            record.update({f"{pc}_active_intents": len(intents), f"{pc}_active_commands": len(commands),
                           f"{pc}_active_statuses": len(statuses)})
        delivery.append(record)
    write_csv(out / "active_delivery.csv", delivery)
    summary["camera_active_count"] = len(active)
    summary["active_delivery_missing"] = [r for r in delivery if any(r[f"{pc}_{kind}"] == 0 for pc in bags for kind in ("active_intents", "active_commands", "active_statuses"))]
    summary["cross_pc_command_payloads_equal"] = Counter(
        tuple((k, json.dumps(v, sort_keys=True)) for k, v in r.items() if k not in ("bag_ns", "camera_relative_sec", "in_camera_window"))
        for r in bags["kobuki"]["/collision/ffb_command"]) == Counter(
        tuple((k, json.dumps(v, sort_keys=True)) for k, v in r.items() if k not in ("bag_ns", "camera_relative_sec", "in_camera_window"))
        for r in bags["hsr"]["/collision/ffb_command"])
    # Compare identities, never infer delivery only from wall-clock coincidence.
    summary["cross_pc_command_identities_equal"] = Counter(map(command_identity, bags["kobuki"]["/collision/ffb_command"])) == Counter(map(command_identity, bags["hsr"]["/collision/ffb_command"]))
    reviewed = read_csv(out / "manual_review.csv")
    summary["review_labels"] = dict(Counter(r["label"] for r in reviewed))
    joined = [{**review, "time_sec": camera[int(review["frame"]) - 1]["time_sec"],
               **{k: camera[int(review["frame"]) - 1][k] for k in ("detected", "measurement_accepted", "collision_risk_level", "odom_linear_mps")}} for review in reviewed]
    write_csv(out / "review_live_join.csv", joined)
    review_times = [0.0] + [float(r["time_sec"]) for r in joined] + [float(camera[-1]["time_sec"])]
    summary["max_unreviewed_gap_sec"] = max(b - a for a, b in zip(review_times, review_times[1:]))
    summary["full_occlusion_3sec_condition"] = (
        "NOT_MET" if summary["max_unreviewed_gap_sec"] < 3.0
        and all(r["label"] in ("visible", "partial_occlusion") for r in reviewed)
        else "REQUIRES_INTERVAL_REVIEW")
    summary["recorded_delivery_decision"] = "PASS" if (
        active and not summary["active_delivery_missing"]
        and summary["cross_pc_command_payloads_equal"]
        and all(r["collision_ffb_publish_success"] == "1" for r in camera)
        and all(not summary[pc]["faults_full_bag"]
                and not summary[pc]["relay_active_rejections"]
                and set(summary[pc]["output_modes"]) == {"dry_run"}
                and summary[pc]["max_applied_magnitude"] <= 0.05 + 1e-7
                and not summary[pc]["last_status"]["output_active"] for pc in bags)
    ) else "REVIEW_REQUIRED"
    frozen = out / "frozen_comparison/frame_results.csv"
    if frozen.exists():
        results = read_csv(frozen)
        labels = {r["frame"]: r for r in reviewed}
        joined_candidates = [{**r, **labels[r["frame"]]} for r in results if r["frame"] in labels]
        write_csv(out / "review_candidate_join.csv", joined_candidates)
        summary["frozen_comparison_rows"] = len(results)
        summary["candidate_review_counts"] = []
        for variant in sorted({r["variant"] for r in joined_candidates}):
            for label in sorted({r["label"] for r in joined_candidates}):
                group = [r for r in joined_candidates if r["variant"] == variant and r["label"] == label]
                summary["candidate_review_counts"].append(dict(variant=variant, label=label, samples=len(group),
                    detected=sum(r["detected"] in ("1", "True") for r in group)))
    summary["mock_scenario_csv_supplied"] = False
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    # Timeline uses raw camera log, bag ODOM and bag status; visual labels are points only.
    t = np.array([float(r["time_sec"]) for r in camera])
    fig, axes = plt.subplots(4, 1, figsize=(13, 9), sharex=True, constrained_layout=True)
    odom = bags["kobuki"]["/phase5/mock_odom"]
    axes[0].step([r["camera_relative_sec"] for r in odom], [r["linear_x"] for r in odom], where="post", label="mock ODOM (no physical motion)")
    axes[0].set_ylabel("mock speed [m/s]")
    for label, color in (("visible", "green"), ("partial_occlusion", "orange"), ("full_occlusion", "red")):
        points = [r for r in joined if r["label"] == label]
        axes[0].scatter([float(r["time_sec"]) for r in points], [-0.03] * len(points), color=color, marker="|", label=f"raw reviewed: {label}")
    axes[0].legend(fontsize=8, loc="upper right")
    axes[1].step(t, [int(r["detected"]) for r in camera], where="post", label="detected")
    axes[1].step(t, [int(r["measurement_accepted"]) for r in camera], where="post", alpha=.7, label="measurement accepted")
    axes[1].set_ylabel("live observation"); axes[1].legend(fontsize=8)
    levels = {"CLEAR": 0, "PATH": 1, "WARNING": 2, "WARNING_HOLD": 3, "CRITICAL": 4, "UNKNOWN": 5}
    axes[2].step(t, [levels[r["collision_risk_level"]] for r in camera], where="post")
    axes[2].set_yticks(list(levels.values()), list(levels), fontsize=8)
    axes[2].set_ylabel("live risk")
    axes[3].step(t, [float(r["collision_ffb_requested_magnitude"]) if r["collision_ffb_active"] == "1" else 0 for r in camera], where="post", label="camera intent")
    status = bags["hsr"]["/collision/ffb_status"]
    axes[3].step([r["camera_relative_sec"] for r in status], [r["applied_magnitude"] for r in status], where="post", label="adapter dry_run (cap 0.05)")
    axes[3].set_ylabel("normalized demand"); axes[3].set_xlabel("time after camera recording start [s]")
    axes[3].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.25); ax.set_xlim(0, float(t[-1]))
    fig.suptitle(args.plot_title)
    fig.savefig(out / "trial_timeline.png", dpi=150)
    plt.close(fig)
    # Preserve the transient at second recovery; this is not a true closing-speed measurement.
    recovery = [r for r in camera if args.recovery_window[0] <= float(r["time_sec"]) <= args.recovery_window[1]]
    write_csv(out / "second_recovery_live.csv", recovery)
    def numbers(key):
        return [float(r[key]) if r[key] else math.nan for r in recovery]
    rt = numbers("time_sec")
    fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=True, constrained_layout=True)
    axes[0].plot(rt, numbers("raw_z_m"), ".-", label="raw z")
    axes[0].plot(rt, numbers("filtered_z_m"), ".-", label="filtered z")
    axes[0].set_ylabel("estimated z [m]"); axes[0].legend()
    axes[1].plot(rt, numbers("smoothed_vz_mps"), ".-", label="selected relative vz")
    axes[1].axhline(-0.25, ls="--", label="mock odom closing component")
    axes[1].set_ylabel("relative vz [m/s]"); axes[1].legend()
    axes[2].plot(rt, numbers("ttc_sec"), ".-", label="estimated TTC")
    axes[2].axhline(2, ls="--", color="red", label="CRITICAL threshold")
    axes[2].set_ylabel("TTC [s]"); axes[2].set_xlabel("time after camera recording start [s]")
    axes[2].legend()
    for ax in axes:
        ax.grid(alpha=.25)
    fig.suptitle("Second recovery: recorded distance / velocity / TTC (live v12)")
    fig.savefig(out / "second_recovery_transient.png", dpi=150)
    plt.close(fig)
    print(json.dumps({k: summary[k] for k in ("camera_active_count", "active_delivery_missing", "review_labels", "v12_parameter_differences", "cross_pc_command_payloads_equal")}, indent=2))


if __name__ == "__main__":
    main()
