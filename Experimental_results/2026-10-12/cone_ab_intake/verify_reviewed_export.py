#!/usr/bin/env python3
"""Validate a label/review export against local original images without merging it."""
import argparse
from collections import Counter
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
from cone_dataset import dataset_yaml, label_path, read_csv, sha256, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=REPO / "datasets/cone/ab_bootstrap_v01")
    parser.add_argument("--output", type=Path, default=HERE / "human_review_verification.json")
    args = parser.parse_args()
    source = args.dataset.resolve()
    original = read_csv(source / "manifest.csv")
    expected = {"reviews.csv", "manifest.csv", "dataset.json", "data.yaml"} | {
        str(label_path(source, r["image"]).relative_to(source)) for r in original}
    payload = {}
    with tarfile.open(args.input, "r:xz") as archive:
        members = archive.getmembers()
        if len(members) > 200 or sum(m.size for m in members) > 4 * 1024 * 1024:
            raise ValueError("review export size/member limit exceeded")
        for member in members:
            p = PurePosixPath(member.name)
            if p.is_absolute() or ".." in p.parts or member.issym() or member.islnk():
                raise ValueError("unsafe review archive member")
            if member.isdir():
                if member.name.rstrip("/") not in {"labels", "labels/train", "labels/val"}:
                    raise ValueError("unexpected archive directory")
                continue
            if (not member.isfile() or member.name not in expected or member.name in payload):
                raise ValueError("unexpected or duplicate review archive file")
            with archive.extractfile(member) as stream:
                payload[member.name] = stream.read()
    if set(payload) != expected:
        raise ValueError("export file set differs from the original dataset")
    for name in ("manifest.csv", "dataset.json"):
        if payload[name] != (source / name).read_bytes():
            raise ValueError("submitted frame selection/source metadata differs from original")
    metadata = json.loads(payload["dataset.json"])
    gpu_root = "/home/hsr/yopi_ws/RICHO-theta/datasets/cone/ab_bootstrap_v01"
    if payload["data.yaml"].decode() != dataset_yaml(gpu_root, development_only=True):
        raise ValueError("GPU PC dataset YAML differs from expected root/train/val/classes")
    changed = sorted(name for name in expected if name.startswith("labels/")
        and payload[name] != (source / name).read_bytes())
    with tempfile.TemporaryDirectory(prefix="cone_review_check_") as tmp:
        stage = Path(tmp) / "dataset"
        stage.mkdir()
        for name, content in payload.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        # No GPU PC raw images were submitted. Check our matching original PNGs.
        shutil.copytree(source / "images", stage / "images")
        (stage / "data.yaml").write_text(dataset_yaml(stage, development_only=True))
        integrity = validate(stage)
        reviews = read_csv(stage / "reviews.csv")
        human = sum(r["note"] == "human full-frame review: all visible cone boxes annotated"
                    for r in reviews)
        if human != len(original):
            raise ValueError("not all frames carry the explicit GUI human-review record")
        integrity.pop("dataset")  # Temporary validation path is not the GPU dataset location.
    result = dict(date="2026-10-12", decision="PASS_REVIEW_RECORDS_AND_DATASET_INTEGRITY_NOT_MODEL_ACCURACY",
        archive=str(args.input.resolve()), archive_sha256=sha256(args.input),
        submitted_files=len(payload), manifest_matches_original=True, source_metadata_matches_original=True,
        submitted_gpu_dataset_root=gpu_root, reviews=len(reviews), human_review_records=human,
        review_note_counts=dict(Counter(r["note"] for r in reviews)), changed_labels=changed,
        original_dataset_modified=False, original_pngs_verified=len(original),
        gpu_pc_pngs_directly_reverified=False,
        image_verification_scope="Submitted manifest matches local original; checked local full-resolution PNG hashes. GPU PC raw PNGs were not included in this export.",
        dataset_integrity=integrity, model_training_performed=False,
        physical_output=False, verifier_sha256=sha256(Path(__file__)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = args.output.with_name("human_review_snapshot.csv")
    snapshot.write_bytes(payload["reviews.csv"])
    result["human_review_snapshot_sha256"] = sha256(snapshot)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(decision=result["decision"], human_review_records=human,
        label_changes=len(changed), counts=integrity["counts"], warnings=integrity["warnings"],
        report=str(args.output.resolve())), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
