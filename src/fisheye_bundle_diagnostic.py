"""Offline fisheye joint-fit diagnostic; never installed into the live pipeline.

Same OpenCV four-coefficient projection and unweighted pixel residuals, but a
SciPy trust-region joint update instead of alternating OpenCV recalibration.
The original fit and its provenance remain untouched. SciPy is optional and
needed only when this diagnostic module is explicitly imported.
"""
import math

import cv2
import numpy as np
import scipy
from scipy.optimize import least_squares
from scipy.sparse import coo_matrix

from fisheye_intrinsic_calibration import (Board, FRONT_ROI, IMAGE_SIZE, SCREEN,
    checked_corners, corner_rms, coverage, partition_views)


def grid_audit(points, board):
    p = checked_corners(points, board).reshape(board.inner_rows, board.inner_columns, 2)
    horizontal = p[:-1, 1:] - p[:-1, :-1]
    vertical = p[1:, :-1] - p[:-1, :-1]
    signed = horizontal[..., 0]*vertical[..., 1] - horizontal[..., 1]*vertical[..., 0]
    spacing = np.r_[np.linalg.norm(np.diff(p, axis=0), axis=2).ravel(),
                    np.linalg.norm(np.diff(p, axis=1), axis=2).ravel()]
    return dict(cell_orientation_consistent=bool(np.all(signed > 0) or np.all(signed < 0)),
                minimum_absolute_cell_area_px2=float(np.min(abs(signed))),
                minimum_adjacent_spacing_px=float(spacing.min()),
                median_adjacent_spacing_px=float(np.median(spacing)))


def checked_views(views, board):
    checked = [checked_corners(p, board) for p in views]
    train, validation = partition_views(checked)
    if any(corner_rms(p, q) < SCREEN['duplicate_rms_px'] for i, p in enumerate(checked) for q in checked[:i]):
        raise ValueError('near-duplicate views')
    for p in checked:
        a = grid_audit(p, board)
        if not a['cell_orientation_consistent'] or a['median_adjacent_spacing_px'] < SCREEN['min_grid_spacing_px']:
            raise ValueError('folded or undersized corner grid')
    distribution = coverage([checked[i] for i in train], FRONT_ROI)
    if (distribution['centre_bins'] < SCREEN['centre_bins'] or
        min(distribution['span_fraction_x'], distribution['span_fraction_y']) < SCREEN['image_span_fraction']):
        raise ValueError('training image coverage insufficient')
    return checked, train, validation, distribution


class PixelBundle:
    """Shared log-fx/log-fy/cx/cy/k1..k4, then 6 centred-board pose params/view.

    Pose order is Rodrigues[3], tx, ty, log(tz). Analytic OpenCV Jacobians are
    transformed by the chain rule and assembled sparsely. No robust loss,
    image rejection or validation data are used in this objective.
    """
    def __init__(self, points, object_points):
        self.points = [np.asarray(p, float).reshape(-1, 2) for p in points]
        self.objects = np.asarray(object_points, float).reshape(1, -1, 3)
        if not self.points or any(p.shape != (self.objects.shape[1], 2) for p in self.points):
            raise ValueError('matching complete object and image grids required')
        self.count = self.objects.shape[1]
        self.n = 8 + 6*len(self.points)
        self.last_x = None
        self.last_residual = None
        self.last_jacobian = None
        self.trace = []

    @staticmethod
    def camera(x):
        fx, fy = np.exp(x[:2])
        return np.array([[fx, 0., x[2]], [0., fy, x[3]], [0., 0., 1.]]), np.asarray(x[4:8]).reshape(4, 1)

    @staticmethod
    def pose(x, i):
        p = x[8+6*i:14+6*i]
        return p[:3].reshape(3, 1), np.array([p[3], p[4], np.exp(p[5])]).reshape(3, 1)

    def evaluate(self, x):
        if self.last_x is not None and np.array_equal(x, self.last_x):
            return
        K, D = self.camera(x)
        residuals, row_indices, column_indices, values = [], [], [], []
        width = 2*self.count
        for i, points in enumerate(self.points):
            rvec, tvec = self.pose(x, i)
            projected, J = cv2.fisheye.projectPoints(self.objects, rvec, tvec, K, D)
            residuals.append((projected.reshape(-1, 2) - points).ravel())
            shared = J[:, :8].copy()
            shared[:, 0] *= K[0, 0]
            shared[:, 1] *= K[1, 1]
            pose = J[:, 8:14].copy()
            pose[:, 5] *= tvec[2, 0]
            block = np.hstack([shared, pose])
            columns = np.r_[np.arange(8), np.arange(8+6*i, 14+6*i)]
            row_indices.append(np.repeat(np.arange(width)+width*i, 14))
            column_indices.append(np.tile(columns, width))
            values.append(block.ravel())
        residual = np.concatenate(residuals)
        if not np.isfinite(residual).all() or not np.isfinite(np.concatenate(values)).all():
            raise ValueError('nonfinite projection or derivative')
        self.last_residual = residual
        self.last_jacobian = coo_matrix((np.concatenate(values),
            (np.concatenate(row_indices), np.concatenate(column_indices))), shape=(width*len(self.points), self.n)).tocsr()
        self.last_x = np.asarray(x).copy()
        self.trace.append(dict(evaluation=len(self.trace), pixel_rms=float(np.sqrt(np.mean(residual.reshape(-1, 2)**2)*2))))

    def residual(self, x):
        self.evaluate(x)
        return self.last_residual

    def jacobian(self, x):
        self.evaluate(x)
        return self.last_jacobian


def initial_parameters(views, board, initial_K):
    K = np.asarray(initial_K, float).copy()
    if (K.shape != (3, 3) or not np.isfinite(K).all() or min(K[0, 0], K[1, 1]) <= 0
        or not np.array_equal(K[2], [0, 0, 1]) or K[0, 1] != 0):
        raise ValueError('finite zero-skew initial intrinsic matrix required')
    # Count=0 computes initial extrinsics without the unstable intrinsic update.
    rms, _, _, rvecs, tvecs = cv2.fisheye.calibrate([board.object_points.copy() for _ in views],
        [p.reshape(1, -1, 2) for p in views], IMAGE_SIZE, K.copy(), np.zeros((4, 1)), flags=15,
        criteria=(cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 0, 1e-9))
    centre = board.object_points.reshape(-1, 3).mean(axis=0)
    poses = []
    for r, t in zip(rvecs, tvecs):
        t = t.reshape(3) + cv2.Rodrigues(r)[0]@centre
        if t[2] <= 0:
            raise ValueError('initial board centre behind camera')
        poses.extend([*r.ravel(), t[0], t[1], math.log(t[2])])
    x = np.r_[np.log([K[0, 0], K[1, 1]]), K[0, 2], K[1, 2], np.zeros(4), poses]
    return x, board.object_points - centre.reshape(1, 1, 3), float(rms)


def fit_bundle(views, board, initial_K, *, max_nfev=300):
    """Fit train only; same fixed split and quality thresholds as original core."""
    checked, train, validation, distribution = checked_views(views, board)
    x0, objects, initial_rms = initial_parameters([checked[i] for i in train], board, initial_K)
    bundle = PixelBundle([checked[i] for i in train], objects)
    # Broad finite bounds prevent exponential overflow, not a measured optical prior.
    lower = np.full_like(x0, -np.inf)
    upper = np.full_like(x0, np.inf)
    lower[:4] = [math.log(1.), math.log(1.), 0., 0.]
    upper[:4] = [math.log(10000.), math.log(10000.), 640., 720.]
    lower[13::6] = math.log(1e-6)
    upper[13::6] = math.log(1000.)
    result = least_squares(bundle.residual, x0, jac=bundle.jacobian, method='trf',
        x_scale='jac', loss='linear', bounds=(lower, upper), tr_solver='lsmr',
        tr_options=dict(regularize=True, atol=1e-12, btol=1e-12, maxiter=2000),
        max_nfev=max_nfev, ftol=1e-9, xtol=1e-9, gtol=1e-9)
    K, D = bundle.camera(result.x)
    per_view, normals, residual_vectors = [], [], []
    all_front = True
    pose_conditions = []
    for local, i in enumerate(train):
        rvec, tvec = bundle.pose(result.x, local)
        rotation = cv2.Rodrigues(rvec)[0]
        camera_points = objects.reshape(-1, 3)@rotation.T + tvec.reshape(3)
        all_front &= bool(np.all(camera_points[:, 2] > 0))
        projected, jac = cv2.fisheye.projectPoints(objects, rvec, tvec, K, D)
        residual = projected.reshape(-1, 2) - checked[i]
        residual_vectors.append(dict(view_index=i, residual_px=residual.tolist()))
        singular = np.linalg.svd(jac[:, 8:14], compute_uv=False)
        condition = float(singular[0]/singular[-1]) if singular[-1] > 0 else float('inf')
        pose_conditions.append(condition)
        per_view.append(dict(view_index=i, split='train', rms_px=float(np.sqrt(np.mean(np.sum(residual**2, axis=1)))),
            minimum_camera_z_m=float(camera_points[:, 2].min()), pose_jacobian_condition=condition))
        normals.append(rotation[:, 2])
    # Evaluate the same undistortPoints + ITERATIVE solvePnP validation as core.
    for i in validation:
        undistorted = cv2.fisheye.undistortPoints(checked[i].reshape(1, -1, 2), K, D)
        ok, rvec, tvec = cv2.solvePnP(objects.reshape(-1, 3), undistorted.reshape(-1, 2),
                                   np.eye(3), None, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            raise ValueError('held-out pose not solvable; no view removal')
        camera_points = objects.reshape(-1, 3)@cv2.Rodrigues(rvec)[0].T+tvec.reshape(3)
        all_front &= bool(np.all(camera_points[:, 2] > 0))
        projected, jac = cv2.fisheye.projectPoints(objects, rvec, tvec, K, D)
        residual = projected.reshape(-1, 2) - checked[i]
        residual_vectors.append(dict(view_index=i, residual_px=residual.tolist()))
        per_view.append(dict(view_index=i, split='pose_validation_only', rms_px=float(np.sqrt(np.mean(np.sum(residual**2, axis=1)))),
            minimum_camera_z_m=float(camera_points[:, 2].min()), pose_jacobian_condition=None))
    train_rms = float(np.sqrt(np.mean([r['rms_px']**2 for r in per_view if r['split']=='train'])))
    validation_rms = float(np.sqrt(np.mean([r['rms_px']**2 for r in per_view if r['split']=='pose_validation_only'])))
    spread = max(math.degrees(math.acos(float(np.clip(abs(a@b), 0., 1.)))) for a in normals for b in normals)
    normalized = cv2.fisheye.undistortPoints(np.concatenate([checked[i] for i in train]).reshape(1, -1, 2), K, D).reshape(-1, 2)
    theta_max = float(np.max(np.arctan(np.linalg.norm(normalized, axis=1))))
    theta = np.linspace(0., theta_max, 1000)
    derivative = np.ones_like(theta)
    for i, coefficient in enumerate(D.ravel(), 1):
        derivative += (2*i+1)*coefficient*theta**(2*i)
    checks = dict(train_rms=train_rms <= SCREEN['train_rms_px'], validation_rms=validation_rms <= SCREEN['pose_validation_rms_px'],
        normal_diversity=spread >= SCREEN['normal_spread_deg'], centre_in_selected_lens=0 < K[0, 2] < 640 and 0 < K[1, 2] < 720,
        focal_ratio=.5 <= K[0, 0]/K[1, 1] <= 2., monotonic_in_observed_train_angle=bool(np.all(derivative>0)),
        optimizer_converged=bool(result.success), all_points_in_front=all_front,
        train_pose_condition_below_1e6=max(pose_conditions)<1e6)
    checks = {k:bool(v) for k,v in checks.items()}
    return dict(schema='offline_joint_fisheye_diagnostic_v1', camera_model='opencv_fisheye_4coef',
        selected_lens='front_left', image_size=list(IMAGE_SIZE), roi_native_xywh=list(FRONT_ROI), board=vars(board),
        K=K.tolist(), D=D.ravel().tolist(), initial_K=np.asarray(initial_K).tolist(), initial_D=[0.]*4,
        initial_train_rms_px=initial_rms, calibration_rms_px=train_rms, pose_validation_rms_px=validation_rms,
        train_indices=train, validation_indices=validation, coverage=distribution, normal_spread_deg=spread,
        observed_train_max_theta_rad=theta_max, train_pose_condition_max=max(pose_conditions),
        optimizer=dict(method='scipy_trf_joint', loss='linear', x_scale='jac', max_nfev=max_nfev,
            status=int(result.status), success=bool(result.success), message=str(result.message), nfev=int(result.nfev),
            njev=int(result.njev), cost=float(result.cost), optimality=float(result.optimality)),
        checks=checks, screen=SCREEN, per_view=per_view, per_view_residuals=residual_vectors, trace=bundle.trace,
        scipy_version=scipy.__version__, opencv_version=cv2.__version__, pose_validation_refits_intrinsics=False,
        all_views_retained=True, robust_loss_used=False, original_pixels_modified=False,
        decision='JOINT_DIAGNOSTIC_CANDIDATE_ONLY' if all(checks.values()) else 'REJECTED_JOINT_DIAGNOSTIC',
        usable_for_ffb=False, physical_floor_distance_verified=False, camera_to_floor_extrinsics_measured=False)
