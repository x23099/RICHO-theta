#!/usr/bin/env python3
"""Native/cropped/upscaled detector controls only. Never saves edited images.

ROI is a declared observed board location, NOT tuned using pose/height results.
Upsampling coordinates use the pixel-centre inverse mapping, not simple /scale.
"""
import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import digest, load_config
from fisheye_intrinsic_calibration import Board
from floor_reference_pose import planar_floor_pose_candidates


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-json", type=Path, required=True)
    args = p.parse_args()
    board = Board(square_mm=20.)
    _, camera, _, _ = load_config()
    rows, sources = [], {}
    for frame, roi in ((1259, (260, 395, 130, 65)), (1655, (335, 390, 130, 70))):
        path = ROOT/f"recordings/2026-10-30_floor_board_intake_r01/decoded_15ae673c24484d119952ae391df611aa_f{frame:06d}.png"
        sources[str(path)] = digest(path)
        image = cv2.imread(str(path))
        if image is None or image.shape != (720, 1280, 3):
            raise ValueError("native frame required")
        x, y, w, h = roi
        gray = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
        for method, scale in (("classic", 1), ("SB", 1), ("SB", 2), ("SB", 4)):
            work = gray if scale == 1 else cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            if method == "classic":
                found, corners = cv2.findChessboardCorners(work, (9, 6), flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
            else:
                found, corners = cv2.findChessboardCornersSB(work, (9, 6),
                    flags=cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
            row = dict(frame=frame, roi_xywh=list(roi), detector=method, scale=scale, found=bool(found),
                       native_accuracy_approved=False, usable_for_ffb=False)
            if found:
                native = (corners.reshape(-1, 2).astype(float)+.5)/scale-.5+[x, y]
                grid = native.reshape(6, 9, 2)
                gaps = np.r_[np.linalg.norm(np.diff(grid, axis=0), axis=2).ravel(),
                             np.linalg.norm(np.diff(grid, axis=1), axis=2).ravel()]
                row.update(corners_native_xy=native.tolist(), grid_median_px=float(np.median(gaps)),
                           grid_min_px=float(gaps.min()),
                           per_axis_median_px=[float(np.median(np.linalg.norm(np.diff(grid, axis=a), axis=2))) for a in (0, 1)])
                pose = planar_floor_pose_candidates(native, board.object_points.reshape(-1, 3), camera)
                row["pose_candidates"] = pose["candidates"]
            rows.append(row)
    sources[str(Path(__file__).resolve())] = digest(Path(__file__).resolve())
    with args.output_json.open("x") as f:
        json.dump(dict(status="DETECTOR_CONTROLS_NOT_CALIBRATION_APPROVAL", rows=rows, source_sha256=sources), f, indent=2)
        f.write("\n")
    for row in rows:
        print({k: v for k, v in row.items() if k not in ("corners_native_xy", "pose_candidates")})
        if row.get("pose_candidates"):
            print([(c["solution_index"], c["camera_height_above_floor_m"], c["fit_native_rmse_px"]) for c in row["pose_candidates"]])


if __name__ == "__main__":
    main()
