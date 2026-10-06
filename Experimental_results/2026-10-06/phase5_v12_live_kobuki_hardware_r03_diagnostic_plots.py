#!/usr/bin/env python3
"""r03のライブCSVを可視化し、元解像度フレームを保存する（実機出力なし）。"""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/phase5_r03_matplotlib")
import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ground_contact import detect_blue_ground_contact


def number(row, key):
    try:
        value = float(row[key])
        return value if math.isfinite(value) else float("nan")
    except (ValueError, KeyError):
        return float("nan")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    day = Path(__file__).resolve().parent
    output = day / "phase5_v12_live_kobuki_hardware_r03_analysis"
    assets = day / "report_assets"
    output.mkdir(exist_ok=True)
    assets.mkdir(exist_ok=True)
    with (args.session / "detections.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    parameters = json.loads((args.session / "metadata.json").read_text())["parameters"]
    t = [number(r, "time_sec") for r in rows]
    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(11, 9))
    axes[0].plot(t, [number(r, "raw_z_m") for r in rows], ".", ms=2, label="Live raw z")
    axes[0].plot(t, [number(r, "filtered_z_m") for r in rows], label="Live tracked z")
    axes[0].axhline(1.35, ls="--", color="grey", label="Calibration z upper limit")
    axes[0].set_ylabel("Estimated z (m)")
    axes[0].legend(loc="upper right", ncol=3)
    axes[1].plot(t, [number(r, "odom_linear_mps") for r in rows], label="Real odom speed")
    axes[1].plot(t, [-number(r, "visual_smoothed_vz_mps") for r in rows], label="Visual closing speed")
    axes[1].set_ylabel("Speed (m/s)")
    axes[1].legend(loc="upper left", ncol=2)
    axes[2].step(t, [number(r, "detected") for r in rows], where="post", label="Detected")
    axes[2].step(t, [number(r, "measurement_accepted") for r in rows], where="post", label="Measurement accepted")
    axes[2].set_ylabel("Detection / acceptance")
    axes[2].set_yticks([0, 1])
    axes[2].legend(loc="upper left", ncol=2)
    risk_map = {"CLEAR": 0, "PATH": 1, "UNKNOWN": 2, "WARNING": 3, "WARNING_HOLD": 3, "CRITICAL": 4}
    axes[3].step(t, [risk_map[r["collision_risk_level"]] for r in rows], where="post", label="Live risk")
    active_t = [number(r, "time_sec") for r in rows if r["collision_ffb_active"] == "1"]
    axes[3].scatter(active_t, [4.6] * len(active_t), marker="|", color="red", label="Active FFB command")
    axes[3].set_yticks(range(5), ["CLEAR", "PATH", "UNKNOWN", "WARNING / HOLD", "CRITICAL"])
    axes[3].set_ylim(-0.3, 5)
    axes[3].legend(loc="upper left", ncol=2)
    axes[3].set_xlabel("Recording elapsed time (s)")
    for ax in axes:
        ax.grid(alpha=0.25)
    fig.suptitle("2026-10-06 hardware r03: live camera CSV (pre-trial rosbag activity excluded)")
    fig.tight_layout()
    fig.savefig(output / "live_distance_ttc_ffb_timeline.png", dpi=150)
    plt.close(fig)

    # AVI再検出はMJPG再圧縮の影響を受ける。ライブCSVの代用ではない。
    selected = [1, 204, 205, 206, 207, 267, 268, 269, 270, 271, 272, 283, 300, 350, 400, 478]
    cap = cv2.VideoCapture(str(args.session / "raw.avi"))
    if not cap.isOpened():
        raise RuntimeError("raw.aviを開けません")
    diagnostics = []
    try:
        for frame_number in selected:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number - 1)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"frame {frame_number}を読めません")
            if frame_number in (206, 350):
                path = assets / f"phase5_v12_live_hardware_r03_raw_frame_{frame_number:04d}.png"
                if not cv2.imwrite(str(path), frame):
                    raise RuntimeError(f"PNG保存失敗: {path}")
            detection, mask = detect_blue_ground_contact(frame, parameters)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            near = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                # 診断用の固定領域。PNG自体には切り抜き・注釈を行わない。
                if 275 < x + w / 2 < 350 and 340 < y + h / 2 < 480:
                    near.append((cv2.contourArea(contour), x, y, w, h))
            largest = max(near, default=(0, 0, 0, 0, 0))
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[360:405, 298:325]
            live = rows[frame_number - 1]
            diagnostics.append({
                "frame": frame_number, "time_sec": live["time_sec"],
                "live_detected": live["detected"], "live_raw_z_m": live["raw_z_m"],
                "live_rejection_reason": live["rejection_reason"],
                "avi_recomputed_detected": int(detection is not None),
                "avi_recomputed_raw_z_m": detection["z_m"] if detection else "",
                "avi_near_contour_area_px": largest[0],
                "avi_near_bbox_xywh": json.dumps(largest[1:]),
                "avi_near_aspect_ratio": largest[3] / max(largest[4], 1),
                "avi_fixed_box_patch_median_v": float(np.median(hsv[:, :, 2])),
                "avi_fixed_box_patch_v_below_30_fraction": float(np.mean(hsv[:, :, 2] < 30)),
            })
    finally:
        cap.release()
    with (output / "selected_frame_live_vs_avi_diagnostics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(diagnostics[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(diagnostics)
    print(f"Saved r03 graph, raw PNGs and selected-frame diagnostics: {output}")


if __name__ == "__main__":
    main()
