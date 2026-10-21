"""Keep frozen 57 observations; compare a continuous angular-domain diagnostic."""
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256,write_csv
from fisheye_intrinsic_calibration import Board
from fisheye_angular_bundle_diagnostic import fit_angular_bundle


def main():
    output=HERE/'angular_results_r01'
    if output.exists():raise ValueError('no angular result overwrite')
    path=HERE.parent/'front_intrinsics_a4_real_r03/combined_candidate_r01/merged_observations.json'
    data=json.loads(path.read_text())
    sources={str(p):sha256(p) for p in (path,Path(__file__),HERE/'angular_method.md',
        ROOT/'src/fisheye_bundle_diagnostic.py',ROOT/'src/fisheye_angular_bundle_diagnostic.py',
        ROOT/'tests/test_fisheye_angular_bundle_diagnostic.py',HERE/'results_r01/summary.json',
        HERE/'results_r01/corner_audit.csv')}
    sources.update(data['source_sha256'])
    assert all(sha256(Path(p))==v for p,v in sources.items())
    output.mkdir()
    (output/'input_provenance.json').write_text(json.dumps(dict(source_sha256=sources,
        train_indices=data['train_indices'],validation_indices=data['validation_indices'],
        all_original_57_views_retained=True,physical_output=False,usable_for_ffb=False),indent=2)+'\n')
    f=640/math.pi;K=np.array([[f,0.,319.5],[0.,f,300.],[0.,0.,1.]])
    result=fit_angular_bundle([r['corners_native'] for r in data['selected_views']],Board(**data['board']),K,max_nfev=300)
    result.update(source_sha256=sources)
    (output/'angular_diagnostic_candidate.json').write_text(json.dumps(result,indent=2)+'\n')
    rows=[dict(r,session=data['selected_views'][r['view_index']]['session'],
        source_frame=data['selected_views'][r['view_index']]['source_frame']) for r in result['per_view']]
    write_csv(output/'reprojection_by_view.csv',rows)
    write_csv(output/'evaluation_trace.csv',result['trace'])
    assert all(sha256(Path(p))==v for p,v in sources.items())
    summary={k:result[k] for k in ('decision','calibration_rms_px','pose_validation_rms_px','initial_train_rms_px',
        'K','D','normal_spread_deg','observed_max_angle_deg','points_beyond_90','stationarity_scaled_gradient',
        'intrinsic_profile_condition','checks','optimizer','usable_for_ffb','direct_opencv_full_fov_undistort_compatible')}
    summary.update(source_files_verified=True,source_sha256=sources,physical_output=False,
        original_pixels_modified=False,production_settings_changed=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
