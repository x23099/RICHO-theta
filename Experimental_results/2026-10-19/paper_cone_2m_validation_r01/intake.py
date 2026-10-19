"""Safe intake of one paper-cone-paper recording; no model/ROS/hardware."""
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
from analyze_field_recording import safe_extract_archive, summarize_session_integrity
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import CAMERA_KEYS

ARCHIVE = Path("/home/robo25/Downloads/paper_cone_center_z2p00_r01_20261019_180411_245.tar.xz")
DESTINATION = ROOT / "recordings/2026-10-19_paper_cone_2m_intake_r01"


def main():
    if DESTINATION.exists() or (HERE / "intake_summary.json").exists():
        raise ValueError("new intake required; cannot overwrite recording or results")
    digest = sha256(ARCHIVE)
    safe_extract_archive(ARCHIVE, DESTINATION, 3*1024**3)
    videos = list(DESTINATION.rglob("raw.avi"))
    if len(videos) != 1:
        raise ValueError("one raw session required")
    session = videos[0].parent
    names = ("raw.avi", "metadata.json", "detections.csv", "bev.avi", "detection.avi")
    paths = [session / name for name in names]
    if any(not p.is_file() or p.is_symlink() for p in paths):
        raise ValueError("complete regular recording files required")
    hashes = {str(p): sha256(p) for p in [ARCHIVE, *paths]}
    metadata = json.loads((session / "metadata.json").read_text())
    rows = read_csv(session / "detections.csv")
    times = [float(r["time_sec"]) for r in rows]
    if (not rows or [int(r["frame"]) for r in rows] != list(range(1, len(rows)+1))
            or any(not math.isfinite(t) or t < 0 for t in times)
            or any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError("complete consecutive frames and finite increasing time required")
    samples = set(np.linspace(1, len(rows), 18, dtype=int).tolist())
    folder = HERE / "raw_samples"
    folder.mkdir()
    cap = cv2.VideoCapture(str(session / "raw.avi"))
    manifest = []
    try:
        for number, r in enumerate(rows, 1):
            ok, image = cap.read()
            if not ok or image.shape != (720, 1280, 3):
                raise ValueError("native raw/CSV frame mismatch")
            if number in samples:
                path = folder / f"paper_cone_f{number:06d}.png"
                if not cv2.imwrite(str(path), image):
                    raise ValueError("native PNG export failed")
                pixel_digest = hashlib.sha256(image.tobytes()).hexdigest()
                if hashlib.sha256(cv2.imread(str(path)).tobytes()).hexdigest() != pixel_digest:
                    raise ValueError("native PNG pixels changed")
                manifest.append(dict(file=str(path.relative_to(HERE)), session=session.name, frame=number,
                    time_sec=times[number-1], width=1280, height=720, png_sha256=sha256(path),
                    decoded_bgr_sha256=pixel_digest, source_raw_sha256=hashes[str(session / "raw.avi")],
                    reason="18 uniform native samples before phase assignment; unedited"))
        if cap.read()[0]:
            raise ValueError("extra raw frames")
    finally:
        cap.release()
    config = ROOT / "Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json"
    expected = json.loads(config.read_text())
    geometry = {k: metadata["parameters"][k] for k in CAMERA_KEYS}
    differences = {k: dict(recorded=v, previous=expected[k]) for k, v in geometry.items() if v != expected[k]}
    write_csv(HERE / "raw_sample_manifest.csv", manifest)
    if not all(sha256(p) == h for p, h in hashes.items()):
        raise ValueError("source changed during intake")
    summary = dict(status="COMPLETED_NATIVE_INTAKE_NOT_DISTANCE_APPROVAL", archive=str(ARCHIVE),
        session=str(session), source_sha256=hashes, metadata=metadata, total_frames=len(rows),
        last_time_sec=times[-1], recording_rate_fps=(len(rows)-1)/(times[-1]-times[0]),
        all_raw_frames_decoded=True, original_pngs_verified=len(manifest),
        integrity=summarize_session_integrity(session, str(ARCHIVE)), recorded_geometry=geometry,
        geometry_differences_from_previous_capture=differences,
        odom_available_frames=sum(r["odom_available"] == "1" for r in rows),
        max_abs_odom_linear_mps=max((abs(float(r["odom_linear_mps"])) for r in rows if r["odom_linear_mps"]), default=None),
        max_abs_odom_angular_radps=max((abs(float(r["odom_angular_radps"])) for r in rows if r["odom_angular_radps"]), default=None),
        phases_not_yet_assigned=True, nominal_target_z_m=2., reference_from_requested_procedure_not_independent_survey=True,
        physical_output=False, script_sha256=sha256(Path(__file__)))
    (HERE / "intake_summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({k: summary[k] for k in ("total_frames", "last_time_sec", "recording_rate_fps", "original_pngs_verified",
                      "geometry_differences_from_previous_capture", "odom_available_frames")}, indent=2))


if __name__ == "__main__":
    main()
