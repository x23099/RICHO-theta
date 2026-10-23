"""Frozen poses and unchanged quality gate -> metric comparisons, never hardware."""
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(ROOT/'src'),str(OLD)]
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate,unproject,floor_from_rays,segment_from_rays
from scene_geometry import align_up_preserving_heading_reference


def key(r):return r['session'],int(r['frame'])


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:groups[r['dataset'],r['condition'],r['model']].append(r)
    output=[]
    for (dataset,condition,model),group in sorted(groups.items()):
        for window in ('all','heldout_time'):
            base=[r for r in group if window=='all' or r['time_role']=='heldout']
            for population in ('geometry_only','quality_gated'):
                used=[r for r in base if r['geometry_estimated'] and (population=='geometry_only' or r['measurement_emitted'])]
                reference=group[0]['reference_z_m']
                errors=np.array([r['raw_floor_z_m']-reference for r in used]) if reference is not None else np.array([])
                med=lambda k:float(np.median([r[k] for r in used if r[k] is not None])) if any(r[k] is not None for r in used) else None
                output.append(dict(dataset=dataset,condition=condition,model=model,time_window=window,population=population,
                    all_frames=len(base),estimated=len(used),estimated_fraction=len(used)/len(base) if base else 0,
                    reference_z_m=reference,z_median_m=med('raw_floor_z_m'),radial_median_m=med('raw_floor_radial_m'),
                    z_median_bias_m=float(np.median(errors)) if len(errors) else None,
                    z_abs_error_p95_m=float(np.percentile(abs(errors),95)) if len(errors) else None,
                    z_abs_error_max_m=float(abs(errors).max()) if len(errors) else None,
                    abs_error_over20cm_frames=int((abs(errors)>.2).sum()) if len(errors) else None,
                    height_z_median_m=med('height_z_m'),height_base_median_m=med('height_base_m'),
                    usable_for_ffb=False))
    return output


def main():
    output=HERE/'metric_results_r01'
    if output.exists():raise ValueError('new metric output required; no overwrite')
    observed_path=ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    sources={str(p):sha256(p) for p in (observed_path,candidate,floor,HERE/'method.md',Path(__file__),
        ROOT/'src/angular_fisheye_geometry.py',ROOT/'src/fisheye_floor_geometry.py',OLD/'scene_geometry.py')}
    camera=camera_from_candidate(json.loads(candidate.read_text()));Tprior=np.array(json.loads(floor.read_text())['transform_target_from_source'])
    models={}
    for name,folder in [('uniform_images','scene_results_r01'),('pooled_planes','pooled_results_r01')]:
        p=HERE/folder/'session_hypotheses.csv';sources[str(p)]=sha256(p)
        proof=json.loads((HERE/folder/'summary.json').read_text());sources[str(HERE/folder/'summary.json')]=sha256(HERE/folder/'summary.json')
        assert proof['output_sha256'][p.name]==sha256(p)
        models[name]={r['session']:np.array(json.loads(r['conditional_transform_json'])) for r in read_csv(p) if r['metric_eligible']=='True'}
    quality_path=HERE/'quality_results_r01/all_frame_quality.csv';quality_proof=HERE/'quality_results_r01/summary.json'
    sources[str(quality_path)]=sha256(quality_path);sources[str(quality_proof)]=sha256(quality_proof)
    quality_info=json.loads(quality_proof.read_text())
    assert quality_info['historical_decision_mismatches']==0 and quality_info['prefix_invariance_verified']
    assert quality_info['output_sha256'][quality_path.name]==sha256(quality_path)
    quality={key(r):r for r in read_csv(quality_path)}
    plan_path=HERE/'intake_r01/sampling_plan.json';sources[str(plan_path)]=sha256(plan_path)
    plans=json.loads(plan_path.read_text())['sessions']
    middle={r['session']:(r['first_time_sec']+r['last_time_sec'])/2 for r in plans}
    observed=read_csv(observed_path);rows=[]
    assert len(observed)==len(quality)==6876
    for model,poses in models.items():
        for source in observed:
            q=quality[key(source)];accepted=q['quality_accepted']=='True'
            assert accepted==(source['quality_accepted']=='True')
            T=poses.get(source['session']);pair=json.loads(source['native_colour_pair_json']) if source['native_colour_pair_json'] else None
            row=dict(dataset=source['dataset'],session=source['session'],frame=int(source['frame']),time_sec=float(source['time_sec']),
                time_role='estimate' if float(source['time_sec'])<middle[source['session']] else 'heldout',
                condition=source['condition'],model=model,reference_z_m=float(source['reference_z_m']) if source['reference_z_m'] else None,
                pose_temporally_checked=T is not None,quality_accepted=accepted,quality_reason=q['reason'],
                geometry_estimated=False,measurement_emitted=False,raw_floor_x_right_m=None,raw_floor_z_m=None,
                raw_floor_radial_m=None,emitted_floor_z_m=None,height_z_m=None,height_base_m=None,tip_elevation_deg=None,
                reason='no_temporally_checked_pose' if T is None else 'missing_colour_pair',
                distance_imputed=False,floor_contact_verified=False,usable_for_ffb=False)
            if T is not None and pair is not None:
                rays,valid=unproject(pair,camera,image_size=(1280,720))
                if valid.all():
                    p,v=floor_from_rays(rays[1:],valid[1:],T);height=segment_from_rays(rays,T)
                    if v[0]:
                        row.update(geometry_estimated=True,raw_floor_x_right_m=float(-p[0,1]),raw_floor_z_m=float(p[0,0]),
                            raw_floor_radial_m=float(np.linalg.norm(p[0,:2])),
                            tip_elevation_deg=float(np.degrees(np.arcsin(np.clip((T[:3,:3]@rays[0])[2],-1,1)))),
                            measurement_emitted=accepted,emitted_floor_z_m=float(p[0,0]) if accepted else None,
                            reason='conditional_current_frame_measurement' if accepted else 'quality_withheld:'+q['reason'])
                    if height['estimated']:row.update(height_z_m=height['base_target_m'][0],height_base_m=height['base_target_m'][2])
            if not row['measurement_emitted']:assert row['emitted_floor_z_m'] is None
            rows.append(row)
    # Re-evaluate floor reference points only when their OWN session has a checked pose.
    paper_path=ROOT/'Experimental_results/2026-10-15/paper_reference7_r01/analysis_r01/reference_points_primary170.csv'
    paired_path=ROOT/'Experimental_results/2026-10-19/paper_cone_2m_validation_r01/analysis_r01/summary.json'
    for p in (paper_path,paired_path):sources[str(p)]=sha256(p)
    paper=[dict(r,session='itiawase2_20261015_183552_599') for r in read_csv(paper_path)]
    pair=json.loads(paired_path.read_text())
    paper.append(dict(point_id='paper_cone_2m',session='paper_cone_center_z2p00_r01_20261019_180411_245',
        pixel_x=pair['paper_reference_native_xy'][0],pixel_y=pair['paper_reference_native_xy'][1],reference_x_m=0.,reference_z_m=2.))
    paper_rows=[]
    for model,poses in models.items():
        for r in paper:
            T=poses.get(r['session']);record=dict(model=model,session=r['session'],point_id=r['point_id'],estimated=False,
                reference_x_m=float(r['reference_x_m']),reference_z_m=float(r['reference_z_m']),
                z_forward_m=None,x_right_m=None,reason='no_own_session_checked_pose',usable_for_ffb=False)
            if T is not None:
                ray,valid=unproject([[float(r['pixel_x']),float(r['pixel_y'])]],camera,image_size=(1280,720))
                p,v=floor_from_rays(ray,valid,T)
                if v[0]:record.update(estimated=True,z_forward_m=float(p[0,0]),x_right_m=float(-p[0,1]),reason='conditional_floor_reference')
            paper_rows.append(record)
    # Empirical scene-direction sensitivity, not a statistical accuracy interval.
    scene_frames=HERE/'scene_results_r01/image_diagnostics.csv';sources[str(scene_frames)]=sha256(scene_frames)
    hypotheses=read_csv(scene_frames);sensitivity=[]
    for session in models['uniform_images']:
        frames=[r for r in hypotheses if r['session']==session and r['role']=='heldout' and r['accepted']=='True']
        conditions=sorted({r['condition'] for r in observed if r['session']==session and r['reference_z_m']})
        for condition in conditions:
            population=[r for r in observed if r['session']==session and r['condition']==condition and r['native_colour_pair_json'] and quality[key(r)]['quality_accepted']=='True']
            pixels=np.array([json.loads(r['native_colour_pair_json']) for r in population]);median=np.median(pixels,axis=0)
            index=int(np.argmin(np.linalg.norm(pixels-median,axis=(1,2))));representative=population[index]
            ray,valid=unproject([pixels[index,1]],camera,image_size=(1280,720))
            for h in frames:
                T=align_up_preserving_heading_reference(Tprior,json.loads(h['up_optical_json']))
                p,v=floor_from_rays(ray,valid,T)
                sensitivity.append(dict(session=session,condition=condition,observed_frame=int(representative['frame']),
                    actual_bottom_native_json=json.dumps(pixels[index,1].tolist()),hypothesis_frame=int(h['frame']),
                    estimated=bool(v[0]),z_forward_m=float(p[0,0]) if v[0] else None,
                    uncertainty_confidence_interval=False,usable_for_ffb=False))
    assert len(rows)==2*6876 and all(sha256(Path(p))==h for p,h in sources.items())
    output.mkdir()
    write_csv(output/'all_frame_metrics.csv',rows);write_csv(output/'condition_summary.csv',summarize(rows))
    write_csv(output/'paper_reference_results.csv',paper_rows)
    write_csv(output/'empirical_pose_sensitivity.csv',sensitivity,fields=['session','condition','observed_frame','actual_bottom_native_json','hypothesis_frame','estimated','z_forward_m','uncertainty_confidence_interval','usable_for_ffb'])
    write_csv(output/'occlusion_comparison.csv',[r for r in rows if r['dataset']=='sequence' and 1110<=r['frame']<=1155])
    report=dict(status='COMPLETED_METRIC_AND_CAUSAL_QUALITY_COMPARISON',work_date='2026-10-22',source_sha256=sources,
        input_frames=6876,comparison_rows=len(rows),metric_labels_used_for_pose=False,
        geometry_only_and_quality_gated_both_retained=True,heldout_time_evaluation_separate=True,
        rejected_observations_imputed=0,production_settings_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([r for r in summarize(rows) if r['estimated'] and r['reference_z_m'] is not None and r['time_window']=='all'],indent=2))


if __name__=='__main__':main()
