"""Offline planar-reference pose candidates. No background lines or ROS/TF.

Native angular KB4 pixels -> unit rays -> normalized perspective points ->
OpenCV IPPE. Preserve both planar solutions; no automatic physical approval,
height fitting, cone-distance labels, or transfer to another recording.
"""
import cv2
import numpy as np

from angular_fisheye_geometry import project, unproject
from fisheye_floor_geometry import checked_transform


def planar_floor_pose_candidates(native_pixels, floor_points_m, camera):
    """Floor axes x-forward/y-left/z-up, optical x-right/y-down/z-forward.

    All floor points must be known corresponding points with z=0 in ONE
    static camera geometry. The caller, not this solver, must establish that
    physical condition. Calibration points are NOT evaluation holdout points.
    """
    if np.iscomplexobj(native_pixels) or np.iscomplexobj(floor_points_m):
        raise ValueError("real matching floor references required")
    pixels = np.asarray(native_pixels, np.float64)
    world = np.asarray(floor_points_m, np.float64)
    if (pixels.ndim != 2 or pixels.shape[1] != 2 or len(pixels) < 4
            or world.shape != (len(pixels), 3) or not np.isfinite(pixels).all()
            or not np.isfinite(world).all() or not np.allclose(world[:, 2], 0, atol=1e-12, rtol=0)
            or len(np.unique(world, axis=0)) != len(world)
            or len(np.unique(pixels, axis=0)) != len(pixels)
            or np.linalg.matrix_rank(world[:, :2]-world[:, :2].mean(axis=0)) < 2
            or np.linalg.matrix_rank(pixels-pixels.mean(axis=0)) < 2):
        raise ValueError("at least four distinct noncollinear planar z=0 correspondences required")
    rays, valid = unproject(pixels, camera, image_size=(1280, 720))
    if not valid.all() or np.any(rays[:, 2] <= 1e-6):
        raise ValueError("all points must lie in the calibrated front perspective hemisphere")
    normalized = np.ascontiguousarray(rays[:, :2]/rays[:, 2, None])
    result = cv2.solvePnPGeneric(np.ascontiguousarray(world), normalized, np.eye(3), None,
                                 flags=cv2.SOLVEPNP_IPPE)
    candidates = []
    for index, (rvec, tvec) in enumerate(zip(result[1], result[2])):
        rotation = cv2.Rodrigues(rvec)[0]
        translation = np.asarray(tvec, float).reshape(3)
        optical = world @ rotation.T + translation
        transform = np.eye(4)
        transform[:3, :3] = rotation.T
        transform[:3, 3] = -rotation.T @ translation
        transform = checked_transform(transform)
        uv, projected = project(optical, camera)
        all_projected = bool(projected.all())
        rms = float(np.sqrt(np.mean(np.sum((uv-pixels)**2, axis=1)))) if all_projected else None
        positive_depth = bool(np.all(optical[:, 2] > 0))
        above = bool(transform[2, 3] > 0)
        candidates.append(dict(solution_index=index, transform_floor_from_optical=transform.tolist(),
            camera_position_floor_m=transform[:3, 3].tolist(), up_optical=rotation[:, 2].tolist(),
            camera_height_above_floor_m=float(transform[2, 3]), fit_native_rmse_px=rms,
            all_projected_in_calibrated_domain=all_projected,
            all_reference_points_positive_depth=positive_depth, camera_above_floor=above,
            geometry_consistent=all_projected and positive_depth and above,
            physical_transform_independently_measured=False, usable_for_ffb=False))
    return dict(schema="offline_planar_floor_ippe_diagnostic_v1", method="native_KB4_rays_then_IPPE",
                point_count=len(world), candidates=candidates, solution_count=len(candidates),
                selected_solution=None, intrinsics_refitted=False, background_lines_used=False,
                caller_supplied_floor_correspondence_required=True,
                physical_metric_verified=False, published_to_ros=False, usable_for_ffb=False)
