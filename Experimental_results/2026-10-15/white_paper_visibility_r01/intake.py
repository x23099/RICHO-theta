"""Intake a white-paper corner visibility recording, not a calibration fit."""
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
from analyze_field_recording import safe_extract_archive, summarize_session_integrity
from cone_dataset import read_csv, sha256, write_csv

ARCHIVE = Path("/home/robo25/Downloads/itikakunin_20261015_181034_492.tar.xz")
DESTINATION = ROOT/"recordings/2026-10-15_white_paper_visibility_intake_r01"


def main():
    if DESTINATION.exists() or (HERE/"intake_summary.json").exists():
        raise ValueError("new intake required; no overwrite")
    archive_digest = sha256(ARCHIVE)
    safe_extract_archive(ARCHIVE, DESTINATION, 3*1024**3)
    videos = list(DESTINATION.rglob("raw.avi"))
    if len(videos) != 1:
        raise ValueError("exactly one raw session required")
    session = videos[0].parent
    files = {name: session/name for name in ("raw.avi", "metadata.json", "detections.csv")}
    if any(not p.is_file() or p.is_symlink() for p in files.values()):
        raise ValueError("complete regular recording required")
    before = {str(p): sha256(p) for p in files.values()}
    before[str(ARCHIVE)] = archive_digest
    metadata = json.loads(files["metadata.json"].read_text())
    rows = read_csv(files["detections.csv"])
    times = [float(r["time_sec"]) for r in rows]
    if (not rows or [int(r["frame"]) for r in rows] != list(range(1, len(rows)+1))
            or any(not math.isfinite(t) or t < 0 for t in times)
            or any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError("contiguous increasing finite frame/time table required")
    sample_ids = set(np.linspace(1, len(rows), min(8, len(rows)), dtype=int).tolist())
    folder = HERE/"raw_samples"
    folder.mkdir()
    capture = cv2.VideoCapture(str(files["raw.avi"]))
    if not capture.isOpened():
        raise ValueError("raw video unreadable")
    manifest = []
    try:
        for number in range(1, len(rows)+1):
            ok, image = capture.read()
            if not ok or image.shape != (720, 1280, 3):
                raise ValueError("native raw/CSV frame mismatch")
            if number in sample_ids:
                target = folder/f"paper_f{number:06d}.png"
                if not cv2.imwrite(str(target), image):
                    raise ValueError("PNG export failed")
                pixels_digest = hashlib.sha256(image.tobytes()).hexdigest()
                if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest() != pixels_digest:
                    raise ValueError("PNG differs from decoded raw pixels")
                manifest.append(dict(file=str(target.relative_to(HERE)), session=session.name, frame=number,
                                     time_sec=times[number-1], width=1280, height=720,
                                     png_sha256=sha256(target), decoded_bgr_sha256=pixels_digest,
                                     source_raw_sha256=before[str(files["raw.avi"])]))
        if capture.read()[0]:
            raise ValueError("extra raw frames beyond CSV")
    finally:
        capture.release()
    write_csv(HERE/"raw_sample_manifest.csv", manifest)
    integrity = summarize_session_integrity(session, str(ARCHIVE))
    odom = [r for r in rows if r.get("odom_available") == "1"]
    speeds = {}
    for key in ("odom_linear_mps", "odom_angular_radps"):
        values = [float(r[key]) for r in odom if r.get(key) not in (None, "")]
        if any(not math.isfinite(v) for v in values):
            raise ValueError("nonfinite odom")
        speeds["max_abs_"+key] = max(map(abs, values), default=None)
    assert all(sha256(Path(p)) == digest for p, digest in before.items())
    report = dict(status="COMPLETED_NATIVE_PAPER_VISIBILITY_INTAKE_NOT_CALIBRATION_APPROVAL",
                  archive=str(ARCHIVE), session=str(session), source_sha256=before,
                  metadata=metadata, integrity=integrity, total_frames=len(rows),
                  last_time_sec=times[-1], sample_read_rate_fps=(len(rows)-1)/(times[-1]-times[0]) if len(rows)>1 else None,
                  native_samples=len(manifest), all_raw_frames_decoded=True,
                  odom_available_frames=len(odom), **speeds,
                  user_note="A3があったので２枚を合わせて左端を２ｍに合わせています。車体中央も問題ないと思います",
                  reference_point="requested vehicle-near left corner; left edge at2m reported; exact corner image association pending review",
                  reference_z_m=2.0, reported_central_alignment="user thinks alignment is correct; no measured X uncertainty supplied",
                  paper_dimensions_orientation_and_joint_not_measured=True,
                  parameters_fitted=False, physical_output=False, production_settings_changed=False,
                  intake_script_sha256=sha256(Path(__file__)))
    (HERE/"intake_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n")
    print(json.dumps({k:report[k] for k in ("status", "total_frames", "last_time_sec", "sample_read_rate_fps", "native_samples", "odom_available_frames", *speeds)}, indent=2))


if __name__ == "__main__":
    main()
