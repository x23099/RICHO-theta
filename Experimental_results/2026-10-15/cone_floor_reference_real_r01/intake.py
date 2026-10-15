"""Accept one real-camera floor-marker recording; no inferred coordinates."""
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

ARCHIVE = Path("/home/robo25/Downloads/floor_reference_real_r01_20261015_144248_636.tar.xz")
DESTINATION = ROOT / "recordings/2026-10-15_floor_reference_real_intake_r01"


def main():
    if DESTINATION.exists() or (HERE / "intake_summary.json").exists():
        raise ValueError("new intake required; no overwrite")
    archive_hash = sha256(ARCHIVE)
    safe_extract_archive(ARCHIVE, DESTINATION, 2*1024**3)
    sessions = list(DESTINATION.rglob("raw.avi"))
    if len(sessions) != 1:
        raise ValueError("exactly one raw recording expected")
    session = sessions[0].parent
    files = {name:session/name for name in ("raw.avi", "metadata.json", "detections.csv")}
    if any(not f.is_file() or f.is_symlink() for f in files.values()):
        raise ValueError("regular complete session files required")
    hashes = {name:sha256(path) for name, path in files.items()}
    meta = json.loads(files["metadata.json"].read_text())
    if str(meta.get("device")) != "0":
        raise ValueError("expected locally attached camera 0; do not substitute WebSim/network data")
    width, height = int(meta["requested_camera_width"]), int(meta["requested_camera_height"])
    if (width, height) != (1280, 720):
        raise ValueError("native 1280x720 recording required")
    p = meta["parameters"]
    config_file = ROOT / "Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json"
    config = json.loads(config_file.read_text())
    geometry_matches = all(p[key] == config[key] for key in CAMERA_KEYS)
    if not geometry_matches or any(p.get(key) != 0 for key in
            ("enable_ai", "collision_ffb_publish_enabled", "collision_ffb_relay_enabled")):
        raise ValueError("unexpected camera geometry or recording output flags")
    rows = read_csv(files["detections.csv"])
    times = [float(row["time_sec"]) for row in rows]
    if (len(rows) < 2 or [int(r["frame"]) for r in rows] != list(range(1, len(rows)+1))
            or any(not math.isfinite(t) or t < 0 for t in times)
            or any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError("contiguous frames and finite strictly increasing timestamps required")
    samples = set(np.linspace(1, len(rows), 6, dtype=int).tolist())
    image_dir = HERE / "raw_samples"
    image_dir.mkdir(exist_ok=False)
    manifest = []
    video = cv2.VideoCapture(str(files["raw.avi"]))
    if not video.isOpened():
        raise ValueError("raw video cannot be decoded")
    try:
        for number in range(1, len(rows)+1):
            ok, pixels = video.read()
            if not ok or pixels.shape != (height, width, 3):
                raise ValueError("video/CSV/native-size mismatch")
            if number not in samples:
                continue
            target = image_dir / f"floor_reference_f{number:06d}.png"
            if not cv2.imwrite(str(target), pixels):
                raise ValueError("native PNG export failed")
            pixel_hash = hashlib.sha256(pixels.tobytes()).hexdigest()
            if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest() != pixel_hash:
                raise ValueError("exported PNG pixels changed")
            manifest.append(dict(file=str(target.relative_to(HERE)), session=session.name,
                frame=number, time_sec=times[number-1], width=width, height=height,
                png_sha256=sha256(target), decoded_bgr_sha256=pixel_hash,
                source_raw_sha256=hashes["raw.avi"],
                reason="uniform native samples for V-apex visibility review; no inferred measured coordinates"))
        if video.read()[0]:
            raise ValueError("raw contains extra frames beyond CSV")
    finally:
        video.release()
    odom = [r for r in rows if r.get("odom_available") == "1"]
    def velocity_max(key):
        values = [float(r[key]) for r in odom if r.get(key) not in (None, "")]
        if any(not math.isfinite(v) for v in values):
            raise ValueError("nonfinite recorded velocity")
        return max(map(abs, values), default=None)
    if any(sha256(files[name]) != digest for name, digest in hashes.items()) or sha256(ARCHIVE) != archive_hash:
        raise ValueError("source changed during intake")
    write_csv(HERE / "raw_sample_manifest.csv", manifest)
    report = dict(status="PASS_RECORDING_INTAKE_NOT_CALIBRATION_OR_POINT_IDENTIFICATION",
        archive=str(ARCHIVE), archive_sha256=archive_hash, session=str(session), source_sha256=hashes,
        metadata=meta, frames=len(rows), last_time_sec=times[-1], sample_span_sec=times[-1]-times[0],
        sample_read_rate_fps=(len(rows)-1)/(times[-1]-times[0]), native_samples=len(manifest),
        all_raw_frames_decoded=True, original_png_pixels_verified=True,
        camera_geometry_matches_previous_capture_config=geometry_matches,
        odom_available_frames=len(odom), max_abs_odom_linear_mps=velocity_max("odom_linear_mps"),
        max_abs_odom_angular_radps=velocity_max("odom_angular_radps"),
        source_kind="user submitted real-camera floor recording; metadata device=0, not network simulation",
        reference_user_note="V字になっているテープの交点の先端が目標距離になっています",
        measured_coordinates="NOT_YET_CONFIRMED", measured_camera_height="NOT_YET_PROVIDED",
        physical_output=False, fitted_parameters=False, production_settings_changed=False,
        script_sha256=sha256(Path(__file__)), capture_config_sha256=sha256(config_file))
    (HERE / "intake_summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({key:report[key] for key in ("status", "frames", "last_time_sec", "sample_read_rate_fps",
        "native_samples", "odom_available_frames", "max_abs_odom_linear_mps", "max_abs_odom_angular_radps")}, indent=2))


if __name__ == "__main__":
    main()
