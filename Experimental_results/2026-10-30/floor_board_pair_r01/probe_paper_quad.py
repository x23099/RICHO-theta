#!/usr/bin/env python3
"""White-paper perimeter controls. No invented hidden corners or image edits.

Metric poses require externally supplied paper dimensions. Both assignments
of long/short side and both planar solutions are retained; never height-fit.
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
from floor_reference_pose import planar_floor_pose_candidates


def white_quads(image, roi, threshold):
    x, y, w, h = roi
    gray = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
    contours = cv2.findContours(cv2.inRange(gray, threshold, 255), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    rows = []
    for contour in contours:
        if cv2.contourArea(contour) < 200:
            continue
        bx, by, bw, bh = cv2.boundingRect(contour)
        if bx == 0 or by == 0 or bx+bw >= w or by+bh >= h:
            continue
        poly = cv2.approxPolyDP(contour, .02*cv2.arcLength(contour, True), True)
        if len(poly) != 4 or not cv2.isContourConvex(poly):
            continue
        points = poly[:, 0, :]+[x, y]
        order = np.argsort(points[:, 1], kind="stable")
        far = points[order[:2]][np.argsort(points[order[:2], 0])]
        near = points[order[2:]][np.argsort(points[order[2:], 0])]
        if min(near[:, 1])-max(far[:, 1]) < 3:
            continue
        ordered = np.asarray([far[0], far[1], near[1], near[0]])
        rows.append(dict(quad_xy=ordered.tolist(), contour_area_px=float(cv2.contourArea(contour)),
                         all_corners_observed_hypothesis=True, physical_paper_edge_identity_verified=False))
    return sorted(rows, key=lambda r: -r["contour_area_px"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-json", type=Path, required=True)
    p.add_argument("--long-side-mm", type=float)
    p.add_argument("--short-side-mm", type=float)
    args = p.parse_args()
    if (args.long_side_mm is None) != (args.short_side_mm is None):
        raise ValueError("both independently supplied physical dimensions required")
    if args.long_side_mm is not None and not (np.isfinite(args.long_side_mm) and np.isfinite(args.short_side_mm)
                                             and args.long_side_mm >= args.short_side_mm > 0):
        raise ValueError("finite positive ordered dimensions required")
    _, camera, _, _ = load_config()
    rows, sources = [], {}
    for frame, roi in ((1259, (260, 395, 130, 65)), (1655, (335, 390, 130, 70))):
        path = ROOT/f"recordings/2026-10-30_floor_board_intake_r01/decoded_15ae673c24484d119952ae391df611aa_f{frame:06d}.png"
        image = cv2.imread(str(path))
        if image is None or image.shape != (720, 1280, 3):
            raise ValueError("native source required")
        sources[str(path)] = digest(path)
        for threshold in (150, 170, 190, 210):
            quads = white_quads(image, roi, threshold)
            for quad in quads:
                if args.long_side_mm is not None:
                    poses = {}
                    for name, (width, depth) in {
                        "image_far_edge_long": (args.long_side_mm/1000, args.short_side_mm/1000),
                        "image_far_edge_short": (args.short_side_mm/1000, args.long_side_mm/1000)}.items():
                        world = [[0, 0, 0], [width, 0, 0], [width, depth, 0], [0, depth, 0]]
                        poses[name] = planar_floor_pose_candidates(quad["quad_xy"], world, camera)
                    quad["poses"] = poses
            rows.append(dict(frame=frame, threshold=threshold, roi_native_xywh=list(roi), quads=quads))
    sources[str(Path(__file__).resolve())] = digest(Path(__file__).resolve())
    report = dict(status="NATIVE_WHITE_PAPER_QUADS_NOT_APPROVED", primary_threshold=170,
                  paper_size_mm=[args.long_side_mm, args.short_side_mm],
                  metric_pose_computed=args.long_side_mm is not None, rows=rows, source_sha256=sources,
                  physical_metric_verified=False, usable_for_ffb=False)
    with args.output_json.open("x") as f:
        json.dump(report, f, indent=2, allow_nan=False)
        f.write("\n")
    for row in rows:
        print(row["frame"], row["threshold"], [r["quad_xy"] for r in row["quads"]])


if __name__ == "__main__":
    main()
