"""Replay frozen cone predictions through offline camera geometry, without ROS.

No new inference, threshold search, training, image editing, or deployment.
Run from any cwd; --output-dir must be new. Input paths refer to the preserved
October 14 comparison and its local (Git-ignored) datasets.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import label_path, parse_label, read_csv, sha256, verify_image, write_csv
from cone_detection_diagnostics import aggregate, prepare_inputs
from cone_observation import ConeGroundProjector, checked_bbox

PRIOR = ROOT / "Experimental_results/2026-10-14"
SNAPSHOT = PRIOR / "friend_models_review_r01/evaluation_summary.json"
CONFIG = ROOT / "Experimental_results/2026-10-12/cone_yolo_preparation/cone_capture_config.json"
GROUPS = dict(b=("ab_bootstrap_augmented_v03", "val"),
              d=("de_negative_train_review_v01", "train"),
              e=("de_evaluation_review_v01", "val"))
RUNS = {
    "baseline_35": ("cone_baseline_fp32_diagnose_r01", "cone_de_d_baseline_diagnose_r01", "cone_de_e_baseline_diagnose_r01"),
    "augmented_36": ("cone_augmented_v03_fp32_diagnose_r01", "cone_de_d_augmented_diagnose_r01", "cone_de_e_augmented_diagnose_r01"),
    "negative_52": ("cone_negative_v04_b_diagnose_r01", "cone_negative_v04_d_diagnose_r01", "cone_negative_v04_e_diagnose_r01"),
}
THRESHOLDS = (.25, .5)  # Same two fixed comparison points as October 14.


def reviewed_inputs(root, split, *, require_human):
    metadata = json.loads((root / "dataset.json").read_text())
    if sha256(root / "manifest.csv") != metadata["manifest_sha256"]:
        raise ValueError("dataset manifest changed")
    images, truths = prepare_inputs(root, split)
    reviews = read_csv(root / "reviews.csv")
    by_name = {row["image"]: row for row in reviews}
    if len(by_name) != len(reviews):
        raise ValueError("duplicate review records")
    for row in images:
        verify_image(root, row)
        review = by_name[row["image"]]
        label = label_path(root, row["image"])
        if (label.is_symlink() or not label.is_file()
                or review["status"] not in ("positive", "negative")
                or review["label_sha256"] != sha256(label)
                or bool(parse_label(label)) != (review["status"] == "positive")
                or (require_human and not review["note"].startswith("human full-frame review:"))):
            raise ValueError("current explicit review and labels required")
    return images, truths, [by_name[row["image"]] for row in images]


def predictions_from(path, pinned_hashes, images, root, group, *, friend=False):
    file = path / "predictions.csv"
    if pinned_hashes.get(str(file)) != sha256(file):
        raise ValueError("prediction differs from completed October 14 snapshot")
    provenance = json.loads((path / "provenance.json").read_text())
    if not provenance["status"].startswith("COMPLETED_"):
        raise ValueError("completed prediction run required")
    kwargs = provenance.get("prediction_kwargs", provenance.get("kwargs"))
    if kwargs["imgsz"] != 960 or kwargs["conf"] != .01 or kwargs["rect"] is not False:
        raise ValueError("frozen 960px full-frame conditions required")
    manifest = read_csv(path / "raw_review_manifest.csv") if friend else provenance.get("images", [])
    original = {row["image"]: row for row in images}
    if friend:
        mapping = {row["file"]: row for row in manifest}
        selected = [row for row in manifest if row["source_set"] == group]
        if {row["original_image"] for row in selected} != set(original):
            raise ValueError("friend sample set mismatch")
        if any(row["png_sha256"] != original[row["original_image"]]["png_sha256"] for row in selected):
            raise ValueError("friend source image mismatch")
    elif manifest:
        by_name = {row.get("file", row["image"]): row for row in manifest}
        if set(by_name) != set(original) or any(
            by_name[name]["png_sha256"] != original[name]["png_sha256"] for name in original
        ):
            raise ValueError("source image set/hash mismatch")
    else:
        # Standard B diagnostic: its original dataset may have a different
        # training split, so check each val image and label against that run.
        check = provenance["dataset_check"]
        old_manifest = read_csv(Path(check["dataset"]) / "manifest.csv")
        if sha256(Path(check["dataset"]) / "manifest.csv") != check["manifest_sha256"]:
            raise ValueError("original B manifest changed")
        old = {row["image"]: row for row in old_manifest if row["split"] == "val"}
        if set(old) != set(original):
            raise ValueError("B image set changed")
        for name in original:
            label = label_path(root, name)
            if (old[name]["png_sha256"] != original[name]["png_sha256"]
                    or check["labels_sha256"][str(label.relative_to(root))] != sha256(label)):
                raise ValueError("B input/label changed from original diagnostic")
    converted, seen = [], set()
    for raw in read_csv(file):
        if friend:
            source = mapping[raw["image"]]
            if source["source_set"] != group:
                continue
            raw = dict(raw, image=source["original_image"])
        if raw["image"] not in original:
            raise ValueError("prediction image not in selected dataset")
        row = dict(raw, prediction_index=int(raw["prediction_index"]), class_id=int(raw["class_id"]))
        for key in ("confidence", "x1", "y1", "x2", "y2"):
            row[key] = float(row[key])
        key = (row["image"], row["prediction_index"])
        if key in seen or row["prediction_index"] < 0 or row["class_id"] != 0:
            raise ValueError("duplicate prediction index or unsupported class")
        seen.add(key)
        image = original[row["image"]]
        checked_bbox(row, int(image["width"]), int(image["height"]))
        if not .01 <= row["confidence"] <= 1:
            raise ValueError("prediction score outside recorded floor/range")
        converted.append(row)
    return converted, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists():
        raise ValueError("new output directory required; no run overwrite")
    if output == ROOT or output in ROOT.parents or any(
        output.is_relative_to(ROOT / directory) or (ROOT / directory).is_relative_to(output)
        for directory in ("datasets", "recordings", "runs", "src", "tests")
    ):
        raise ValueError("output must not overlap datasets, recordings, runs, or source")
    snapshot = json.loads(SNAPSHOT.read_text())
    pinned = snapshot["source_sha256"]
    camera = json.loads(CONFIG.read_text())
    projector = ConeGroundProjector(camera, width=1280, height=720, front_lens="left")
    inputs, hashes, review_rows = {}, {}, []
    for group, (name, split) in GROUPS.items():
        root = ROOT / "datasets/cone" / name
        images, truths, reviews = reviewed_inputs(root, split, require_human=group != "b")
        if any((int(r["width"]), int(r["height"])) != (1280, 720) for r in images):
            raise ValueError("native 1280x720 camera geometry required")
        if group in ("d", "e"):
            for file in ("dataset.json", "reviews.csv", "manifest.csv"):
                if pinned.get(str(root / file)) != sha256(root / file):
                    raise ValueError("D/E review differs from October 14 snapshot")
        inputs[group] = root, images, truths
        review_rows.extend(dict(set=group, **row) for row in reviews)
        for file in ("manifest.csv", "reviews.csv", "dataset.json"):
            hashes[str(root / file)] = sha256(root / file)
        for row in images:
            hashes[str(root / row["image"])] = sha256(root / row["image"])
            label = label_path(root, row["image"])
            hashes[str(label)] = sha256(label)
    # Keep E exactly as human-labelled yesterday; never replace its GT with
    # model predictions or remove far/occluded GT to improve recall.
    e_hashes = {r["image"]: r["label_sha256"] for r in read_csv(PRIOR / "friend_models_review_r01/human_e_ground_truth.csv")}
    if any(r["label_sha256"] != e_hashes[r["image"]] for r in inputs["e"][2]):
        raise ValueError("human E label snapshot changed")
    metrics, projection_rows, rejection_rows, matches, conditions = [], [], [], [], []
    for model in (*RUNS, "friend_yolo11n"):
        for group_index, group in enumerate(GROUPS):
            root, images, truths = inputs[group]
            path = (PRIOR / "friend_models_review_r01/cone_inference_960" if model == "friend_yolo11n"
                    else PRIOR / RUNS[model][group_index])
            predictions, provenance = predictions_from(path, pinned, images, root, group, friend=model == "friend_yolo11n")
            for name in ("predictions.csv", "provenance.json"):
                hashes[str(path / name)] = sha256(path / name)
            checkpoint_hash = provenance.get("weights_sha256", provenance.get("checkpoint_sha256"))
            if not checkpoint_hash:
                raise ValueError("recorded model checkpoint hash required")
            conditions.append(dict(model=model, set=group, weights_sha256=checkpoint_hash,
                                   prediction_file=str(path / "predictions.csv")))
            image_by_name = {row["image"]: row for row in images}
            front_truths = [row for row in truths if projector.centre_in_front_lens(row)]
            for threshold in THRESHOLDS:
                projector.confidence_threshold = threshold
                kept = [row for row in predictions if row["confidence"] >= threshold]
                front = [row for row in kept if projector.centre_in_front_lens(row)]
                projected = []
                for row in kept:
                    image = image_by_name[row["image"]]
                    result = projector.project(row, frame_width=int(image["width"]), frame_height=int(image["height"]))
                    projection_rows.append(dict(model=model, set=group, confidence_threshold=threshold,
                                                **row, **result))
                    if result["projection_candidate"]:
                        projected.append(row)
                reasons = Counter(row["reason"] for row in projection_rows
                                  if row["model"] == model and row["set"] == group
                                  and row["confidence_threshold"] == threshold)
                rejection_rows.extend(dict(model=model, set=group, confidence_threshold=threshold,
                                           reason=reason, count=count) for reason, count in sorted(reasons.items()))
                for scope, gt, pred in (("all_view_detection", truths, kept),
                                        ("front_centre_detection", front_truths, front),
                                        ("front_projection_hypotheses", front_truths, projected)):
                    _, mm, totals, _ = aggregate(images, gt, pred, dict(confidence_thresholds=[threshold], match_iou=.5))
                    metrics.append(dict(model=model, set=group, scope=scope, **totals[0]))
                    matches.extend(dict(model=model, set=group, scope=scope, **r) for r in mm)
                    if scope == "all_view_detection":
                        old = next(r for r in snapshot["comparisons"] if r["model"] == model
                                   and r["set"] == group and r["imgsz"] == 960
                                   and r["confidence_threshold"] == threshold)
                        if any(totals[0][k] != old[k] for k in ("tp", "fp", "fn", "gt_count", "images")):
                            raise ValueError("original all-view evaluation not reproduced")
    for file in (SNAPSHOT, CONFIG, Path(__file__), ROOT / "src/cone_observation.py",
                 ROOT / "src/cone_detection_diagnostics.py", ROOT / "src/ground_contact.py"):
        hashes[str(file)] = sha256(file)
    # No output until all inputs and matching to the previous report pass.
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "metrics.csv", metrics)
    write_csv(output / "projection_hypotheses.csv", projection_rows)
    write_csv(output / "reasons.csv", rejection_rows)
    write_csv(output / "matches.csv", matches)
    write_csv(output / "review_snapshot.csv", review_rows)
    summary = dict(status="COMPLETED_OFFLINE_CONE_READINESS_NOT_DEPLOYMENT_APPROVAL",
                   adopted=False, physical_output=False, ros_used=False, retrained=False,
                   front_lens="left", native_size=[1280, 720], confidence_thresholds=THRESHOLDS,
                   diagnostic_range_m=[.2, 4.0], camera_geometry=projector.parameters,
                   blue_box_corrections_used=False, floor_contact_verified=False,
                   all_view_previous_results_reproduced=True, inputs=conditions, source_sha256=hashes,
                   limitations=["B has legacy assistant visual labels; see review_snapshot.csv; not newly human confirmed.",
                                "D is training resubstitution for negative_52, not independent holdout.",
                                "E is human-reviewed separate capture but development data, not blind final test.",
                                "Front scope is bbox-centre-in-configured-circle, not human visibility/distance GT.",
                                "Both front scopes retain the SAME GT denominator; range-rejected GT stay FN.",
                                "Bottom bbox projection assumes floor contact; handheld/occluded cones violate it.",
                                "Geometry hypotheses are not qualified positions, hazards, TTC, or FFB commands.",
                                "No time continuity, real range accuracy, end-to-end latency or hardware test."])
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(dict(status=summary["status"], physical_output=False,
                          conditions=len(conditions), output=str(output)), indent=2))


if __name__ == "__main__":
    main()
