#!/usr/bin/env python3
"""Frozen images/bboxes, prior shadow and bounded completion. No inference.

Bbox +/-1px translations are numerical controls, not more recorded frames.
No ground-truth distances or new calibration are used to select any points.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_colour_support_candidate import observe_separated_support
from cone_distance_core import digest, load_config, observe_support
from cone_support_completion_candidate import observe_lateral_completion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    old_dir = ROOT / "Experimental_results/2026-10-30/cone_colour_shadow_r01/evaluation_r02"
    old_summary = json.loads((old_dir / "summary.json").read_text())
    for path, expected in old_summary["source_sha256"].items():
        if digest(Path(path)) != expected:
            raise ValueError("changed frozen evaluation source: "+path)
    old_rows = [json.loads(line) for line in (old_dir / "box_comparison.jsonl").read_text().splitlines()]
    manifest = ROOT / "Experimental_results/2026-10-22/scene_uniform_validation_r01/intake_r01/native_sample_manifest.csv"
    with manifest.open(newline="") as f:
        samples = {(r["session"], int(r["frame"])): r for r in csv.DictReader(f)}
    entries = []
    for row in old_rows:
        kind, identity = row["source_kind"], row["identity"]
        if kind == "historical_saved_model_box":
            session, frame, _ = identity.rsplit(":", 2)
            path = Path(samples[(session, int(frame))]["source_native_png"])
        elif kind == "reviewed_human_bbox_NOT_detector_prediction":
            path = ROOT / "datasets/cone/ab_bootstrap_v01" / identity.rsplit(":", 1)[0]
        elif kind == "saved_frame_CPU_reinference_NOT_original_live_box":
            path = ROOT / "recordings/2026-10-30/cone_distance_live_r01/decoded_f1f1b17f34a6447a9789291af128f991_f004903.png"
        else:
            raise ValueError("unknown frozen input kind")
        box = dict(zip(("x1", "y1", "x2", "y2"), map(float, row["bbox_xyxy"])))
        entries.append(dict(identity=identity, kind=kind, image=path, box=box, old=row))
    pair_dir = ROOT / "Experimental_results/2026-10-30/floor_board_pair_r01"
    extra_sources = []
    for frame in (1259, 1655):
        path = pair_dir / f"originals/decoded_15ae673c24484d119952ae391df611aa_f{frame:06d}.png"
        pred_path = pair_dir / f"cone_same_session_r01/inference_f{frame:06d}/audit.json"
        prediction = json.loads(pred_path.read_text())
        for p, expected in prediction["source_sha256"].items():
            if digest(Path(p)) != expected:
                raise ValueError("changed native pair inference source: "+p)
        extra_sources.extend((path, pred_path))
        for i, box in enumerate(prediction["all_predictions"]):
            entries.append(dict(identity=f"native_pair:{frame}:{i}", kind="same_session_native_pair_CPU_box",
                                image=path, box=box, old=None))
    _, camera, _, _ = load_config()
    images, rows, jitters, timing = {}, [], [], []
    for entry in entries:
        path = entry["image"]
        if path not in images:
            images[path] = cv2.imread(str(path))
            if images[path] is None or images[path].shape != (720, 1280, 3):
                raise ValueError("native 1280x720 image required")
        image = images[path]
        before = image.copy()
        box = entry["box"]
        baseline = observe_support(image, box, camera)
        old = observe_separated_support(image, box, camera)
        if entry["old"] is not None:
            frozen = entry["old"]
            if (old["point"] != frozen["shadow_point"] or old["reason"] != frozen["shadow_reason"]
                    or baseline["point"] != frozen["baseline_point"] or baseline["reason"] != frozen["baseline_reason"]):
                raise ValueError("original extraction differs from frozen result: "+entry["identity"])
        start = time.perf_counter()
        candidate = observe_lateral_completion(image, box, camera)
        timing.append(1000*(time.perf_counter()-start))
        rows.append(dict(identity=entry["identity"], source_kind=entry["kind"], image=str(path), bbox=box,
            baseline_point=baseline["point"], baseline_reason=baseline["reason"],
            previous_shadow_point=old["point"], previous_shadow_reason=old["reason"], candidate=candidate,
            physical_metric_verified=False, usable_for_ffb=False))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                moved = dict(box, x1=float(box["x1"])+dx, x2=float(box["x2"])+dx,
                             y1=float(box["y1"])+dy, y2=float(box["y2"])+dy)
                if not (0 <= moved["x1"] < moved["x2"] <= 1280 and 0 <= moved["y1"] < moved["y2"] <= 720):
                    jitters.append(dict(identity=entry["identity"], source_kind=entry["kind"], dx=dx, dy=dy,
                                        state="INVALID_TRANSLATED_BBOX"))
                    continue
                v1 = observe_separated_support(image, moved, camera)
                v2 = observe_lateral_completion(image, moved, camera)
                jitters.append(dict(identity=entry["identity"], source_kind=entry["kind"], dx=dx, dy=dy, state="EVALUATED",
                    previous_point=v1["point"], previous_reason=v1["reason"], candidate_point=v2["point"],
                    candidate_reason=v2["reason"], completion_granted=v2["completion_granted"],
                    completion_reason=v2["completion_reason"]))
        if not np.array_equal(before, image):
            raise ValueError("native image was modified")
    groups = {}
    for kind in sorted({r["source_kind"] for r in rows}):
        group = [r for r in rows if r["source_kind"] == kind]
        j = [r for r in jitters if r["source_kind"] == kind and r["state"] == "EVALUATED"]
        groups[kind] = dict(boxes=len(group), previous_points=sum(r["previous_shadow_point"] is not None for r in group),
            candidate_points=sum(r["candidate"]["point"] is not None for r in group),
            gained=sum(r["previous_shadow_point"] is None and r["candidate"]["point"] is not None for r in group),
            lost=sum(r["previous_shadow_point"] is not None and r["candidate"]["point"] is None for r in group),
            prior_points_changed=sum(r["previous_shadow_point"] is not None and r["previous_shadow_point"] != r["candidate"]["point"] for r in group),
            completion_reasons=dict(Counter(r["candidate"]["completion_reason"] for r in group)),
            jitter_evaluated=len(j), jitter_previous_points=sum(r["previous_point"] is not None for r in j),
            jitter_candidate_points=sum(r["candidate_point"] is not None for r in j),
            jitter_prior_points_changed=sum(r["previous_point"] is not None and r["previous_point"] != r["candidate_point"] for r in j))
    sources = dict(old_summary["source_sha256"])
    sources.update({str(p): digest(p) for p in (old_dir / "summary.json", old_dir / "box_comparison.jsonl", manifest,
        Path(__file__).resolve(), ROOT / "src/cone_support_completion_candidate.py", *extra_sources)})
    summary = dict(status="OFFLINE_COMPLETION_CANDIDATE_NOT_PHYSICAL_APPROVAL", evaluated_boxes=len(rows),
        unique_native_images=len(images), frozen_prior_results_compared=len(old_rows),
        translated_bbox_controls=len(jitters), invalid_translated_bbox_controls=sum(r["state"] != "EVALUATED" for r in jitters),
        image_edits=0, prior_source_hash_mismatches=0, default_extraction_mismatches=0,
        groups=groups, cpu_candidate_latency_ms=dict(median=float(np.median(timing)), p95=float(np.percentile(timing, 95)),
            max=float(max(timing)), note="single-pass local CPU timing, not GPU/live/FPS benchmark"),
        source_sha256=sources, runtime_integrated=False, physical_metric_verified=False, usable_for_ffb=False,
        no_new_detector_accuracy_or_floor_contact_truth=True,
        missing_prediction_images_are_not_negative_samples=old_summary["images_missing_saved_predictions"])
    with (args.output_dir / "summary.json").open("x") as f:
        json.dump(summary, f, indent=2, allow_nan=False)
        f.write("\n")
    for name, data in (("box_comparison.jsonl", rows), ("bbox_translation_controls.jsonl", jitters)):
        with (args.output_dir / name).open("x") as f:
            for row in data:
                f.write(json.dumps(row, allow_nan=False)+"\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    main()
