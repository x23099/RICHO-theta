#!/usr/bin/env python3
"""同フォルダのCSVからオフライン比較グラフを生成。カメラ画像は加工しない。"""
import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/phase5_velocity_candidate_matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
with (root / "live_trials/frame_results.csv").open(newline="") as stream:
    rows = [r for r in csv.DictReader(stream) if "hardware_r03_" in r["session"]]
base = [r for r in rows if r["variant"] == "baseline"]
candidate = [r for r in rows if r["variant"] == "confidence_candidate"]
levels = {"CLEAR": 0, "PATH": 1, "UNKNOWN": 2, "WARNING_HOLD": 3, "WARNING": 4, "CRITICAL": 5}
fig, axes = plt.subplots(3, 1, sharex=True, figsize=(11, 8))
for group, label, style in [(base, "Baseline", "--"), (candidate, "Offline candidate", "-")]:
    t = [float(r["time_sec"]) for r in group]
    axes[0].step(t, [levels[r["risk"]] for r in group], where="post", label=label, ls=style)
    axes[2].step(t, [float(r["virtual_active"]) for r in group], where="post", label=label, ls=style)
t = [float(r["time_sec"]) for r in candidate]
for key, label in [("visual_vz_mps", "Recorded visual velocity"), ("robust_vz_mps", "Past raw-distance trend")]:
    axes[1].plot(t, [float(r[key]) if r[key] else float("nan") for r in candidate], label=label)
withheld = [r for r in candidate if r["alert_withheld"] == "1"]
axes[1].scatter([float(r["time_sec"]) for r in withheld],
                [float(r["visual_vz_mps"]) for r in withheld], marker="x", color="red", label="Visual alert withheld")
axes[0].set_yticks(list(levels.values()), list(levels.keys()))
axes[1].set_ylabel("Relative z velocity (m/s)")
axes[2].set_ylabel("Virtual demand active")
axes[2].set_yticks([0, 1])
axes[2].set_xlabel("Recording elapsed time (s)")
axes[2].set_xlim(6.5, 10.2)
for ax in axes:
    ax.grid(alpha=.25)
    ax.legend(loc="best", fontsize=9)
fig.suptitle("r03 velocity-evidence candidate: offline replay ONLY\nDistance/TTC inputs retained; virtual demand is not measured hardware output")
fig.tight_layout()
fig.savefig(root / "r03_confidence_comparison.png", dpi=150)
plt.close(fig)

with (root / "synthetic_summary.csv").open(newline="") as stream:
    artificial = list(csv.DictReader(stream))
names = ["clean_fast_moving_target_stationary_robot", "noisy_5mm_fast_moving_target", "reacquired_fast_moving_target"]
fig, ax = plt.subplots(figsize=(9, 4.5))
for shift, variant, label in [(-.22, "baseline", "Baseline"), (0, "maturity_only_control", "Maturity-only control"),
                              (.22, "confidence_candidate", "Offline candidate")]:
    values = [1000 * float(next(r for r in artificial if r["scenario"] == name and r["variant"] == variant)["additional_critical_delay_sec"]) for name in names]
    ax.bar([i + shift for i in range(3)], values, width=.22, label=label)
ax.axhline(100, color="red", ls="--", label="Exploratory check: 100 ms")
ax.set_xticks(range(3), ["Clean 1 m/s approach", "Approach + small noise", "Reacquired approach"])
ax.set_ylabel("Added CRITICAL onset delay (ms)")
ax.set_title("Artificial 30 Hz measurements, stationary robot\nNot independently recorded fast-target validation")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=.25)
fig.tight_layout()
fig.savefig(root / "synthetic_critical_response.png", dpi=150)
plt.close(fig)
print("Saved two offline candidate comparison graphs")
