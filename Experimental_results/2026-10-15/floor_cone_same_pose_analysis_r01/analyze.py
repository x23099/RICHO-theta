"""Validate frozen geometry in one video; no pixel/parameter fitting or ROS."""
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EXPERIMENT=HERE.parent/'cone_geometry_candidates_r01'
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(EXPERIMENT))
from cone_dataset import read_csv,sha256,write_csv
from cone_observation import CAMERA_KEYS,ConeGroundProjector
from geometry_models import project_pixels_to_floor
from run_cone_review_frames import verify_frame
from view_registration import REGIONS,match_region


def phase_at(frame,scope):
    matches=[r for r in scope['phase_windows'] if r['start_frame']<=frame<=r['end_frame']]
    if len(matches)!=1:raise ValueError('frame must have exactly one predeclared phase')
    return matches[0]


def select_central(rows,limits):
    return [r for r in rows if limits[0]<=(float(r['x1'])+float(r['x2']))/2<=limits[1]]


def main():
    output=HERE/'analysis_r01'
    if output.exists():raise ValueError('new diagnostic required; no overwrite')
    intake=json.loads((HERE/'intake_summary.json').read_text())
    scope=json.loads((HERE/'scope.json').read_text())
    infer=json.loads((HERE/'inference_r01/provenance.json').read_text())
    if infer['status']!='COMPLETED_STATIC_CONE_INFERENCE_NOT_DISTANCE_OR_FFB_APPROVAL':raise ValueError('completed inference required')
    for file,digest in infer['source_sha256'].items():
        if sha256(Path(file))!=digest:raise ValueError('inference source changed')
    p={k:intake['metadata']['parameters'][k] for k in CAMERA_KEYS}
    frozen_path=EXPERIMENT/'results_r01/candidate_parameters.json'
    frozen=json.loads(frozen_path.read_text())
    models={'recorded58':p,'measured59':dict(p,camera_height=.59),
            'frozen_centre2':frozen['models'][frozen['predeclared_primary']]['parameters']}
    frames=read_csv(HERE/'inference_r01/frames.csv')
    predictions=read_csv(HERE/'inference_r01/predictions.csv')
    if len(frames)!=intake['total_frames'] or [int(r['frame']) for r in frames]!=list(range(1,len(frames)+1)):
        raise ValueError('all original frames required')
    if sha256(Path(intake['model']['path']))!=intake['model']['sha256']:raise ValueError('frozen model changed')
    by_frame={}
    for r in predictions:by_frame.setdefault(int(r['frame']),[]).append(r)
    manifest=read_csv(HERE/'raw_sample_manifest.csv')+read_csv(HERE/'raw_boundary_manifest.csv')
    for r in manifest:verify_frame(HERE,r)
    sources=[Path(__file__),HERE/'intake.py',HERE/'infer.py',HERE/'export_boundaries.py',HERE/'intake_summary.json',
        HERE/'scope.json',HERE/'contact_candidates.csv',HERE/'raw_sample_manifest.csv',HERE/'raw_boundary_manifest.csv',
        HERE/'inference_r01/provenance.json',HERE/'inference_r01/predictions.csv',HERE/'inference_r01/frames.csv',
        ROOT/'src/cone_observation.py',ROOT/'src/ground_contact.py',frozen_path,
        EXPERIMENT/'geometry_models.py',EXPERIMENT/'view_registration.py']
    sources.extend(HERE/r['file'] for r in manifest)
    sources.extend(Path(intake['session'])/name for name in intake['source_sha256'])
    sources.extend(sorted((ROOT/'src').glob('bird_eye_config*.json')))
    before={str(f):sha256(f) for f in sources}
    projectors={name:ConeGroundProjector(q,width=1280,height=720,front_lens='left',confidence_threshold=.5) for name,q in models.items()}
    observations=[]
    for frame in frames:
        number=int(frame['frame']);phase=phase_at(number,scope)
        all_boxes=by_frame.get(number,[])
        selected=select_central(all_boxes,scope['central_bbox_midpoint_x_px_inclusive'])
        for name,projector in projectors.items():
            row=dict(frame=number,time_sec=frame['time_sec'],phase=phase['name'],model=name,
                all_view_predictions=len(all_boxes),central_predictions=len(selected),other_predictions=len(all_boxes)-len(selected),
                expected_central_cone=phase['expected_central_cone'],reference_z_m=phase['reference_z_m'],
                target_hypothesis_used=False,reason='',confidence=None,pixel_x=None,pixel_y=None,
                x_m=None,z_m=None,error_z_m=None,physical_contact_verified=False,usable_for_ffb=False)
            if len(selected)!=1:
                row['reason']='no_central_prediction' if not selected else 'ambiguous_central_predictions'
            else:
                result=projector.project(selected[0],frame_width=1280,frame_height=720)
                row['reason']=result['reason']
                if result['projection_candidate']:
                    row.update(target_hypothesis_used=True,confidence=float(selected[0]['confidence']),
                        pixel_x=result['pixel_x'],pixel_y=result['pixel_y'],x_m=result['x_m'],z_m=result['z_m'])
                    if phase['reference_z_m'] is not None:row['error_z_m']=result['z_m']-phase['reference_z_m']
            observations.append(row)
    summaries=[]
    for phase in scope['phase_windows']:
        for name in models:
            group=[r for r in observations if r['phase']==phase['name'] and r['model']==name]
            valid=[r for r in group if r['target_hypothesis_used']]
            summaries.append(dict(phase=phase['name'],model=name,frames=len(group),reference_z_m=phase['reference_z_m'],
                start_time_sec=group[0]['time_sec'],end_time_sec=group[-1]['time_sec'],
                central_output_frames=sum(r['central_predictions']>0 for r in group),
                no_central_output_frames=sum(r['central_predictions']==0 for r in group),
                ambiguous_central_frames=sum(r['central_predictions']>1 for r in group),used_frames=len(valid),
                x_median_m=float(np.median([r['x_m'] for r in valid])) if valid else None,
                z_median_m=float(np.median([r['z_m'] for r in valid])) if valid else None,
                z_std_m=float(np.std([r['z_m'] for r in valid])) if valid else None,
                z_p05_m=float(np.percentile([r['z_m'] for r in valid],5)) if valid else None,
                z_p95_m=float(np.percentile([r['z_m'] for r in valid],95)) if valid else None,
                z_error_median_m=float(np.median([r['error_z_m'] for r in valid])) if valid and phase['reference_z_m'] is not None else None,
                bottom_pixel_y_median=float(np.median([r['pixel_y'] for r in valid])) if valid else None))
    contacts=[]
    anchors=read_csv(HERE/'contact_candidates.csv')
    for anchor in anchors:
        pixel=(float(anchor['pixel_x']),float(anchor['pixel_y']))
        for name,q in models.items():
            ground=project_pixels_to_floor([pixel],q)[0]
            probe=project_pixels_to_floor([[pixel[0]+dx,pixel[1]+dy] for dx in range(-2,3) for dy in range(-2,3)],q)
            contacts.append(dict(anchor,model=name,x_m=float(ground[0]),z_m=float(ground[1]),
                error_z_m=float(ground[1]-float(anchor['reference_z_m'])),hypothetical_2px_z_min_m=float(probe[:,1].min()),
                hypothetical_2px_z_max_m=float(probe[:,1].max()),physical_contact_verified=False,usable_for_ffb=False))
    relative=[]
    for point_id,phase in (('C130','cone_130'),('C200','cone_200')):
        floor_point=next(r for r in anchors if r['kind']=='floor' and r['point_id']==point_id)
        cone_point=next(r for r in anchors if r['kind']=='cone' and r['point_id']==point_id)
        static=next(r for r in summaries if r['phase']==phase and r['model']=='recorded58')
        relative.append(dict(point_id=point_id,reference_z_m=floor_point['reference_z_m'],floor_pixel_x=floor_point['pixel_x'],
            floor_pixel_y=floor_point['pixel_y'],manual_cone_pixel_x=cone_point['pixel_x'],manual_cone_pixel_y=cone_point['pixel_y'],
            manual_cone_minus_floor_y_px=float(cone_point['pixel_y'])-float(floor_point['pixel_y']),
            bbox_bottom_y_median=static['bottom_pixel_y_median'],
            bbox_median_minus_floor_y_px=static['bottom_pixel_y_median']-float(floor_point['pixel_y']),
            interpretation='same recording, unverified visual points; no pixel shift applied'))
    # Compare fixed vehicle features only within the new continuous recording.
    ref_path=HERE/'raw_samples/same_pose_f000141.png'
    reference=cv2.imread(str(ref_path),cv2.IMREAD_GRAYSCALE)
    matches=[]
    for sample in manifest:
        current=cv2.imread(str(HERE/sample['file']),cv2.IMREAD_GRAYSCALE)
        for region in REGIONS:
            try:match=match_region(reference,current,region)
            except ValueError as exc:raise ValueError('native vehicle view comparison failed: '+str(exc)) from exc
            matches.append(dict(file=sample['file'],frame=sample['frame'],**match))
    output.mkdir(exist_ok=False)
    for name,data in (('observations.csv',observations),('phase_summary.csv',summaries),('contact_projections.csv',contacts),
        ('relative_contact_pixels.csv',relative),('within_video_vehicle_features.csv',matches)):
        write_csv(output/name,data)
    plot(output,observations,summaries,contacts,scope)
    if any(sha256(Path(f))!=digest for f,digest in before.items()):raise ValueError('original/source/code/config changed')
    accepted=[r for r in matches if r['reliable_for_local_feature_comparison']]
    report=dict(status='COMPLETED_SAME_VIDEO_FROZEN_MODEL_DIAGNOSIS_NOT_TTC_OR_FFB_APPROVAL',
        source_sha256=before,models=models,floor_points_used_for_fit=0,cone_points_used_for_fit=0,
        frames_retained=len(frames),observation_rows=len(observations),all_view_predictions_retained=len(predictions),
        central_roi_is_experiment_scope_not_runtime_multi_object_policy=True,
        missing_final_floor='user confirmed not recorded; no before-after empty-floor verification claimed',
        floor_markers='user confirmed only1.30m and2.00m; no new seven-point calibration',
        unknown_height_or_placement_uncertainty='not inferred from protocol',
        vehicle_matches_total=len(matches),vehicle_matches_accepted=len(accepted),
        accepted_vehicle_dx_range=[min(r['delta_x_current_minus_reference_px'] for r in accepted),max(r['delta_x_current_minus_reference_px'] for r in accepted)],
        accepted_vehicle_dy_range=[min(r['delta_y_current_minus_reference_px'] for r in accepted),max(r['delta_y_current_minus_reference_px'] for r in accepted)],
        production_settings_changed=False,physical_output=False,model_trained=False,new_geometry_fitted=False,
        limits=['static single sequence, central targets only; not live timing/TTC/FFB test',
            'assistant visual apex candidates nonblind and uncertain, +/-2px is hypothetical not CI',
            'central ROI separates known experimental target; other real cones remain in all-view predictions',
            'passer occlusion retained in cone200 statistics; no per-frame bbox ground truth',
            'floor-after missing, so empty-floor recovery/return cannot be verified',
            'local vehicle feature agreement does not prove invariant physical camera pose'],
        output_sha256={f.name:sha256(f) for f in sorted(output.iterdir()) if f.is_file()})
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Vehicle feature accepted offsets',report['accepted_vehicle_dx_range'],report['accepted_vehicle_dy_range'],len(accepted),'/',len(matches))
    for row in summaries:
        if row['phase'] in ('floor_before','cone_130','cone_200'):print(json.dumps(row))
    print('Relative pixels',json.dumps(relative))
    print('Manual/floor contacts',json.dumps(contacts))


def plot(output,observations,summaries,contacts,scope):
    os.environ.setdefault('MPLCONFIGDIR',str(HERE/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,(a,b)=plt.subplots(2,1,figsize=(11,7),sharex=True,constrained_layout=True)
    labels={'recorded58':'Recorded58','measured59':'Height59 only','frozen_centre2':'Frozen previous centre2'}
    for name,label in labels.items():
        rows=[r for r in observations if r['model']==name]
        a.plot([float(r['time_sec']) for r in rows],[r['z_m'] if r['z_m'] is not None else np.nan for r in rows],label=label,lw=.9)
    base=[r for r in observations if r['model']=='recorded58']
    b.plot([float(r['time_sec']) for r in base],[r['central_predictions'] for r in base],label='Central predictions')
    b.plot([float(r['time_sec']) for r in base],[r['other_predictions'] for r in base],label='Other scene predictions',alpha=.6)
    for phase in scope['phase_windows']:
        rows=[r for r in base if r['phase']==phase['name']]
        t0,t1=float(rows[0]['time_sec']),float(rows[-1]['time_sec'])
        if phase['reference_z_m'] is not None:a.plot([t0,t1],[phase['reference_z_m']]*2,'k--',lw=1.5)
        else:a.axvspan(t0,t1,color='gray',alpha=.08)
        a.text((t0+t1)/2,3.5,phase['name'],ha='center',fontsize=8)
    a.set(ylabel='Unverified target Z [m]',ylim=(.4,3.8),title='Full sequence retained; transition and passer gaps not filled')
    b.set(xlabel='Recorded elapsed time [s]',ylabel='Prediction count')
    for panel in (a,b):panel.grid(alpha=.25);panel.legend(fontsize=8)
    fig.savefig(output/'sequence_positions.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    for panel,phase,identity in zip(axes,('cone_130','cone_200'),('C130','C200')):
        indices=np.arange(3)
        names=list(labels)
        floor=[next(r for r in contacts if r['kind']=='floor' and r['point_id']==identity and r['model']==m) for m in names]
        cone=[next(r for r in summaries if r['phase']==phase and r['model']==m) for m in names]
        panel.bar(indices-.17,[r['z_m'] for r in floor],width=.34,label='Floor V-tip candidate')
        panel.bar(indices+.17,[r['z_median_m'] for r in cone],width=.34,label='Cone bbox median')
        panel.axhline(float(floor[0]['reference_z_m']),color='black',ls='--',label='Placement reference')
        panel.set(xticks=indices,xticklabels=[labels[m] for m in names],ylabel='Z [m]',title=phase+': validation only, NO new fit')
        panel.tick_params(axis='x',rotation=15);panel.grid(axis='y',alpha=.25);panel.legend(fontsize=8)
    fig.savefig(output/'floor_cone_comparison.png',dpi=150);plt.close(fig)


if __name__=='__main__':main()
