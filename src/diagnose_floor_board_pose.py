#!/usr/bin/env python3
"""Saved native floor-board image -> offline plane candidates, never a live TF.

No camera, ROS, model, network, calibration replacement, or physical output.
The user must establish that the rigid board lies flat on the actual floor.
"""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path

import cv2
import numpy as np

from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from fisheye_intrinsic_calibration import Board, checked_corners, checked_roi, SCREEN
from floor_reference_pose import planar_floor_pose_candidates
from theta_rtc_frames import native_frame


def _detect(image, board, roi):
    x, y, w, h = roi
    gray = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
    found, corners = cv2.findChessboardCornersSB(gray, (board.inner_columns, board.inner_rows),
                                               flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    return None if not found else corners.reshape(-1, 2)+[x, y]


def analyse_board_frame(image, camera, *, square_mm, floor_placement_confirmed=False,
                        board_thickness_mm=None, roi=(0, 300, 640, 340)):
    native_frame(image)
    roi = checked_roi(roi)
    if roi[0]+roi[2] > 640:
        raise ValueError("front-left native ROI only; no rear-lens substitution")
    if type(floor_placement_confirmed) is not bool:
        raise ValueError("explicit bool floor placement confirmation required")
    if type(square_mm) not in (int, float) or not math.isfinite(square_mm):
        raise ValueError("measured finite square size required")
    if board_thickness_mm is not None and (type(board_thickness_mm) not in (int, float)
            or not math.isfinite(board_thickness_mm) or not 0 <= board_thickness_mm <= 100):
        raise ValueError("finite measured board thickness in 0..100 mm required")
    board = Board(square_mm=square_mm)
    result = dict(status="BOARD_NOT_FOUND", board=asdict(board), roi_native_xywh=list(roi),
                  floor_placement_user_confirmed=floor_placement_confirmed,
                  board_thickness_mm=board_thickness_mm, pose_candidates=[],
                  vehicle_heading_verified=False, base_link_transform_available=False,
                  physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    points = _detect(image, board, roi)
    if points is None:
        return result
    try:
        points = checked_corners(points, board, roi)
    except ValueError:
        return dict(result, status="INVALID_OR_PARTIAL_GRID")
    grid = points.reshape(board.inner_rows, board.inner_columns, 2)
    distances = np.r_[np.linalg.norm(np.diff(grid, axis=0), axis=2).ravel(),
                      np.linalg.norm(np.diff(grid, axis=1), axis=2).ravel()]
    spacing = float(np.median(distances))
    result.update(corners_native_xy=points.tolist(), corner_count=len(points),
                  grid_spacing_median_px=spacing, grid_spacing_min_px=float(distances.min()),
                  original_intrinsic_grid_spacing_screen_passed=spacing >= SCREEN["min_grid_spacing_px"])
    if not floor_placement_confirmed:
        return dict(result, status="FLOOR_PLACEMENT_NOT_CONFIRMED_NO_FLOOR_POSE")
    try:
        pose = planar_floor_pose_candidates(points, board.object_points.reshape(-1, 3), camera)
    except ValueError as exc:
        return dict(result, status="NO_COMPATIBLE_FRONT_POSE", reason=str(exc))
    for candidate in pose["candidates"]:
        signed_height = candidate["camera_height_above_floor_m"]
        if abs(signed_height) < 1e-9:
            continue
        # Grid axes are arbitrary; orient the plane normal toward the camera.
        # This is not a yaw/vehicle-axis determination or a solution selection.
        sign = 1. if signed_height > 0 else -1.
        normal = sign*np.array(candidate["up_optical"])
        surface_height = abs(signed_height)
        floor_height = None if board_thickness_mm is None else surface_height+board_thickness_mm/1000
        result["pose_candidates"].append(dict(solution_index=candidate["solution_index"],
            normal_toward_camera_optical=normal.tolist(), camera_to_printed_plane_m=surface_height,
            camera_to_floor_m_if_thickness_supplied=floor_height,
            printed_plane_height_difference_from_0p59_m=surface_height-.59,
            plane_equation_optical=dict(normal=normal.tolist(), offset_m=surface_height),
            native_reprojection_rmse_px=candidate["fit_native_rmse_px"],
            all_points_positive_depth=candidate["all_reference_points_positive_depth"],
            all_points_in_calibrated_domain=candidate["all_projected_in_calibrated_domain"],
            selected=False, physical_metric_verified=False, usable_for_ffb=False))
    result.update(status=("FLOOR_PLANE_CANDIDATES_NOT_APPROVED" if spacing >= SCREEN["min_grid_spacing_px"]
                          else "FLOOR_PLANE_CANDIDATES_SMALL_GRID_NOT_APPROVED"),
                  note="Both planar solutions retained. Printed plane != floor if board thickness is unknown. No vehicle heading.")
    if not result["pose_candidates"]:
        result["status"] = "NO_PLANE_CANDIDATES"
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--square-mm", type=float, required=True)
    p.add_argument("--board-on-floor", action="store_true")
    p.add_argument("--board-thickness-mm", type=float)
    p.add_argument("--roi", type=int, nargs=4, default=(0, 300, 640, 340), metavar=("X", "Y", "W", "H"))
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = p.parse_args(argv)
    if args.output_dir.exists():
        raise ValueError("new output required")
    image = cv2.imread(str(args.image))
    if image is None:
        raise ValueError("existing native image required")
    _, camera, _, _ = load_config(args.config)
    result = analyse_board_frame(image, camera, square_mm=args.square_mm,
        floor_placement_confirmed=args.board_on_floor, board_thickness_mm=args.board_thickness_mm, roi=tuple(args.roi))
    result["source_sha256"] = {str(path.resolve()): digest(path)
        for path in (args.image, args.config, Path(__file__), Path(__file__).with_name("floor_reference_pose.py"),
                     Path(__file__).with_name("fisheye_intrinsic_calibration.py"))}
    args.output_dir.mkdir(parents=True)
    (args.output_dir/"floor_board_report.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(result["status"])
    print("Report:", args.output_dir/"floor_board_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
