"""Independent bookkeeping/point-equation verification, never accuracy PASS."""
import json
from pathlib import Path
import statistics
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(HERE.parent/'cone_geometry_candidates_r01'))
from cone_dataset import read_csv,sha256
from geometry_models import project_pixels_to_floor
from run_cone_review_frames import verify_frame


def main():
    target=HERE/'verification.json'
    if target.exists():raise ValueError('no verification overwrite')
    intake=json.loads((HERE/'intake_summary.json').read_text())
    assert sha256(Path(intake['archive']))==intake['archive_sha256']
    assert sha256(HERE/'intake.py')==intake['script_sha256']
    assert sha256(Path(intake['model']['path']))==intake['model']['sha256']
    reports=[(HERE/'analysis_r01','summary.json'),(HERE/'inference_r01','provenance.json'),
             (HERE/'occlusion_diagnosis_r01','provenance.json')]
    for folder,filename in reports:
        report=json.loads((folder/filename).read_text())
        for file,digest in report['source_sha256'].items():assert sha256(Path(file))==digest,file
        for name,digest in report.get('output_sha256',{}).items():assert sha256(folder/name)==digest,name
    manifest=read_csv(HERE/'raw_sample_manifest.csv')+read_csv(HERE/'raw_boundary_manifest.csv')
    for row in manifest:verify_frame(HERE,row)
    for row in read_csv(HERE/'occlusion_diagnosis_r01/raw_manifest.csv'):
        verify_frame(HERE/'occlusion_diagnosis_r01',row)
    p=json.loads((HERE/'analysis_r01/summary.json').read_text())
    source=read_csv(Path(intake['session'])/'detections.csv')
    inferred=read_csv(HERE/'inference_r01/frames.csv')
    predictions=read_csv(HERE/'inference_r01/predictions.csv')
    rows=read_csv(HERE/'analysis_r01/observations.csv')
    assert len(source)==len(inferred)==1547 and len(rows)==1547*3
    assert len(predictions)==2784
    for name,parameters in p['models'].items():
        group=[r for r in rows if r['model']==name]
        assert [int(r['frame']) for r in group]==list(range(1,1548))
        used=[r for r in group if r['target_hypothesis_used']=='True']
        pixels=[[float(r['pixel_x']),float(r['pixel_y'])] for r in used]
        ground=project_pixels_to_floor(pixels,parameters)
        np.testing.assert_allclose(ground,[[float(r['x_m']),float(r['z_m'])] for r in used],rtol=0,atol=1e-12)
        for r in group:
            assert r['usable_for_ffb']=='False' and r['physical_contact_verified']=='False'
            assert int(r['all_view_predictions'])==int(r['central_predictions'])+int(r['other_predictions'])
            if r['target_hypothesis_used']!='True':assert r['z_m']==''
            if r['reference_z_m']=='':assert r['error_z_m']==''
    for summary in read_csv(HERE/'analysis_r01/phase_summary.csv'):
        group=[r for r in rows if r['model']==summary['model'] and r['phase']==summary['phase']]
        used=[r for r in group if r['target_hypothesis_used']=='True']
        assert len(group)==int(summary['frames']) and len(used)==int(summary['used_frames'])
        if used:
            assert abs(statistics.median(float(r['z_m']) for r in used)-float(summary['z_median_m']))<1e-12
            assert abs(statistics.pstdev(float(r['z_m']) for r in used)-float(summary['z_std_m']))<1e-12
    matches=read_csv(HERE/'analysis_r01/within_video_vehicle_features.csv')
    accepted=[r for r in matches if r['reliable_for_local_feature_comparison']=='True']
    assert len(matches)==75 and len(accepted)==45
    assert all(r['delta_x_current_minus_reference_px']=='0' and r['delta_y_current_minus_reference_px']=='0' for r in accepted)
    assert p['floor_points_used_for_fit']==p['cone_points_used_for_fit']==0
    assert not p['physical_output'] and not p['production_settings_changed']
    final=dict(status='PASS_INTEGRITY_SPLIT_AND_EQUATION_CHECKS_NOT_DISTANCE_TTC_OR_HARDWARE_APPROVAL',
        original_frames_retained=1547,all_view_predictions_retained=2784,model_observation_rows=4641,
        native_pngs_verified=17,phase_statistics_independently_recomputed=True,
        missing_and_partial_occlusion_rows_preserved=True,new_fit_points=0,
        original_runtime_configs_and_camera_images_unchanged=True,final_empty_floor_not_fabricated=True,
        frozen_previous_geometry_promoted=False,baseline_or_height59_accuracy_approved=False,
        physical_output=False,verification_script_sha256=sha256(Path(__file__)))
    target.write_text(json.dumps(final,indent=2)+'\n')
    print(json.dumps(final,indent=2))


if __name__=='__main__':main()
