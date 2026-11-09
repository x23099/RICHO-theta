"""Prepare a portable, explicitly unverified camera-relative plane profile.

Use a metric rectangle in arbitrary local coordinates, not vehicle left/right.
No E fitting, mirror correction, hardware, ROS, network, or model approval.
"""
import argparse
import json
from pathlib import Path
import re

import numpy as np

from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_fixed_floor_live_load import bounded_regular_bytes, png_digest
from cone_motion_range import FLAGS, PROFILE_SCHEMA, parse_motion_profile
from floor_reference_pose import planar_floor_pose_candidates


def prepare(image, points_file, config, primary_solution):
    sha = png_digest(image)
    match = re.fullmatch(r"decoded_([a-zA-Z0-9]+)_f([0-9]+)\.png", Path(image).name)
    if not match:
        raise ValueError("decoded session/frame PNG basename required")
    data = json.loads(bounded_regular_bytes(points_file, 64*1024))
    if (data.get("schema") != "native_metric_rectangle_points_v1" or data.get("image_sha256") != sha
            or data.get("corner_order") != ["near_image_left", "near_image_right", "far_image_left", "far_image_right"]):
        raise ValueError("image-bound rectangle with explicit native image order required")
    width, depth = data["width_m"], data["depth_m"]
    if any(type(v) not in (int, float) or not np.isfinite(v) or v <= 0 for v in (width, depth)):
        raise ValueError("positive finite rectangle dimensions required")
    points = np.asarray(data["corners_native_xy"], float)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("exactly four finite floor points, no E fitting")
    settings, camera, _, _ = load_config(config)
    # Arbitrary right-handed local board axes, NOT measured base_link axes.
    world = np.array([[0., 0., 0.], [width, 0., 0.], [0., depth, 0.], [width, depth, 0.]])
    fit = planar_floor_pose_candidates(points, world, camera)
    models = [dict(id=f"ippe_{c['solution_index']}", up_optical=c["up_optical"],
        height_m=c["camera_height_above_floor_m"], native_rmse_px=c["fit_native_rmse_px"],
        solution_index=c["solution_index"]) for c in fit["candidates"] if c["geometry_consistent"]]
    primary = f"ippe_{primary_solution}"
    if primary not in {m["id"] for m in models}:
        raise ValueError("requested diagnostic solution is not above-floor/valid; no abs-height repair")
    result = dict(schema=PROFILE_SCHEMA, camera_sha256=settings["camera_sha256"],
        config_sha256=digest(config), image_size=[1280, 720], native_ray_basis="unmodified",
        metric="horizontal_camera_foot_range_m", primary_model=primary, models=models,
        source=dict(image_sha256=sha, image_file=Path(image).name, session=match[1], frame=int(match[2]),
                    points_sha256=digest(points_file), E_used=False),
        local_metric_rectangle=dict(width_m=width, depth_m=depth, corners_native_xy=points.tolist(),
            coordinate_frame="arbitrary_metric_board_NOT_vehicle_or_base_link"),
        mount_or_floor_tilt_compensated=False, cross_session_mount_verified=False, **FLAGS)
    parse_motion_profile(json.dumps(result).encode(), settings)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-image", type=Path, required=True)
    parser.add_argument("--floor-points", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--primary-solution", type=int, choices=(0, 1), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = prepare(args.reference_image, args.floor_points, args.config, args.primary_solution)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print("Prepared UNVERIFIED rigid-mount range profile:", args.output)


if __name__ == "__main__":
    main()
