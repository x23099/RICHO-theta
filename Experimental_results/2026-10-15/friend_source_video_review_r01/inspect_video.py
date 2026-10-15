"""Inspect a received ZIP/video as data; retain native, untouched sample PNGs."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv

ARCHIVE = Path("/home/robo25/Downloads/video-20261015T041958Z-1-001.zip")
RETAINED = ROOT / "recordings/2026-10-15_friend_video_intake_r01"


def main():
    if (HERE / "intake_summary.json").exists():
        raise ValueError("completed intake exists; do not overwrite results")
    allowed = {"video/camera.mp4", "video/camera_stamps.csv", "video/camera_ffmpeg.log"}
    archive_hash = sha256(ARCHIVE)
    with zipfile.ZipFile(ARCHIVE) as archive:
        entries = archive.infolist()
        if len(entries) != 3 or {i.filename for i in entries} != allowed:
            raise ValueError("only the three inspected regular video files permitted")
        if sum(i.file_size for i in entries) > 512*1024**2:
            raise ValueError("uncompressed input exceeds 512 MiB budget")
        for entry in entries:
            mode = entry.external_attr >> 16
            if (entry.is_dir() or entry.flag_bits & 1 or stat.S_ISLNK(mode)
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ValueError("encrypted/nonregular ZIP entries refused")
        reuse = RETAINED.exists()
        if reuse and (RETAINED.is_symlink() or (RETAINED / "video").is_symlink()
                or {str(p.relative_to(RETAINED)) for p in RETAINED.rglob("*") if p.is_file() or p.is_symlink()} != allowed):
            raise ValueError("existing intake has unexpected paths")
        RETAINED.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            target = RETAINED / entry.filename  # Exact whitelist; no archive-controlled traversal.
            target.parent.mkdir(parents=True, exist_ok=True)
            if reuse:
                if target.is_symlink():
                    raise ValueError("existing intake symlink refused")
                source_digest = hashlib.sha256()
                with archive.open(entry) as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b""):
                        source_digest.update(chunk)
                if source_digest.hexdigest() != sha256(target):
                    raise ValueError("existing original differs from ZIP; never overwrite")
            else:
                with archive.open(entry) as stream, target.open("xb") as destination:
                    shutil.copyfileobj(stream, destination, 1024*1024)
            if target.stat().st_size != entry.file_size:
                raise ValueError("extracted size mismatch")
    video = RETAINED / "video/camera.mp4"
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-count_frames", "-show_streams", "-show_format", "-of", "json", str(video)], text=True))
    streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
    if len(streams) != 1:
        raise ValueError("single video stream required")
    stream = streams[0]
    width, height, reported_frames = int(stream["width"]), int(stream["height"]), int(stream["nb_read_frames"])
    if max(width, height) > 4096 or not 1 <= reported_frames <= 100000:
        raise ValueError("video geometry/frame count outside inspection budget")
    stamps = read_csv(RETAINED / "video/camera_stamps.csv")
    stamps_contiguous = [int(row["frame"]) for row in stamps] == list(range(len(stamps)))
    timestamp_values = [[float(row[key]) for row in stamps] for key in ("stamp_sec", "receive_sec")]
    if not all(np.isfinite(values).all() for values in timestamp_values):
        raise ValueError("nonfinite timestamp data")
    alignment = stamps_contiguous and len(stamps) == reported_frames
    selected = set(np.linspace(1, reported_frames, min(12, reported_frames), dtype=int).tolist())
    samples, decoded = [], 0
    folder = HERE / "raw_samples"
    folder.mkdir(exist_ok=False)
    capture = cv2.VideoCapture(str(video))
    if hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
        capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    if not capture.isOpened():
        raise ValueError("cannot decode received video")
    nominal_fps = float(capture.get(cv2.CAP_PROP_FPS))
    video_hash = sha256(video)
    try:
        while True:
            ok, pixels = capture.read()
            if not ok:
                break
            decoded += 1
            if pixels.shape != (height, width, 3) or decoded > reported_frames:
                raise ValueError("decoded geometry/count differs from native stream")
            if decoded not in selected:
                continue
            file = folder / f"camera_f{decoded:06d}.png"
            if not cv2.imwrite(str(file), pixels):
                raise ValueError("PNG export failed")
            pixel_hash = hashlib.sha256(pixels.tobytes()).hexdigest()
            if hashlib.sha256(cv2.imread(str(file)).tobytes()).hexdigest() != pixel_hash:
                raise ValueError("saved frame pixels changed")
            samples.append(dict(file=str(file.relative_to(HERE)), session="friend_reference_camera",
                frame=decoded, csv_frame_index=decoded-1 if alignment else "",
                time_sec=(decoded-1)/nominal_fps,
                time_definition="nominal frame-index/fps; NOT verified capture timestamp",
                stamp_sec=stamps[decoded-1]["stamp_sec"] if alignment else "",
                receive_sec=stamps[decoded-1]["receive_sec"] if alignment else "",
                width=width, height=height, png_sha256=sha256(file), decoded_bgr_sha256=pixel_hash,
                source_raw_sha256=video_hash, reason="uniform full-video reference sample; training membership unknown"))
            print(f"[INFO] Native sample {decoded}/{reported_frames}", flush=True)
    finally:
        capture.release()
    if decoded != reported_frames:
        raise ValueError("incomplete native video decode")
    hashes = {str(RETAINED / name): sha256(RETAINED / name) for name in allowed}
    if sha256(ARCHIVE) != archive_hash:
        raise ValueError("input archive changed during inspection")
    write_csv(HERE / "raw_sample_manifest.csv", samples)
    (HERE / "ffprobe.json").write_text(json.dumps(probe, indent=2) + "\n")
    summary = dict(status="COMPLETED_REFERENCE_VIDEO_INTAKE_NOT_CONFIRMED_TRAINING_DATA",
        archive=str(ARCHIVE), archive_sha256=archive_hash, retained=str(RETAINED), file_sha256=hashes,
        width=width, height=height, decoded_frames=decoded, fps_nominal=nominal_fps,
        fps_stream=stream["avg_frame_rate"], duration_stream_sec=float(stream["duration"]),
        timestamp_rows=len(stamps), timestamp_indices_zero_based_contiguous=stamps_contiguous,
        frame_csv_count_matches=alignment,
        nonincreasing_stamp_intervals=int(sum(np.diff(timestamp_values[0]) <= 0)),
        nonincreasing_receive_intervals=int(sum(np.diff(timestamp_values[1]) <= 0)),
        raw_sample_count=len(samples), input_timestamp_warning_log="video/camera_ffmpeg.log",
        confirmed_training_membership=False, trained=False, physical_output=False,
        source_script_sha256=sha256(Path(__file__)))
    (HERE / "intake_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
