"""Export selected whole raw frames, preserving every decoded BGR pixel.

This only prepares images for visual review; it never labels visibility.
"""
import argparse
import csv
import hashlib
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    args = parser.parse_args()
    ids = set(args.frames)
    if min(ids) < 1 or len(ids) != len(args.frames):
        parser.error("frames must be unique positive one-based numbers")
    with (args.session_dir / "detections.csv").open(newline="") as stream:
        source = list(csv.DictReader(stream))
    if max(ids) > len(source) or [int(r["frame"]) for r in source] != list(range(1, len(source) + 1)):
        raise ValueError("source frame mismatch")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.session_dir / "raw.avi"))
    rows = []
    try:
        for n in range(1, max(ids) + 1):
            ok, frame = cap.read()
            if not ok:
                raise ValueError("short video")
            if n not in ids:
                continue
            if frame.shape != (720, 1280, 3):
                raise ValueError("unexpected raw frame geometry")
            path = args.output_dir / f"{args.prefix}_raw_frame_{n:04d}.png"
            if not cv2.imwrite(str(path), frame) or not np.array_equal(cv2.imread(str(path)), frame):
                raise ValueError("saved PNG pixels differ from raw frame")
            rows.append(dict(session=args.session_dir.name, frame_one_based=n,
                             time_sec=source[n - 1]["time_sec"], raw_png=str(path.resolve()),
                             decoded_bgr_pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest()))
    finally:
        cap.release()
    with (args.output_dir / f"{args.prefix}_export_manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Exported {len(rows)} whole unmodified frames from {args.session_dir.name}")


if __name__ == "__main__":
    main()
