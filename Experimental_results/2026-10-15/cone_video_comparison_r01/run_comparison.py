"""Frozen two-profile, full-frame offline video comparison. No ROS/FFB."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_detection_diagnostics import prepare_inputs, prediction_kwargs
from run_cone_video import build_parser, load_plan, run_video, validated_args
from run_cone_yolo import check_cuda, configure_offline


def pinned_inputs():
    """Reuse unchanged input/label/review checks from the completed first stage."""
    previous = HERE.parent / "cone_ffb_readiness_r01/evaluation_r01/summary.json"
    snapshot = json.loads(previous.read_text())
    if not snapshot["all_view_previous_results_reproduced"] or snapshot["physical_output"]:
        raise ValueError("completed offline reference required")
    for file, expected in snapshot["source_sha256"].items():
        if sha256(Path(file)) != expected:
            raise ValueError(f"reference input/code changed: {file}")
    images, truths = [], []
    for name, split in (("ab_bootstrap_augmented_v03", "val"),
                        ("de_negative_train_review_v01", "train"),
                        ("de_evaluation_review_v01", "val")):
        ii, tt = prepare_inputs(ROOT / "datasets/cone" / name, split)
        images.extend(ii); truths.extend(tt)
    if len(images) != 78 or len(truths) != 88:
        raise ValueError("expected unchanged B38+D16+E24 / B56+E32 anchors")
    return (images, truths), previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preview", action="store_true")
    options = parser.parse_args()
    output = options.output_dir.expanduser().resolve()
    if output.exists() or not output.is_relative_to(ROOT / "Experimental_results/2026-10-15"):
        raise ValueError("NEW dated Experimental_results output required")
    profile_path, plan = HERE / "profiles.json", HERE / "video_plan.csv"
    frozen = json.loads(profile_path.read_text())
    inputs, reference = pinned_inputs()
    prepared = []
    for profile in frozen["profiles"]:
        weights = ROOT / profile["weights"]
        if sha256(weights) != profile["weights_sha256"]:
            raise ValueError("frozen model weights changed")
        args = validated_args(build_parser().parse_args([
            "video", "--plan", str(plan), "--weights", str(weights),
            "--output-dir", str(output / profile["name"]),
            "--confidence", str(profile["confidence"]), "--imgsz", str(frozen["imgsz"]),
            "--nms-iou", str(frozen["nms_iou"]), "--track-iou", str(frozen["track_iou"]),
            "--max-det", str(frozen["max_det"])]))
        sessions = load_plan(plan, args.output_dir, weights)
        prepared.append((profile, args, sessions))
    source_hashes = {str(file): sha256(file) for file in (profile_path, plan, reference, Path(__file__))}
    for _, args, sessions in prepared:
        source_hashes[str(args.weights)] = sha256(args.weights)
        for session in sessions:
            for name, digest in session["hashes"].items():
                source_hashes[str(session["root"] / name)] = digest
    print(json.dumps(dict(status="PREVIEW_ONLY" if options.preview else "FROZEN_INPUTS_VERIFIED",
                          frames_per_profile=sum(len(s["rows"]) for s in prepared[0][2]),
                          profiles=[p[0]["name"] for p in prepared], anchors=len(inputs[0])), indent=2), flush=True)
    if options.preview:
        return
    import torch
    gpu = check_cuda(torch, 0)
    torch.set_num_threads(2)
    output.mkdir(parents=True, exist_ok=False)
    # Create writable local package configuration before importing Ultralytics.
    config = output / "ultralytics_config"
    (config / "Ultralytics").mkdir(parents=True)
    os.environ["YOLO_CONFIG_DIR"] = str(config)
    offline = configure_offline(config)
    from ultralytics import YOLO, settings
    from ultralytics.utils import AUTOINSTALL, ONLINE, USER_CONFIG_DIR
    if ONLINE or AUTOINSTALL or Path(USER_CONFIG_DIR).resolve() != config / "Ultralytics":
        raise ValueError("local offline package configuration not honored")
    for key in ("wandb", "comet", "clearml", "mlflow", "neptune", "hub"):
        if key in settings:
            settings.update({key: False})
    summary_path = output / "comparison_provenance.json"
    provenance = dict(status="STARTED_NOT_COMPLETE", gpu=gpu, offline_setup=offline,
                      source_sha256=source_hashes,
                      versions={name: importlib.metadata.version(name) for name in
                                ("torch", "torchvision", "ultralytics", "opencv-python")},
                      code_sha256={name: sha256(ROOT / "src" / name) for name in
                                   ("run_cone_video.py", "cone_dataset.py", "cone_detection_diagnostics.py", "run_cone_yolo.py")},
                      physical_output=False, ros_used=False, trained=False, adopted=False,
                      fp32=True, torch_num_threads=2, completed_profiles=[])
    summary_path.write_text(json.dumps(provenance, indent=2) + "\n")
    (output / "environment_freeze.txt").write_text(subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    reports = []
    for profile, args, sessions in prepared:
        print(f"[INFO] Begin frozen profile {profile['name']}", flush=True)
        args.output_dir.mkdir(exist_ok=False)
        # Locally trained, hash-pinned own models; no friend pickle is loaded.
        model = YOLO(str(args.weights))
        if model.names != {0: "traffic_cone"}:
            raise ValueError("single traffic_cone model required")
        model.overrides.update(half=False)
        report = run_video(model, args, sessions, inputs)
        if report["annotated_anchor_images"] != 78 or report["anchor_pixel_mismatches"]:
            raise ValueError("all 78 original anchor pixels must match")
        conditions = dict(name=profile["name"], weights_sha256=profile["weights_sha256"],
                          prediction_kwargs=dict(prediction_kwargs(args), half=False),
                          annotated_anchor_images=report["annotated_anchor_images"],
                          anchor_pixel_mismatches=report["anchor_pixel_mismatches"])
        (args.output_dir / "conditions.json").write_text(json.dumps(conditions, indent=2) + "\n")
        reports.extend(dict(profile=profile["name"], **row) for row in report["sessions"])
        provenance["completed_profiles"].append(profile["name"])
        summary_path.write_text(json.dumps(provenance, indent=2) + "\n")
        del model
    # Verify all original videos, timestamps, models and frozen conditions again.
    for file, expected in source_hashes.items():
        if sha256(Path(file)) != expected:
            raise ValueError(f"input changed during comparison: {file}")
    write_csv(output / "session_throughput.csv", reports)
    provenance["status"] = "COMPLETED_OFFLINE_VIDEO_COMPARISON_NOT_DEPLOYMENT"
    provenance["input_hashes_unchanged"] = True
    summary_path.write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"[INFO] Comparison complete: {summary_path}", flush=True)


if __name__ == "__main__":
    main()
