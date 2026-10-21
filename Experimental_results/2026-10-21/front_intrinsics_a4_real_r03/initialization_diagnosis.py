"""Explicit offline initial-K ablation, retaining all observations and screens.

This does not replace the provenance-frozen production fit implementation.
Quality equations mirror src/fisheye_intrinsic_calibration.py; parity is tested.
"""
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256,write_csv
from fisheye_intrinsic_calibration import Board,FRONT_ROI,IMAGE_SIZE,SCREEN,checked_corners,corner_rms,coverage,partition_views


def fit_from_initial(views,board,initial_K):
    views=[checked_corners(p,board) for p in views]
    train,validation=partition_views(views)
    if any(corner_rms(p,q)<SCREEN['duplicate_rms_px'] for i,p in enumerate(views) for q in views[:i]):
        raise ValueError('near-duplicate views')
    distribution=coverage([views[i] for i in train],FRONT_ROI)
    if (distribution['centre_bins']<SCREEN['centre_bins'] or
        min(distribution['span_fraction_x'],distribution['span_fraction_y'])<SCREEN['image_span_fraction']):
        raise ValueError('training image coverage insufficient')
    K=np.asarray(initial_K,np.float64).copy()
    if K.shape!=(3,3) or not np.isfinite(K).all() or min(K[0,0],K[1,1])<=0 or not np.array_equal(K[2],[0,0,1]):
        raise ValueError('valid initial intrinsic matrix required')
    D=np.zeros((4,1))
    flags=(cv2.fisheye.CALIB_USE_INTRINSIC_GUESS|cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC|
           cv2.fisheye.CALIB_CHECK_COND|cv2.fisheye.CALIB_FIX_SKEW)
    rms,K,D,rvecs,tvecs=cv2.fisheye.calibrate([board.object_points.copy() for _ in train],
        [views[i].reshape(1,-1,2) for i in train],IMAGE_SIZE,K,D,flags=flags,
        criteria=(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,100,1e-9))
    if not np.isfinite(K).all() or not np.isfinite(D).all() or min(K[0,0],K[1,1])<=0 or not math.isfinite(rms):
        raise ValueError('invalid solution')
    normals,per_view=[],[]
    for i,rvec,tvec in zip(train,rvecs,tvecs):
        rotation=cv2.Rodrigues(rvec)[0]
        normals.append(rotation[:,2])
        if np.min((board.object_points.reshape(-1,3)@rotation.T+tvec.reshape(3))[:,2])<=0:
            raise ValueError('board behind optical camera')
        projected=cv2.fisheye.projectPoints(board.object_points,rvec,tvec,K,D)[0].reshape(-1,2)
        per_view.append(dict(view_index=i,split='train',rms_px=float(np.sqrt(np.mean(np.sum((projected-views[i])**2,axis=1))))))
    for i in validation:
        undistorted=cv2.fisheye.undistortPoints(views[i].reshape(1,-1,2),K,D)
        ok,rvec,tvec=cv2.solvePnP(board.object_points.reshape(-1,3),undistorted.reshape(-1,2),
                               np.eye(3),None,flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            raise ValueError('held-out pose not solvable')
        rotation=cv2.Rodrigues(rvec)[0]
        if np.min((board.object_points.reshape(-1,3)@rotation.T+tvec.reshape(3))[:,2])<=0:
            raise ValueError('held-out board behind camera')
        projected=cv2.fisheye.projectPoints(board.object_points,rvec,tvec,K,D)[0].reshape(-1,2)
        per_view.append(dict(view_index=i,split='pose_validation_only',rms_px=float(np.sqrt(np.mean(np.sum((projected-views[i])**2,axis=1))))))
    spread=max(math.degrees(math.acos(float(np.clip(abs(a@b),0.,1.)))) for a in normals for b in normals)
    validation_rms=float(np.sqrt(np.mean([r['rms_px']**2 for r in per_view if r['split']=='pose_validation_only'])))
    normalized=cv2.fisheye.undistortPoints(np.concatenate([views[i] for i in train]).reshape(1,-1,2),K,D).reshape(-1,2)
    maximum_theta=float(np.max(np.arctan(np.linalg.norm(normalized,axis=1))))
    theta=np.linspace(0.,maximum_theta,1000)
    derivative=np.ones_like(theta)
    for i,coefficient in enumerate(D.ravel(),1):
        derivative+=(2*i+1)*coefficient*theta**(2*i)
    checks=dict(train_rms=rms<=SCREEN['train_rms_px'],validation_rms=validation_rms<=SCREEN['pose_validation_rms_px'],
        normal_diversity=spread>=SCREEN['normal_spread_deg'],centre_in_selected_lens=0<K[0,2]<640 and 0<K[1,2]<720,
        focal_ratio=.5<=K[0,0]/K[1,1]<=2.,monotonic_in_observed_train_angle=bool(np.all(derivative>0.)))
    checks={k:bool(v) for k,v in checks.items()}
    return dict(schema='offline_initial_K_diagnostic_candidate_v1',camera_model='opencv_fisheye_4coef',
        image_size=list(IMAGE_SIZE),roi_native_xywh=list(FRONT_ROI),selected_lens='front_left',board=vars(board),
        initial_K=np.asarray(initial_K).tolist(),initial_D=[0.]*4,K=K.tolist(),D=D.ravel().tolist(),
        flags=flags,opencv_version=cv2.__version__,train_indices=train,validation_indices=validation,
        per_view=per_view,calibration_rms_px=float(rms),pose_validation_rms_px=validation_rms,
        normal_spread_deg=spread,observed_train_max_theta_rad=maximum_theta,coverage=distribution,screen=SCREEN,checks=checks,
        pose_validation_refits_intrinsics=False,
        decision='DIAGNOSTIC_CANDIDATE_ONLY' if all(checks.values()) else 'REJECTED_DIAGNOSTIC_CANDIDATE',
        usable_for_ffb=False,physical_floor_distance_verified=False,camera_to_floor_extrinsics_measured=False)


def initial_angles(points,K):
    return np.degrees(np.linalg.norm((np.asarray(points)-K[:2,2])/[K[0,0],K[1,1]],axis=1))


def main():
    output=HERE/'initialization_diagnosis_r01'
    if output.exists():
        raise ValueError('no initialization diagnosis overwrite')
    path=HERE/'combined_candidate_r01/merged_observations.json'
    data=json.loads(path.read_text())
    assert all(data['prefit_checks'].values())
    sources={str(p):sha256(p) for p in (path,Path(__file__),HERE/'initialization_diagnosis_method.md',
        ROOT/'src/fisheye_intrinsic_calibration.py')}
    sources.update(data['source_sha256'])
    assert all(sha256(Path(p))==v for p,v in sources.items())
    f=640/math.pi
    original_K=np.array([[f,0,319.5],[0,f,359.5],[0,0,1.]])
    initial_K=original_K.copy()
    initial_K[1,2]=300.
    output.mkdir()
    angles=[]
    for r in data['selected_views']:
        a=initial_angles(r['corners_native'],original_K)
        b=initial_angles(r['corners_native'],initial_K)
        angles.append(dict(merged_index=r['merged_index'],session=r['session'],frame=r['source_frame'],
            split=r['split'],original_initial_max_angle_deg=float(a.max()),diagnostic_initial_max_angle_deg=float(b.max()),
            original_angles_at_or_above_90=int(np.count_nonzero(a>=90.))))
    write_csv(output/'initial_angle_audit.csv',angles)
    specification=dict(initial_K=initial_K.tolist(),changed_only='initial cy: 359.5 -> 300 px',
        original_fit_result='combined_candidate_r01/run_summary.json',all_views_retained=True,
        train_indices=data['train_indices'],validation_indices=data['validation_indices'],source_sha256=sources,
        no_initial_value_sweep=True,no_residual_based_pruning=True,production_settings_changed=False,usable_for_ffb=False)
    (output/'specification.json').write_text(json.dumps(specification,indent=2)+'\n')
    summary=dict(intrinsic_solver_attempted=True,all_views_retained=True,usable_for_ffb=False,source_sha256=sources,
        physical_output=False,production_settings_changed=False)
    try:
        candidate=fit_from_initial([r['corners_native'] for r in data['selected_views']],Board(**data['board']),initial_K)
        candidate.update(source_sha256=sources,merged_observations_sha256=sha256(path))
        (output/'intrinsics_diagnostic_candidate.json').write_text(json.dumps(candidate,indent=2)+'\n')
        per_view=[dict(r,session=data['selected_views'][r['view_index']]['session'],
                      source_frame=data['selected_views'][r['view_index']]['source_frame']) for r in candidate['per_view']]
        write_csv(output/'reprojection_by_view.csv',per_view)
        summary.update({k:candidate[k] for k in ('decision','calibration_rms_px','pose_validation_rms_px','normal_spread_deg','checks','K','D')})
    except (ValueError,RuntimeError,cv2.error) as error:
        summary.update(decision='DIAGNOSTIC_SOLVER_REJECTED',error_type=type(error).__name__,error=str(error))
    assert all(sha256(Path(p))==v for p,v in sources.items())
    (output/'run_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
