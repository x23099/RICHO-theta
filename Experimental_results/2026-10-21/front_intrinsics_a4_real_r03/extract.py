"""Native r03 checkerboard observations; no fitting or physical output."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/'src'))
from cone_dataset import read_csv, write_csv, sha256
from fisheye_intrinsic_calibration import Board, IMAGE_SIZE, FRONT_ROI, SCREEN, checked_corners, corner_rms, coverage, partition_views


def inspect(image, board):
    if image.shape != (720,1280,3) or image.dtype != np.uint8:
        raise ValueError('native full frame required')
    found, corners = cv2.findChessboardCornersSB(cv2.cvtColor(image[:,:640], cv2.COLOR_BGR2GRAY),
        (board.inner_columns,board.inner_rows), flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    row = dict(detected=bool(found), corners_native=None, centre_x=None, centre_y=None,
               median_spacing_px=None, eligible=False, reason='board_not_found')
    if not found:
        return row
    points = corners.reshape(-1,2).astype(float)
    row.update(corners_native=points.tolist(), centre_x=float(points[:,0].mean()), centre_y=float(points[:,1].mean()))
    try:
        checked_corners(points, board)
    except ValueError:
        return dict(row, reason='roi_edge_or_invalid_grid')
    grid = points.reshape(board.inner_rows,board.inner_columns,2)
    spacing = np.r_[np.linalg.norm(np.diff(grid,axis=0),axis=2).ravel(),
                    np.linalg.norm(np.diff(grid,axis=1),axis=2).ravel()]
    row['median_spacing_px'] = float(np.median(spacing))
    if row['median_spacing_px'] < SCREEN['min_grid_spacing_px']:
        return dict(row, reason='grid_too_small')
    return dict(row, eligible=True, reason='handheld_candidate_needs_native_review')


def fields(rows):
    return list(dict.fromkeys(k for r in rows for k in r))


def main():
    output = HERE/'extraction_r01'
    if output.exists():
        raise ValueError('no extraction overwrite')
    intake = json.loads((HERE/'intake_summary.json').read_text())
    session = Path(intake['session'])
    board_spec = ROOT/'Experimental_results/2026-10-19/fisheye_intrinsic_target_a4_r01/board_spec.json'
    board = Board(**json.loads(board_spec.read_text())['board'])
    assert board.square_mm == 20.
    reference_path = HERE.parent/'front_intrinsics_a4_real_r02/raw_samples/raw_f000472.png'
    sources = {str(p):sha256(p) for p in (session/'raw.avi', session/'metadata.json', session/'detections.csv',
        board_spec, reference_path, HERE/'method.md', Path(__file__), ROOT/'src/fisheye_intrinsic_calibration.py')}
    reference = cv2.imread(str(reference_path))
    assert reference.shape == (720,1280,3)
    frames = read_csv(session/'detections.csv')
    output.mkdir()
    (output/'raw_frames').mkdir()
    attempts, views, signal, manifest = [], [], [], []
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(str(session/'raw.avi'))
    try:
        for i, original in enumerate(frames,1):
            ok, image = cap.read()
            assert ok and image.shape == (720,1280,3)
            difference = float(np.mean(cv2.absdiff(image,reference)))
            no_signal = difference <= 1.0
            signal.append(dict(frame=i,time_sec=float(original['time_sec']),reference_mae=difference,no_signal_reference_match=no_signal))
            if (i-1)%5:
                continue
            r = inspect(image,board) if not no_signal else dict(detected=False,corners_native=None,
                centre_x=None,centre_y=None,median_spacing_px=None,eligible=False,reason='no_signal_reference')
            r.update(frame=i,time_sec=float(original['time_sec']),retained=False)
            if r['eligible']:
                points = np.asarray(r['corners_native'])
                nearest = min((corner_rms(points,np.asarray(v['corners_native'])) for v in views),default=None)
                r['nearest_prior_pose_rms_px'] = nearest
                if nearest is not None and nearest < SCREEN['duplicate_rms_px']:
                    r['reason'] = 'near_duplicate_pose'
                else:
                    file = output/'raw_frames'/f'raw_f{i:06d}.png'
                    assert cv2.imwrite(str(file),image)
                    assert np.array_equal(cv2.imread(str(file)),image)
                    r.update(retained=True,retained_index=len(views),native_png=str(file.relative_to(output)),
                             png_sha256=sha256(file),decoded_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest())
                    views.append(r.copy())
                    manifest.append(dict(file=str(file.relative_to(HERE)),session=session.name,frame=i,
                        time_sec=r['time_sec'],png_sha256=r['png_sha256'],decoded_bgr_sha256=r['decoded_bgr_sha256'],image_edited=False))
            attempts.append(r)
            if len(attempts)%50 == 0:
                print('sampled',len(attempts),'/',len(range(1,len(frames)+1,5)),'retained',len(views),flush=True)
        assert not cap.read()[0]
    finally:
        cap.release()
    assert all(sha256(Path(p))==v for p,v in sources.items())
    train, validation = partition_views(views) if len(views)>=20 else ([],[])
    train_coverage = coverage([np.asarray(views[i]['corners_native']) for i in train],FRONT_ROI) if train else None
    result = dict(schema='single_fisheye_native_corners_v1',image_size=list(IMAGE_SIZE),roi_native_xywh=list(FRONT_ROI),
        selected_lens='front_left',board=vars(board),source_sha256=sources,frames_decoded=len(frames),sample_every=5,
        attempts=attempts,retained_views=views,train_indices=train,validation_indices=validation,
        train_only_coverage=train_coverage,all_retained_coverage=coverage([np.asarray(v['corners_native']) for v in views],FRONT_ROI) if views else None,
        source_pixels_edited=False,usable_for_ffb=False)
    (output/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    csv_rows = [dict(r,corners_native=json.dumps(r['corners_native'])) for r in attempts]
    write_csv(output/'attempts.csv',csv_rows,fields=fields(csv_rows))
    write_csv(output/'raw_frame_manifest.csv',manifest,fields=fields(manifest))
    write_csv(output/'signal_audit.csv',signal)
    summary = dict(retained_views=len(views),attempts=len(attempts),counts=dict(Counter(r['reason'] for r in attempts)),
        no_signal_reference_matched_frames=sum(r['no_signal_reference_match'] for r in signal),
        train_only_coverage=train_coverage,all_retained_coverage=result['all_retained_coverage'],
        intrinsic_solver_attempted=False,source_files_verified=True,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
