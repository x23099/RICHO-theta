"""Infer native reference samples; no training, GT invention, ROS, or FFB."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from run_cone_review_frames import infer_frames, load_manifest
from run_cone_yolo import check_cuda, configure_offline


def main():
    output = HERE / "inference_r01"
    if output.exists():
        raise ValueError("new inference output required; no overwrite")
    intake = json.loads((HERE / "intake_summary.json").read_text())
    images = load_manifest(HERE, HERE / "raw_sample_manifest.csv")
    receipt_path = ROOT / "Experimental_results/2026-10-14/friend_models_review_r01/checkpoint_inspection.json"
    receipt = json.loads(receipt_path.read_text())
    tensors = Path(receipt["cone"]["tensor_only_path"])
    if sha256(tensors) != receipt["cone"]["tensor_only_sha256"]:
        raise ValueError("previously sanitized friend weights changed")
    own = ROOT / "runs/cone/train_ab_augmented_v03_local_20261014_r01/yolov8n/weights/best.pt"
    if sha256(own) != "3a6e124adb15c16efd7d22c853406066371f48873c82f1d3cfc445b22ae5997b":
        raise ValueError("own model differs from selected development candidate")
    import torch
    gpu = check_cuda(torch, 0)
    torch.set_num_threads(2)
    output.mkdir(exist_ok=False)
    config = output / "ultralytics_config"
    (config / "Ultralytics").mkdir(parents=True)
    os.environ["YOLO_CONFIG_DIR"] = str(config)
    offline = configure_offline(config)
    from ultralytics import YOLO, settings
    from ultralytics.models.yolo.detect.predict import DetectionPredictor
    from ultralytics.nn.tasks import DetectionModel
    from ultralytics.utils import AUTOINSTALL, ONLINE, USER_CONFIG_DIR
    if ONLINE or AUTOINSTALL or Path(USER_CONFIG_DIR).resolve() != config / "Ultralytics":
        raise ValueError("offline/local settings not honored")
    for key in ("wandb", "comet", "clearml", "mlflow", "neptune", "hub"):
        if key in settings:
            settings.update({key: False})
    provenance = dict(status="STARTED_NOT_COMPLETE", gpu=gpu, offline_setup=offline,
        tensor_checkpoint_sha256=sha256(tensors), friend_original_checkpoint_sha256=receipt["files"]["cone.pt"]["sha256"],
        own_checkpoint_sha256=sha256(own), manifest_sha256=sha256(HERE / "raw_sample_manifest.csv"),
        intake_summary_sha256=sha256(HERE / "intake_summary.json"), receipt_sha256=sha256(receipt_path),
        script_sha256=sha256(Path(__file__)), confirmed_training_membership=False,
        trained=False, adopted=False, physical_output=False, completed_profiles=[])
    summary_path = output / "provenance.json"
    summary_path.write_text(json.dumps(provenance, indent=2) + "\n")
    tallies = []
    for name, size, friend in (("friend_640", 640, True), ("friend_960", 960, True), ("own36_960", 960, False)):
        run = output / name
        run.mkdir(exist_ok=False)
        kwargs = dict(device=0, imgsz=size, conf=.01, iou=.7, max_det=300, rect=False, quantize=32,
                      batch=1, half=False, augment=False, save=False, save_txt=False, save_crop=False,
                      show=False, visualize=False, verbose=False)
        if friend:
            # Never load or execute the friend's original serialized module.
            saved = torch.load(tensors, map_location="cpu", weights_only=True)
            model = DetectionModel(cfg=saved["cfg"], ch=3, nc=1, verbose=False)
            model.load_state_dict(saved["state_dict"], strict=True)
            model.names = {0: "traffic_cone"}
            model.eval().float()
            predictor = DetectionPredictor(overrides=kwargs)
            predictor.setup_model(model=model, verbose=False)
            class Adapter:
                def predict(self, source, **unused):
                    return predictor(source=source, stream=False)
            detector = Adapter()
        else:
            detector = YOLO(str(own))
            detector.overrides.update(half=False)
            if detector.names != {0: "traffic_cone"}:
                raise ValueError("single traffic_cone model required")
        args = SimpleNamespace(input_dir=HERE, output_dir=run, device=0, imgsz=size,
                               prediction_floor=.01, nms_iou=.7, max_det=300)
        report = infer_frames(detector, args, images)
        predictions = read_csv(run / "predictions.csv")
        for image in images:
            pp = [r for r in predictions if r["image"] == image["file"]]
            tallies.append(dict(profile=name, image=image["file"], frame=image["frame"],
                predictions_ge_025=sum(float(r["confidence"]) >= .25 for r in pp),
                predictions_ge_050=sum(float(r["confidence"]) >= .5 for r in pp),
                maximum_confidence=max((float(r["confidence"]) for r in pp), default=0),
                truth="no bbox GT; detection counts are NOT accuracy or recall"))
        (run / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        (run / "prediction_kwargs.json").write_text(json.dumps(kwargs, indent=2) + "\n")
        provenance["completed_profiles"].append(name)
        summary_path.write_text(json.dumps(provenance, indent=2) + "\n")
        del detector
        if friend:
            del model, predictor, saved
    write_csv(output / "sample_detection_counts.csv", tallies)
    for path, digest in intake["file_sha256"].items():
        if sha256(Path(path)) != digest:
            raise ValueError("original received file changed")
    if sha256(tensors) != provenance["tensor_checkpoint_sha256"] or sha256(own) != provenance["own_checkpoint_sha256"]:
        raise ValueError("model changed during inference")
    provenance["status"] = "COMPLETED_REFERENCE_SAMPLES_NOT_ACCURACY_OR_DEPLOYMENT_APPROVAL"
    summary_path.write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(dict(status=provenance["status"], profiles=provenance["completed_profiles"],
                          images=len(images)), indent=2))


if __name__ == "__main__":
    main()
