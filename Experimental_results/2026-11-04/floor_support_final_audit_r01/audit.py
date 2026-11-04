"""Three offline audits; no calibration selection or runtime changes."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from angular_fisheye_geometry import unproject
from cone_distance_core import load_config, digest, support_from_colour_mask
from cone_fixed_floor_candidate import measure_support
from cone_observation import checked_bbox
from cone_upper_support_candidate import observe_upper_completion
from floor_reference_pose import planar_floor_pose_candidates
from summarize_cone_distance_live import load_frames

DAY=ROOT/'Experimental_results/2026-11-04'


def json_write(path,data):
    path.write_text(json.dumps(data,indent=2,allow_nan=False,ensure_ascii=False)+'\n')


def csv_write(path,rows):
    with path.open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader();writer.writerows(rows)


def rectangle_at_height(rays,normal,plane_height_m):
    """Intersections at the separately reported height, not a height fit."""
    ray=np.asarray(rays,float);normal=np.asarray(normal,float)
    if (ray.shape!=(4,3) or normal.shape!=(3,) or not np.isfinite(ray).all()
            or not np.isfinite(normal).all() or not np.isclose(np.linalg.norm(normal),1)
            or not math.isfinite(plane_height_m) or plane_height_m<=0):
        raise ValueError('four rays, unit up normal and positive height required')
    dot=ray@normal
    if np.any(dot>=-1e-9):return None
    points=ray*(-plane_height_m/dot)[:,None]
    return np.linalg.norm(np.roll(points,-1,axis=0)-points,axis=1)*1000


def context_probe(image,box,candidate,camera,pads):
    """Descriptive crop experiment only. It never grants an observation."""
    x1,y1,x2,y2=checked_bbox(box,1280,720)
    px,pt,pb=pads
    left,right=math.floor(x1)-px,math.ceil(x2)+px
    top,bottom=math.floor(y1)-pt,math.ceil(y2)+pb
    result=dict(crop_xyxy=[left,top,right,bottom],diagnostic_only=True,usable_for_ffb=False)
    if left<0 or top<0 or right>1280 or bottom>720:
        return dict(result,reason='outside_native_image')
    _,valid=unproject([[x,y] for x in (left,right-1) for y in (top,bottom-1)],camera,image_size=(1280,720))
    if not valid.all():return dict(result,reason='outside_calibrated_domain')
    hsv=cv2.cvtColor(image[top:bottom,left:right],cv2.COLOR_BGR2HSV)
    colour=candidate['selected_colour']
    if colour=='red':
        mask=cv2.inRange(hsv,(0,80,30),(10,255,255))|cv2.inRange(hsv,(170,80,30),(179,255,255))
    elif colour=='yellow':mask=cv2.inRange(hsv,(15,80,30),(40,255,255))
    else:return dict(result,reason='no_original_seed_colour')
    a,b,c,d=candidate['seed_xyxy']
    if not(left<=a<c<=right and top<=b<d<=bottom):return dict(result,reason='seed_outside_context')
    labels=cv2.connectedComponents(mask,connectivity=8)[1]
    present=np.unique(labels[b-top:d-top,a-left:c-left]);present=present[present!=0]
    if len(present)!=1:return dict(result,reason='seed_not_one_component')
    label=int(present[0]);yy,xx=np.nonzero(labels==label)
    pixels=np.column_stack((xx+left,yy+top)).astype('<i4')
    xs=np.unique(pixels[:,0]);lo,hi=xs[0],xs[-1]
    lower=[[int(x),int(pixels[pixels[:,0]==x,1].max())] for x in xs if lo+.1*(hi-lo)<=x<=hi-.1*(hi-lo)]
    touches=dict(left=bool(np.any(xx==0)),right=bool(np.any(xx==right-left-1)),
        top=bool(np.any(yy==0)),bottom=bool(np.any(yy==bottom-top-1)))
    obs=support_from_colour_mask(mask,left,top)
    point=obs['point']
    connected=point is not None and int(labels[point[1]-top,point[0]-left])==label
    return dict(result,reason=obs['reason'],point=point,support=obs['support'],
        point_in_original_bbox=bool(point is not None and x1<=point[0]<=x2 and y1<=point[1]<=y2),
        point_connected_to_original_seed=connected,
        pixel_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),pixel_count=len(pixels),
        component_bounds_xyxy=[int(v) for v in [pixels[:,0].min(),pixels[:,1].min(),pixels[:,0].max(),pixels[:,1].max()]],
        touching_edges=touches,original_or_expanded_lower_support=lower)


def assert_same_session(rows,expected_session,expected_model_sha):
    if any(r['session']!=expected_session or r['fixed_floor_load']['state']!='active'
            or r['fixed_floor_shadow']['model_bundle_sha256']!=expected_model_sha for r in rows):
        raise ValueError('distance case must use its own active session/model')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args()
    out=args.output_dir;out.mkdir(parents=True,exist_ok=False)
    settings,camera,heading,_=load_config()
    input_sha={}
    def read(path):
        input_sha[str(path.relative_to(ROOT))]=digest(path)
        return json.loads(path.read_text())
    geometry=[];controls=[];image_sha={};pose_reproduced=0
    for key in ['9b7d9a17','df33e833','b559e424']:
        folder=DAY/f'floor_reference_{key}_r01'
        for report_path in sorted(folder.glob('derived*/derivation_report.json')):
            report=read(report_path)
            for rec in report['poses']:
                rays,valid=unproject(rec['corners_or_grid_native_xy'],camera,image_size=(1280,720))
                if not valid.all():raise ValueError('invalid source rectangle rays')
                repeated=planar_floor_pose_candidates(rec['corners_or_grid_native_xy'],rec['known_plane_points_m'],camera)
                if not np.allclose([c['transform_floor_from_optical'] for c in repeated['candidates']],
                        [c['transform_floor_from_optical'] for c in rec['pose']['candidates']],rtol=0,atol=1e-10):
                    raise ValueError('stored floor solutions do not reproduce')
                pose_reproduced+=len(repeated['candidates'])
                for c in repeated['candidates']:
                    signed=c['camera_height_above_floor_m']
                    normal=np.array(c['up_optical'])*(1 if signed>0 else -1)
                    floor_height=abs(signed)+report['board_thickness_mm']/1000
                    edges=rectangle_at_height(rays,normal,
                        (report['external_floor_height_mm']-report['board_thickness_mm'])/1000)
                    expected=np.tile(rec['dimensions_mm'],2)
                    row=dict(session=report['session'],control=report_path.parent.name,frame=rec['frame'],
                        assignment=rec['assignment'],solution=c['solution_index'],
                        image_plane_height_mm=1000*abs(signed),image_derived_floor_height_mm=1000*floor_height,
                        reported_floor_height_mm=report['external_floor_height_mm'],
                        floor_height_difference_mm=1000*floor_height-report['external_floor_height_mm'],
                        reprojection_rmse_px=c['fit_native_rmse_px'],
                        nominal_optical_up_deviation_deg=float(np.degrees(np.arccos(np.clip(normal@[0,-1,0],-1,1)))),
                        nominal_up_is_not_measured_gravity=True,normal_x=normal[0],normal_y=normal[1],normal_z=normal[2],
                        side_01_expected_mm=rec['dimensions_mm'][0],side_12_expected_mm=rec['dimensions_mm'][1],
                        positive_plane_rays_at_reported_height=edges is not None,selected=False,usable_for_ffb=False)
                    if edges is not None:
                        row.update({f'side_{i}_at_reported_height_mm':v for i,v in enumerate(edges)})
                        row['side_residual_rms_mm']=float(np.sqrt(np.mean((edges-expected)**2)))
                    geometry.append(row)
            for name,hashed in report['source_sha256'].items():
                if name.endswith('.png'):
                    # Old reports can refer to Downloads; use the byte-identical archived copy.
                    path=ROOT/f'recordings/2026-11-04/floor_reference_{key}_r01'/Path(name).name
                    if digest(path)!=hashed:raise ValueError('floor source image changed')
                    input_sha[str(path.relative_to(ROOT))]=hashed;image_sha[str(path.relative_to(ROOT))]=hashed
        for assignment in ['as_listed','swapped']:
            family=[r for r in geometry if r['session'].startswith(key) and r['assignment']==assignment and r['solution']==0]
            controls.append(dict(session=family[0]['session'],assignment=assignment,
                floor_height_min_mm=min(r['image_derived_floor_height_mm'] for r in family),
                floor_height_max_mm=max(r['image_derived_floor_height_mm'] for r in family),
                controls=len(family),confidence_interval=False,usable_for_ffb=False))
    csv_write(out/'paper_geometry.csv',geometry);csv_write(out/'corner_controls.csv',controls)
    # Compare each recording using its own prepared bundle only. No model transfer or fitted offset.
    spec=read(DAY/'floor_df33e833_multidistance_r01/cases.json')
    prepared=DAY/'floor_reference_df33e833_r01/derived_primary_r01/prepared_floor.json'
    dfbundle=read(prepared)
    if digest(prepared)!=spec['bundle_sha256']:raise ValueError('df33 prepared bytes mismatch')
    distances=[];model_points=Counter();measured_values=0
    for case in spec['cases']:
        path=ROOT/case['input'];rows,truncated,sha=load_frames(path)
        if truncated or sha!=case['sha256']:raise ValueError('case changed or truncated')
        input_sha[case['input']]=sha
        assert_same_session(rows,spec['session'],spec['bundle_sha256'])
        if case['image']:
            if digest(ROOT/case['image'])!=case['image_sha256']:raise ValueError('distance image changed')
            input_sha[case['image']]=case['image_sha256']
        for model in dfbundle['models']:
            vals=[]
            for r in rows:
                m=next(m for m in r['fixed_floor_shadow']['models'] if m['model_name']==model['name'])
                if not m['range_available']:continue
                measured=measure_support(r['fixed_floor_shadow']['support_pixel'],model,camera,heading,
                    session=r['session'],diagnostic_range_m=settings['diagnostic_range_m'])
                if not measured['range_available'] or abs(measured['horizontal_camera_foot_range_m']-m['horizontal_camera_foot_range_m'])>1e-10:
                    raise ValueError('distance recomputation mismatch')
                vals.append(m['horizontal_camera_foot_range_m']);measured_values+=1
            med=float(np.median(vals)) if vals else None
            distances.append(dict(session=spec['session'],model_sha256=spec['bundle_sha256'],
                case=case['id'],branch='legacy',reference_m=case['reference_m'],reference_status=case['reference_status'],
                model_name=model['name'],rows=len(rows),numeric_rows=len(vals),numeric_fraction=len(vals)/len(rows),
                median_m=med,median_minus_reference_cm=100*(med-case['reference_m']) if med is not None else None,
                physical_point_equivalence_verified=False,model_selected=False))
    cap=read(DAY/'upper_support_capture_analysis_r01/results_r02/audit.json')
    ref=read(DAY/'upper_support_capture_analysis_r01/reference.json')
    capture_root=(ROOT/Path(cap['extracted_root'])).resolve()
    capture_root.relative_to(ROOT)
    bprepared=capture_root/'prepared_floor.json'
    bbundle=read(bprepared)
    if digest(bprepared)!=cap['model_sha256'] or bbundle['session']!=ref['session']:
        raise ValueError('b559 own model/session mismatch')
    for branch in ['legacy','upper']:
        for model in bbundle['models']:
            v=cap['model_ranges_m'].get(branch+'__'+model['name'])
            count=v['count'] if v else 0
            median=v['median'] if v else None
            distances.append(dict(session=ref['session'],model_sha256=cap['model_sha256'],case='z1p00',
                branch=branch,reference_m=ref['distance_m'],reference_status='user_confirmed',model_name=model['name'],
                rows=cap['counts']['active']['rows'],numeric_rows=count,numeric_fraction=count/cap['counts']['active']['rows'],
                median_m=median,median_minus_reference_cm=100*(median-ref['distance_m']) if v else None,
                physical_point_equivalence_verified=False,model_selected=False))
    csv_write(out/'session_distance_comparison.csv',distances)
    # Audit all saved native refusal/recovery images using exactly their logged detector bbox.
    root=capture_root;log=root/'upper_support_comparison.jsonl'
    if digest(log)!=cap['input_sha256']['upper_support_comparison.jsonl']:raise ValueError('upper log changed')
    input_sha[str(log.relative_to(ROOT))]=digest(log)
    probes=[];probe_rows=[];same_frame=0
    for line in log.open():
        r=json.loads(line)
        if r['evidence']['status']!='saved':continue
        path=root/r['evidence']['file'];before=digest(path)
        if before!=r['evidence']['sha256']:raise ValueError('saved evidence changed')
        image=cv2.imread(str(path));original=image.copy()
        candidate=observe_upper_completion(image,r['selected_detector_boxes'][0],camera)
        if candidate!=r['upper_candidate']:raise ValueError('same-frame candidate mismatch')
        same_frame+=1;input_sha[str(path.relative_to(ROOT))]=before
        contexts={name:context_probe(image,r['selected_detector_boxes'][0],candidate,camera,pad)
            for name,pad in [('original',(4,4,4)),('top16',(4,16,4)),('top32',(4,32,4)),
                ('lateral16',(16,4,4)),('lateral32',(32,4,4)),('bottom16',(4,4,16)),('bottom32',(4,4,32))]}
        probes.append(dict(session=r['session'],frame=r['frame'],image=str(path.relative_to(ROOT)),
            original_decision=candidate['upper_completion_reason'],contexts=contexts,
            original_point=candidate['point'],not_production_observations=True,usable_for_ffb=False))
        for family in ['top','lateral','bottom']:
            a,b=contexts[family+'16'],contexts[family+'32']
            closed=all(c.get('point') is not None and not any(c.get('touching_edges',{}).values()) for c in [a,b])
            same=(a.get('pixel_sha256') is not None and a.get('pixel_sha256')==b.get('pixel_sha256')
                  and a.get('support')==b.get('support') and a.get('point')==b.get('point'))
            preserves_lower=a.get('support') is not None and a.get('support')==contexts['original'].get('original_or_expanded_lower_support')
            probe_rows.append(dict(frame=r['frame'],direction=family,closed_in_both=closed,
                same_component_and_support=same,original_lower_support_unchanged=preserves_lower,
                proposed_point=str(a.get('point')),point_in_original_bbox=a.get('point_in_original_bbox',False),
                seed_connected=a.get('point_connected_to_original_seed',False),original_decision=candidate['upper_completion_reason'],
                new_runtime_grant=False,physical_contact_verified=False))
        if not np.array_equal(image,original) or digest(path)!=before:raise ValueError('image modified')
    csv_write(out/'saved_frame_contexts.csv',probe_rows);json_write(out/'saved_frame_contexts.json',probes)
    # Present session-scoped series; do not pool or call separate sessions an A/B experiment.
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,key in zip(axes,['df33e833','b559e424']):
        subset=[r for r in distances if r['session'].startswith(key) and r['branch']=='legacy'
            and '_as_listed_s0_image_plane_plus_thickness' in r['model_name']]
        subset.sort(key=lambda r:r['reference_m'])
        ax.plot([r['reference_m'] for r in subset],[r['median_m'] for r in subset],'o-',label='First-listed own-session model')
        ax.plot([1,2],[1,2],'k--',label='Reported reference')
        ax.set_title(key+' / own model only');ax.set_xlabel('Reported reference [m]');ax.set_ylabel('Conditional median [m]')
        ax.legend(fontsize=7);ax.grid(alpha=.2)
    fig.suptitle('Separate sessions, NOT calibration transfer or accuracy approval')
    fig.savefig(out/'session_distances.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    labels=[];heights=[]
    for r in geometry:
        if r['control']=='derived_primary_r01' and r['solution']==0:
            labels.append(r['session'][:8]+'\n'+r['assignment']);heights.append(r['image_derived_floor_height_mm'])
    ax.bar(labels,heights);ax.axhline(590,color='k',ls='--',label='Reported lens-floor height, not exact ground truth')
    ax.set_ylabel('Paper-derived floor height [mm]');ax.legend(fontsize=8)
    ax.set_title('Independent dimension/height check; no candidate selected')
    fig.savefig(out/'paper_height_consistency.png',dpi=150);plt.close(fig)
    summary=dict(status='THREE_OFFLINE_AUDITS_COMPLETED_NOT_METRIC_OR_FFB_APPROVAL',
        pose_solutions_reproduced=pose_reproduced,paper_geometry_records=len(geometry),
        distance_rows_revalidated=1800,df33_distance_values_recomputed=measured_values,
        b559_paired_rows_prior_audit_reused=cap['validated_paired_rows'],
        distance_comparison_rows=len(distances),native_saved_frames_reproduced=same_frame,
        context_probes=len(probe_rows),source_sha256=input_sha,
        selected_model=None,height_tolerance_invented=False,calibration_fitted=False,
        mixed_session_calibration=False,original_images_modified=False,
        runtime_changed=False,physical_metric_verified=False,usable_for_ffb=False)
    json_write(out/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':main()
