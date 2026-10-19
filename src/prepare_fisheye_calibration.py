#!/usr/bin/env python3
"""Print target, extract native corners, fit an OFFLINE calibration candidate."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

from cone_dataset import sha256
from fisheye_intrinsic_calibration import (Board, FRONT_ROI, IMAGE_SIZE, SCREEN, checked_roi,
                                         corner_rms, detect_board, fit_candidate)


def new_output(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def board_target(output, paper="A3"):
    """Vector print target, NOT an edited camera image."""
    board = Board(square_mm=30. if paper == "A3" else 20.)
    width, height = (420., 297.) if paper == "A3" else (297., 210.)
    bw, bh = (board.inner_columns+1)*board.square_mm, (board.inner_rows+1)*board.square_mm
    left, top = (width-bw)/2, (height-bh)/2
    squares = [(left+c*board.square_mm, top+r*board.square_mm)
               for r in range(board.inner_rows+1) for c in range(board.inner_columns+1) if (r+c) % 2 == 0]
    rectangles = "\n".join(f'<rect x="{x}" y="{y}" width="{board.square_mm}" height="{board.square_mm}" fill="black"/>' for x, y in squares)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">'
           f'<rect width="{width}" height="{height}" fill="white"/>{rectangles}'
           f'<text x="{left}" y="{top-10}" font-family="sans-serif" font-size="4">9 x 6 INNER corners; {board.square_mm:g} mm squares; print ACTUAL SIZE 100%</text>'
           f'<path d="M {left} {height-16} h 100 m -100 -2 v 4 m 100 -4 v 4" stroke="black" fill="none" stroke-width="0.3"/>'
           f'<text x="{left+105}" y="{height-14}" font-family="sans-serif" font-size="4">100 mm: measure after printing</text></svg>')
    (output/"checkerboard.svg").write_text(svg+"\n")
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig = plt.figure(figsize=(width/25.4, height/25.4))
    axis = fig.add_axes((0, 0, 1, 1))
    axis.set(xlim=(0, width), ylim=(height, 0))
    axis.axis("off")
    for x, y in squares:
        axis.add_patch(Rectangle((x, y), board.square_mm, board.square_mm, facecolor="black", edgecolor="none"))
    axis.text(left, top-10, f"9 x 6 INNER corners; {board.square_mm:g} mm squares; print ACTUAL SIZE 100%", fontsize=9)
    axis.plot([left, left+100], [height-16]*2, color="black", linewidth=.6)
    for x in (left, left+100):
        axis.plot([x, x], [height-18, height-14], color="black", linewidth=.6)
    axis.text(left+105, height-14, "100 mm: measure after printing", fontsize=9)
    fig.savefig(output/"checkerboard.pdf", bbox_inches=None, pad_inches=0)
    plt.close(fig)
    result = dict(board=asdict(board), paper=paper, page_mm=[width, height], pattern_mm=[bw, bh],
                  pattern_squares=[10, 7], inner_corners=[9, 6], generated_not_camera_image=True,
                  print_scale_required_percent=100, physical_square_must_be_measured=True,
                  output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    write_json(output/"board_spec.json", result)
    return result


def extract(video, spec_path, output, sample_every=15, max_frames=18000, save_raw=False):
    if sample_every < 1 or not 1 <= max_frames <= 108000:
        raise ValueError("positive sample interval and bounded frame count required")
    video, spec_path = Path(video).resolve(), Path(spec_path).resolve()
    if not video.is_file() or not spec_path.is_file():
        raise ValueError("existing raw video and printed board specification required")
    board = Board(**json.loads(spec_path.read_text())["board"])
    sources = {str(p):sha256(p) for p in (video, spec_path)}
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError("video not readable")
    views, attempts, frame = [], [], 0
    if save_raw:
        (output/"raw_frames").mkdir()
    try:
        while frame < max_frames:
            ok, image = cap.read()
            if not ok:
                break
            frame += 1
            if image.shape != (720, 1280, 3):
                raise ValueError("not native1280x720 video: do not use BEV/detection/rectified video")
            if (frame-1) % sample_every:
                continue
            points, reason = detect_board(image, board)
            duplicate = min((corner_rms(points, np.asarray(v["corners_native"])) for v in views), default=None) if points is not None else None
            retained = points is not None and (duplicate is None or duplicate >= SCREEN["duplicate_rms_px"])
            record = dict(frame=frame, corners_native=points.tolist() if points is not None else None,
                          retained=retained, reason="near_duplicate_pose" if points is not None and not retained else reason,
                          nearest_prior_pose_rms_px=duplicate)
            if retained:
                record["retained_index"] = len(views)
                if save_raw:
                    name = f"raw_frames/raw_f{frame:06d}.png"
                    if not cv2.imwrite(str(output/name), image) or not np.array_equal(cv2.imread(str(output/name)), image):
                        raise ValueError("unedited native PNG roundtrip failed")
                    record.update(native_png=name, png_sha256=sha256(output/name), decoded_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest())
                views.append(record.copy())
            attempts.append(record)
            if len(attempts) % 20 == 0:
                print(f"[INFO] sampled={len(attempts)} retained_distinct_views={len(views)}", flush=True)
    finally:
        cap.release()
    if any(sha256(Path(p)) != digest for p, digest in sources.items()):
        raise ValueError("source changed during extraction")
    result = dict(schema="single_fisheye_native_corners_v1", image_size=list(IMAGE_SIZE), roi_native_xywh=list(FRONT_ROI),
                  selected_lens="front_left", board=asdict(board), source_sha256=sources,
                  frames_decoded=frame, sample_every=sample_every, max_frames=max_frames,
                  limit_reached=frame == max_frames, attempts=attempts, retained_views=views,
                  enough_views_for_fit=len(views) >= SCREEN["min_views"],
                  detector="OpenCV findChessboardCornersSB", detector_version=cv2.__version__,
                  source_pixels_edited=False, usable_for_ffb=False)
    write_json(output/"observations.json", result)
    return dict(frames_decoded=frame, sampled=len(attempts), retained_views=len(views),
                enough_views_for_fit=result["enough_views_for_fit"])


def fit(observations, measured_square_mm, output):
    observations = Path(observations).resolve()
    digest = sha256(observations)
    data = json.loads(observations.read_text())
    if (data.get("schema") != "single_fisheye_native_corners_v1" or data.get("image_size") != list(IMAGE_SIZE)
            or data.get("roi_native_xywh") != list(FRONT_ROI) or data.get("selected_lens") != "front_left"):
        raise ValueError("native front-left observation schema required")
    board = Board(data["board"]["inner_columns"], data["board"]["inner_rows"], measured_square_mm)
    for path, expected in data["source_sha256"].items():
        if sha256(Path(path)) != expected:
            raise ValueError("original extraction source changed or inaccessible; preserve provenance")
    views = data["retained_views"]
    if ([r.get("retained_index") for r in views] != list(range(len(views)))
            or any(not r["retained"] for r in views)
            or any(b["frame"] <= a["frame"] for a, b in zip(views, views[1:]))):
        raise ValueError("consecutive retained indices and increasing source frames required")
    candidate = fit_candidate([r["corners_native"] for r in views], board)
    candidate.update(observations_path=str(observations), observations_sha256=digest,
                     source_frames=[r["frame"] for r in views], original_designed_square_mm=data["board"]["square_mm"],
                     source_sha256=data["source_sha256"])
    if sha256(observations) != digest:
        raise ValueError("observation source changed during fit")
    write_json(output/"intrinsics_candidate.json", candidate)
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("board")
    p.add_argument("--paper", choices=("A3", "A4"), default="A3")
    p.add_argument("--output-dir", required=True)
    p = sub.add_parser("extract")
    p.add_argument("--video", required=True)
    p.add_argument("--board-spec", required=True)
    p.add_argument("--sample-every", type=int, default=15)
    p.add_argument("--max-frames", type=int, default=18000)
    p.add_argument("--save-raw-frames", action="store_true")
    p.add_argument("--output-dir", required=True)
    p = sub.add_parser("fit")
    p.add_argument("--observations", required=True)
    p.add_argument("--measured-square-mm", type=float, required=True)
    p.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = None
    cv2.setNumThreads(1)
    try:
        output = new_output(args.output_dir)
        if args.command == "board":
            result = board_target(output, args.paper)
        elif args.command == "extract":
            result = extract(args.video, args.board_spec, output, args.sample_every, args.max_frames, args.save_raw_frames)
        else:
            result = fit(args.observations, args.measured_square_mm, output)
        print(json.dumps(result, indent=2))
        return 2 if result.get("decision") == "REJECTED_CANDIDATE" else 0
    except (ValueError, OSError, KeyError, cv2.error) as error:
        if output is not None:
            write_json(output/"failure.json", dict(error=str(error), command=args.command,
                       no_automatic_retry_or_cpu_gpu_changes=True, usable_for_ffb=False))
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
