"""Audit native corner identities and compare an offline joint fisheye solver."""
import hashlib
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
from fisheye_intrinsic_calibration import Board,corner_rms
from fisheye_bundle_diagnostic import grid_audit,fit_bundle


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('no overwrite')
    path=HERE.parent/'front_intrinsics_a4_real_r03/combined_candidate_r01/merged_observations.json'
    data=json.loads(path.read_text())
    sources={str(p):sha256(p) for p in (path,Path(__file__),HERE/'method.md',
        ROOT/'src/fisheye_bundle_diagnostic.py',ROOT/'tests/test_fisheye_bundle_diagnostic.py')}
    sources.update(data['source_sha256'])
    assert all(sha256(Path(p))==v for p,v in sources.items())
    board=Board(**data['board'])
    output.mkdir()
    (output/'input_provenance.json').write_text(json.dumps(dict(source_sha256=sources,
        frozen_train_indices=data['train_indices'],frozen_validation_indices=data['validation_indices'],
        original_images_edited=False,physical_output=False,usable_for_ffb=False),indent=2)+'\n')
    audit=[]
    cv2.setNumThreads(1)
    for row in data['selected_views']:
        path=Path(row['source_native_png'])
        assert sha256(path)==row['png_sha256']
        image=cv2.imread(str(path))
        assert image.shape==(720,1280,3)
        assert hashlib.sha256(image.tobytes()).hexdigest()==row['decoded_bgr_sha256']
        points=np.asarray(row['corners_native'])
        gray=cv2.cvtColor(image[:,:640],cv2.COLOR_BGR2GRAY)
        refined=points.astype(np.float32).reshape(-1,1,2).copy()
        cv2.cornerSubPix(gray,refined,(3,3),(-1,-1),(3,50,1e-4))
        delta=np.linalg.norm(refined.reshape(-1,2)-points,axis=1)
        found,classic=cv2.findChessboardCorners(gray,(board.inner_columns,board.inner_rows),
            flags=cv2.CALIB_CB_ADAPTIVE_THRESH|cv2.CALIB_CB_NORMALIZE_IMAGE|cv2.CALIB_CB_FAST_CHECK)
        classic_rms=None
        if found:
            cv2.cornerSubPix(gray,classic,(3,3),(-1,-1),(3,50,1e-4))
            classic_rms=corner_rms(points,classic.reshape(-1,2))
        audit.append(dict(merged_index=row['merged_index'],session=row['session'],source_frame=row['source_frame'],
            split=row['split'],**grid_audit(points,board),subpix_movement_rms_px=float(np.sqrt(np.mean(delta**2))),
            subpix_movement_max_px=float(delta.max()),classic_found=bool(found),classic_grid_rms_px=classic_rms,
            original_coordinates_used_for_fit=True))
        if len(audit)%10==0:print('native corner audit',len(audit),'/',len(data['selected_views']),flush=True)
    write_csv(output/'corner_audit.csv',audit)
    assert all(r['cell_orientation_consistent'] for r in audit),'folded grid; stop before fitting'
    f=640/math.pi
    initial_K=np.array([[f,0.,319.5],[0.,f,300.],[0.,0.,1.]])
    print('fitting all 46 train views jointly; 11 held-out poses kept separate',flush=True)
    summary=dict(source_sha256=sources,source_view_count=len(data['selected_views']),
        train_count=len(data['train_indices']),validation_count=len(data['validation_indices']),
        intrinsic_solver_attempted=True,original_pixels_edited=False,production_settings_changed=False,
        physical_output=False,usable_for_ffb=False)
    try:
        result=fit_bundle([r['corners_native'] for r in data['selected_views']],board,initial_K,max_nfev=300)
        result.update(source_sha256=sources)
        (output/'joint_diagnostic_candidate.json').write_text(json.dumps(result,indent=2)+'\n')
        per_view=[dict(r,session=data['selected_views'][r['view_index']]['session'],
                      source_frame=data['selected_views'][r['view_index']]['source_frame']) for r in result['per_view']]
        write_csv(output/'reprojection_by_view.csv',per_view)
        write_csv(output/'evaluation_trace.csv',result['trace'])
        summary.update({k:result[k] for k in ('decision','initial_train_rms_px','calibration_rms_px',
            'pose_validation_rms_px','normal_spread_deg','train_pose_condition_max','checks','K','D','optimizer')})
    except (ValueError,RuntimeError,cv2.error) as error:
        summary.update(decision='JOINT_SOLVER_REJECTED',error_type=type(error).__name__,error=str(error))
    assert all(sha256(Path(p))==v for p,v in sources.items())
    summary['source_files_verified']=True
    summary['output_sha256']={p.name:sha256(p) for p in output.iterdir() if p.is_file()}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
