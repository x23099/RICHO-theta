"""Frozen 36-image model on all six static raw recordings; no ROS or FFB."""
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import sha256
from cone_detection_diagnostics import prediction_kwargs
from run_cone_video import build_parser, load_plan, run_video, validated_args
from run_cone_yolo import check_cuda, configure_offline


def main():
    intake_path = HERE / "intake_summary.json"
    intake = json.loads(intake_path.read_text())
    candidate = intake["model"]
    if sha256(Path(candidate["path"])) != candidate["sha256"]:
        raise ValueError("fixed candidate weights changed")
    args = validated_args(build_parser().parse_args([
        "video", "--plan", str(HERE / "video_plan.csv"), "--weights", candidate["path"],
        "--output-dir", str(HERE / "inference_r01"), "--confidence", str(candidate["confidence"]),
        "--imgsz", str(candidate["imgsz"]), "--nms-iou", str(candidate["nms_iou"]),
        "--max-det", str(candidate["max_det"])]))
    sessions = load_plan(args.plan, args.output_dir, args.weights)
    expected = {row["path"]:row["hashes"] for row in intake["inputs"]}
    for session in sessions:
        if session["hashes"] != expected[str(session["root"])]:
            raise ValueError("raw/metadata/CSV changed since intake")
    import torch
    gpu = check_cuda(torch, 0)
    torch.set_num_threads(2)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    config = args.output_dir / "ultralytics_config"
    (config / "Ultralytics").mkdir(parents=True)
    os.environ["YOLO_CONFIG_DIR"] = str(config)
    offline = configure_offline(config)
    from ultralytics import YOLO, settings
    from ultralytics.utils import AUTOINSTALL, ONLINE, USER_CONFIG_DIR
    if AUTOINSTALL or ONLINE or Path(USER_CONFIG_DIR).resolve() != config / "Ultralytics":
        raise ValueError("offline/local configuration not honored")
    for name in ("wandb", "comet", "clearml", "mlflow", "neptune", "hub"):
        if name in settings:
            settings.update({name:False})
    model = YOLO(candidate["path"])
    model.overrides.update(half=False)
    if model.names != {0:"traffic_cone"}:
        raise ValueError("single traffic_cone detector required")
    provenance = dict(status="STARTED_NOT_COMPLETE", gpu=gpu, candidate=candidate,
        kwargs=dict(prediction_kwargs(args), half=False), offline_setup=offline,
        source_sha256={str(HERE / "video_plan.csv"):sha256(HERE / "video_plan.csv"),
                       str(intake_path):sha256(intake_path), str(Path(__file__)):sha256(Path(__file__)),
                       str(ROOT / "src/run_cone_video.py"):sha256(ROOT / "src/run_cone_video.py")},
        native_dimensions=[1280,720], source_sessions=expected, torch_num_threads=2,
        ground_truth_bboxes_provided=False, physical_output=False, trained=False, adopted=False)
    target = args.output_dir / "provenance.json"
    target.write_text(json.dumps(provenance, indent=2)+"\n")
    # No empty-label anchors: no bbox GT has been provided for these positives.
    report = run_video(model, args, sessions, ([], []))
    if report["total_frames"] != intake["total_frames"]:
        raise ValueError("all intake frames must be inferred")
    for session in sessions:
        if any(sha256(session["root"] / name) != digest for name, digest in session["hashes"].items()):
            raise ValueError("source changed during inference")
    if sha256(args.weights) != candidate["sha256"]:
        raise ValueError("model changed during inference")
    provenance["status"] = "COMPLETED_STATIC_CONE_INFERENCE_NOT_DISTANCE_OR_FFB_APPROVAL"
    provenance["source_hashes_unchanged"] = True
    target.write_text(json.dumps(provenance, indent=2)+"\n")
    print(json.dumps(dict(status=provenance["status"], total_frames=report["total_frames"]), indent=2))


if __name__ == "__main__":
    main()
