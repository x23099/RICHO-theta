"""Offline, single-lens OpenCV fisheye calibration candidates only.

K uses full native1280x720 coordinates. Board poses are NOT camera-to-floor TF.
No model here is automatically installed, published or used for physical output.
"""
from dataclasses import dataclass
import math

import cv2
import numpy as np

IMAGE_SIZE = (1280, 720)
FRONT_ROI = (0, 0, 640, 720)
SCREEN = dict(min_views=20, duplicate_rms_px=12., min_grid_spacing_px=8.,
              train_rms_px=1., pose_validation_rms_px=1.5, centre_bins=4,
              image_span_fraction=.35, normal_spread_deg=15.)


@dataclass(frozen=True)
class Board:
    inner_columns: int = 9
    inner_rows: int = 6
    square_mm: float = 30.

    def __post_init__(self):
        if (type(self.inner_columns) is not int or type(self.inner_rows) is not int
                or min(self.inner_columns, self.inner_rows) < 3 or max(self.inner_columns, self.inner_rows) > 30
                or not math.isfinite(self.square_mm) or not 1 <= self.square_mm <= 200):
            raise ValueError("valid board inner corner dimensions and measured square size required")

    @property
    def count(self):
        return self.inner_columns*self.inner_rows

    @property
    def object_points(self):
        p = np.zeros((1, self.count, 3), np.float64)
        p[0, :, :2] = np.mgrid[0:self.inner_columns, 0:self.inner_rows].T.reshape(-1, 2)*(self.square_mm/1000.)
        return p


def checked_roi(roi):
    if len(roi) != 4 or any(type(v) is not int for v in roi):
        raise ValueError("integer native xywh ROI required")
    x, y, w, h = roi
    if min(x, y) < 0 or min(w, h) < 40 or x+w > IMAGE_SIZE[0] or y+h > IMAGE_SIZE[1]:
        raise ValueError("ROI must fit native image")
    return x, y, w, h


def checked_corners(points, board, roi=FRONT_ROI):
    if np.iscomplexobj(points):
        raise ValueError("real native corner coordinates required")
    p = np.asarray(points, np.float64)
    if p.shape != (board.count, 2) or not np.isfinite(p).all():
        raise ValueError("complete finite native corner grid required")
    x, y, w, h = checked_roi(roi)
    if np.any(p < [x+3, y+3]) or np.any(p > [x+w-4, y+h-4]):
        raise ValueError("corner grid crosses selected lens ROI margin")
    return p.copy()


def detect_board(image, board, roi=FRONT_ROI):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("unedited native1280x720 uint8 BGR required")
    x, y, w, h = checked_roi(roi)
    gray = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
    found, corners = cv2.findChessboardCornersSB(gray, (board.inner_columns, board.inner_rows),
                                               flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not found:
        return None, "board_not_found"
    points = corners.reshape(-1, 2).astype(float)+[x, y]
    try:
        points = checked_corners(points, board, roi)
    except ValueError:
        return None, "roi_edge_or_invalid_grid"
    grid = points.reshape(board.inner_rows, board.inner_columns, 2)
    distances = np.r_[np.linalg.norm(np.diff(grid, axis=0), axis=2).ravel(),
                      np.linalg.norm(np.diff(grid, axis=1), axis=2).ravel()]
    if float(np.median(distances)) < SCREEN["min_grid_spacing_px"]:
        return None, "grid_too_small"
    return points, "board_detected_not_human_verified"


def corner_rms(a, b):
    """Grid symmetry is not a different calibration view."""
    return min(float(np.sqrt(np.mean(np.sum((a-b)**2, axis=1)))),
               float(np.sqrt(np.mean(np.sum((a-b[::-1])**2, axis=1)))))


def partition_views(views):
    if len(views) < SCREEN["min_views"]:
        raise ValueError("at least 20 distinct complete views required; no fit performed")
    train = [i for i in range(len(views)) if i % 5 != 4]
    validation = [i for i in range(len(views)) if i % 5 == 4]
    return train, validation


def coverage(views, roi):
    x, y, w, h = checked_roi(roi)
    centres = np.asarray([np.mean(p, axis=0) for p in views])
    bins = np.floor((centres-[x, y])/[w, h]*3).astype(int)
    all_points = np.concatenate(views)
    return dict(centre_bins=len({tuple(p) for p in bins}),
                span_fraction_x=float(np.ptp(all_points[:, 0])/w),
                span_fraction_y=float(np.ptp(all_points[:, 1])/h),
                observed_pixel_min=all_points.min(axis=0).tolist(), observed_pixel_max=all_points.max(axis=0).tolist())


def fit_candidate(views, board, roi=FRONT_ROI):
    """Fit train intrinsics only; validation poses are solved with fixed K,D."""
    roi = checked_roi(roi)
    views = [checked_corners(p, board, roi) for p in views]
    train, validation = partition_views(views)
    # Also reject fabricated/duplicated extracted observations at fit time.
    if any(corner_rms(p, q) < SCREEN["duplicate_rms_px"] for i, p in enumerate(views) for q in views[:i]):
        raise ValueError("near-duplicate views; do not count repeated frames as independent poses")
    c = coverage([views[i] for i in train], roi)
    if (c["centre_bins"] < SCREEN["centre_bins"] or
            min(c["span_fraction_x"], c["span_fraction_y"]) < SCREEN["image_span_fraction"]):
        raise ValueError("training image coverage insufficient; no fit performed")
    x, y, w, h = roi
    f = min(w, h)/math.pi
    K = np.array([[f, 0., x+(w-1)/2], [0., f, y+(h-1)/2], [0., 0., 1.]])
    D = np.zeros((4, 1))
    flags = (cv2.fisheye.CALIB_USE_INTRINSIC_GUESS | cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC
             | cv2.fisheye.CALIB_CHECK_COND | cv2.fisheye.CALIB_FIX_SKEW)
    obj = [board.object_points.copy() for _ in train]
    images = [views[i].reshape(1, -1, 2) for i in train]
    rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(obj, images, IMAGE_SIZE, K, D, flags=flags,
        criteria=(cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-9))
    if (not np.isfinite(K).all() or not np.isfinite(D).all() or min(K[0, 0], K[1, 1]) <= 0
            or not math.isfinite(rms)):
        raise ValueError("nonfinite or nonpositive intrinsic solution")
    normals, pose_checks = [], []
    for i, rvec, tvec in zip(train, rvecs, tvecs):
        rotation = cv2.Rodrigues(rvec)[0]
        normals.append(rotation[:, 2])
        if np.min((board.object_points.reshape(-1, 3) @ rotation.T + tvec.reshape(3))[:, 2]) <= 0:
            raise ValueError("board behind optical camera")
        projected = cv2.fisheye.projectPoints(board.object_points, rvec, tvec, K, D)[0].reshape(-1, 2)
        pose_checks.append(dict(view_index=i, split="train", rms_px=float(np.sqrt(np.mean(np.sum((projected-views[i])**2, axis=1))))))
    for i in validation:
        undistorted = cv2.fisheye.undistortPoints(views[i].reshape(1, -1, 2), K, D)
        ok, rvec, tvec = cv2.solvePnP(board.object_points.reshape(-1, 3), undistorted.reshape(-1, 2),
                                    np.eye(3), None, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            raise ValueError("held-out pose not solvable; do not discard and refit")
        rotation = cv2.Rodrigues(rvec)[0]
        if np.min(board.object_points.reshape(-1, 3) @ rotation.T + tvec.reshape(3), axis=0)[2] <= 0:
            raise ValueError("held-out board behind camera")
        projected = cv2.fisheye.projectPoints(board.object_points, rvec, tvec, K, D)[0].reshape(-1, 2)
        pose_checks.append(dict(view_index=i, split="pose_validation_only", rms_px=float(np.sqrt(np.mean(np.sum((projected-views[i])**2, axis=1))))))
    spread = max(math.degrees(math.acos(float(np.clip(abs(a @ b), 0., 1.)))) for a in normals for b in normals)
    validation_rms = float(np.sqrt(np.mean([r["rms_px"]**2 for r in pose_checks if r["split"] == "pose_validation_only"])))
    # Only the training observations define the angular region used to screen D.
    normalized = cv2.fisheye.undistortPoints(np.concatenate([views[i] for i in train]).reshape(1, -1, 2), K, D).reshape(-1, 2)
    maximum_theta = float(np.max(np.arctan(np.linalg.norm(normalized, axis=1))))
    theta = np.linspace(0., maximum_theta, 1000)
    derivative = np.ones_like(theta)
    for j, coefficient in enumerate(D.ravel(), 1):
        derivative += (2*j+1)*coefficient*theta**(2*j)
    checks = dict(train_rms=rms <= SCREEN["train_rms_px"], validation_rms=validation_rms <= SCREEN["pose_validation_rms_px"],
        normal_diversity=spread >= SCREEN["normal_spread_deg"],
        centre_in_selected_lens=x < K[0, 2] < x+w and y < K[1, 2] < y+h,
        focal_ratio=.5 <= K[0, 0]/K[1, 1] <= 2., monotonic_in_observed_train_angle=bool(np.all(derivative > 0.)))
    checks = {key: bool(value) for key, value in checks.items()}
    return dict(schema="offline_opencv_fisheye_candidate_v1", camera_model="opencv_fisheye_4coef",
        image_size=list(IMAGE_SIZE), selected_lens="front_left", roi_native_xywh=list(roi), K=K.tolist(), D=D.ravel().tolist(),
        flags=int(flags), opencv_version=cv2.__version__, board=vars(board), train_indices=train, validation_indices=validation,
        pose_validation_refits_intrinsics=False, calibration_rms_px=float(rms), pose_validation_rms_px=validation_rms,
        normal_spread_deg=spread, observed_train_max_theta_rad=maximum_theta,
        coverage=c, per_view=pose_checks, screen=SCREEN, checks=checks,
        decision="CANDIDATE_ONLY" if all(checks.values()) else "REJECTED_CANDIDATE", usable_for_ffb=False,
        physical_floor_distance_verified=False, camera_to_floor_extrinsics_measured=False)
