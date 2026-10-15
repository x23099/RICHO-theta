"""Run frozen offline geometry comparison, sensitivity and cone transfer."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import numpy as np
import scipy

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"src"))
from cone_dataset import read_csv,sha256,write_csv
from cone_observation import CAMERA_KEYS,ConeGroundProjector
from geometry_models import (FIT_IDS,CHECK_IDS,FAMILIES,PRIMARY,arrays,fit_model,
    partition,project_floor_to_pixels,project_pixels_to_floor)


def point_results(rows,p,name):
    world,pixels=arrays(rows)
    projected=project_pixels_to_floor(pixels,p)
    expected_pixels=project_floor_to_pixels(world,p)
    return [dict(candidate=name,point_id=r['point_id'],role=r['role'],
        pixel_x=float(pixel[0]),pixel_y=float(pixel[1]),reference_x_m=float(w[0]),reference_z_m=float(w[1]),
        predicted_pixel_x=float(pred[0]),predicted_pixel_y=float(pred[1]),
        pixel_error_x=float(pred[0]-pixel[0]),pixel_error_y=float(pred[1]-pixel[1]),
        x_m=float(g[0]),z_m=float(g[1]),error_x_m=float(g[0]-w[0]),error_z_m=float(g[1]-w[1]),
        position_error_m=float(np.linalg.norm(g-w)),physical_apex_verified=False,usable_for_ffb=False)
        for r,w,pixel,pred,g in zip(rows,world,pixels,expected_pixels,projected)]


def group_summary(rows,name):
    summaries=[]
    for role,ids in (('fit',FIT_IDS),('check',CHECK_IDS)):
        selected=[r for r in rows if r['point_id'] in ids]
        summaries.append(dict(candidate=name,group=role,points=len(selected),
            pixel_point_rmse=float(np.sqrt(np.mean([r['pixel_error_x']**2+r['pixel_error_y']**2 for r in selected]))),
            x_mae_m=float(np.mean([abs(r['error_x_m']) for r in selected])),
            z_mae_m=float(np.mean([abs(r['error_z_m']) for r in selected])),
            z_abs_max_m=max(abs(r['error_z_m']) for r in selected),
            position_rmse_m=float(np.sqrt(np.mean([r['position_error_m']**2 for r in selected])))))
    return summaries


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new run required; no output overwrite')
    floor=HERE.parent/'cone_floor_reference_real_r01'
    cone=HERE.parent/'cone_static_distance_r01'
    floor_intake=json.loads((floor/'intake_summary.json').read_text())
    confirmed=json.loads((floor/'reference_confirmation.json').read_text())
    original={k:floor_intake['metadata']['parameters'][k] for k in CAMERA_KEYS}
    measured=dict(original,camera_height=confirmed['reported_lens_centre_height_m'])
    rows=read_csv(floor/'point_candidates.csv')
    for row in rows:
        if [float(row['reference_x_m']),float(row['reference_z_m'])] != confirmed['placements_m'][row['point_id']]:
            raise ValueError('reference confirmation differs from candidate table')
    train,check=partition(rows)
    # Check previous immutable analyses before deriving new results.
    for report_path in (floor/'analysis_r01/summary.json',cone/'analysis_r01/analysis_summary.json'):
        report=json.loads(report_path.read_text())
        for name,digest in report['source_sha256'].items():
            if sha256(Path(name))!=digest:raise ValueError('previous diagnostic source changed: '+name)
    files=[Path(__file__),HERE/'geometry_models.py',HERE/'method.md',HERE/'test_geometry_models.py',
        floor/'point_candidates.csv',floor/'reference_confirmation.json',floor/'intake_summary.json',
        cone/'analysis_r01/positions.csv',cone/'analysis_r01/summary.csv',cone/'intake_summary.json',
        ROOT/'src/ground_contact.py',ROOT/'src/cone_observation.py',ROOT/'src/bird_eye.py',
        ROOT/'src/diagnose_box_contact_calibration.py']
    files.extend(floor/r['file'] for r in read_csv(floor/'raw_sample_manifest.csv'))
    files.extend(Path(floor_intake['session'])/name for name in floor_intake['source_sha256'])
    # Preserve all tracked runtime parameter files; do not fit or write configs.
    files.extend(sorted((ROOT/'src').glob('bird_eye_config*.json')))
    before={str(f):sha256(f) for f in files}
    models={'recorded58':dict(parameters=original,fit_ids=[],free_parameters=[]),
            'measured59':dict(parameters=measured,fit_ids=[],free_parameters=[])}
    for family in FAMILIES:
        models[family]=fit_model(train,measured,family)  # check rows NEVER enter here.
    all_points,summaries=[],[]
    for name,result in models.items():
        values=point_results(rows,result['parameters'],name)
        all_points.extend(values)
        summaries.extend(group_summary(values,name))
    sensitivity=[]
    scenarios=[]
    for row in train:
        scenarios.append(('leave_one_out',row['point_id'],'',0,[r for r in train if r['point_id']!=row['point_id']]))
        for axis in ('pixel_x','pixel_y'):
            for delta in (-2,2):
                altered=deepcopy(train)
                target=next(r for r in altered if r['point_id']==row['point_id'])
                target[axis]=float(target[axis])+delta
                scenarios.append(('hypothetical_one_point_2px',row['point_id'],axis,delta,altered))
    for kind,identity,axis,delta,subset in scenarios:
        result=fit_model(subset,measured,PRIMARY)
        comparison=point_results(rows,result['parameters'],PRIMARY)
        holdout=next(r for r in group_summary(comparison,PRIMARY) if r['group']=='check')
        sensitivity.append(dict(scenario=kind,point_id=identity,axis=axis,delta_px=delta,
            fit_ids='|'.join(result['fit_ids']),front_cx_offset=result['parameters']['front_cx_offset'],
            front_cy_offset=result['parameters']['front_cy_offset'],check_z_mae_m=holdout['z_mae_m'],
            check_position_rmse_m=holdout['position_rmse_m'],
            **{r['point_id']+'_'+key:r[key] for r in comparison for key in ('x_m','z_m')}))
    fixed_pixel_sensitivity=[]
    for row in rows:
        x,y=float(row['pixel_x']),float(row['pixel_y'])
        probe=project_pixels_to_floor([[x+dx,y+dy] for dx in range(-2,3) for dy in range(-2,3)],models[PRIMARY]['parameters'])
        fixed_pixel_sensitivity.append(dict(point_id=row['point_id'],assumed_pixel_half_width_px=2,
            x_min_m=float(probe[:,0].min()),x_max_m=float(probe[:,0].max()),
            z_min_m=float(probe[:,1].min()),z_max_m=float(probe[:,1].max()),
            interpretation='hypothetical fixed-candidate pixel sensitivity; NOT CI or measured annotation error'))
    p=models[PRIMARY]['parameters']
    projector=ConeGroundProjector(p,width=1280,height=720,front_lens='left',confidence_threshold=.5)
    previous=read_csv(cone/'analysis_r01/positions.csv')
    if len(previous)!=3596:raise ValueError('all previous cone frames must be retained')
    transferred=[]
    for old in previous:
        row={key:old[key] for key in ('condition','session','frame','time_sec','reference_x_m','reference_z_m','measurement_reason')}
        row.update(baseline_used=old['measurement_used']=='True',baseline_x_m=old['x_m'],baseline_z_m=old['z_m'],
            candidate_used=False,candidate_reason='',candidate_x_m=None,candidate_z_m=None,
            candidate_error_x_m=None,candidate_error_z_m=None,floor_contact_verified=False,usable_for_ffb=False)
        if not row['baseline_used']:
            row['candidate_reason']='original_unused_retained:'+old['measurement_reason']
        else:
            box={key:float(old['bbox_'+key]) for key in ('x1','y1','x2','y2')}
            box.update(class_id=0,confidence=float(old['confidence']))
            result=projector.project(box,frame_width=1280,frame_height=720)
            row['candidate_reason']=result['reason']
            if result['projection_candidate']:
                row.update(candidate_used=True,candidate_x_m=result['x_m'],candidate_z_m=result['z_m'],
                    candidate_error_x_m=result['x_m']-float(old['reference_x_m']),
                    candidate_error_z_m=result['z_m']-float(old['reference_z_m']))
        transferred.append(row)
    transfer_summary=[]
    for condition in ('none','center_080','center_130','center_200','left_130','right_130'):
        old=[r for r in previous if r['condition']==condition]
        current=[r for r in transferred if r['condition']==condition]
        valid=[r for r in current if r['candidate_used']]
        row=dict(condition=condition,frames=len(old),baseline_used=sum(r['baseline_used'] for r in current),candidate_used=len(valid))
        for prefix,collection,keys in (('baseline',[r for r in old if r['measurement_used']=='True'],('x_m','z_m','error_x_m','error_z_m')),
            ('candidate',valid,('candidate_x_m','candidate_z_m','candidate_error_x_m','candidate_error_z_m'))):
            for key,short in zip(keys,('x','z','error_x','error_z')):
                row[prefix+'_'+short+'_median_m']=float(np.median([float(r[key]) for r in collection])) if collection else None
        transfer_summary.append(row)
    output.mkdir(exist_ok=False)
    for filename,data in (('floor_point_results.csv',all_points),('model_summary.csv',summaries),
        ('centre2_refit_sensitivity.csv',sensitivity),('centre2_fixed_pixel_sensitivity.csv',fixed_pixel_sensitivity),
        ('cone_transfer_frames.csv',transferred),('cone_transfer_summary.csv',transfer_summary)):
        write_csv(output/filename,data)
    payload=dict(status='EXPLORATORY_OFFLINE_CANDIDATES_NOT_RUNTIME_CONFIG_OR_PHYSICAL_CALIBRATION',
        predeclared_primary=PRIMARY,selection_uses_holdout=False,models=models,
        pixel_labels_verified=False,physical_output_authorized=False,usable_for_ffb=False)
    (output/'candidate_parameters.json').write_text(json.dumps(payload,indent=2)+'\n')
    plot(output,all_points,transfer_summary,fixed_pixel_sensitivity)
    if any(sha256(Path(f))!=digest for f,digest in before.items()):
        raise ValueError('source images/metadata/runtime configs/code changed')
    provenance=dict(status='COMPLETED_OFFLINE_CANDIDATE_COMPARISON_NOT_CALIBRATION_PROMOTION',
        primary=PRIMARY,fit_ids=list(FIT_IDS),check_ids=list(CHECK_IDS),method_sha256=sha256(HERE/'method.md'),
        check_rows_never_passed_to_solver=True,selection_uses_holdout=False,
        fit_label_status='unverified assistant V-apex candidates only; no promotion to physical GT',
        cone_labels_used_for_fit_or_selection=False,models=list(models),refit_scenarios=len(sensitivity),
        cone_frames_retained=len(transferred),cone_candidate_frames=sum(r['candidate_used'] for r in transferred),
        source_sha256=before,scipy_version=scipy.__version__,numpy_version=np.__version__,
        runtime_config_files_preserved=sum(Path(f).name.startswith('bird_eye_config') for f in before),
        original_camera_images_changed=False,production_settings_changed=False,physical_output=False,
        limitations=['single view and small nonblind pixel set, farther apex unresolved',
            'H100/H160 were already used for baseline diagnosis before this exploratory fit',
            'H100/H160 held out of solver and model choice, not a fully blind independent experiment',
            'heldout points are central and cannot validate new lateral layouts',
            'pixel/pose/radius may compensate one another; fit values not proven physical intrinsics',
            'hypothetical pixel probes are NOT confidence intervals or measured error bounds',
            'static cone transfer not a TTC, live ROS, or physical FFB evaluation'],
        output_sha256={f.name:sha256(f) for f in sorted(output.iterdir()) if f.is_file()})
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    for row in summaries:
        if row['group']=='check':print(json.dumps(row))
    print('Cone transfer:',json.dumps(transfer_summary))
    print('Primary parameters:',json.dumps(models[PRIMARY]['parameters']))


def plot(output,points,cone,pixel_bands):
    os.environ.setdefault('MPLCONFIGDIR',str(HERE/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    primary=[r for r in points if r['candidate']==PRIMARY]
    baseline=[r for r in points if r['candidate']=='recorded58']
    band={r['point_id']:r for r in pixel_bands}
    central=sorted([r for r in primary if r['reference_x_m']==0],key=lambda r:r['reference_z_m'])
    fig,(a,b)=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    a.plot([.7,2.4],[.7,2.4],'k--',label='Reference = estimate')
    old=[next(v for v in baseline if v['point_id']==r['point_id']) for r in central]
    a.plot([r['reference_z_m'] for r in old],[r['z_m'] for r in old],'s',label='Recorded58')
    a.errorbar([r['reference_z_m'] for r in central],[r['z_m'] for r in central],
        yerr=np.array([[r['z_m']-band[r['point_id']]['z_min_m'] for r in central],
                       [band[r['point_id']]['z_max_m']-r['z_m'] for r in central]]),
        fmt='o',capsize=3,label='Predeclared centre2; hypothetical +/-2px')
    for r in central:
        if r['point_id'] in CHECK_IDS:a.annotate(r['point_id']+' CHECK',(r['reference_z_m'],r['z_m']),xytext=(4,8),textcoords='offset points',fontsize=8)
    a.set(xlabel='Confirmed placement Z [m]',ylabel='Estimated Z [m]',title='Floor V candidates: no physical calibration approval')
    ticks=np.arange(len(primary))
    b.bar(ticks-.18,[100*next(v for v in baseline if v['point_id']==r['point_id'])['error_x_m'] for r in primary],width=.36,label='Recorded58')
    b.bar(ticks+.18,[100*r['error_x_m'] for r in primary],width=.36,label='Predeclared centre2')
    b.set(xticks=ticks,xticklabels=[r['point_id'] for r in primary],ylabel='X error [cm]',title='Floor X; central H points not used for fit')
    for panel in (a,b):panel.grid(alpha=.25);panel.legend(fontsize=8)
    fig.savefig(output/'floor_primary_comparison.png',dpi=150);plt.close(fig)
    positive=[r for r in cone if r['condition']!='none']
    ticks=np.arange(len(positive))
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    for panel,axis in zip(axes,('z','x')):
        for shift,prefix in ((-.18,'baseline'),(.18,'candidate')):
            panel.bar(ticks+shift,[100*r[prefix+'_error_'+axis+'_median_m'] for r in positive],width=.36,
                label='Recorded58' if prefix=='baseline' else 'Predeclared centre2')
        panel.axhline(0,color='black',lw=.8)
        panel.set(xticks=ticks,xticklabels=[r['condition'] for r in positive],ylabel=axis.upper()+' median error [cm]',
                  title='Cone bbox transfer: no re-inference, no FFB')
        panel.tick_params(axis='x',rotation=25);panel.legend(fontsize=8);panel.grid(axis='y',alpha=.25)
    fig.savefig(output/'cone_transfer_comparison.png',dpi=150);plt.close(fig)


if __name__=='__main__':main()
