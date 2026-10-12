#!/usr/bin/env python3
"""Reproduce reviewed annotation stage without GPU, ROS, or changing images."""
import json
from collections import Counter
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
from annotate_cone_dataset import import_visual_reviews
from cone_dataset import parse_label, label_path, prepare, read_csv, sha256, validate, verify_image, write_csv


def main():
    source = REPO / "datasets/cone/ab_dev_v01"
    starter = REPO / "datasets/cone/ab_bootstrap_v01"
    annotations = HERE / "visual_annotations.csv"
    source_import = import_visual_reviews(source, annotations)
    # Never remove pending images or weaken the original 400-image check.
    if not starter.exists():
        prepare(HERE / "bootstrap_recording_plan.csv", starter, development_only=True)
    expected = {r["image"] for r in read_csv(annotations)}
    if {r["image"] for r in read_csv(starter / "manifest.csv")} != expected:
        raise ValueError("bootstrap frame set differs from explicit reviewed selection")
    starter_import = import_visual_reviews(starter, annotations)
    starter_check = validate(starter)
    # A full original dataset check must still fail while images are pending.
    try:
        validate(source)
    except ValueError as exc:
        if "unreviewed annotation" not in str(exc):
            raise
        original_check = dict(status="EXPECTED_REFUSAL_PENDING_ANNOTATIONS", reason=str(exc))
    else:
        original_check = dict(status="ALL_ORIGINAL_IMAGES_REVIEWED")
    source_manifest = read_csv(source / "manifest.csv")
    source_by_name = {r["image"]: r for r in source_manifest}
    starter_manifest = read_csv(starter / "manifest.csv")
    for row in source_manifest:
        verify_image(source, row)
    for row in starter_manifest:
        original = source_by_name[row["image"]]
        if row != original:
            raise ValueError("starter raw frame/provenance differs from original dataset")
        a, b = label_path(source, row["image"]), label_path(starter, row["image"])
        if a.read_bytes() != b.read_bytes():
            raise ValueError("starter annotation differs from original dataset")
    progress = []
    reviews = {r["image"]: r for r in read_csv(source / "reviews.csv")}
    for session in sorted({r["session"] for r in source_manifest}):
        rows = [r for r in source_manifest if r["session"] == session]
        counts = Counter(reviews[r["image"]]["status"] for r in rows)
        boxes = sum(len(parse_label(label_path(source, r["image"]))) for r in rows
                    if reviews[r["image"]]["status"] != "pending")
        progress.append(dict(session=session, split=rows[0]["split"], images=len(rows),
            positive=counts["positive"], negative=counts["negative"], pending=counts["pending"], boxes=boxes))
    write_csv(HERE / "annotation_progress.csv", progress)
    write_csv(HERE / "bootstrap_frame_manifest.csv", starter_manifest)
    # This snapshot is labels/hashes only; no additional camera images in Git.
    write_csv(HERE / "bootstrap_review_snapshot.csv", read_csv(starter / "reviews.csv"))
    result = dict(stage="2026-10-12 annotated bootstrap; not model accuracy or human approval",
        class_policy="0 traffic_cone: all visible red/yellow cones in both lenses",
        reviewer="assistant full-frame visual review; independent human quality review pending",
        original_import=source_import, original_integrity_check=original_check,
        bootstrap_import=starter_import, bootstrap_integrity_check=starter_check,
        original_raw_images_verified=len(source_manifest), bootstrap_raw_images_verified=len(starter_manifest),
        model_training_performed=False, physical_output=False,
        selection="long recordings: frame 1 then every 300 frames; short recordings: frame 1 then every 30 frames; no model-output selection",
        artifact_sha256={p.name: sha256(p) for p in (annotations, HERE / "bootstrap_recording_plan.csv", Path(__file__))},
        code_sha256={name: sha256(REPO / "src" / name) for name in ("cone_dataset.py", "annotate_cone_dataset.py", "run_cone_yolo.py")})
    (HERE / "annotation_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(original_pending=source_import["remaining_pending"],
        bootstrap_counts=starter_check["counts"], warnings=starter_check["warnings"],
        decision="PASS_BOOTSTRAP_INTEGRITY_ONLY_NO_MODEL_TRAINING"), indent=2))


if __name__ == "__main__":
    main()
