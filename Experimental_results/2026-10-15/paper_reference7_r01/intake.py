"""Safe native intake of the requested seven-pose paper recording."""
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

ARCHIVE = Path("/home/robo25/Downloads/itiawase2_20261015_183552_599.tar.xz")
DESTINATION = ROOT/"recordings/2026-10-15_paper_reference7_intake_r01"


def main():
    if DESTINATION.exists() or (HERE/"intake_summary.json").exists():
        raise ValueError("new intake required; no overwrite")
    digest = sha256(ARCHIVE)
    print("Safely extracting archive...", flush=True)
    safe_extract_archive(ARCHIVE, DESTINATION, 6*1024**3)
    videos = list(DESTINATION.rglob("raw.avi"))
    if len(videos) != 1:
        raise ValueError("exactly one continuous raw session required")
    session = videos[0].parent
    files = {name: session/name for name in ("raw.avi", "metadata.json", "detections.csv")}
    if any(not path.is_file() or path.is_symlink() for path in files.values()):
        raise ValueError("complete regular session required")
    hashes = {str(path): sha256(path) for path in files.values()}
    hashes[str(ARCHIVE)] = digest
    metadata = json.loads(files["metadata.json"].read_text())
    rows = read_csv(files["detections.csv"])
    times = [float(row["time_sec"]) for row in rows]
    if (not rows or [int(r["frame"]) for r in rows] != list(range(1, len(rows)+1))
            or any(not math.isfinite(t) or t < 0 for t in times)
            or any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError("contiguous native frame/time table required")
    print(f"Decoding {len(rows)} raw frames, duration {times[-1]:.2f}s...", flush=True)
    sample_ids = set(np.linspace(1, len(rows), min(32, len(rows)), dtype=int).tolist())
    sample_dir = HERE/"raw_samples"
    sample_dir.mkdir()
    capture = cv2.VideoCapture(str(files["raw.avi"]))
    if not capture.isOpened():
        raise ValueError("cannot read raw video")
    manifest = []
    try:
        for frame in range(1, len(rows)+1):
            ok, image = capture.read()
            if not ok or image.shape != (720, 1280, 3):
                raise ValueError("raw/CSV/native resolution mismatch")
            if frame in sample_ids:
                target = sample_dir/f"paper7_f{frame:06d}.png"
                if not cv2.imwrite(str(target), image):
                    raise ValueError("native PNG export failed")
                pixel_hash = hashlib.sha256(image.tobytes()).hexdigest()
                if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest() != pixel_hash:
                    raise ValueError("exported PNG changed raw pixels")
                manifest.append(dict(file=str(target.relative_to(HERE)), session=session.name, frame=frame,
                    time_sec=times[frame-1], width=1280, height=720, png_sha256=sha256(target),
                    decoded_bgr_sha256=pixel_hash, source_raw_sha256=hashes[str(files["raw.avi"])],
                    reason="32 uniform native samples before phase/position assignment"))
            if frame % 1000 == 0:
                print(f"Decoded {frame}/{len(rows)}", flush=True)
        if capture.read()[0]:
            raise ValueError("extra raw frames beyond CSV")
    finally:
        capture.release()
    write_csv(HERE/"raw_sample_manifest.csv", manifest)
    odom = [r for r in rows if r.get("odom_available") == "1"]
    speeds = {}
    for key in ("odom_linear_mps", "odom_angular_radps"):
        values = [float(r[key]) for r in odom if r.get(key) not in (None, "")]
        if any(not math.isfinite(v) for v in values):
            raise ValueError("nonfinite odom")
        speeds["max_abs_"+key] = max(map(abs, values), default=None)
    assert all(sha256(Path(path)) == value for path, value in hashes.items())
    result = dict(status="COMPLETED_NATIVE_PAPER7_INTAKE_PHASES_NOT_YET_CONFIRMED", archive=str(ARCHIVE),
                  session=str(session), source_sha256=hashes, metadata=metadata,
                  integrity=summarize_session_integrity(session, str(ARCHIVE)), total_frames=len(rows),
                  last_time_sec=times[-1], recording_rate_fps=(len(rows)-1)/(times[-1]-times[0]),
                  native_samples=len(manifest), all_raw_frames_decoded=True,
                  odom_available_frames=len(odom), **speeds,
                  user_note="７箇所全てで録画したつもりですが、もしかしたら何か足らなかったりするかも",
                  requested_protocol=str(HERE.parent/"white_paper_visibility_r01/next_capture.md"),
                  coordinates_assigned=False, parameters_fitted=False, physical_output=False,
                  production_settings_changed=False, intake_script_sha256=sha256(Path(__file__)))
    (HERE/"intake_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n")
    print(json.dumps({k:result[k] for k in ("total_frames", "last_time_sec", "recording_rate_fps", "native_samples", "odom_available_frames", *speeds)}, indent=2))


if __name__ == "__main__":
    main()
