"""Verify experimental artifacts, split isolation and every transferred point."""
import json
from pathlib import Path
import statistics
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256
from geometry_models import (CHECK_IDS,FIT_IDS,PRIMARY,fit_model,partition,
    project_floor_to_pixels,project_pixels_to_floor)


def main():
    target=HERE/'verification.json'
    if target.exists():raise ValueError('no verification overwrite')
    results=HERE/'results_r01'
    p=json.loads((results/'provenance.json').read_text())
    reports=[p,json.loads((HERE/'contact_transfer_r01/provenance.json').read_text())]
    for report in reports:
        for file,digest in report['source_sha256'].items():assert sha256(Path(file))==digest,file
    for folder in (results,HERE/'contact_transfer_r01'):
        report=json.loads((folder/'provenance.json').read_text())
        for name,digest in report['output_sha256'].items():assert sha256(folder/name)==digest,name
    assert p['primary']==PRIMARY and p['check_rows_never_passed_to_solver']
    assert not p['selection_uses_holdout'] and not p['cone_labels_used_for_fit_or_selection']
    candidates=json.loads((results/'candidate_parameters.json').read_text())
    model=candidates['models'][PRIMARY]
    assert set(model['fit_ids'])==set(FIT_IDS) and not set(model['fit_ids'])&set(CHECK_IDS)
    points=read_csv(HERE.parent/'cone_floor_reference_real_r01/point_candidates.csv')
    train,checks=partition(points)
    repeated=fit_model(train,candidates['models']['measured59']['parameters'],PRIMARY)
    assert repeated['parameters']==model['parameters']
    # Changing heldout labels/pixels never affects fitted parameters.
    for r in checks:r.update(pixel_x=-99999,reference_z_m=99999)
    mutated,_=partition(train+checks)
    assert fit_model(mutated,candidates['models']['measured59']['parameters'],PRIMARY)['parameters']==model['parameters']
    for name,m in candidates['models'].items():
        if name not in ('recorded58','measured59'):
            assert set(m['fit_ids'])==set(FIT_IDS)
            assert m['parameters']['camera_height']==.59
            assert not m['usable_for_ffb'] and not m['physical_output_authorized']
    floor_rows=read_csv(results/'floor_point_results.csv')
    assert len(floor_rows)==42
    for row in floor_rows:
        parameters=candidates['models'][row['candidate']]['parameters']
        xy=np.array([[float(row['pixel_x']),float(row['pixel_y'])]])
        estimate=project_pixels_to_floor(xy,parameters)[0]
        assert np.allclose(estimate,[float(row['x_m']),float(row['z_m'])],rtol=0,atol=1e-12)
        world=[[float(row['reference_x_m']),float(row['reference_z_m'])]]
        predicted=project_floor_to_pixels(world,parameters)[0]
        assert np.allclose(predicted,[float(row['predicted_pixel_x']),float(row['predicted_pixel_y'])],rtol=0,atol=1e-12)
    transfer=read_csv(results/'cone_transfer_frames.csv')
    original=read_csv(HERE.parent/'cone_static_distance_r01/analysis_r01/positions.csv')
    assert len(transfer)==len(original)==3596
    for before,after in zip(original,transfer):
        assert all(before[k]==after[k] for k in ('session','frame','condition','measurement_reason'))
        assert (before['measurement_used']=='True')==(after['baseline_used']=='True')
        if before['measurement_used']!='True':
            assert after['candidate_used']=='False' and after['candidate_z_m']==''
        assert after['usable_for_ffb']=='False' and after['floor_contact_verified']=='False'
    used=[(a,b) for a,b in zip(original,transfer) if b['candidate_used']=='True']
    assert len(used)==3261
    xy=[[float(a['bottom_pixel_x']),float(a['bottom_pixel_y'])] for a,b in used]
    expected=project_pixels_to_floor(xy,model['parameters'])
    saved=[[float(b['candidate_x_m']),float(b['candidate_z_m'])] for a,b in used]
    np.testing.assert_allclose(expected,saved,rtol=0,atol=1e-12)
    for summary in read_csv(results/'cone_transfer_summary.csv'):
        rows=[r for r in transfer if r['condition']==summary['condition']]
        valid=[r for r in rows if r['candidate_used']=='True']
        assert len(rows)==int(summary['frames']) and len(valid)==int(summary['candidate_used'])
        if valid:
            for key in ('candidate_x_m','candidate_z_m','candidate_error_x_m','candidate_error_z_m'):
                output=key.replace('_m','_median_m')
                assert abs(statistics.median(float(r[key]) for r in valid)-float(summary[output]))<1e-12
    sensitivity=read_csv(results/'centre2_refit_sensitivity.csv')
    assert len(sensitivity)==25
    assert sum(r['scenario']=='leave_one_out' for r in sensitivity)==5
    for r in sensitivity:assert not set(r['fit_ids'].split('|'))&set(CHECK_IDS)
    record=dict(status='PASS_INTERNAL_SPLIT_HASH_AND_EQUATION_CHECKS_NOT_PHYSICAL_CALIBRATION',
        fitted_model_families=4,checks_never_fitted=True,holdout_mutation_invariance=True,
        deterministic_primary_refit=True,point_equations_verified=42,cone_frames_retained=3596,
        cone_positions_recomputed=3261,sensitivity_scenarios=25,unused_cone_frames_preserved=335,
        runtime_configs_preserved=p['runtime_config_files_preserved'],physical_output=False,
        calibration_promoted=False,verification_script_sha256=sha256(Path(__file__)))
    target.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
