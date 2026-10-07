"""Summarize independently reviewed intervals and validate offline artifacts.

Does not publish ROS messages or open an input/hardware device. Official ROS
imports below are used solely to deserialize recorded messages.
"""
import argparse
import ast
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import cv2
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "phase5_full_occlusion_dryrun_r01"))
import analyze_trial as common


def payload(row):
    return tuple((k, v) for k, v in row.items()
                 if k not in ("bag_ns", "camera_relative_sec", "in_camera_window"))


def main():
    global HERE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--kobuki-db", type=Path, required=True)
    parser.add_argument("--hsr-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    parser.add_argument("--review-interval", type=int, nargs=2, action="append")
    parser.add_argument("--asset-prefix", default="full_occlusion_r02")
    args = parser.parse_args()
    HERE = args.output_dir.resolve()
    summary = json.loads((HERE / "summary.json").read_text())
    camera = common.read_csv(args.session / "detections.csv")
    reviews = common.read_csv(HERE / "review_live_join.csv")
    intervals = []
    for index, (first, last) in enumerate(args.review_interval or [(390, 493), (731, 864)], 1):
        name = f"moving_occlusion_{index}"
        points = [r for r in reviews if first <= int(r["frame"]) <= last]
        assert points and all(r["label"] == "full_occlusion" for r in points)
        times = [float(r["time_sec"]) for r in points]
        assert times[-1] - times[0] >= 3.0
        interval = dict(name=name, first_reviewed_frame=first, last_reviewed_frame=last,
                        first_reviewed_sec=times[0], last_reviewed_sec=times[-1],
                        reviewed_points=len(points), reviewed_span_sec=times[-1] - times[0],
                        max_review_step_sec=max(b - a for a, b in zip(times, times[1:])),
                        all_reviewed_points_mock_forward=all(r["odom_linear_mps"] == "0.250000" for r in points),
                        all_reviewed_points_no_detection=all(r["detected"] == "0" for r in points),
                        all_reviewed_points_no_accepted_measurement=all(r["measurement_accepted"] == "0" for r in points))
        intervals.append(interval)
    assert all(r["all_reviewed_points_mock_forward"] and r["all_reviewed_points_no_detection"]
               and r["all_reviewed_points_no_accepted_measurement"] for r in intervals)
    common.write_csv(HERE / "visual_review_intervals.csv", intervals)
    bags = {pc: {kind: common.read_csv(HERE / f"{pc}_{kind}.csv") for kind in (
        "ffb_intent", "ffb_command", "ffb_status", "ffb_relay_diagnostics")} for pc in ("kobuki", "hsr")}
    seqs = {r["collision_ffb_sequence"] for r in camera if r["collision_ffb_active"] == "1"}
    active_payloads = {pc: Counter(payload(r) for r in bags[pc]["ffb_command"] if r["active"] == "True" and r["sequence"] in seqs) for pc in bags}
    assert active_payloads["kobuki"] == active_payloads["hsr"]
    assert sum(active_payloads["hsr"].values()) == len(seqs) and seqs
    fault_window = {pc: [r for r in summary[pc]["faults_full_bag"] if r["in_camera_window"]] for pc in bags}
    packet_differences = []
    for kind, seq_key in (("ffb_command", "sequence"), ("ffb_intent", "sequence"), ("ffb_relay_diagnostics", "intent_sequence")):
        krows, hrows = bags["kobuki"][kind], bags["hsr"][kind]
        kcounts, hcounts = Counter(r[seq_key] for r in krows), Counter(r[seq_key] for r in hrows)
        for pc, rows, missing in (("kobuki_only", krows, kcounts - hcounts), ("hsr_only", hrows, hcounts - kcounts)):
            for r in rows:
                if r[seq_key] in missing:
                    packet_differences.append(dict(kind=kind, observation=pc, **r))
    common.write_csv(HERE / "cross_pc_bag_differences.csv", packet_differences)
    kcommands = {r["sequence"]: r for r in bags["kobuki"]["ffb_command"]}
    hcommands = {r["sequence"]: r for r in bags["hsr"]["ffb_command"]}
    common_sequences = set(kcommands) & set(hcommands)
    shared_payload_equal = all(payload(kcommands[s]) == payload(hcommands[s]) for s in common_sequences)
    assert shared_payload_equal
    active = [r for r in camera if r["collision_ffb_active"] == "1"]
    unknown_runs = [r for r in common.runs(camera, "collision_risk_level", "time_sec") if r["value"] == "UNKNOWN"]
    for run in unknown_runs:
        emitted = [r for r in active if run["first_sec"] <= float(r["time_sec"]) <= run["last_sec"]]
        run["active_samples"] = len(emitted)
        run["single_notice_start_sec"] = float(emitted[0]["time_sec"]) if emitted else None
        run["single_notice_last_active_sec"] = float(emitted[-1]["time_sec"]) if emitted else None
        run["single_active_windows"] = sum(
            i == 0 or int(r["frame"]) != int(emitted[i - 1]["frame"]) + 1 for i, r in enumerate(emitted))
    common.write_csv(HERE / "unknown_notifications.csv", unknown_runs)
    episodes = []
    for row in active:
        risk, t = row["collision_risk_level"], float(row["time_sec"])
        if not episodes or risk != episodes[-1]["risk"] or t - episodes[-1]["last_active_sec"] > 0.5:
            episodes.append(dict(risk=risk, first_active_sec=t, last_active_sec=t,
                                 active_updates=0, active_windows=0, last_frame=0))
        episode = episodes[-1]
        episode["active_windows"] += int(int(row["frame"]) != episode["last_frame"] + 1)
        episode["active_updates"] += 1
        episode["last_frame"], episode["last_active_sec"] = int(row["frame"]), t
    for episode in episodes:
        episode["following_inactive_sec"] = float(camera[episode["last_frame"]]["time_sec"]) if episode["last_frame"] < len(camera) else None
    common.write_csv(HERE / "notification_episodes.csv", episodes)
    assert len(unknown_runs) == 2 and all(r["single_active_windows"] == 1 for r in unknown_runs)
    assert [r["risk"] for r in episodes] == ["WARNING", "UNKNOWN", "WARNING", "UNKNOWN", "WARNING"]
    assert [r["active_windows"] for r in episodes] == [3, 1, 3, 1, 3]
    # Field decoding is checked against official deserialization, for every packet.
    checked = {}
    for pc, db in (("kobuki", args.kobuki_db), ("hsr", args.hsr_db)):
        checked[pc] = {}
        with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            for topic_id, name, kind in conn.execute("SELECT id,name,type FROM topics"):
                msg_type, n = get_message(kind), 0
                for (data,) in conn.execute("SELECT data FROM messages WHERE topic_id=?", (topic_id,)):
                    actual = deserialize_message(data, msg_type)
                    decoded = common.DECODERS[name](data)
                    if name.endswith("mock_odom"):
                        assert decoded["linear_x"] == actual.twist.twist.linear.x
                        assert decoded["angular_z"] == actual.twist.twist.angular.z
                    elif name.endswith("diagnostics"):
                        assert decoded == json.loads(actual.data)
                    else:
                        for key, value in decoded.items():
                            if key not in ("stamp_ns", "frame_id"):
                                assert value == getattr(actual, key)
                    if "stamp_ns" in decoded:
                        assert decoded["stamp_ns"] == actual.header.stamp.sec * 1_000_000_000 + actual.header.stamp.nanosec
                        assert decoded["frame_id"] == actual.header.frame_id
                    n += 1
                checked[pc][name] = n
    cv2.setNumThreads(1)
    counts, manifest = {}, []
    labels = {int(r["frame"]): r["label"] for r in reviews}
    for name in ("raw.avi", "bev.avi", "detection.avi"):
        cap, n = cv2.VideoCapture(str(args.session / name)), 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            if name == "raw.avi":
                assert frame.shape == (720, 1280, 3)
                if n in labels:
                    manifest.append(dict(session=args.session.name, frame=n, label=labels[n],
                                         decoded_bgr_pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest()))
        cap.release()
        counts[name] = n
    assert set(counts.values()) == {len(camera)} and len(manifest) == len(reviews)
    common.write_csv(HERE / "review_frame_manifest.csv", manifest)
    hashes = {r["frame"]: r["decoded_bgr_pixels_sha256"] for r in manifest}
    assets = HERE.parent / "report_assets"
    images = common.read_csv(assets / f"{args.asset_prefix}_export_manifest.csv")
    for row in images:
        frame = cv2.imread(str(assets / Path(row["raw_png"]).name))
        assert frame.shape == (720, 1280, 3)
        assert hashlib.sha256(frame.tobytes()).hexdigest() == hashes[int(row["frame_one_based"])]
    frozen = common.read_csv(HERE / "frozen_comparison/frame_results.csv")
    assert len(frozen) == 3 * len(camera)
    for variant in {r["variant"] for r in frozen}:
        assert [int(r["frame"]) for r in frozen if r["variant"] == variant] == list(range(1, len(camera) + 1))
    provenance = json.loads((HERE / "frozen_comparison/provenance.json").read_text())
    assert provenance["frozen_candidate_check"]["settings_match"]
    assert provenance["frozen_candidate_check"]["candidate_implementation_matches"]
    assert not summary["v12_parameter_differences"] and not summary["active_delivery_missing"]
    assert all(not faults for faults in fault_window.values())
    assert all(not summary[pc]["relay_active_rejections"] for pc in bags)
    assert all(set(summary[pc]["output_modes"]) == {"dry_run"} for pc in bags)
    assert all(summary[pc]["max_applied_magnitude"] <= 0.05 + 1e-7 for pc in bags)
    assert all(not summary[pc]["last_status"]["output_active"] for pc in bags)
    assessment = dict(
        visual_condition="PASS_WITH_0P5SEC_SAMPLED_RAW_REVIEW",
        visual_limit="Intermediate frames were not individually visually labeled; reviewed spans are not exact boundary times.",
        active_delivery=f"PASS_{len(seqs)}_OF_{len(seqs)}_BOTH_PCS",
        full_bag_communication=summary["recorded_delivery_decision"],
        visual_intervals=intervals, unknown_notifications=unknown_runs,
        notification_episodes=episodes,
        fault_count_in_camera_window={pc: len(f) for pc, f in fault_window.items()},
        active_command_payloads_equal=True, shared_command_payloads_equal=shared_payload_equal,
        common_command_count=len(common_sequences), cross_pc_bag_difference_count=len(packet_differences),
        critical_frames=sum(r["collision_risk_level"] == "CRITICAL" for r in camera),
        hardware_or_production_promotion=False,
    )
    (HERE / "trial_assessment.json").write_text(json.dumps(assessment, indent=2) + "\n")
    for script in (Path(__file__), HERE.parent / "phase5_full_occlusion_dryrun_r01/analyze_trial.py"):
        ast.parse(script.read_text())
    (HERE / "verification.json").write_text(json.dumps(dict(
        script_syntax=True, sequential_video_frame_counts=counts,
        official_cdr_all_records_match=checked, representative_png_pixels_match_raw=len(images),
        frozen_rows=len(frozen), active_delivery_and_recording_window_checks=True,
        limitations_preserved_in_trial_assessment=True), indent=2) + "\n")
    print(json.dumps(assessment, indent=2))


if __name__ == "__main__":
    main()
