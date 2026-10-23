"""Replay frozen same-frame scene evidence and current-frame cone observations."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
UNIFORM=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
GEOMETRY=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
CONTRACT=HERE.parent/'metric_eligibility_contract_r01'
sys.path[:0]=[str(ROOT/'src'),str(GEOMETRY),str(CONTRACT)]
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import infer_up,angle_degrees,align_up_preserving_heading_reference
from angular_fisheye_geometry import camera_from_candidate,unproject,floor_from_rays
from eligibility import Evidence,decide
from causal_pose import PastOnlyPose,MODES


def flag(s):
    if s not in ('True','False'):raise ValueError('explicit frozen bool required')
    return s=='True'


def key(r):return r['session'],int(r['frame'])


def replay_session(samples,observations,quality,camera,prior_transform):
    """Only exact current frame lookups: no session split, labels or future state."""
    features={int(r['frame']):r for r in samples};controller=PastOnlyPose();rows=[];events=[]
    if len(features)!=len(samples):raise ValueError('duplicate scene image frame')
    timeline=observations if observations else [dict(frame=r['frame'],time_sec=r['time_sec']) for r in samples]
    for ob in timeline:
        frame=int(ob['frame']);time=float(ob['time_sec'])
        if frame in features:
            f=features[frame];assert time==float(f['time_sec'])
            accepted=flag(f['accepted']);up=json.loads(f['up_optical_json']) if accepted else None
            was_ready=controller.ready
            controller.ingest(frame,time,accepted,up)
            event=controller.query(frame,time,'sample_only')
            events.append(dict(frame=frame,time_sec=time,scene_accepted=accepted,scene_reason=f['reason'],
                initialization_event=controller.ready and not was_ready,**event))
        for mode in MODES:
            status=controller.query(frame,time,mode)
            if not observations:continue
            q=quality[frame];assert float(q['time_sec'])==time
            pair=json.loads(ob['native_colour_pair_json']) if ob['native_colour_pair_json'] else None
            raw=None;geometry=False
            if status['pose_available'] and pair is not None:
                T=align_up_preserving_heading_reference(prior_transform,status['up_optical'])
                rays,valid=unproject(pair,camera,image_size=(1280,720))
                points,available=floor_from_rays(rays[1:],valid[1:],T)
                if available[0]:raw=float(points[0,0]);geometry=True
            decision=decide(Evidence(source_provenance_verified=True,same_frame_inputs=True,native_coordinate_contract=True,
                calibration_candidate_checked=True,own_session_pose_candidate=status['pose_available'],
                current_frame_observation=pair is not None,image_support_quality=flag(q['quality_accepted']),
                floor_intersection_valid=geometry,raw_forward_m=raw))
            rows.append(dict(frame=frame,time_sec=time,mode=mode,**status,quality_accepted=flag(q['quality_accepted']),quality_reason=q['reason'],
                raw_floor_z_m=raw,diagnostic_available=decision['offline_diagnostic_available'],
                diagnostic_z_m=decision['offline_diagnostic_distance_m'],physical_metric_verified=decision['physical_metric_checks_satisfied'],
                distance_imputed=False,blockers=decision['all_blockers']))
    return rows,events


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new output version required')
    paths=[HERE/'method.md',Path(__file__),HERE/'causal_pose.py',GEOMETRY/'scene_geometry.py',ROOT/'src/angular_fisheye_geometry.py',
        CONTRACT/'eligibility.py',UNIFORM/'scene_results_r01/image_diagnostics.csv',UNIFORM/'scene_results_r01/line_candidates.csv',
        UNIFORM/'intake_r01/native_sample_manifest.csv',UNIFORM/'intake_r01/sampling_plan.json',
        UNIFORM/'quality_results_r01/all_frame_quality.csv',UNIFORM/'metric_results_r01/all_frame_metrics.csv',
        ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv',
        ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json',
        ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json']
    sources={str(p):sha256(p) for p in paths}
    for folder in (UNIFORM/'scene_results_r01',UNIFORM/'quality_results_r01',UNIFORM/'metric_results_r01',UNIFORM/'intake_r01'):
        p=folder/'summary.json';info=json.loads(p.read_text());sources[str(p)]=sha256(p)
        for name,h in info['output_sha256'].items():assert sha256(folder/name)==h
        for p,h in info['source_sha256'].items():assert sha256(Path(p))==h,p
    features=read_csv(paths[6]);lines=defaultdict(list)
    for r in read_csv(paths[7]):
        if flag(r['accepted']):lines[key(r)].append(json.loads(r['normal_json']))
    transform=json.loads(paths[14].read_text());T=np.array(transform['transform_target_from_source'])
    prior=np.array(transform['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    camera=camera_from_candidate(json.loads(paths[13].read_text()))
    sample_map={key(r):r for r in read_csv(paths[8])}
    for f in features:
        sample=sample_map[key(f)];assert float(f['time_sec'])==float(sample['time_sec'])
        assert sha256(Path(sample['source_native_png']))==sample['png_sha256']==f['png_sha256']
        current=infer_up(np.array(lines[key(f)]).reshape(-1,3),prior)
        assert current['accepted']==flag(f['accepted']) and current['reason']==f['reason']
        if current['accepted']:assert angle_degrees(current['up'],json.loads(f['up_optical_json']))<1e-5
    observed=read_csv(paths[12]);quality=read_csv(paths[10]);historical=read_csv(paths[11])
    qindex={key(r):r for r in quality};old={(key(r),r['model']):r for r in historical}
    grouped=defaultdict(list);ogs=defaultdict(list)
    for f in features:grouped[f['session']].append(f)
    for ob in observed:ogs[ob['session']].append(ob)
    all_rows=[];all_events=[];sessions=[];summaries=[]
    for session,samples in sorted(grouped.items()):
        samples=sorted(samples,key=lambda r:int(r['frame']));obs=sorted(ogs[session],key=lambda r:int(r['frame']))
        q={int(r['frame']):qindex[key(r)] for r in obs}
        replay,events=replay_session(samples,obs,q,camera,T)
        for event in events:all_events.append(dict(session=session,**event))
        # Identity and labels are attached after the controller/geometry replay.
        all_rows.extend(dict(session=session,**row) for row in replay)
        init=[r for r in events if r['initialization_event']]
        sessions.append(dict(session=session,scene_images=len(samples),accepted_scene_images=sum(flag(r['accepted']) for r in samples),
            initialization_events=len(init),first_initialization_time_sec=init[0]['time_sec'] if init else None,
            first_initialization_elapsed_sec=init[0]['time_sec']-float(samples[0]['time_sec']) if init else None,
            cone_frames=len(obs),physical_metric_verified=False,usable_for_ffb=False))
        obindex={int(r['frame']):r for r in obs}
        for mode in MODES:
            selected=[r for r in replay if r['mode']==mode]
            for r in selected:
                ob=obindex[r['frame']];r.update(dataset=ob['dataset'],condition=ob['condition'],reference_z_m=ob['reference_z_m'])
            for condition in sorted({r['condition'] for r in selected}):
                group=[r for r in selected if r['condition']==condition]
                used=[r for r in group if r['diagnostic_available']];ref=group[0]['reference_z_m']
                errors=np.array([r['diagnostic_z_m']-float(ref) for r in used]) if ref else np.array([])
                summaries.append(dict(session=session,mode=mode,condition=condition,all_frames=len(group),diagnostic_frames=len(used),
                    reference_z_m=ref,z_median_m=float(np.median([r['diagnostic_z_m'] for r in used])) if used else None,
                    z_bias_m=float(np.median(errors)) if len(errors) else None,z_abs_error_max_m=float(max(abs(errors))) if len(errors) else None,
                    historical_offline_diagnostic_frames=sum(flag(old[(session,r['frame']),'uniform_images']['measurement_emitted']) for r in group),
                    pose_reason_counts=json.dumps(dict(Counter(r['pose_reason'] for r in group))),physical_metric_verified=False,usable_for_ffb=False))
    # Attach observational labels to the saved all-frame copy, never to the state machine.
    observed_index={key(r):r for r in observed}
    for r in all_rows:
        ob=observed_index[key(r)];r.update(dataset=ob['dataset'],condition=ob['condition'],reference_z_m=ob['reference_z_m'])
    assert len(all_rows)==13752 and len(all_events)==492
    assert all(sha256(Path(p))==h for p,h in sources.items())
    def serialize(rows):
        structured={'training_frames','validation_frames','up_optical','blockers'}
        return [{k+'_json' if k in structured else k:json.dumps(v) if k in structured and v is not None else ('' if k in structured else v) for k,v in r.items()} for r in rows]
    output.mkdir()
    for name,rows in [('frame_metrics.csv',all_rows),('scene_events.csv',all_events),('session_summary.csv',sessions),('condition_summary.csv',summaries)]:
        write_csv(output/name,serialize(rows))
    report=dict(status='COMPLETED_PAST_ONLY_INPUT_REPLAY_NOT_REALTIME_OR_PHYSICAL_APPROVAL',work_date='2026-10-23',source_sha256=sources,
        scene_images=len(features),single_frame_scene_replay_mismatches=0,recordings=len(sessions),initialized_recordings=sum(r['initialization_events']>0 for r in sessions),
        unique_cone_frames=len(observed),all_mode_frame_rows=len(all_rows),diagnostic_frames_by_mode={m:sum(r['mode']==m and r['diagnostic_available'] for r in all_rows) for m in MODES},
        first_initializations=[r for r in sessions if r['initialization_events']],future_images_used=False,processing_latency_simulated=False,
        source_images_edited=False,production_settings_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
