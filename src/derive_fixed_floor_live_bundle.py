#!/usr/bin/env python3
"""Saved native floor reference -> all IPPE hypotheses -> local L-key bundle.

Reuses the existing KB4-ray/IPPE solver. No intrinsic refit, distance labels,
cross-session reuse, solution selection, image writes, GPU, camera, ROS or FFB.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

import cv2
import numpy as np

from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_fixed_floor_candidate import COORDINATE_FRAME, SCHEMA
from cone_fixed_floor_live_load import bounded_regular_bytes, png_digest
from fisheye_intrinsic_calibration import Board, checked_roi, detect_board
from floor_reference_pose import planar_floor_pose_candidates
from prepare_fixed_floor_live_bundle import prepare


def measured(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"explicit finite {name} in [{low},{high}] required")
    return float(value)


def source(path):
    path = Path(path)
    match = re.fullmatch(r"decoded_([A-Za-z0-9_-]{1,128})_f([0-9]+)\.png", path.name)
    if match is None or int(match[2]) < 1 or path.name != f"decoded_{match[1]}_f{int(match[2]):06d}.png":
        raise ValueError("exact saved receiver session/frame PNG name required")
    hashed = png_digest(path)
    data = bounded_regular_bytes(path, 8*1024*1024)
    if hashlib.sha256(data).hexdigest() != hashed:
        raise ValueError("source changed while reading")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return dict(path=path, session=match[1], frame=int(match[2]), sha256=hashed, image=image)


def rectangle_references(spec_path, image_dir):
    payload = bounded_regular_bytes(spec_path, 512*1024)
    def invalid(value):
        raise ValueError("nonfinite reference JSON: "+value)
    spec = json.loads(payload, parse_constant=invalid)
    if not isinstance(spec, dict) or spec.get("schema") != "native_floor_rectangles_v1":
        raise ValueError("explicit native_floor_rectangles_v1 reference specification required")
    entries = spec.get("frames")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        raise ValueError("1..16 explicit reference frames required")
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("reference frame record required")
        filename = entry.get("file")
        if type(filename) is not str or Path(filename).name != filename:
            raise ValueError("PNG basename only; no path traversal")
        item = source(Path(image_dir)/filename)
        if item["sha256"] != entry.get("sha256"):
            raise ValueError("reference/image hash mismatch")
        points = entry.get("corners_native_xy")
        if np.iscomplexobj(points):
            raise ValueError("real native rectangle corners required")
        points = np.asarray(points, dtype=float)
        if (points.shape != (4, 2) or not np.isfinite(points).all()
                or np.any(points < [0, 0]) or np.any(points >= [640, 720])
                or not cv2.isContourConvex(points.astype(np.float32))
                or len(np.unique(points, axis=0)) != 4):
            raise ValueError("four ordered observed corners in native front-left lens required")
        sizes = entry.get("side_lengths_mm")
        if not isinstance(sizes, list) or len(sizes) != 2 or entry.get("side_assignment") != "both":
            raise ValueError("two explicit side lengths and side_assignment=both required")
        width, depth = [measured(v, "rectangle side (mm)", 1, 2000) for v in sizes]
        provenance = entry.get("coordinates_source")
        if type(provenance) is not str or not provenance.strip():
            raise ValueError("observed corner coordinate source required")
        assignments = [("as_listed", width, depth)]
        if width != depth:
            assignments.append(("swapped", depth, width))
        references = []
        for name, w, d in assignments:
            world = np.array([[0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0]], float)/1000
            references.append(dict(assignment=name, pixels=points, world=world,
                dimensions_mm=[w, d], coordinate_source=provenance))
        result.append(dict(item, references=references))
    return result, hashlib.sha256(payload).hexdigest()


def checkerboard_reference(path, square_mm, roi):
    item = source(path)
    roi = checked_roi(tuple(roi))
    if roi[0]+roi[2] > 640:
        raise ValueError("front-left lens ROI required")
    board = Board(square_mm=measured(square_mm, "square size (mm)", 1, 200))
    points, reason = detect_board(item["image"], board, roi)
    if points is None:
        raise ValueError("checkerboard withheld: "+reason+"; no rectangle fallback")
    return [dict(item, references=[dict(assignment="detected_grid", pixels=points,
        world=board.object_points.reshape(-1, 3), dimensions_mm=[board.square_mm],
        coordinate_source=reason, roi_native_xywh=list(roi))])]


def derive(items, settings, camera, *, board_thickness_mm=None, external_height_mm=None):
    """Keep each frame, dimension assignment and planar solution separately."""
    if not items or len(items) > 16 or len({p["session"] for p in items}) != 1:
        raise ValueError("one explicit session with 1..16 references required")
    if len({p["frame"] for p in items}) != len(items) or len({p["path"].parent.resolve() for p in items}) != 1:
        raise ValueError("unique source frames in one receiver output directory required")
    if board_thickness_mm is None and external_height_mm is None:
        raise ValueError("explicit board thickness and/or external floor height required; no default height")
    thickness = None if board_thickness_mm is None else measured(board_thickness_mm, "board thickness (mm)", 0, 100)/1000
    external = None if external_height_mm is None else measured(external_height_mm, "external lens height (mm)", 1, 4999)/1000
    heading = dict(path=settings["floor_candidate"], sha256=settings["floor_sha256"])
    models, reports = [], []
    for item in items:
        for reference in item["references"]:
            pose = planar_floor_pose_candidates(reference["pixels"], reference["world"], camera)
            record = dict(frame=item["frame"], assignment=reference["assignment"],
                corners_or_grid_native_xy=np.asarray(reference["pixels"]).tolist(),
                known_plane_points_m=np.asarray(reference["world"]).tolist(),
                dimensions_mm=reference["dimensions_mm"], coordinates_source=reference["coordinate_source"],
                pose=pose, exclusions=[])
            reports.append(record)
            for solution in pose["candidates"]:
                signed = solution["camera_height_above_floor_m"]
                if (not solution["all_reference_points_positive_depth"]
                        or not solution["all_projected_in_calibrated_domain"] or abs(signed) < 1e-9):
                    record["exclusions"].append(dict(solution=solution["solution_index"], reason="invalid_front_plane_geometry"))
                    continue
                normal = np.asarray(solution["up_optical"])*(1 if signed > 0 else -1)
                heights = []
                if thickness is not None:
                    heights.append(("image_plane_plus_thickness", abs(signed)+thickness))
                if external is not None:
                    heights.append(("external_height_image_normal", external))
                for origin, height in heights:
                    if not 0 < height < 5:
                        record["exclusions"].append(dict(solution=solution["solution_index"], height_source=origin,
                            reason="height_outside_model_domain"))
                        continue
                    models.append(dict(schema=SCHEMA,
                        name=f"f{item['frame']:06d}_{reference['assignment']}_s{solution['solution_index']}_{origin}",
                        session=item["session"], normal_optical=normal.tolist(), camera_to_floor_m=height,
                        coordinate_frame=COORDINATE_FRAME, heading_reference=heading,
                        evidence=[f"source PNG {item['path'].name} sha256={item['sha256']}",
                            "coordinate source: "+reference["coordinate_source"],
                            f"native KB4/IPPE solution {solution['solution_index']}; no solution selected",
                            f"board thickness input mm={board_thickness_mm}; external floor height input mm={external_height_mm}"],
                        assumptions=["operator confirms a rigid board lies flat and parallel to the same floor",
                            "image correspondences are observed hypotheses, not independently verified physical corners",
                            "camera/capture geometry is static within this session",
                            "external height with image normal is a separate control, not a fitted metric result",
                            "paper7 supplies heading convention only; yaw and base_link transform are not measured"],
                        invalidation_conditions=["session, camera mount, capture geometry or floor changes",
                            "board not rigid/flat/on floor, or image correspondence incorrect",
                            "physical distance or FFB authority requested"],
                        height_source=origin, printed_plane_height_m=abs(signed),
                        native_reprojection_rmse_px=solution["fit_native_rmse_px"],
                        role="unselected_planar_hypothesis", controlling_distance=False,
                        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False))
    if not models:
        raise ValueError("no front-plane hypotheses; model not exported")
    return dict(schema="explicit_floor_models_v1", session=items[0]["session"], heading_reference=heading,
                models=models), reports


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--references", type=Path, help="explicit native rectangle correspondences and PNG hashes")
    mode.add_argument("--checkerboard-image", type=Path, help="one saved PNG; complete native grid detection only")
    parser.add_argument("--image-dir", type=Path, help="rectangle PNG directory; defaults to references parent")
    parser.add_argument("--square-mm", type=float)
    parser.add_argument("--roi", type=int, nargs=4, help="explicit floor-board native XYWH; checkerboard mode only")
    parser.add_argument("--board-thickness-mm", type=float)
    parser.add_argument("--external-height-mm", type=float, help="independent input, not a fitted or verified height")
    parser.add_argument("--board-on-floor", action="store_true")
    parser.add_argument("--rigid-board", action="store_true")
    parser.add_argument("--static-camera", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.output_dir.exists():
        raise ValueError("new output directory required; existing evidence is never overwritten")
    if not (args.board_on_floor and args.rigid_board and args.static_camera):
        raise ValueError("explicit floor/rigid-board/static-camera confirmations required")
    code_dir = Path(__file__).resolve().parent
    sources = [args.config, Path(__file__).resolve(), *[code_dir/name for name in (
        "floor_reference_pose.py", "angular_fisheye_geometry.py", "fisheye_intrinsic_calibration.py",
        "prepare_fixed_floor_live_bundle.py", "cone_fixed_floor_live_load.py", "cone_fixed_floor_shadow.py",
        "cone_fixed_floor_candidate.py", "cone_distance_core.py")]]
    input_hashes = {str(p.resolve()): digest(p) for p in sources}
    settings, camera, _, _ = load_config(args.config)
    if digest(args.config) != input_hashes[str(args.config.resolve())]:
        raise ValueError("config changed while loading")
    root = code_dir.parent
    for name in ("camera", "floor"):
        input_hashes[str((root/settings[name+"_candidate"]).resolve())] = settings[name+"_sha256"]
    if args.references is not None:
        if args.square_mm is not None or args.roi is not None:
            raise ValueError("square size/ROI belong to checkerboard mode only")
        items, hashed = rectangle_references(args.references, args.image_dir or args.references.parent)
        input_hashes[str(args.references.resolve())] = hashed
    else:
        if args.image_dir is not None:
            raise ValueError("image directory belongs to rectangle mode only")
        if args.roi is None:
            raise ValueError("explicit floor-board ROI required; do not select a background wall board")
        items = checkerboard_reference(args.checkerboard_image, args.square_mm, args.roi)
    bundle, poses = derive(items, settings, camera, board_thickness_mm=args.board_thickness_mm,
                           external_height_mm=args.external_height_mm)
    input_hashes.update({str(p["path"].resolve()): p["sha256"] for p in items})
    args.output_dir.mkdir(parents=True, exist_ok=False)
    model_path = args.output_dir/"explicit_floor_models.json"
    with model_path.open("x") as stream:
        stream.write(json.dumps(bundle, indent=2, allow_nan=False)+"\n")
    payload = prepare(model_path, [p["path"] for p in items], args.config,
                      board_on_floor=True, rigid_board=True, static_camera=True)
    # A source change during fitting/export must not leave an acceptable model.
    if any(digest(Path(path)) != hashed for path, hashed in input_hashes.items()):
        raise ValueError("reference/config changed during derivation; no prepared model exported")
    report = dict(schema="saved_floor_derivation_v1", status="UNSELECTED_FLOOR_HYPOTHESES_NOT_APPROVED",
        session=bundle["session"], model_count=len(bundle["models"]), selected_solution=None,
        board_thickness_mm=args.board_thickness_mm, external_floor_height_mm=args.external_height_mm,
        source_sha256=input_hashes, poses=poses, fit_images_are_not_distance_holdout=True,
        original_images_modified=False, intrinsics_refitted=False, physical_metric_verified=False,
        floor_contact_verified=False, usable_for_ffb=False, published_to_ros=False)
    with (args.output_dir/"derivation_report.json").open("x") as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False)+"\n")
    with (args.output_dir/"prepared_floor.json").open("xb") as stream:
        stream.write(payload)
    print(f"Prepared {len(bundle['models'])} unselected comparison hypotheses: {args.output_dir/'prepared_floor.json'}")
    print("Press L only in the SAME receiver connection; this is NOT distance/physical approval.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, cv2.error) as exc:
        print("[ERROR]", exc)
        raise SystemExit(1)
