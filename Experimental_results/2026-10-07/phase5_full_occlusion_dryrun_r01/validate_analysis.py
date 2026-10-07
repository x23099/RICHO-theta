"""Validate saved results against extracted video and official ROS CDR messages.

Run after sourcing Humble and the local oit_interfaces install. No ROS nodes are started.
"""
import argparse
import ast
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import cv2
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_trial as analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--kobuki-db", type=Path, required=True)
    parser.add_argument("--hsr-db", type=Path, required=True)
    args = parser.parse_args()
    checks = {}
    for script in (HERE / "analyze_trial.py", Path(__file__)):
        ast.parse(script.read_text())
    checks["script_syntax"] = True
    with (HERE / "manual_review.csv").open(newline="") as stream:
        reviews = {int(r["frame"]): r for r in csv.DictReader(stream)}
    manifest, counts = [], {}
    cv2.setNumThreads(1)
    for name in ("raw.avi", "bev.avi", "detection.avi"):
        cap = cv2.VideoCapture(str(args.session / name))
        count = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            count += 1
            if name == "raw.avi":
                assert frame.shape == (720, 1280, 3)
                if count in reviews:
                    manifest.append(dict(session=args.session.name, frame=count, label=reviews[count]["label"],
                                         decoded_bgr_pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest()))
        cap.release()
        counts[name] = count
    assert set(counts.values()) == {1372}
    assert len(manifest) == 24
    analysis.write_csv(HERE / "review_frame_manifest.csv", manifest)
    checks["actual_sequential_decode_counts"] = counts
    checked = {}
    for pc, path in (("kobuki", args.kobuki_db), ("hsr", args.hsr_db)):
        checked[pc] = {}
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
            for topic_id, name, kind in connection.execute("SELECT id,name,type FROM topics"):
                msg_type = get_message(kind)
                n = 0
                for (data,) in connection.execute("SELECT data FROM messages WHERE topic_id=?", (topic_id,)):
                    actual = deserialize_message(data, msg_type)
                    decoded = analysis.DECODERS[name](data)
                    if name.endswith("mock_odom"):
                        assert decoded["linear_x"] == actual.twist.twist.linear.x
                        assert decoded["angular_z"] == actual.twist.twist.angular.z
                    elif name.endswith("diagnostics"):
                        assert decoded == json.loads(actual.data)
                    else:
                        for key, value in decoded.items():
                            if key not in ("stamp_ns", "frame_id"):
                                assert value == getattr(actual, key), (pc, name, key)
                    if "stamp_ns" in decoded:
                        assert decoded["stamp_ns"] == actual.header.stamp.sec * 1_000_000_000 + actual.header.stamp.nanosec
                        assert decoded["frame_id"] == actual.header.frame_id
                    n += 1
                checked[pc][name] = n
    checks["all_cdr_records_match_official_deserialization"] = checked
    summary = json.loads((HERE / "summary.json").read_text())
    assert not summary["v12_parameter_differences"]
    assert not summary["active_delivery_missing"]
    assert summary["cross_pc_command_payloads_equal"]
    assert summary["camera_active_count"] == 42
    for pc in ("kobuki", "hsr"):
        assert not summary[pc]["faults_full_bag"]
        assert not summary[pc]["relay_active_rejections"]
        assert set(summary[pc]["output_modes"]) == {"dry_run"}
        assert summary[pc]["max_applied_magnitude"] <= 0.05 + 1e-7
        assert not summary[pc]["last_status"]["output_active"]
    rows = analysis.read_csv(HERE / "frozen_comparison/frame_results.csv")
    assert len(rows) == 1372 * 3
    for variant in {r["variant"] for r in rows}:
        assert [int(r["frame"]) for r in rows if r["variant"] == variant] == list(range(1, 1373))
    provenance = json.loads((HERE / "frozen_comparison/provenance.json").read_text())
    assert provenance["frozen_candidate_check"]["settings_match"]
    assert provenance["frozen_candidate_check"]["candidate_implementation_matches"]
    checks["delivery_cap_modes_and_frozen_comparison_consistent"] = True
    assets = HERE.parent / "report_assets"
    with (assets / "full_occlusion_r01_export_manifest.csv").open(newline="") as stream:
        images = list(csv.DictReader(stream))
    hashes = {r["frame"]: r["decoded_bgr_pixels_sha256"] for r in manifest}
    for row in images:
        image_path = assets / Path(row["raw_png"]).name
        frame = cv2.imread(str(image_path))
        assert frame.shape == (720, 1280, 3)
        assert hashlib.sha256(frame.tobytes()).hexdigest() == hashes[int(row["frame_one_based"])]
    checks["representative_png_pixels_match_raw"] = len(images)
    (HERE / "verification.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
