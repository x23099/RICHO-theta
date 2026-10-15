"""Six static-cone recordings: safe intake/native samples, no model/ROS/FFB."""
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from analyze_field_recording import safe_extract_archive
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import CAMERA_KEYS

ARCHIVE = Path("/home/robo25/Downloads/10151400.tar.xz")
DESTINATION = ROOT / "recordings/2026-10-15_cone_static_distance_intake_r01"
REFERENCE = {
    "cone_static_no_cone_r01": ("none", None, None),
    "cone_static_center_z0p80_r01": ("center_080", 0.0, .80),
    "one_static_center_z0p80_r01": ("center_080", 0.0, .80),  # Preserve original typo.
    "cone_static_center_z1p30_r01": ("center_130", 0.0, 1.30),
    "cone_static_center_z2p00_r01": ("center_200", 0.0, 2.00),
    "cone_static_left_z1p30_r01": ("left_130", -.40, 1.30),
    "cone_static_right_z1p30_r01": ("right_130", .40, 1.30),
}


def main():
    if DESTINATION.exists() or (HERE / "intake_summary.json").exists():
        raise ValueError("new intake outputs required; no overwrite")
    archive_hash = sha256(ARCHIVE)
    safe_extract_archive(ARCHIVE, DESTINATION, 5*1024**3)
    sessions = sorted(path.parent for path in DESTINATION.rglob("raw.avi"))
    if len(sessions) != 6:
        raise ValueError("exactly six raw sessions expected")
    weights = ROOT / "runs/cone/train_ab_augmented_v03_local_20261014_r01/yolov8n/weights/best.pt"
    weight_hash = "3a6e124adb15c16efd7d22c853406066371f48873c82f1d3cfc445b22ae5997b"
    if sha256(weights) != weight_hash:
        raise ValueError("fixed development candidate changed")
    samples, conditions, inventories, plan, seen = [], [], [], [], set()
    expected_camera = json.loads((ROOT / "Experimental_results/2026-10-12/cone_yolo_preparation/cone_capture_config.json").read_text())
    folder = HERE / "raw_samples"
    folder.mkdir(exist_ok=False)
    for session in sessions:
        files = {name: session / name for name in ("raw.avi", "metadata.json", "detections.csv")}
        if any(not path.is_file() or path.is_symlink() for path in files.values()):
            raise ValueError("complete regular session files required")
        hashes = {name: sha256(path) for name, path in files.items()}
        metadata = json.loads(files["metadata.json"].read_text())
        label = metadata["experiment_label"]
        if label not in REFERENCE:
            raise ValueError(f"unrecognized capture label: {label}")
        key, reference_x, reference_z = REFERENCE[label]
        if key in seen:
            raise ValueError("duplicate static condition")
        seen.add(key)
        rows = read_csv(files["detections.csv"])
        times = [float(row["time_sec"]) for row in rows]
        if (not rows or [int(row["frame"]) for row in rows] != list(range(1, len(rows)+1))
                or any(not math.isfinite(t) or t < 0 for t in times)
                or any(b <= a for a, b in zip(times, times[1:]))):
            raise ValueError("contiguous frames and finite strictly increasing times required")
        parameters = metadata["parameters"]
        if any(name not in parameters for name in CAMERA_KEYS):
            raise ValueError("recorded camera geometry incomplete")
        width, height = int(metadata["requested_camera_width"]), int(metadata["requested_camera_height"])
        if (width, height) != (1280, 720):
            raise ValueError("native THETA 1280x720 frames required")
        selected = set(np.linspace(1, len(rows), 4, dtype=int).tolist())
        capture = cv2.VideoCapture(str(files["raw.avi"]))
        if not capture.isOpened():
            raise ValueError("cannot decode static recording")
        try:
            for number in range(1, len(rows)+1):
                ok, pixels = capture.read()
                if not ok or pixels.shape != (height, width, 3):
                    raise ValueError("CSV/video length or native geometry mismatch")
                if number not in selected:
                    continue
                target = folder / f"{key}_f{number:06d}.png"
                if not cv2.imwrite(str(target), pixels):
                    raise ValueError("native PNG export failed")
                digest = hashlib.sha256(pixels.tobytes()).hexdigest()
                if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest() != digest:
                    raise ValueError("PNG pixels changed")
                samples.append(dict(file=str(target.relative_to(HERE)), condition=key,
                    session=session.name, frame=number, time_sec=times[number-1], width=width, height=height,
                    png_sha256=sha256(target), decoded_bgr_sha256=digest, source_raw_sha256=hashes["raw.avi"],
                    reason="four fixed native samples per static session; not bbox GT or training"))
            if capture.read()[0]:
                raise ValueError("video has extra frames beyond CSV")
        finally:
            capture.release()
        if any(sha256(files[name]) != digest for name, digest in hashes.items()):
            raise ValueError("source changed during intake")
        odom = [row for row in rows if row.get("odom_available") == "1" and row.get("odom_linear_mps") not in (None, "")]
        conditions.append(dict(condition=key, label=label, session=session.name, reference_x_m=reference_x,
            reference_z_m=reference_z, reference_kind="capture label nominal coordinates; user says customary unchanged camera/robot-centre measurement",
            frames=len(rows), last_record_time_sec=times[-1], sample_span_sec=times[-1]-times[0],
            sample_read_rate_fps=(len(rows)-1)/(times[-1]-times[0]) if len(rows) > 1 else None,
            odom_available_frames=len(odom), max_abs_odom_linear_mps=max((abs(float(r["odom_linear_mps"])) for r in odom), default=None),
            max_abs_odom_angular_radps=max((abs(float(r["odom_angular_radps"])) for r in odom if r.get("odom_angular_radps") not in (None,"")), default=None),
            ai_enabled=parameters.get("enable_ai"), ffb_publish_enabled=parameters.get("collision_ffb_publish_enabled"),
            ffb_relay_enabled=parameters.get("collision_ffb_relay_enabled"),
            same_camera_parameters_as_capture_config=all(float(parameters[k]) == float(expected_camera[k]) for k in CAMERA_KEYS)))
        inventories.append(dict(condition=key, path=str(session), hashes=hashes, metadata=metadata))
        plan.append(dict(session_dir=str(session), note=f"{key}; stationary floor-cone reference; no per-frame bbox GT"))
        print(f"[INFO] {key}: {len(rows)} frames / {times[-1]:.2f}s / native decode PASS", flush=True)
    if sha256(ARCHIVE) != archive_hash:
        raise ValueError("archive changed during intake")
    write_csv(HERE / "raw_sample_manifest.csv", samples)
    write_csv(HERE / "session_conditions.csv", conditions)
    write_csv(HERE / "video_plan.csv", plan)
    summary = dict(status="COMPLETED_STATIC_RECORDING_INTAKE_NOT_POSITION_ACCURACY_PASS",
        archive=str(ARCHIVE), archive_sha256=archive_hash, retained=str(DESTINATION), inputs=inventories,
        sessions=len(sessions), total_frames=sum(r["frames"] for r in conditions), native_samples=len(samples),
        reference_user_note="従来のやり方です。今回だけ変更しているとかはありません",
        reference_origin="camera ground projection / Kobuki centre, as customary",
        reference_values="nominal positions from capture labels; fine placement uncertainty/base dimensions not supplied",
        model=dict(path=str(weights), sha256=weight_hash, confidence=.5, imgsz=960, nms_iou=.7, max_det=300),
        metadata_only_input=True, trained=False, physical_output=False, script_sha256=sha256(Path(__file__)))
    (HERE / "intake_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k:summary[k] for k in ("status", "sessions", "total_frames", "native_samples")}, indent=2))


if __name__ == "__main__":
    main()
