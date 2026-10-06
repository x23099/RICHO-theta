#!/usr/bin/env python3
"""同フォルダの根拠CSVから診断グラフを再生成する。"""
import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/phase5_ablation_matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

root = Path(__file__).resolve().parent
with (root / "detector_sensitivity.csv").open(newline="") as stream:
    sweeps = [r for r in csv.DictReader(stream) if "hardware_r03_" in r["session"]]
labels = ["V30 baseline", "V20", "V25", "V35", "No aspect limit", "Contact 2%", "Contact 16%"]
fig, ax = plt.subplots(figsize=(11, 4.5))
x = np.arange(len(sweeps))
ax.bar(x - .17, [100 * float(r["avi_detection_rate"]) for r in sweeps], .34, label="AVI detected")
ax.bar(x + .17, [100 * float(r["avi_calibration_valid_rate"]) for r in sweeps], .34, label="Inside calibration range")
ax.set_xticks(x, labels)
ax.set_ylim(0, 110)
ax.set_ylabel("% of all 478 frames")
ax.set_title("r03 offline detector sensitivity (MJPG replay; not distance-accuracy validation)")
ax.legend()
ax.grid(axis="y", alpha=.25)
fig.tight_layout()
fig.savefig(root / "r03_detector_sensitivity.png", dpi=150)
plt.close(fig)

with (root / "reinitialization_prior_ablation.csv").open(newline="") as stream:
    priors = list(csv.DictReader(stream))
fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 7))
for sigma in [.5, .2, .1]:
    rows = [r for r in priors if float(r["diagnostic_initial_velocity_sigma_mps"]) == sigma]
    t = [float(r["time_sec"]) for r in rows]
    axes[0].plot(t, [-float(r["replayed_vz_mps"]) for r in rows], marker=".", label=f"Initial velocity sigma={sigma} m/s")
    axes[1].plot(t, [float(r["ttc_sec"]) if r["ttc_sec"] else np.nan for r in rows], marker=".", label=f"sigma={sigma}")
    if sigma == .5:
        axes[0].plot(t, [float(r["odom_linear_mps"]) for r in rows], color="black", ls="--", label="Measured real odom speed")
axes[0].set_ylabel("Estimated closing speed (m/s)")
axes[1].set_ylabel("Recomputed TTC (s)")
axes[1].axhline(2.0, color="red", ls="--", label="CRITICAL threshold 2.0 s")
axes[1].axhline(4.6, color="grey", ls="--", label="WARNING threshold 4.6 s")
axes[1].set_xlabel("Recording elapsed time (s)")
for ax in axes:
    ax.grid(alpha=.25)
    ax.legend(loc="upper right", fontsize=9)
fig.suptitle("r03 reinitialization: same live measurements, altered prior ONLY for diagnosis\nNot approved hardware settings or a full-pipeline replay")
fig.tight_layout()
fig.savefig(root / "r03_reinitialization_sensitivity.png", dpi=150)
plt.close(fig)
print("Saved detector and reinitialization diagnostic graphs")
