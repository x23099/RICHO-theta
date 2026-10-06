#!/usr/bin/env python3
"""CSVからライブ／測定再構築／動画再計算の比較を保存する。"""
import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/phase5_raw_confidence_matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
with (root / "live_video_comparison.csv").open(newline="") as stream:
    rows = list(csv.DictReader(stream))
levels = {"CLEAR": 0, "PATH": 1, "UNKNOWN": 2, "WARNING_HOLD": 3, "WARNING": 4, "CRITICAL": 5}
sessions = sorted({r["session"] for r in rows})
fig, axes = plt.subplots(len(sessions), 1, figsize=(12, 9))
for ax, session in zip(axes, sessions):
    group = [r for r in rows if r["session"] == session]
    t = [float(r["time_sec"]) for r in group]
    for key, label, style, alpha in [("live_risk", "Recorded live state", "-", 1),
                                     ("logged_measurement_rebuild", "Logged measurement reconstruction", "--", .8),
                                     ("raw_video_baseline", "Video baseline", "-", .7),
                                     ("raw_video_candidate", "Video candidate", ":", 1)]:
        ax.step(t, [levels[r[key]] for r in group], where="post", label=label, ls=style, alpha=alpha)
    ax.set_yticks(list(levels.values()), list(levels.keys()), fontsize=9)
    ax.set_title(session.split("hardware_")[1].split("_2026")[0])
    ax.set_xlabel("Recorded elapsed time (s)")
    ax.grid(alpha=.25)
axes[0].legend(loc="upper left", fontsize=9, ncol=2)
fig.suptitle("Offline video-pipeline replay vs live CSV\nVideo baseline and candidate agree here; this is NOT proof of candidate improvement")
fig.tight_layout()
fig.savefig(root / "live_video_risk_comparison.png", dpi=150)
plt.close(fig)

fig, axes = plt.subplots(len(sessions), 1, figsize=(12, 8))
for ax, session in zip(axes, sessions):
    group = [r for r in rows if r["session"] == session]
    t = [float(r["time_sec"]) for r in group]
    for key, label in [("live_z_m", "Recorded live raw z"), ("video_z_m", "Recomputed video raw z")]:
        ax.plot(t, [float(r[key]) if r[key] else float("nan") for r in group], label=label, lw=1)
    ax.set_title(session.split("hardware_")[1].split("_2026")[0])
    ax.set_ylabel("Calibrated observation z (m)")
    ax.set_xlabel("Recorded elapsed time (s)")
    ax.grid(alpha=.25)
axes[0].legend()
fig.suptitle("Live vs saved MJPG observations\nVelocity-confidence candidate does not correct these distance measurements")
fig.tight_layout()
fig.savefig(root / "live_video_distance_comparison.png", dpi=150)
plt.close(fig)

aggregated = []
for output in (root, root / "controls", root / "motion_controls"):
    path = output / "live_video_comparison.csv"
    if not path.exists():
        continue
    with path.open(newline="") as stream:
        data = list(csv.DictReader(stream))
    for session in sorted({r["session"] for r in data}):
        group = [r for r in data if r["session"] == session]
        aggregated.append({"session": session, "frames": len(group),
                           "control_acceptance_difference_frames": sum(r["live_accepted"] != r["control_accepted"] for r in group),
                           "control_risk_difference_frames": sum(r["live_risk"] != r["logged_measurement_rebuild"] for r in group),
                           "video_detection_difference_frames": sum(r["live_detected"] != r["video_detected"] for r in group),
                           "video_acceptance_difference_frames": sum(r["live_accepted"] != r["video_accepted"] for r in group),
                           "video_risk_difference_frames": sum(r["live_risk"] != r["raw_video_baseline"] for r in group),
                           "candidate_added_risk_difference_frames": sum(r["raw_video_baseline"] != r["raw_video_candidate"] for r in group)})
with (root / "comparison_summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(aggregated[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(aggregated)
print("Saved two graphs and comparison_summary.csv")
