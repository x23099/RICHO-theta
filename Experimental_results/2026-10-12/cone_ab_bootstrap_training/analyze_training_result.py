#!/usr/bin/env python3
"""Audit received offline training artifacts and plot CSV, without loading checkpoints."""
import argparse
import csv
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
from analyze_field_recording import safe_extract_archive
from cone_dataset import sha256

METRICS = ("metrics/precision(B)", "metrics/recall(B)", "metrics/mAP50(B)", "metrics/mAP50-95(B)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    archive = args.input.resolve()
    prefix = "train_ab_bootstrap_v01_r01"
    relative = ("provenance.json", "environment_freeze.txt", "metrics.json", "yolov8n/args.yaml",
                "yolov8n/results.csv", "yolov8n/weights/best.pt", "yolov8n/weights/last.pt")
    expected = {f"{prefix}/{name}" for name in relative}
    with tarfile.open(archive, "r:xz") as source:
        members = source.getmembers()
        if len(members) > 100 or sum(m.size for m in members) > 100 * 1024 * 1024:
            raise ValueError("training archive size/member limit exceeded")
        seen = set()
        for member in members:
            p = PurePosixPath(member.name)
            if (p.is_absolute() or ".." in p.parts or p.parts[0] != prefix
                    or not (member.isdir() or member.isfile()) or member.name in seen):
                raise ValueError("unsafe or duplicate training archive member")
            seen.add(member.name)
        if {m.name for m in members if m.isfile()} != expected:
            raise ValueError("unexpected training archive file set")
    local = REPO / "runs/cone/received_train_ab_bootstrap_v01_r01"
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".training_intake_", dir=local.parent) as tmp:
            safe_extract_archive(archive, Path(tmp), 100 * 1024 * 1024)
            (Path(tmp) / prefix).rename(local)
    # Existing received files must match; never overwrite model weights.
    with tarfile.open(archive, "r:xz") as source:
        import hashlib
        for name in relative:
            with source.extractfile(f"{prefix}/{name}") as stream:
                submitted = hashlib.sha256(stream.read()).hexdigest()
            if sha256(local / name) != submitted:
                raise ValueError("existing received artifact differs; no overwrite")
    provenance = json.loads((local / "provenance.json").read_text())
    metrics = json.loads((local / "metrics.json").read_text())
    with (local / "yolov8n/results.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if [int(r["epoch"]) for r in rows] != list(range(1, 51)):
        raise ValueError("expected 50 contiguous epochs")
    if any(not math.isfinite(float(v)) for r in rows for v in r.values()):
        raise ValueError("nonfinite CSV value")
    times = [float(r["time"]) for r in rows]
    if times[0] <= 0 or any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("invalid cumulative training time")
    for name in METRICS:
        if not 0 <= metrics[name] <= 1 or any(not 0 <= float(r[name]) <= 1 for r in rows):
            raise ValueError("invalid metric range")
    if provenance["mode"] != "train" or provenance["status"] != "COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL":
        raise ValueError("training completion provenance missing")
    if provenance["physical_output"] is not False:
        raise ValueError("unexpected physical output")
    planned = dict(epochs=50, batch=8, imgsz=960, seed=0, device=0, workers=0, plots=False)
    if any(provenance["kwargs"].get(k) != v for k, v in planned.items()):
        raise ValueError("training settings differ from planned run")
    receipt = json.loads((HERE.parent / "cone_ab_intake/human_review_verification.json").read_text())
    actual = provenance["dataset_check"]
    for name in ("manifest_sha256", "reviews_sha256", "labels_sha256", "counts"):
        if actual[name] != receipt["dataset_integrity"][name]:
            raise ValueError("training dataset differs from accepted human review")
    if provenance["weights_sha256"] != sha256(REPO / "src/yolov8n.pt"):
        raise ValueError("initial weights differ from prepared local baseline")
    for name in ("yolov8n/weights/best.pt", "yolov8n/weights/last.pt"):
        if (local / name).stat().st_size == 0:
            raise ValueError("empty checkpoint")
    # Save small evidence in dated results; checkpoints stay ignored under runs/.
    for name in ("provenance.json", "environment_freeze.txt", "metrics.json"):
        shutil.copyfile(local / name, HERE / name)
    shutil.copyfile(local / "yolov8n/results.csv", HERE / "results.csv")
    shutil.copyfile(local / "yolov8n/args.yaml", HERE / "training_args.yaml")
    assets = HERE.parent / "report_assets"
    assets.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cone_plot_config_") as tmp:
        os.environ["MPLCONFIGDIR"] = tmp
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.3), layout="constrained")
        epochs = [int(r["epoch"]) for r in rows]
        for key, label in zip(METRICS, ("Precision", "Recall", "mAP@0.50", "mAP@0.50:0.95")):
            axes[0].plot(epochs, [float(r[key]) for r in rows], label=label)
        axes[0].set(xlabel="Epoch", ylabel="Validation metric", ylim=(0, 1.02), title="Development validation only")
        axes[0].legend(fontsize=8)
        for key in ("train/box_loss", "train/cls_loss", "train/dfl_loss"):
            axes[1].plot(epochs, [float(r[key]) for r in rows], label=key)
        axes[1].set(xlabel="Epoch", ylabel="Training loss (log scale)", yscale="log", title="Training loss")
        axes[1].legend(fontsize=8)
        for axis in axes:
            axis.grid(alpha=.25)
        fig.suptitle("Cone bootstrap: train A=35, val B=38; no empty-cone negatives or independent test", fontsize=10)
        fig.savefig(assets / "cone_ab_bootstrap_training_curve.png", dpi=150)
        plt.close(fig)
    result = dict(date="2026-10-12", decision="PASS_TRAINING_COMPLETION_NOT_DEPLOYMENT_APPROVAL",
        archive=str(archive), archive_sha256=sha256(archive), epochs=len(rows),
        cumulative_epoch_time_sec=times[-1], full_command_wall_time_available=False,
        time_scope="CSV cumulative time through epoch 50; startup and final post-loop processing excluded",
        training_dataset_matches_accepted_human_review=True, final_reported_metrics=metrics,
        epoch50_csv_metrics={k: float(rows[-1][k]) for k in METRICS},
        gpu=provenance["gpu"], dataset_counts=actual["counts"],
        actual_gpu_best_weights="/home/hsr/yopi_ws/RICHO-theta/runs/cone/train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt",
        actual_output_name="yolov8n", requested_output_name=provenance["kwargs"]["name"],
        artifacts={name: dict(path=str(local / name), bytes=(local / name).stat().st_size,
                              sha256=sha256(local / name)) for name in relative},
        checkpoints_deserialized=False, local_model_inference_performed=False,
        independent_test_available=False, empty_cone_negative_images=0,
        verifier_sha256=sha256(Path(__file__)),
        graph=dict(path=str(assets / "cone_ab_bootstrap_training_curve.png"),
            sha256=sha256(assets / "cone_ab_bootstrap_training_curve.png"), source_csv_sha256=sha256(HERE / "results.csv")),
        interpretation="Red/yellow combined development metrics, not red-only or unseen-course accuracy; missed detections need per-image/threshold analysis.")
    (HERE / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("decision", "epochs", "cumulative_epoch_time_sec", "final_reported_metrics", "actual_gpu_best_weights")}, indent=2))


if __name__ == "__main__":
    main()
