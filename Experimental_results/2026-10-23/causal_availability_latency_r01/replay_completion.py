"""Local-service-cost counterfactual; current cone observations cost zero here."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
CAUSAL=HERE.parent/'causal_pose_replay_r01'
sys.path.insert(0,str(CAUSAL))
from replay_saved import UNIFORM,CONTRACT,key,flag
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import align_up_preserving_heading_reference
from angular_fisheye_geometry import camera_from_candidate,unproject,floor_from_rays
from finish_aware import schedule,FinishAwarePose

SCENARIOS=('zero_service_reference','local_three_pass_median','local_three_pass_observed_max')


def diagnostic_row(ob,q,pose,camera,Tprior):
    raw=None
    if pose['pose_available'] and ob['native_colour_pair_json']:
        pair=json.loads(ob['native_colour_pair_json']);rays,valid=unproject(pair,camera,image_size=(1280,720))
        T=align_up_preserving_heading_reference(Tprior,pose['up_optical'])
        xyz,valid=floor_from_rays(rays[1:],valid[1:],T)
        if valid[0] and float(xyz[0,0])>0:raw=float(xyz[0,0])
    available=raw is not None and flag(q['quality_accepted'])
    return dict(raw_floor_z_m=raw,quality_accepted=flag(q['quality_accepted']),diagnostic_available=available,
        diagnostic_z_m=raw if available else None,distance_imputed=False,physical_metric_verified=False,usable_for_ffb=False)


def replay(samples,observations,quality,service,camera,Tprior):
    jobs=schedule(samples,service);worker=FinishAwarePose(jobs);rows=[];release_index=0;latest_released=None
    for ob in observations:
        frame=int(ob['frame']);t=float(ob['time_sec']);pose=worker.query(frame,t)
        while release_index<len(jobs) and jobs[release_index]['release_sec']<=t:
            latest_released=jobs[release_index];release_index+=1
        # Post-hoc diagnostic only. Never used by worker or by the distance gate.
        pending_rejection=bool(latest_released is not None and latest_released['sample']['accepted']=='False'
            and latest_released['frame']>pose['latest_scene_frame'])
        q=quality[frame];assert float(q['time_sec'])==t
        result=diagnostic_row(ob,q,pose,camera,Tprior)
        rows.append(dict(frame=frame,time_sec=t,pose_available=pose['pose_available'],pose_reason=pose['pose_reason'],initialized=pose['initialized'],
            latest_completed_scene_frame=pose['latest_scene_frame'],latest_scene_source_time_sec=pose['latest_scene_time_sec'],
            source_age_sec=pose['latest_scene_age_sec'],newer_unfinished_rejection_posthoc=pending_rejection,**result))
    return rows,jobs,worker.events


def loss_reason(row):
    if flag(row['diagnostic_available']):return 'retained'
    if not flag(row['initialized']):return 'not_initialized_yet'
    if not flag(row['pose_available']):return row['pose_reason']
    if not flag(row['quality_accepted']):return 'current_image_quality_withheld'
    if not row['raw_floor_z_m']:return 'current_colour_or_floor_intersection_unavailable'
    raise ValueError('unaccounted diagnostic loss')


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new replay output required')
    benchmark=HERE/'benchmark_r01';proof=json.loads((benchmark/'summary.json').read_text())
    for name,h in proof['output_sha256'].items():assert sha256(benchmark/name)==h
    for p,h in proof['source_sha256'].items():assert sha256(Path(p))==h,p
    session=proof['benchmark_session']
    paths=[Path(__file__),HERE/'method.md',HERE/'finish_aware.py',CAUSAL/'causal_pose.py',benchmark/'summary.json',
        benchmark/'scene_stage_measurements.csv',CAUSAL/'results_r01/frame_metrics.csv',
        UNIFORM/'metric_results_r01/all_frame_metrics.csv',UNIFORM/'scene_results_r01/image_diagnostics.csv',
        UNIFORM/'quality_results_r01/all_frame_quality.csv',
        ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv',
        ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json',
        ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json']
    sources={str(p):sha256(p) for p in paths}
    previous=read_csv(paths[6]);historical={(key(r),r['model']):r for r in read_csv(paths[7])}
    parts=[]
    for mode in ('sample_only','bounded_between_samples_1s'):
        selected=[r for r in previous if r['mode']==mode and flag(historical[key(r),'uniform_images']['measurement_emitted'])]
        assert len(selected)==1107
        counts=Counter(loss_reason(r) for r in selected)
        parts.extend(dict(mode=mode,population='historical_1107_diagnostic_frames',reason=reason,frames=n,
            mutually_exclusive=True,total_population=len(selected)) for reason,n in sorted(counts.items()))
    samples=[r for r in read_csv(paths[8]) if r['session']==session]
    obs=[r for r in read_csv(paths[10]) if r['session']==session]
    quality={int(r['frame']):r for r in read_csv(paths[9]) if r['session']==session}
    costs=defaultdict(list)
    for r in read_csv(paths[5]):costs[int(r['frame'])].append(float(r['scene_service_ms'])/1000.)
    assert set(costs)=={int(r['frame']) for r in samples} and all(len(v)==3 for v in costs.values())
    camera=camera_from_candidate(json.loads(paths[11].read_text()));T=np.array(json.loads(paths[12].read_text())['transform_target_from_source'])
    rows=[];jobs=[];events=[];summaries=[];conditions=[]
    reference={int(r['frame']):r for r in previous if r['session']==session and r['mode']=='bounded_between_samples_1s'}
    for scenario in SCENARIOS:
        service={f:0. if scenario=='zero_service_reference' else float(np.median(v)) if scenario=='local_three_pass_median' else max(v) for f,v in costs.items()}
        current,scheduled,applied=replay(samples,obs,quality,service,camera,T)
        for r,ob in zip(current,obs):
            if scenario=='zero_service_reference':
                old=reference[r['frame']]
                assert r['pose_available']==flag(old['pose_available']) and r['diagnostic_available']==flag(old['diagnostic_available'])
                assert r['diagnostic_z_m']==(float(old['diagnostic_z_m']) if old['diagnostic_z_m'] else None)
            rows.append(dict(session=session,scenario=scenario,**r,condition=ob['condition'],reference_z_m=ob['reference_z_m']))
        jobs.extend(dict(scenario=scenario,**{k:v for k,v in j.items() if k!='sample'}) for j in scheduled)
        events.extend(dict(scenario=scenario,**e) for e in applied)
        initial=[e for e in applied if e['initialization_event']]
        retained=sum(r['diagnostic_available'] and flag(reference[r['frame']]['diagnostic_available']) for r in current)
        extra=sum(r['diagnostic_available'] and not flag(reference[r['frame']]['diagnostic_available']) for r in current)
        summaries.append(dict(scenario=scenario,frames=len(current),diagnostic_frames=sum(r['diagnostic_available'] for r in current),
            retained_from_zero_service=retained,lost_from_zero_service=377-retained,additional_vs_zero_service=extra,
            outputs_with_newer_unfinished_rejection=sum(r['diagnostic_available'] and r['newer_unfinished_rejection_posthoc'] for r in current),
            max_queue_wait_sec=max(j['queue_wait_sec'] for j in scheduled),
            initialization_source_time_sec=initial[0]['source_time_sec'] if initial else None,
            initialization_completion_time_sec=initial[0]['completion_time_sec'] if initial else None,
            initialization_first_query_time_sec=initial[0]['first_query_time_sec'] if initial else None,
            cone_query_compute_cost_simulated=False,physical_metric_verified=False,usable_for_ffb=False))
        groups=defaultdict(list)
        for r,ob in zip(current,obs):
            if ob['reference_z_m']:groups[ob['condition']].append((r,ob))
        for condition,group in sorted(groups.items()):
            used=[r for r,_ in group if r['diagnostic_available']];ref=float(group[0][1]['reference_z_m'])
            conditions.append(dict(scenario=scenario,condition=condition,frames=len(group),diagnostic_frames=len(used),reference_z_m=ref,
                z_median_m=float(np.median([r['diagnostic_z_m'] for r in used])) if used else None,physical_metric_verified=False,usable_for_ffb=False))
    assert len(rows)==3*1547 and all(sha256(Path(p))==h for p,h in sources.items())
    output.mkdir()
    for name,data in [('historical_loss_partition.csv',parts),('completion_frame_metrics.csv',rows),('scene_job_schedule.csv',jobs),
        ('applied_scene_events.csv',events),('completion_summary.csv',summaries),('condition_summary.csv',conditions)]:write_csv(output/name,data)
    report=dict(status='COMPLETED_COMPLETION_AWARE_COUNTERFACTUAL_NOT_END_TO_END_MEASUREMENT',work_date='2026-10-23',source_sha256=sources,
        replay_session=session,scenarios=len(SCENARIOS),unique_frames=1547,all_scenario_frame_rows=len(rows),zero_service_reference_mismatches=0,
        summaries=summaries,recorded_blue_time_used_as_scene_service=False,scene_age_reset_on_completion=False,
        current_cone_compute_cost_included=False,original_capture_and_delivery_latency_reproduced=False,
        source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
