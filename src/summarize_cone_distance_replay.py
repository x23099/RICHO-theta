#!/usr/bin/env python3
"""Post-hoc recording labels and figures; never inputs to the distance engine."""
import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path

import cv2
import numpy as np

from cone_distance_core import digest, render_distance
from run_cone_distance_replay import read_rows


def summarize(root, scope_file, output):
    root, scope_file, output = map(Path, (root, scope_file, output))
    if output.exists():
        raise ValueError("new report directory required")
    cases = {}
    sources = {str(scope_file.resolve()): digest(scope_file), str(Path(__file__).resolve()): digest(__file__)}
    for path in sorted(root.glob("*/summary.json")):
        summary = json.loads(path.read_text())
        for name, expected in summary["source_sha256"].items():
            if digest(name) != expected:
                raise ValueError("changed replay source: " + name)
        rows_file = path.parent / "frame_results.csv"
        if digest(rows_file) != summary["output_sha256"]["frame_results.csv"]:
            raise ValueError("changed replay rows")
        sources.update({str(path.resolve()): digest(path), str(rows_file.resolve()): digest(rows_file)})
        cases[path.parent.name] = summary, read_rows(rows_file)
    if not cases:
        raise ValueError("completed replay cases required")
    phases = json.loads(scope_file.read_text())["phase_windows"]
    statistics = []
    for case, (summary, rows) in cases.items():
        windows = phases if summary["session"].startswith("floor_cone_same_pose_") else [
            dict(name="whole_recording", start_frame=1, end_frame=len(rows), reference_z_m=None)]
        for window in windows:
            group = [r for r in rows if window["start_frame"] <= int(r["frame"]) <= window["end_frame"]]
            active = [r for r in group if r["distance_available"] == "True"]
            values = np.array([float(r["distance_forward_m"]) for r in active])
            reference = window["reference_z_m"]
            errors = values-reference if reference is not None else np.array([])
            statistics.append(dict(case=case, phase=window["name"], frames=len(group),
                diagnostic_frames=len(active), posthoc_reference_forward_m=reference,
                median_forward_m=float(np.median(values)) if len(values) else None,
                median_difference_from_reference_m=float(np.median(errors)) if len(errors) else None,
                p95_absolute_difference_m=float(np.percentile(abs(errors), 95)) if len(errors) else None,
                reasons_json=json.dumps(dict(Counter(r["reason"] for r in group))),
                physical_metric_verified=False, usable_for_ffb=False))
    output.mkdir(parents=True, exist_ok=False)
    table = output / "phase_summary.csv"
    with table.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(statistics[0]))
        writer.writeheader()
        writer.writerows(statistics)
    central_summary, central = cases["declared_central_scope"]
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, layout="constrained")
    active = [r for r in central if r["distance_available"] == "True"]
    axes[0].scatter([float(r["source_time_sec"]) for r in active],
                    [float(r["distance_forward_m"]) for r in active], s=6, label="conditional output only")
    for window in phases:
        if window["reference_z_m"] is None:
            continue
        times = [float(r["source_time_sec"]) for r in central if window["start_frame"] <= int(r["frame"]) <= window["end_frame"]]
        axes[0].plot([times[0], times[-1]], [window["reference_z_m"]]*2, "k--", label=window["name"]+" nominal reference")
    axes[0].set(ylabel="Forward distance [m]", title="Recorded recomputation: explicit central ROI, NOT live / physical validation")
    axes[0].legend(fontsize=8)
    names = list(dict.fromkeys(r["reason"] for r in central))
    for index, reason in enumerate(names):
        group = [r for r in central if r["reason"] == reason]
        axes[1].scatter([float(r["source_time_sec"]) for r in group], [index]*len(group), s=3)
    axes[1].set_yticks(range(len(names)), [n.replace("CONDITIONAL_DIAGNOSTIC_NOT_VERIFIED_CONTACT", "CONDITIONAL OUTPUT") for n in names], fontsize=7)
    axes[1].set(xlabel="Original recording time [s]", title="Every original frame: withheld distances are NOT filled")
    for axis in axes:
        axis.grid(alpha=.2)
    plot = output / "distance_and_withholding_timeline.png"
    fig.savefig(plot, dpi=130)
    plt.close(fig)
    examples = []
    raw = next(Path(p) for p in central_summary["source_sha256"] if p.endswith("/raw.avi"))
    for phase in ("cone_130", "cone_200"):
        window = next(w for w in phases if w["name"] == phase)
        selected = next((r for r in central if r["distance_available"] == "True"
                         and window["start_frame"] <= int(r["frame"]) <= window["end_frame"]), None)
        if selected is None:
            continue
        number = int(selected["frame"])
        capture = cv2.VideoCapture(str(raw))
        try:
            if not capture.isOpened() or not capture.set(cv2.CAP_PROP_POS_FRAMES, number-1):
                raise ValueError("cannot seek example frame")
            ok, image = capture.read()
            if not ok or round(capture.get(cv2.CAP_PROP_POS_FRAMES)) != number:
                raise ValueError("example frame seek mismatch")
        finally:
            capture.release()
        result = dict(selected, frame=number, distance_available=True,
                      distance_forward_m=float(selected["distance_forward_m"]),
                      base_pixel=json.loads(selected["base_pixel"]),
                      target_roi_native_xyxy=json.loads(selected["target_roi_native_xyxy"]))
        original = output / "originals" / f"{phase}_raw_f{number:06d}.png"
        derived = output / "visualizations" / f"{phase}_recomputed_f{number:06d}.png"
        for p in (original, derived):
            p.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(original), image) or not cv2.imwrite(str(derived), render_distance(image, result, replay=True)):
            raise RuntimeError("example save failed")
        examples.append(dict(phase=phase, frame=number, source_time_sec=float(selected["source_time_sec"]),
            distance_forward_m=result["distance_forward_m"], selection="FIRST available frame in posthoc evaluation interval",
            original=str(original.relative_to(output)), original_sha256=digest(original),
            visualization=str(derived.relative_to(output)), visualization_sha256=digest(derived),
            source_image_edited=False, label_is_posthoc_recomputation=True))
    report = dict(status="COMPLETED_POSTHOC_REPLAY_REPORT_NOT_PHYSICAL_OR_REALTIME_APPROVAL",
                  phase_labels_used_by_engine=False, source_sha256=sources, examples=examples,
                  unique_recordings=len({s["session"] for s, _ in cases.values()}),
                  replay_case_frame_rows=sum(len(rows) for _, rows in cases.values()),
                  physical_metric_verified=False, usable_for_ffb=False,
                  output_sha256={p.name: digest(p) for p in (table, plot)})
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(statistics, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--scope-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.replay_root, args.scope_json, args.output_dir)
