#!/usr/bin/env python3
"""連続する原録画＋保存検出だけを用いる支持点ログの比較。実機性能試験ではない。"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import ConeDistanceEngine, digest
from cone_support_quality import ConeSupportQualityGate
from run_cone_distance_replay import load_saved_run
from theta_rtc_frames import NativeFrame, native_frame


def load_reference():
    path = Path(__file__).with_name("source_snapshot") / "cone_distance_core.py"
    module = types.ModuleType("contiguous_reference_core")
    module.__file__ = str(ROOT / "src/cone_distance_core.py")
    sys.modules[module.__name__] = module
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module.ConeDistanceEngine


def point_spans(rows, prefix):
    spans, start = [], None
    for row in rows:
        if row[prefix+"_point"] is None and start is None:
            start = row["frame"]
        elif row[prefix+"_point"] is not None and start is not None:
            spans.append([start, row["frame"]-1])
            start = None
    if start is not None and rows:
        spans.append([start, rows[-1]["frame"]])
    return spans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    reference = load_reference()
    saved = ROOT / "Experimental_results/2026-10-15/cone_static_distance_r01/inference_r01"
    source = ROOT / "recordings/2026-10-15_cone_static_distance_intake_r01"
    summary, counts, hashes = [], Counter(), {}
    files = [Path(__file__).resolve(), *Path(__file__).with_name("source_snapshot").glob("*.py")]
    files += [ROOT / "src" / p for p in (
        "cone_distance_core.py", "cone_support_completion_candidate.py", "cone_colour_support_candidate.py",
        "cone_support_quality.py", "cone_scene_diagnostic.py", "run_cone_distance_replay.py",
        "cone_distance_diagnostic_config.json", "angular_fisheye_geometry.py", "fisheye_floor_geometry.py")]
    files += [saved / p for p in ("frames.csv", "predictions.csv", "provenance.json")]
    with (args.output_dir / "replay_frames.jsonl").open("x") as log:
        for session in sorted(p for p in source.iterdir() if (p / "raw.avi").exists()):
            baseline = reference(colour_support_shadow=True)
            current = ConeDistanceEngine(colour_support_shadow=True, support_completion_shadow=True)
            for engine in (baseline, current):
                engine.reset(session.name)
            times, predictions = load_saved_run(session, saved, current.settings)
            files += [session / p for p in ("raw.avi", "metadata.json", "detections.csv")]
            files += [ROOT / current.settings[k+"_candidate"] for k in ("camera", "floor")]
            gates = {key: ConeSupportQualityGate() for key in ("old", "new")}
            cap = cv2.VideoCapture(str(session / "raw.avi"))
            if not cap.isOpened():
                raise ValueError("cannot decode original: " + session.name)
            rows, c = [], Counter()
            try:
                for number, timestamp in enumerate(times, 1):
                    ok, pixels = cap.read()
                    if not ok:
                        raise ValueError("short video: " + session.name)
                    native_frame(pixels)
                    original_pixels_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
                    frame = NativeFrame(session.name, number, timestamp, timestamp, pixels)
                    before = baseline.measure(frame, predictions[number], timestamp+.01)
                    after = current.measure(frame, predictions[number], timestamp+.01)
                    stripped = dict(after)
                    stripped.pop("support_completion_shadow")
                    mismatch = stripped != before
                    c["baseline_mismatches"] += mismatch
                    if hashlib.sha256(pixels.tobytes()).hexdigest() != original_pixels_sha:
                        raise ValueError("native pixels changed")
                    old = (after["colour_support_shadow"]["candidate"] or {})
                    new = (after["support_completion_shadow"]["candidate"] or {})
                    row = dict(session=session.name, frame=number, source_time_sec=timestamp,
                        baseline_equal=not mismatch, old_point=old.get("point"), new_point=new.get("point"),
                        old_reason=old.get("reason", after["colour_reason"]),
                        new_reason=new.get("reason", after["colour_reason"]),
                        completion_attempted=bool(new.get("completion_attempted")),
                        completion_granted=bool(new.get("completion_granted")),
                        completion_reason=new.get("completion_reason"),
                        baseline_reason=after["reason"], baseline_distance_available=after["distance_available"],
                        selected_detector_boxes=after["selected_detector_boxes"])
                    for key, candidate in (("old", old), ("new", new)):
                        candidates = ([dict(support=candidate.get("support"),
                                            unavailable_reason=candidate.get("reason"))] if candidate else
                                      [dict(support=None) for _ in range(after["front_candidates"])])
                        gate = gates[key].update(timestamp, candidates)
                        row[key+"_quality_accepted"] = gate["quality_accepted"]
                        row[key+"_quality_reason"] = gate["reason"]
                        c[key+"_points"] += candidate.get("point") is not None
                        # Gate is intentionally independent, OFFLINE ONLY; never substitutes the runtime gate.
                        c[key+"_quality_accepted"] += gate["quality_accepted"]
                    c["completion_attempted"] += row["completion_attempted"]
                    c["completion_granted"] += row["completion_granted"]
                    c["lost_points"] += old.get("point") is not None and new.get("point") is None
                    c["changed_prior_points"] += old.get("point") is not None and new.get("point") != old["point"]
                    c["baseline_distances"] += after["distance_available"]
                    rows.append(row)
                    log.write(json.dumps(row, separators=(",", ":"), allow_nan=False)+"\n")
                if cap.read()[0]:
                    raise ValueError("extra video frames beyond ledger")
            finally:
                cap.release()
            c["frames"] = len(rows)
            detail = dict(session=session.name, **dict(c))
            for key in ("old", "new"):
                detail[key+"_missing_point_spans"] = point_spans(rows, key)
                detail[key+"_reason_counts"] = dict(Counter(r[key+"_reason"] for r in rows))
                steps = [float(np.linalg.norm(np.array(b[key+"_point"])-a[key+"_point"]))
                         for a, b in zip(rows, rows[1:])
                         if a[key+"_point"] is not None and b[key+"_point"] is not None]
                detail[key+"_adjacent_point_pairs"] = len(steps)
                detail[key+"_point_step_p95_px"] = float(np.percentile(steps, 95)) if steps else None
                detail[key+"_point_step_max_px"] = max(steps) if steps else None
            summary.append(detail)
            counts.update(c)
            print(session.name, dict(c), flush=True)
    hashes = {str(p.resolve()): digest(p) for p in sorted(set(files))}
    result = dict(schema="offline_contiguous_support_logging_v1", sessions=summary, totals=dict(counts),
        replay_timing="logical original time + 10 ms for BOTH engines; NOT measured live latency",
        scene_estimator_exercised=False, scene_initialized=False,
        detector_source="saved predictions; exact raw bytes/ledger/settings checked; no fresh inference",
        physical_metric_verified=False, usable_for_ffb=False, physical_output=False,
        source_sha256=hashes)
    (args.output_dir / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    os.environ.setdefault("MPLCONFIGDIR", str(args.output_dir / "matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = np.arange(len(summary))
    fig, ax = plt.subplots(figsize=(10, 4.8))
    for offset, key, label in ((-.18, "old", "Separated colour shadow"), (.18, "new", "Bounded completion shadow")):
        ax.bar(x+offset, [s[key+"_points"] for s in summary], .36, label=label)
    ax.set_xticks(x)
    ax.set_xticklabels([s["session"].split("_2026")[0].replace("cone_static_", "") for s in summary], rotation=20, ha="right")
    ax.set_ylabel("Frames with unverified image point")
    ax.set_title("Offline contiguous saved-detection replay; not distance accuracy")
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.output_dir / "support_availability.png", dpi=140)
    plt.close(fig)
    with (args.output_dir / "session_counts.csv").open("x", newline="") as stream:
        fields = ["session", *sorted(counts)]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary)
    return 0 if not any(counts[k] for k in ("baseline_mismatches", "lost_points", "changed_prior_points")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
