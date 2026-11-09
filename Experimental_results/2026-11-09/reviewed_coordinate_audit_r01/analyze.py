"""Audit manual coordinates separately from image/colour/floor assumptions.

No live bundle export, geometry fitting to cone distances, runtime changes,
image export, cross-session geometry or physical output.
"""
import argparse
from collections import Counter
import copy
import csv
import json
from pathlib import Path
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from review_physical_reference import read_json,validate_queue,load_decisions,item_image
from cone_distance_core import load_config,digest
from cone_fixed_floor_candidate import build_explicit_floor_transform,measure_support
from derive_fixed_floor_live_bundle import derive
from angular_fisheye_geometry import unproject,project,floor_from_rays
from summarize_cone_distance_live import load_frames

DAY=ROOT/'Experimental_results/2026-11-09'
PREP=DAY/'physical_reference_review_r01'


def write_json(path,value):
    with path.open('x') as stream:stream.write(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def write_csv(path,rows):
    with path.open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=sorted(set().union(*(r.keys() for r in rows))),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def edge_curve(endpoints,camera,samples=1025):
    """Central-camera image locus of a straight physical edge, not a contact proof.

    The span of its two endpoint rays defines a plane through the camera.
    Sample its in-between directions; do not assume the pixel chord is exact.
    No floor normal, height or distance reference is used for this image test.
    """
    rays,valid=unproject(endpoints,camera,image_size=(1280,720))
    if len(rays)!=2 or not valid.all() or not np.isfinite(rays).all():raise ValueError('two valid endpoint rays required')
    t=np.linspace(0,1,samples)[:,None]
    directions=(1-t)*rays[0]+t*rays[1]
    uv,visible=project(directions,camera)
    if not visible.all() or np.any(np.diff(uv[:,0])<=0):raise ValueError('monotonic visible left-to-right edge required')
    return uv


def edge_offset(point,curve):
    p=np.asarray(point,float)
    if p.shape!=(2,) or not np.isfinite(p).all():raise ValueError('finite image point required')
    inside=bool(curve[0,0]<=p[0]<=curve[-1,0])
    return dict(x_within_reviewed_edge=inside,
        signed_y_below_reviewed_edge_px=float(p[1]-np.interp(p[0],curve[:,0],curve[:,1])) if inside else None,
        closest_sample_distance_px=float(np.linalg.norm(curve-p,axis=1).min()))


def conditional_floor_pixels(points,model,camera,heading,session):
    """Offline float clicks only. Preserve live measure_support's integer rule."""
    if session!=model['session']:raise ValueError('no cross-session floor use')
    transform=build_explicit_floor_transform(model,heading)
    rays,valid=unproject(points,camera,image_size=(1280,720))
    xyz,accepted=floor_from_rays(rays,valid,transform)
    return xyz,accepted


def conditional_point(point,model,camera,heading,session,bounds):
    xyz,ok=conditional_floor_pixels([point],model,camera,heading,session)
    if not ok[0]:return dict(available=False,reason='intersection_unavailable',range_m=None)
    radial=float(np.linalg.norm(xyz[0,:2]))
    reason='behind_heading_reference' if xyz[0,0]<=0 else 'outside_diagnostic_range' if not bounds[0]<=radial<=bounds[1] else None
    return dict(available=reason is None,reason=reason,range_m=radial if reason is None else None)


def conditional_edge(endpoints,model,camera,heading,session,bounds):
    xyz,ok=conditional_floor_pixels(endpoints,model,camera,heading,session)
    if not ok.all():return dict(available=False,reason='endpoint_intersection_unavailable',range_m=None,edge_length_m=None)
    middle=xyz.mean(axis=0);radial=float(np.linalg.norm(middle[:2]))
    reason='behind_heading_reference' if middle[0]<=0 else 'outside_diagnostic_range' if not bounds[0]<=radial<=bounds[1] else None
    return dict(available=reason is None,reason=reason,range_m=radial if reason is None else None,
        edge_length_m=float(np.linalg.norm(xyz[1]-xyz[0])),midpoint_method='mean_of_two_conditional_3D_endpoints_NOT_pixel_mean',
        physical_edge_identity_and_floor_contact_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path);args=parser.parse_args()
    out=args.output_dir
    if out.exists():raise ValueError('new output directory required')
    queue_path=PREP/'prepared_r01/queue.json';queue=validate_queue(read_json(queue_path));queue_sha=digest(queue_path)
    decisions_dir=PREP/'prepared_r01/decisions';decisions=load_decisions(decisions_dir,queue,queue_sha)
    if len(decisions)!=len(queue['items']):raise ValueError('all visual decisions required for this complete audit')
    settings,camera,heading,_=load_config();inputs={str(queue_path.relative_to(ROOT)):queue_sha}
    for item in queue['items']:
        inputs[item['image']]=item['sha256']
        p=decisions_dir/(item['id']+'.json');inputs[str(p.relative_to(ROOT))]=digest(p)
    def read(path):
        inputs[str(path.relative_to(ROOT))]=digest(path);return read_json(path)
    folders={s:ROOT/f'Experimental_results/2026-11-04/floor_reference_{s}_r01' for s in ('b559e424','df33e833')}
    old_bundles={s:read(p/'derived_primary_r01/explicit_floor_models.json') for s,p in folders.items()}
    new_bundles={};corner_rows=[];paper_rows=[]
    for item in queue['items']:
        if item['kind']!='paper':continue
        d=decisions[item['id']]
        if d['status']!='reviewed':continue
        short=item['session'][:8];ref=read(folders[short]/'references.json')['frames'][0]
        for index,(old,new) in enumerate(zip(ref['corners_native_xy'],d['points_native_xy'])):
            delta=np.array(new)-old
            corner_rows.append(dict(item=item['id'],corner=index,old_x=old[0],old_y=old[1],manual_x=new[0],manual_y=new[1],
                dx_px=delta[0],dy_px=delta[1],shift_px=float(np.linalg.norm(delta))))
        refs=[]
        for assignment,width,depth in [('as_listed',296,210),('swapped',210,296)]:
            if d['side_assignment']!='unknown' and (d['side_assignment']=='long_01')!=(assignment=='as_listed'):continue
            world=np.array([[0,0,0],[width,0,0],[width,depth,0],[0,depth,0]],float)/1000
            refs.append(dict(assignment=assignment,pixels=np.array(d['points_native_xy']),world=world,
                dimensions_mm=[width,depth],coordinate_source='explicit human visual coordinates; decision sha256='+inputs[str((decisions_dir/(item['id']+'.json')).relative_to(ROOT))]))
        entry=dict(item_image(item),references=refs)
        bundle,poses=derive([entry],settings,camera,board_thickness_mm=15,external_height_mm=590)
        new_bundles[short]=bundle
        for manual in bundle['models']:
            old=next(m for m in old_bundles[short]['models'] if m['name']==manual['name'])
            paper_rows.append(dict(session=item['session'],model_name=manual['name'],side_assignment_review=d['side_assignment'],
                old_floor_height_mm=1000*old['camera_to_floor_m'],manual_floor_height_mm=1000*manual['camera_to_floor_m'],
                manual_minus_reported_590mm=1000*manual['camera_to_floor_m']-590,
                old_reprojection_rmse_px=old['native_reprojection_rmse_px'],manual_reprojection_rmse_px=manual['native_reprojection_rmse_px'],
                up_change_deg=float(np.degrees(np.arccos(np.clip(np.array(old['normal_optical'])@manual['normal_optical'],-1,1)))),
                source_height_mode=manual['height_source'],model_selected=False))
    df_cases=read(ROOT/'Experimental_results/2026-11-04/floor_df33e833_multidistance_r01/cases.json')
    old_df_prepared=folders['df33e833']/'derived_primary_r01/prepared_floor.json'
    if digest(old_df_prepared)!=df_cases['bundle_sha256'] or read(old_df_prepared)['models']!=old_bundles['df33e833']['models']:
        raise ValueError('old df33 prepared model bytes differ')
    df_rows={};all_df={}
    for case in df_cases['cases']:
        path=ROOT/case['input'];rows,truncated,sha=load_frames(path)
        if truncated or sha!=case['sha256']:raise ValueError('old recording changed')
        inputs[case['input']]=sha;all_df[case['id']]=rows
        if case['image_frame'] is not None:df_rows[case['image_frame']]=next(r for r in rows if r['frame']==case['image_frame'])
    cap=read(ROOT/'Experimental_results/2026-11-04/upper_support_capture_analysis_r01/results_r02/audit.json')
    cap_root=(ROOT/Path(cap['extracted_root'])).resolve();upper_path=cap_root/'upper_support_comparison.jsonl'
    if digest(cap_root/'prepared_floor.json')!=cap['model_sha256'] or read(cap_root/'prepared_floor.json')['models']!=old_bundles['b559e424']['models']:
        raise ValueError('old b559 prepared model bytes differ')
    if digest(upper_path)!=cap['input_sha256']['upper_support_comparison.jsonl']:raise ValueError('upper log changed')
    inputs[str(upper_path.relative_to(ROOT))]=digest(upper_path)
    wanted={(i['session'],i['frame']) for i in queue['items'] if i['kind']=='cone_near_edge' and i['session'].startswith('b559')}
    upper_rows={}
    for line in upper_path.open():
        row=json.loads(line)
        if (row['session'],row['frame']) in wanted:upper_rows[row['frame']]=row
    offsets=[];metrics=[];edge_details=[];recorded_values_reproduced=0;logged_verdicts_checked=0
    for item in queue['items']:
        if item['kind']!='cone_near_edge':continue
        d=decisions[item['id']]
        if d['status']!='reviewed':continue
        short=item['session'][:8];session=item['session'];frame=item['frame'];endpoints=d['points_native_xy']
        curve=edge_curve(endpoints,camera)
        legacy=df_rows[frame] if short=='df33e833' else upper_rows[frame]
        old=(legacy['support_completion_shadow']['candidate'] if short=='df33e833' else legacy['legacy_candidate']) or {}
        point=old.get('point');role='recorded_legacy_point'
        if short=='b559e424':
            upper=legacy['upper_candidate'] or {}
            if point is None and upper.get('point') is not None:point=upper['point'];role='recorded_upper_point'
            elif point is None and upper.get('upper_completion_reason')=='upper_point_outside_original_bbox':
                point=upper['upper_contexts'][-1]['observation']['point'];role='rejected_context_proposal_NOT_live_point'
        if point is not None:
            offsets.append(dict(item=item['id'],session=session,frame=frame,point_role=role,point_x=point[0],point_y=point[1],
                **edge_offset(point,curve),straight_edge_and_intrinsic_model_assumed=True,physical_contact_verified=False))
        support=old.get('support') or []
        if not support and short=='b559e424':support=(legacy['upper_candidate'] or {}).get('support') or []
        deviations=[edge_offset(p,curve)['signed_y_below_reviewed_edge_px'] for p in support if curve[0,0]<=p[0]<=curve[-1,0]]
        edge_details.append(dict(item=item['id'],endpoints=endpoints,reviewed_point_precision_not_measured=True,
            support_columns_compared=len(deviations),median_lower_support_offset_px=float(np.median(deviations)) if deviations else None,
            direct_pixel_chord_max_difference_px=float(np.max(np.abs(curve[:,1]-np.interp(curve[:,0],np.array(endpoints)[:,0],np.array(endpoints)[:,1])))),
            no_point_outside_annotation_span_extrapolated=True))
        ref=2. if item['id'].endswith('064232') else 1.
        for label,bundle in [('old_floor',old_bundles[short]),('manual_paper_floor',new_bundles[short])]:
            if bundle['session']!=session:raise ValueError('no cross-session bundle transfer')
            for model in bundle['models']:
                common=dict(item=item['id'],session=session,frame=frame,geometry=label,model_name=model['name'],
                    reference_m=ref,actual_point_role=role,physical_contact_verified=False,model_selected=False)
                if point is not None:
                    measured=conditional_point(point,model,camera,heading,session,settings['diagnostic_range_m'])
                    metrics.append(dict(common,source='logged_or_rejected_colour_pixel',**measured,
                        minus_reference_cm=100*(measured['range_m']-ref) if measured['available'] else None))
                    if label=='old_floor':
                        integer_result=measure_support(point,model,camera,heading,session=session,diagnostic_range_m=settings['diagnostic_range_m'])
                        if measured['available']!=integer_result['range_available']:raise ValueError('integer acceptance mismatch')
                        if measured['available'] and abs(measured['range_m']-integer_result['horizontal_camera_foot_range_m'])>1e-10:
                            raise ValueError('integer range mismatch')
                        recorded_values_reproduced+=1
                        if role!='rejected_context_proposal_NOT_live_point':
                            shadow=(legacy['fixed_floor_shadow'] if short=='df33e833' else legacy['upper_fixed_floor_shadow'])
                            logged=next(m for m in shadow['models'] if m['model_name']==model['name'])
                            if measured['available']!=logged['range_available']:
                                raise ValueError('stored model verdict mismatch')
                            if logged['range_available'] and abs(measured['range_m']-logged['horizontal_camera_foot_range_m'])>1e-10:
                                raise ValueError('stored same-frame range mismatch')
                            logged_verdicts_checked+=1
                measured=conditional_edge(endpoints,model,camera,heading,session,settings['diagnostic_range_m'])
                metrics.append(dict(common,source='conditional_3D_midpoint_of_reviewed_edge',**measured,
                    minus_reference_cm=100*(measured['range_m']-ref) if measured['available'] else None,
                    minus_carried_375mm_edge_mm=1000*(measured['edge_length_m']-.375) if measured['edge_length_m'] is not None else None,
                    carried_base_width_same_object_not_reconfirmed=True))
    # Replay old df33 support points under its own manual-paper model: floor-only factor, not new live approval.
    replay=[];cache={}
    for case in df_cases['cases']:
        rows=all_df[case['id']]
        for model in new_bundles['df33e833']['models']:
            vals=[];observations=0
            original_values=[m['horizontal_camera_foot_range_m'] for row in rows for m in row['fixed_floor_shadow']['models']
                if m['model_name']==model['name'] and m['range_available']]
            for row in rows:
                shadow=row['fixed_floor_shadow']
                if row['session']!=model['session']:raise ValueError('no cross-session replay')
                if not shadow['image_quality_accepted'] or row['frame_age_ms']>500:continue
                point=shadow['support_pixel']
                if point is None:continue
                observations+=1;key=(model['name'],tuple(point))
                if key not in cache:cache[key]=conditional_point(point,model,camera,heading,model['session'],settings['diagnostic_range_m'])
                result=cache[key]
                if result['available']:vals.append(result['range_m'])
            median=float(np.median(vals)) if vals else None
            old_median=float(np.median(original_values)) if original_values else None
            replay.append(dict(case=case['id'],reference_m=case['reference_m'],model_name=model['name'],rows=len(rows),
                original_quality_passed=observations,numeric_rows=len(vals),median_m=median,
                original_numeric_rows=len(original_values),original_median_m=old_median,
                minus_reference_cm=100*(median-case['reference_m']) if median is not None else None,
                recorded_support_and_quality_kept=True,new_live_confirmation=False))
    out.mkdir(parents=True,exist_ok=False)
    for short,bundle in new_bundles.items():write_json(out/f'{short}_manual_visual_hypotheses_NOT_live.json',bundle)
    write_csv(out/'paper_corner_changes.csv',corner_rows);write_csv(out/'paper_hypotheses.csv',paper_rows)
    write_csv(out/'colour_pixel_vs_reviewed_edge.csv',offsets);write_json(out/'reviewed_edge_details.json',edge_details)
    write_csv(out/'same_frame_factorial_distances.csv',metrics);write_csv(out/'df33_floor_only_replay.csv',replay)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,short in zip(axes,['b559e424','df33e833']):
        rows=[r for r in metrics if r['session'].startswith(short) and '_as_listed_s0_image_plane_plus_thickness' in r['model_name']]
        ids=list(dict.fromkeys(r['item'] for r in rows))
        for geometry,source in [('old_floor','logged_or_rejected_colour_pixel'),('manual_paper_floor','logged_or_rejected_colour_pixel'),
                ('manual_paper_floor','conditional_3D_midpoint_of_reviewed_edge')]:
            selected=[next(r for r in rows if r['item']==i and r['geometry']==geometry and r['source']==source) for i in ids]
            ax.plot(range(len(ids)),[r['range_m'] for r in selected],'o-',label=geometry+' / '+('colour' if source.startswith('logged') else 'manual edge'))
        ax.plot(range(len(ids)),[next(r['reference_m'] for r in rows if r['item']==i) for i in ids],'k--',label='Reported reference')
        ax.set_xticks(range(len(ids)),[i.rsplit('_f',1)[-1] for i in ids]);ax.set_xlabel('Recorded frame');ax.set_ylabel('Conditional range [m]')
        ax.set_title(short+' / same session only');ax.legend(fontsize=6)
    fig.suptitle('Fixed first-listed hypothesis, NOT metric approval\nb559 f32654 colour is a REJECTED proposal, NOT live output',fontsize=11)
    fig.savefig(out/'factor_separation.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,3),layout='constrained')
    ax.bar([r['item'].replace('cone_','') for r in offsets],[r['signed_y_below_reviewed_edge_px'] for r in offsets])
    ax.axhline(0,color='k',lw=.7);ax.set_ylabel('Colour point below reviewed edge [native px]')
    ax.set_title('Manual endpoint + central-camera straight-edge assumption; not contact ground truth')
    fig.savefig(out/'support_pixel_offsets.png',dpi=150);plt.close(fig)
    data=[r for r in replay if '_as_listed_s0_image_plane_plus_thickness' in r['model_name']]
    fig,ax=plt.subplots(figsize=(7,4),layout='constrained')
    reference=[r['reference_m'] for r in data]
    ax.plot(reference,reference,'k--',label='Reported reference')
    ax.plot(reference,[r['original_median_m'] for r in data],'o-',label='Original paper corners')
    ax.plot(reference,[r['median_m'] for r in data],'o-',label='Manual paper corners / same colour points')
    ax.set_xlabel('Reported reference [m]');ax.set_ylabel('Conditional median [m]');ax.legend(fontsize=8)
    ax.set_title('df33 only / floor-only recomputation, NOT new live validation')
    fig.savefig(out/'df33_floor_only_comparison.png',dpi=150);plt.close(fig)
    changed=[p for p,sha in inputs.items() if digest(ROOT/p)!=sha]
    if changed:raise ValueError('input changed during analysis: '+str(changed))
    summary=dict(status='COMPLETED_REVIEWED_COORDINATE_AUDIT_NOT_LIVE_OR_METRIC_APPROVAL',
        human_status_counts=dict(Counter(d['status'] for d in decisions.values())),
        paper_side_assignments={k:d['side_assignment'] for k,d in decisions.items() if d['kind']=='paper'},
        models_per_session={s:len(b['models']) for s,b in new_bundles.items()},paper_corner_count=len(corner_rows),
        image_point_comparisons=len(offsets),factorial_records=len(metrics),df33_replay_records=len(replay),
        same_frame_integer_measurements_crosschecked=recorded_values_reproduced,
        stored_same_frame_model_verdicts_crosschecked=logged_verdicts_checked,
        selected_model=None,source_sha256=inputs,original_images_modified=False,
        physical_edge_identity_and_floor_contact_verified=False,calibration_fitted_to_distance=False,
        runtime_changed=False,usable_for_ffb=False,physical_metric_verified=False)
    write_json(out/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':main()
