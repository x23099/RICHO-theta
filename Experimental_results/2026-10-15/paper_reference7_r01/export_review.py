"""Export extra native frames for visual interval review; no image modifications."""
import hashlib
import json
from pathlib import Path
import sys

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]/"src"))
from cone_dataset import read_csv, sha256, write_csv


def main():
    intake = json.loads((HERE/"intake_summary.json").read_text())
    session = Path(intake["session"])
    rows = read_csv(session/"detections.csv")
    seconds = [18, 27, 36, 46, 54, 104, 110, 122, 126, 130, 134, 145, 153,
               202, 211, 224, 228, 239, 245]
    selected = {min(rows, key=lambda r: abs(float(r["time_sec"])-t))["frame"] for t in seconds}
    destination = HERE/"interval_review"
    destination.mkdir()
    cap = cv2.VideoCapture(str(session/"raw.avi"))
    manifest = []
    try:
        for row in rows:
            ok, raw = cap.read()
            if not ok or raw.shape != (720, 1280, 3):
                raise ValueError("raw mismatch")
            if row["frame"] not in selected:
                continue
            path = destination/f"paper7_f{int(row['frame']):06d}.png"
            assert cv2.imwrite(str(path), raw)
            pixel_hash = hashlib.sha256(raw.tobytes()).hexdigest()
            assert hashlib.sha256(cv2.imread(str(path)).tobytes()).hexdigest() == pixel_hash
            manifest.append(dict(file=str(path.relative_to(HERE)), frame=row["frame"],
                time_sec=row["time_sec"], session=session.name, width=1280, height=720,
                png_sha256=sha256(path), decoded_bgr_sha256=pixel_hash,
                source_raw_sha256=intake["source_sha256"][str(session/"raw.avi")],
                reason="interval boundary/representative review, not selected by metric error"))
    finally:
        cap.release()
    assert sha256(session/"raw.avi") == intake["source_sha256"][str(session/"raw.avi")]
    write_csv(HERE/"interval_review_manifest.csv", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
