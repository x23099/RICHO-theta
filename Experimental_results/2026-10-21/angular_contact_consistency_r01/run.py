"""Frozen native ray-plane selection and necessary floor/height checks."""
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate,unproject,segment_from_rays
from contact_geometry import choose_observed_root,central_support,floor_implied_tip_heights


def key(r):return r['dataset'],r['session'],int(r['frame'])


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:groups[r['dataset'],r['condition'],r['model'],r['offset_m']].append(r)
    summary=[]
    for (dataset,condition,model,offset),group in sorted(groups.items()):
        selected=[r for r in group if r['estimated']]
        support=[r for r in group if r['support_tip_height_max_m'] is not None]
        known=[r for r in group if r['tip_elevation_deg'] is not None]
        med=lambda name:float(np.median([r[name] for r in selected if r[name] is not None])) if any(r[name] is not None for r in selected) else None
        ref=group[0]['reference_z_m']
        summary.append(dict(dataset=dataset,condition=condition,model=model,offset_m=offset,frames=len(group),
            evaluated_tip_frames=len(known),tip_not_above_camera_frames=sum(r['tip_elevation_deg']<=0 for r in known),
            tip_elevation_median_deg=float(np.median([r['tip_elevation_deg'] for r in known])) if known else None,
            support_evaluated_frames=len(support),support_all_below_known_height_frames=sum(r['support_tip_height_max_m']<.73 for r in support),
            support_tip_height_min_median_m=float(np.median([r['support_tip_height_min_m'] for r in support])) if support else None,
            support_tip_height_max_median_m=float(np.median([r['support_tip_height_max_m'] for r in support])) if support else None,
            estimated_frames=len(selected),reference_z_m=ref,
            old_height_z_matched_median_m=med('old_height_z_m'),old_base_height_matched_median_m=med('old_height_base_m'),
            selected_height_z_median_m=med('selected_height_z_m'),selected_floor_z_median_m=med('selected_floor_z_m'),
            selected_height_base_height_median_m=med('selected_height_base_m'),
            selected_floor_implied_tip_height_median_m=med('selected_floor_tip_height_m'),
            selected_height_residual_median_m=med('selected_height_residual_m'),
            selected_shift_x_median_px=med('selected_shift_x_px'),selected_shift_y_median_px=med('selected_shift_y_px'),
            selected_plane_angle_median_deg=med('selected_plane_angle_deg'),
            all_reason_counts=json.dumps(dict(Counter(r['reason'] for r in group))),
            physical_contact_verified=False,usable_for_ffb=False))
    return summary


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    previous=HERE.parent/'angular_metric_validation_r01/results_r01'
    candidate=HERE.parent/'front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    observed_path=HERE.parent/'cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    envelope_paths=[ROOT/'Experimental_results/2026-10-19/cone_support_extent_r01/results_r01/lower_envelopes.csv',
                   HERE.parent/'cone_known_size_pinhole_r01/results_r01/additional_full_envelopes.csv']
    inputs=[candidate,observed_path,*envelope_paths,previous/'summary.json',previous/'cone_all_frame_results.csv',
            HERE/'method.md',HERE/'contact_geometry.py',Path(__file__),ROOT/'src/angular_fisheye_geometry.py',
            ROOT/'src/fisheye_floor_geometry.py',ROOT/'src/cone_dataset.py']
    sources={str(p):sha256(p) for p in inputs}
    # Verify each reused CSV against the earlier frozen producer manifest.
    for data_path in [observed_path,*envelope_paths]:
        producer=data_path.parent/'provenance.json'
        manifest=json.loads(producer.read_text())
        assert manifest['output_sha256'][data_path.name]==sha256(data_path),data_path
        sources[str(producer)]=sha256(producer)
    old=json.loads((previous/'summary.json').read_text())
    for name,digest in old['output_sha256'].items():assert sha256(previous/name)==digest,name
    camera=camera_from_candidate(json.loads(candidate.read_text()))
    tf=old['floor_fit']
    transforms={'angular_nominal':np.array(tf['nominal_transform']),
                'angular_paper5_rotation':np.array(tf['transform_target_from_source'])}
    observed=read_csv(observed_path)
    assert len(observed)==6876 and len({key(r) for r in observed})==6876
    baseline={}
    with (previous/'cone_all_frame_results.csv').open(newline='') as stream:
        for r in csv.DictReader(stream):
            if r['model'] in transforms and r['method'] in ('height_vertical_proxy','height_near_edge_assumption'):
                offset=0. if r['method']=='height_vertical_proxy' else .1875
                baseline[key(r),r['model'],offset]=r
    envelopes=defaultdict(list)
    for p in envelope_paths:
        for r in read_csv(p):envelopes[key(r)].append([float(r['x']),float(r['y'])])
    envelopes={k:np.array(v) for k,v in envelopes.items()}
    pairs={key(r):np.array(json.loads(r['native_colour_pair_json'])) for r in observed if r['native_colour_pair_json']}
    unique=np.unique(np.vstack([*envelopes.values(),*[p for p in pairs.values()]]),axis=0)
    rays,valid=unproject(unique,camera,image_size=(1280,720))
    cache={tuple(p):(r,bool(v)) for p,r,v in zip(unique,rays,valid)}
    rows=[]
    for model,T in transforms.items():
        for number,source in enumerate(observed):
            pair=pairs.get(key(source));env=envelopes.get(key(source))
            available=pair is not None and env is not None
            if available:
                tip,tip_valid=cache[tuple(pair[0])]
                er=np.array([cache[tuple(p)][0] for p in env]);ev=np.array([cache[tuple(p)][1] for p in env])
                available=tip_valid
            for offset in (0.,.1875):
                prior=baseline[key(source),model,offset]
                row=dict(dataset=source['dataset'],session=source['session'],frame=int(source['frame']),
                    time_sec=float(source['time_sec']),condition=source['condition'],model=model,offset_m=offset,
                    reference_z_m=float(source['reference_z_m']) if source['reference_z_m'] else None,
                    estimated=False,reason='missing_tip_or_envelope',selected_native_json='',root_groups=None,
                    old_height_z_m=float(prior['z_forward_m']) if prior['estimated']=='True' else None,
                    old_height_base_m=float(prior['base_height_m']) if prior['estimated']=='True' else None,
                    selected_height_z_m=None,selected_floor_z_m=None,selected_height_base_m=None,
                    selected_floor_tip_height_m=None,selected_floor_horizontal_residual_m=None,
                    selected_height_residual_m=None,selected_shift_x_px=None,selected_shift_y_px=None,
                    selected_plane_angle_deg=None,tip_elevation_deg=None,
                    support_tip_height_min_m=None,support_tip_height_max_m=None,
                    physical_contact_verified=False,usable_for_ffb=False)
                if available:
                    floor=floor_implied_tip_heights(tip,er,ev,T,offset_m=offset)
                    row['tip_elevation_deg']=floor['tip_elevation_deg']
                    active=central_support(env)&floor['accepted']
                    if active.any():
                        row.update(support_tip_height_min_m=float(floor['tip_heights'][active].min()),
                                   support_tip_height_max_m=float(floor['tip_heights'][active].max()))
                    choice=choose_observed_root(env,er,ev,tip,T,offset_m=offset)
                    row.update(reason=choice['reason'],root_groups=choice['root_groups'])
                    if choice['selected']:
                        i=choice['index'];segment=segment_from_rays([tip,er[i]],T,tip_forward_offset_m=offset)
                        row.update(selected_native_json=json.dumps(env[i].tolist()),
                            selected_shift_x_px=float(env[i,0]-pair[1,0]),selected_shift_y_px=float(env[i,1]-pair[1,1]),
                            selected_plane_angle_deg=choice['plane_angle_deg'])
                        if segment['estimated'] and floor['accepted'][i]:
                            row.update(estimated=True,selected_height_z_m=segment['base_target_m'][0],
                                selected_floor_z_m=float(floor['points'][i,0]),selected_height_base_m=segment['base_target_m'][2],
                                selected_height_residual_m=segment['residual_m'],
                                selected_floor_tip_height_m=float(floor['tip_heights'][i]),
                                selected_floor_horizontal_residual_m=float(floor['horizontal_residuals'][i]))
                        else:row['reason']='selected_but_nonpositive_or_degenerate_geometry'
                rows.append(row)
            if number%2000==0:print(model,number,flush=True)
    assert len(rows)==6876*4
    assert all(sha256(Path(p))==v for p,v in sources.items())
    output.mkdir()
    write_csv(output/'all_frame_results.csv',rows)
    summary=summarize(rows);write_csv(output/'condition_summary.csv',summary)
    report=dict(status='COMPLETED_CONDITIONAL_CONTACT_DIAGNOSIS_NOT_FFB_APPROVAL',frames=6876,rows=len(rows),
        cached_native_points=len(unique),source_sha256=sources,original_images_edited=False,
        geometry_refitted=False,new_yolo_inference=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([r for r in summary if r['model']=='angular_paper5_rotation' and r['reference_z_m'] is not None],indent=2))


if __name__=='__main__':main()
