#!/usr/bin/env python3
"""品質CSVの集計・グラフと、無加工の代表PNGを保存する。"""
import csv
import hashlib
import json
import os
from pathlib import Path
import statistics

import cv2
import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp/phase5_contact_quality_matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
with (root / "frame_quality.csv").open(newline="") as stream:
    rows = list(csv.DictReader(stream))
sources = json.loads((root / "provenance.json").read_text())["sources"]
sessions = sorted({r["session"] for r in rows if "hardware_r0" in r["session"]})


def value(row, key):
    return float(row[key]) if row[key] else float("nan")


def write(path, records):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


selected_summary, screening, integrity = [], [], []
fields = ["bbox_fill_ratio", "contour_solidity", "dark_blue_hs_fraction", "contact_z_iqr_m", "fraction_z_sensitivity_m"]
rules = [("fill_below_0p60", lambda r: value(r, "bbox_fill_ratio") < .6),
         ("contact_iqr_over_0p03m", lambda r: value(r, "contact_z_iqr_m") > .03),
         ("fraction_sensitivity_over_0p05m", lambda r: value(r, "fraction_z_sensitivity_m") > .05)]
for session in sessions:
    local = [r for r in rows if r["session"] == session]
    detected = [r for r in local if r["video_detected"] == "1"]
    for phase in ["all", "after_stop_plus_0p5"]:
        selected = [r for r in detected if phase == "all" or r["phase"] == phase]
        result = {"session": session, "phase": phase, "selected_contour_frames": len(selected)}
        for key in fields:
            values = [value(r, key) for r in selected if r[key]]
            result[key + "_median"] = statistics.median(values) if values else ""
        selected_summary.append(result)
    recorded = next(s for s in sources if s["session"] == session)
    replay_path = root.parent / "raw_velocity_confidence_candidate" / session / "recomputed_inputs.csv"
    with replay_path.open(newline="") as stream:
        replay = list(csv.DictReader(stream))
    assert len(replay) == len(local)
    max_delta = 0.0
    for a, b in zip(local, replay):
        assert a["frame"] == b["frame"] and a["video_detected"] == b["detected"]
        if a["video_detected"] == "1":
            max_delta = max(max_delta, abs(value(a, "contact_z_m") + recorded["parameters"].get("blue_ground_contact_z_offset_m", 0) - float(b["z_m"])))
    assert max_delta < 1e-10
    integrity.append({"session": session, "frames": len(local), "max_z_difference_vs_prior_raw_replay_m": max_delta})
    accepted_ids = {r["frame"] for r in replay if r["measurement_accepted"] == "1"}
    for label, rule in rules:
        low = [r for r in detected if r["adjacent_motion_residual_m"] and value(r, "adjacent_motion_residual_m") <= .03]
        high = [r for r in detected if r["adjacent_motion_residual_m"] and value(r, "adjacent_motion_residual_m") > .03]
        screening.append({"session": session, "exploratory_rule_NOT_A_GATE": label,
                          "detected_frames": len(detected), "flagged_detected_frames": sum(rule(r) for r in detected),
                          "low_residual_frames": len(low), "flagged_low_residual_frames": sum(rule(r) for r in low),
                          "high_residual_frames": len(high), "flagged_high_residual_frames": sum(rule(r) for r in high),
                          "accepted_measurements": len(accepted_ids), "flagged_accepted_measurements": sum(rule(r) for r in detected if r["frame"] in accepted_ids)})
write(root / "selected_contour_summary.csv", selected_summary)
write(root / "exploratory_screening.csv", screening)
write(root / "raw_replay_integrity.csv", integrity)

fig, axes = plt.subplots(2, 2, figsize=(11, 7))
for ax, (key, label, multiplier) in zip(axes.flat, [
    ("bbox_fill_ratio", "Contour fill ratio", 1), ("dark_blue_hs_fraction", "Blue H/S pixels below V threshold (%)", 100),
    ("contact_z_iqr_m", "Selected contact z IQR (mm)", 1000), ("fraction_z_sensitivity_m", "Contact-fraction sensitivity (mm)", 1000),
]):
    groups = [[multiplier * value(r, key) for r in rows if r["session"] == s and r["video_detected"] == "1"] for s in sessions]
    ax.boxplot(groups, tick_labels=["r01", "r02", "r03"], showfliers=False)
    ax.set_ylabel(label)
    ax.grid(axis="y", alpha=.25)
fig.suptitle("Offline selected-contour quality (all detected frames)\nIndicators are NOT ground-truth distance uncertainty; outliers hidden in boxplots")
fig.tight_layout()
fig.savefig(root / "selected_contour_quality.png", dpi=150)
plt.close(fig)

r03 = [r for r in rows if "hardware_r03_" in r["session"]]
t = [value(r, "time_sec") for r in r03]
fig, axes = plt.subplots(3, 1, sharex=True, figsize=(12, 8))
axes[0].plot(t, [value(r, "live_raw_z_m") for r in r03], label="Recorded live z", alpha=.65)
axes[0].plot(t, [value(r, "contact_z_m") for r in r03], label="Video contact z")
axes[0].set_ylabel("Measured z (m)")
axes[1].plot(t, [1000 * value(r, "contact_z_iqr_m") for r in r03], label="Contact IQR")
axes[1].plot(t, [1000 * value(r, "fraction_z_sensitivity_m") for r in r03], label="2/8/16% fraction sensitivity")
axes[1].set_ylabel("Diagnostic spread (mm)")
axes[2].plot(t, [value(r, "bbox_aspect_ratio") for r in r03], label="Selected/reference contour aspect")
axes[2].axhline(1.5, ls="--", color="red", label="Existing aspect limit 1.5")
missing = [r for r in r03 if r["video_detected"] == "0"]
axes[2].scatter([value(r, "time_sec") for r in missing], [value(r, "bbox_aspect_ratio") for r in missing], marker="x", s=9, color="black", label="Not detected (reference contour)")
axes[2].set_ylabel("BBox width / height")
axes[2].set_xlabel("Recorded elapsed time (s)")
for ax in axes:
    ax.grid(alpha=.25)
    ax.legend(loc="upper left", fontsize=9)
fig.suptitle("r03 contact instability and existing aspect rejection\nNo threshold or production detector changed")
fig.tight_layout()
fig.savefig(root / "r03_contact_quality_timeline.png", dpi=150)
plt.close(fig)

# Original-resolution frame extraction only: no drawing, resizing or correction.
source = next(s for s in sources if "hardware_r03_" in s["session"])
assets = root.parent / "report_assets"
assets.mkdir(exist_ok=True)
video = cv2.VideoCapture(str(Path(source["source"]) / "raw.avi"))
if not video.isOpened():
    raise ValueError("cannot open raw video for representative frames")
manifest = []
try:
    for frame_number in range(1, 308):
        ok, raw = video.read()
        if not ok:
            raise ValueError("video shorter than requested representative frame")
        if frame_number in (306, 307):
            filename = f"phase5_v12_live_hardware_r03_contact_jump_raw_frame_{frame_number:04d}.png"
            if not cv2.imwrite(str(assets / filename), raw):
                raise ValueError("PNG write failed")
            assert np.array_equal(cv2.imread(str(assets / filename)), raw), "saved PNG pixels differ from decoded source frame"
            row = next(r for r in r03 if int(r["frame"]) == frame_number)
            manifest.append({"file": filename, "session": source["session"], "frame": frame_number,
                             "time_sec": row["time_sec"], "width": raw.shape[1], "height": raw.shape[0],
                             "video_contact_z_m": row["contact_z_m"], "contact_pixel_y": row["contact_pixel_y"],
                             "contact_z_iqr_m": row["contact_z_iqr_m"], "modifications": "none"})
finally:
    video.release()
write(root / "raw_assets_manifest.csv", manifest)
quality_provenance = json.loads((root / "provenance.json").read_text())
for name, expected in quality_provenance["implementation_sha256"].items():
    assert hashlib.sha256((root.parents[2] / "src" / name).read_bytes()).hexdigest() == expected
checks = {"sessions": len({r["session"] for r in rows}), "frames": len(rows),
          "production_contact_selection_matched": True, "prior_raw_replay_z_matched": True,
          "implementation_hash_matches": True, "saved_png_pixels_match_decoded_video": True,
          "hardware_approved": False, "new_measurement_gate_implemented": False}
assert checks["sessions"] == 4 and checks["frames"] == 2460
(root / "validation.json").write_text(json.dumps(checks, indent=2) + "\n")
print("Saved selected-quality summaries, exploratory screening, two graphs and two unmodified PNG frames")
