"""r02 native extraction with explicit stationary-grid exclusion and signal audit."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from fisheye_intrinsic_calibration import Board,FRONT_ROI,IMAGE_SIZE,SCREEN,checked_corners,corner_rms,coverage,partition_views
from cone_dataset import read_csv,write_csv,sha256

EXCLUDED_RECT=(195,235,70,85)


def inspect(image,board):
    if image.shape!=(720,1280,3) or image.dtype!=np.uint8:
        raise ValueError('native frame required')
    found,corners=cv2.findChessboardCornersSB(cv2.cvtColor(image[:,:640],cv2.COLOR_BGR2GRAY),
        (board.inner_columns,board.inner_rows),flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    row=dict(detected=bool(found),reason='board_not_found',corners_native=None,centre_x=None,centre_y=None,
             median_spacing_px=None,excluded_fixed_window=False,eligible=False)
    if not found:
        return row
    p=corners.reshape(-1,2).astype(float)
    row.update(corners_native=p.tolist(),centre_x=float(p[:,0].mean()),centre_y=float(p[:,1].mean()))
    x,y,w,h=EXCLUDED_RECT
    if np.all((p>=[x,y])&(p<=[x+w,y+h])):
        return dict(row,excluded_fixed_window=True,reason='stationary_window_grid_or_overlap')
    try:
        checked_corners(p,board)
    except ValueError:
        return dict(row,reason='roi_edge_or_invalid_grid')
    grid=p.reshape(board.inner_rows,board.inner_columns,2)
    d=np.r_[np.linalg.norm(np.diff(grid,axis=0),axis=2).ravel(),np.linalg.norm(np.diff(grid,axis=1),axis=2).ravel()]
    row['median_spacing_px']=float(np.median(d))
    if row['median_spacing_px']<SCREEN['min_grid_spacing_px']:
        return dict(row,reason='grid_too_small')
    return dict(row,eligible=True,reason='handheld_candidate_needs_native_review')


def main():
    output=HERE/'extraction_r01'
    if output.exists():
        raise ValueError('no output overwrite')
    intake=json.loads((HERE/'intake_summary.json').read_text())
    session=Path(intake['session'])
    spec=ROOT/'Experimental_results/2026-10-19/fisheye_intrinsic_target_a4_r01/board_spec.json'
    board=Board(**json.loads(spec.read_text())['board'])
    assert board.square_mm==20.
    source={str(p):sha256(p) for p in (session/'raw.avi',session/'detections.csv',session/'metadata.json',
        spec,HERE/'method.md',Path(__file__),ROOT/'src/fisheye_intrinsic_calibration.py')}
    reference=cv2.imread(str(HERE/'raw_samples/raw_f000472.png'))
    assert reference is not None and reference.shape==(720,1280,3)
    output.mkdir()
    (output/'raw_frames').mkdir()
    frames=read_csv(session/'detections.csv')
    cv2.setNumThreads(1)
    cap=cv2.VideoCapture(str(session/'raw.avi'))
    attempts,views,manifest,signal=[],[],[],[]
    try:
        for i,original in enumerate(frames,1):
            ok,image=cap.read()
            assert ok and image.shape==(720,1280,3)
            # A supplied native no-signal reference; no text/OCR fabrication.
            difference=float(np.mean(cv2.absdiff(image,reference)))
            no_signal=difference<=1.0
            signal.append(dict(frame=i,time_sec=float(original['time_sec']),no_signal_reference_mae=difference,
                               matches_no_signal_reference=no_signal))
            if (i-1)%5:
                continue
            r=inspect(image,board) if not no_signal else dict(detected=False,reason='no_signal_reference',
                corners_native=None,centre_x=None,centre_y=None,median_spacing_px=None,excluded_fixed_window=False,eligible=False)
            r.update(frame=i,time_sec=float(original['time_sec']),retained=False)
            if r['eligible']:
                p=np.asarray(r['corners_native'])
                duplicate=min((corner_rms(p,np.asarray(v['corners_native'])) for v in views),default=None)
                r['nearest_prior_pose_rms_px']=duplicate
                if duplicate is not None and duplicate<SCREEN['duplicate_rms_px']:
                    r['reason']='near_duplicate_pose'
                else:
                    filename=f'raw_frames/raw_f{i:06d}.png'
                    assert cv2.imwrite(str(output/filename),image)
                    digest=hashlib.sha256(image.tobytes()).hexdigest()
                    assert hashlib.sha256(cv2.imread(str(output/filename)).tobytes()).hexdigest()==digest
                    r.update(retained=True,retained_index=len(views),native_png=filename,png_sha256=sha256(output/filename),
                             decoded_bgr_sha256=digest)
                    views.append(r.copy())
                    manifest.append(dict(file=filename,frame=i,time_sec=r['time_sec'],session=session.name,
                        centre_x=r['centre_x'],centre_y=r['centre_y'],median_spacing_px=r['median_spacing_px'],
                        png_sha256=r['png_sha256'],decoded_bgr_sha256=digest,image_edited=False))
            attempts.append(r)
            if len(attempts)%50==0:
                print('sampled',len(attempts),'detected',sum(r['detected'] for r in attempts),'retained',len(views),flush=True)
        assert not cap.read()[0]
    finally:
        cap.release()
    assert all(sha256(Path(p))==v for p,v in source.items())
    distribution=coverage([np.asarray(v['corners_native']) for v in views],FRONT_ROI) if views else None
    train,validation=partition_views(views) if len(views)>=SCREEN['min_views'] else ([],[])
    training=coverage([np.asarray(views[i]['corners_native']) for i in train],FRONT_ROI) if train else None
    checks=dict(enough_views=len(views)>=20,training_centre_bins=bool(training and training['centre_bins']>=4),
        training_span=bool(training and min(training['span_fraction_x'],training['span_fraction_y'])>=.35))
    j=dict(schema='single_fisheye_native_corners_v1',image_size=list(IMAGE_SIZE),roi_native_xywh=list(FRONT_ROI),
        selected_lens='front_left',board=asdict(board),source_sha256=source,frames_decoded=len(frames),sample_every=5,
        attempts=attempts,retained_views=views,enough_views_for_fit=checks['enough_views'],prefit_checks=checks,
        all_retained_coverage=distribution,train_only_coverage=training,train_indices=train,validation_indices=validation,
        source_pixels_edited=False,usable_for_ffb=False,
        decision='REVIEW_BEFORE_FIT' if all(checks.values()) else 'NO_FIT_INSUFFICIENT_OBSERVATIONS')
    (output/'observations.json').write_text(json.dumps(j,indent=2)+'\n')
    write_csv(output/'attempts.csv',[dict(r,corners_native=json.dumps(r['corners_native'])) for r in attempts])
    write_csv(output/'raw_frame_manifest.csv',manifest)
    write_csv(output/'signal_audit.csv',signal)
    print(json.dumps(dict(retained=len(views),attempts=len(attempts),coverage=distribution,checks=checks,
                         no_signal_frames=sum(r['matches_no_signal_reference'] for r in signal)),indent=2))


if __name__=='__main__':
    main()
