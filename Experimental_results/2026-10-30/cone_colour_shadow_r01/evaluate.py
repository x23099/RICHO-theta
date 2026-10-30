#!/usr/bin/env python3
"""既存画像・保存枠で旧抽出と色分離候補を対照。距離ラベル/推論/実機は使わない。"""
import argparse
from collections import Counter
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types

import cv2

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest, load_config, observe_support, select_front_boxes
from cone_colour_support_candidate import observe_separated_support


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def csv_rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    frozen_path = ROOT / "Experimental_results/2026-10-26/cone_distance_report_r01/source_snapshot/cone_distance_core.py"
    frozen = load_module("frozen_colour_support_baseline", frozen_path)
    _, camera, _, _ = load_config()
    manifest = ROOT / "Experimental_results/2026-10-22/scene_uniform_validation_r01/intake_r01/native_sample_manifest.csv"
    samples = csv_rows(manifest)
    saved = load_module("saved_native_box_audit", ROOT / "Experimental_results/2026-10-23/object_excluded_scene_r01/analyze.py")
    _, predictions, coverage, sources = saved.load_saved_boxes(samples)
    present = {(r["session"], r["frame"]) for r in coverage if r["saved_prediction_frame_present"]}
    checks, rows = [], []

    def compare(image, box, identity, kind):
        old = frozen.observe_support(image, box, camera)
        baseline = observe_support(image, box, camera)
        if baseline != old:
            raise AssertionError("default baseline changed: " + identity)
        shadow = observe_separated_support(image, box, camera)
        rows.append(dict(identity=identity, source_kind=kind,
                         bbox_xyxy=[box[k] for k in ("x1", "y1", "x2", "y2")],
                         baseline_reason=baseline["reason"], baseline_point=baseline["point"],
                         shadow_reason=shadow["reason"], shadow_point=shadow["point"],
                         selected_colour=shadow["selected_colour"], seed=shadow["seed_xyxy"],
                         seed_red_pixels=shadow["seed_red_pixels"], seed_yellow_pixels=shadow["seed_yellow_pixels"],
                         seed_purity=shadow["seed_dominant_fraction"],
                         support_changed=(baseline["support"] != shadow["support"]),
                         verified_floor_contact=False, usable_for_ffb=False))

    for sample in samples:
        key = sample["session"], int(sample["frame"])
        if key not in present:
            continue
        path = Path(sample["source_native_png"])
        if digest(path) != sample["png_sha256"]:
            raise ValueError("native source changed: " + str(path))
        image = cv2.imread(str(path))
        boxes = select_front_boxes(predictions[key], camera, .5)
        checks.append(dict(session=key[0], frame=key[1], selected_front_boxes=len(boxes)))
        sources[str(path)] = digest(path)
        for index, box in enumerate(boxes):
            compare(image, box, f"{key[0]}:{key[1]}:{index}", "historical_saved_model_box")

    # Reviewed dataset boxes exercise both colours and small objects. They are
    # HUMAN bbox inputs, not predictions and not a fresh detector evaluation.
    dataset = ROOT / "datasets/cone/ab_bootstrap_v01"
    reviews = {r["image"]: r for r in csv_rows(dataset / "reviews.csv")}
    from cone_dataset import label_path, parse_label
    for sample in csv_rows(dataset / "manifest.csv"):
        path = dataset / sample["image"]
        label = label_path(dataset, sample["image"])
        if digest(path) != sample["png_sha256"] or digest(label) != reviews[sample["image"]]["label_sha256"]:
            raise ValueError("reviewed image/label changed")
        image = cv2.imread(str(path))
        sources[str(path)], sources[str(label)] = digest(path), digest(label)
        for i, (x, y, w, h) in enumerate(parse_label(label)):
            box = dict(x1=(x-w/2)*1280, y1=(y-h/2)*720, x2=(x+w/2)*1280,
                       y2=(y+h/2)*720, confidence=1., class_id=0)
            if select_front_boxes([box], camera, .5):
                compare(image, box, f"{sample['image']}:{i}", "reviewed_human_bbox_NOT_detector_prediction")

    current_image = ROOT / "recordings/2026-10-30/cone_distance_live_r01/decoded_f1f1b17f34a6447a9789291af128f991_f004903.png"
    current_predictions = ROOT / "Experimental_results/2026-10-30/cone_saved_frame_audit_r01/cpu_results_r02/audit.json"
    proof = json.loads(current_predictions.read_text())
    if digest(current_image) != proof["source_sha256"][str(current_image)]:
        raise ValueError("current native frame changed")
    image = cv2.imread(str(current_image))
    for i, box in enumerate(proof["all_predictions"]):
        compare(image, box, f"current_native_4903:{i}", "saved_frame_CPU_reinference_NOT_original_live_box")
    for path in (manifest, frozen_path, current_image, current_predictions,
                 dataset / "manifest.csv", dataset / "reviews.csv", Path(__file__).resolve(),
                 ROOT / "src/cone_distance_core.py", ROOT / "src/cone_colour_support_candidate.py"):
        sources[str(path)] = digest(path)
    summary = dict(status="SHADOW_EXPLORATORY_REGRESSION_NOT_CONTACT_OR_DISTANCE_APPROVAL",
                   manifest_images=len(samples), saved_prediction_images=len(checks),
                   images_missing_saved_predictions=len(samples)-len(checks),
                   evaluated_boxes=len(rows), baseline_mismatches=0,
                   groups={}, source_sha256=sources, controlling_distance=False,
                   physical_metric_verified=False, usable_for_ffb=False)
    for kind in sorted({r["source_kind"] for r in rows}):
        group = [r for r in rows if r["source_kind"] == kind]
        summary["groups"][kind] = dict(boxes=len(group),
            baseline_points=sum(r["baseline_point"] is not None for r in group),
            shadow_points=sum(r["shadow_point"] is not None for r in group),
            gained=sum(r["baseline_point"] is None and r["shadow_point"] is not None for r in group),
            lost=sum(r["baseline_point"] is not None and r["shadow_point"] is None for r in group),
            shared_points_changed=sum(r["baseline_point"] is not None and r["shadow_point"] is not None
                                      and r["baseline_point"] != r["shadow_point"] for r in group),
            colour_counts=dict(Counter(r["selected_colour"] or "withheld" for r in group)),
            shadow_reasons=dict(Counter(r["shadow_reason"] for r in group)))
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    with (args.output_dir / "box_comparison.jsonl").open("x") as f:
        for row in rows:
            f.write(json.dumps(row)+"\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    main()
