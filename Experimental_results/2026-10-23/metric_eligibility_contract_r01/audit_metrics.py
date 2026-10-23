"""Audit frozen full-frame metrics; no recomputation, no runtime publication."""
from collections import Counter,defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
UNIFORM=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
OBJECT=HERE.parent/'object_excluded_scene_r01'
JOIN=HERE.parent/'contour_join_control_r01'
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate
from eligibility import Evidence,decide,DIAGNOSTIC_CHECKS,PHYSICAL_CHECKS


def explicit_bool(value):
    if value not in ('True','False'):raise ValueError('explicit frozen bool required')
    return value=='True'


def frame_key(row):return row['session'],int(row['frame'])


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new result output required')
    metric=UNIFORM/'metric_results_r01';quality=UNIFORM/'quality_results_r01'
    sources={str(p):sha256(p) for p in (Path(__file__),HERE/'eligibility.py',HERE/'method.md',ROOT/'src/angular_fisheye_geometry.py')}
    for folder in (metric,quality,UNIFORM/'intake_r01',OBJECT/'results_r01',JOIN/'results_r01'):
        p=folder/'summary.json';record=json.loads(p.read_text());sources[str(p)]=sha256(p)
        for name,h in record['output_sha256'].items():assert sha256(folder/name)==h
        for path,h in record['source_sha256'].items():assert sha256(Path(path))==h
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    observed=ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    paths=[metric/'all_frame_metrics.csv',quality/'all_frame_quality.csv',candidate,floor,observed,
        UNIFORM/'intake_r01/sampling_plan.json',UNIFORM/'scene_results_r01/session_hypotheses.csv',
        UNIFORM/'pooled_results_r01/session_hypotheses.csv',OBJECT/'results_r01/bbox_coverage.csv',
        OBJECT/'results_r01/session_hypotheses.csv',JOIN/'results_r01/session_hypotheses.csv']
    sources.update({str(p):sha256(p) for p in paths})
    camera_data=json.loads(candidate.read_text());camera=camera_from_candidate(camera_data)
    physical_tf=json.loads(floor.read_text());assert physical_tf['physical_transform_independently_measured'] is False
    plans=json.loads((UNIFORM/'intake_r01/sampling_plan.json').read_text())['sessions']
    own_poses={model:{r['session'] for r in read_csv(UNIFORM/folder/'session_hypotheses.csv') if explicit_bool(r['metric_eligible'])}
        for model,folder in [('uniform_images','scene_results_r01'),('pooled_planes','pooled_results_r01')]}
    observations={frame_key(r):r for r in read_csv(observed)}
    qualities={frame_key(r):r for r in read_csv(quality/'all_frame_quality.csv')}
    rows=read_csv(metric/'all_frame_metrics.csv')
    assert len(observations)==len(qualities)==6876 and len(rows)==13752
    assert set(observations)==set(qualities)
    evidence_rows=[];decisions=[];seen=Counter()
    for source in rows:
        k=frame_key(source);ob=observations[k];q=qualities[k]
        assert source['dataset']==ob['dataset']==q['dataset']
        assert float(source['time_sec'])==float(ob['time_sec'])==float(q['time_sec'])
        assert explicit_bool(source['quality_accepted'])==explicit_bool(q['quality_accepted'])
        assert q['reason']==source['quality_reason'] and not explicit_bool(q['rows_imputed'])
        assert not explicit_bool(source['distance_imputed']) and not explicit_bool(source['usable_for_ffb'])
        pose=source['session'] in own_poses[source['model']]
        assert pose==explicit_bool(source['pose_temporally_checked'])
        pair=json.loads(ob['native_colour_pair_json']) if ob['native_colour_pair_json'] else None
        native=True
        if pair is not None:
            p=np.asarray(pair,float)
            native=bool(p.shape==(2,2) and np.isfinite(p).all() and ((p[:,0]>=0)&(p[:,0]<640)&(p[:,1]>=0)&(p[:,1]<720)).all())
        accepted=explicit_bool(q['quality_accepted'])
        if accepted:
            assert explicit_bool(q['current_frame_observation_only']) and bool(q['observed_support_json'])
        # Physical checks are intentionally not derived from numerical fit quality.
        # These artifacts do not contain operational acceptance, a verified per-
        # recording extrinsic/contact proof, or a distance uncertainty budget.
        e=Evidence(source_provenance_verified=True,same_frame_inputs=True,native_coordinate_contract=native,
            calibration_candidate_checked=bool(camera.image_size==(1280,720)),own_session_pose_candidate=pose,
            current_frame_observation=pair is not None,image_support_quality=accepted,
            floor_intersection_valid=explicit_bool(source['geometry_estimated']),
            raw_forward_m=float(source['raw_floor_z_m']) if source['raw_floor_z_m'] else None,
            operational_intrinsics_verified=False,recording_extrinsics_verified=False,
            floor_contact_verified=explicit_bool(source['floor_contact_verified']),distance_uncertainty_verified=False)
        assert not e.floor_contact_verified
        result=decide(e)
        assert result['offline_diagnostic_available']==explicit_bool(source['measurement_emitted'])
        old=float(source['emitted_floor_z_m']) if source['emitted_floor_z_m'] else None
        assert result['offline_diagnostic_distance_m']==old
        assert result['physically_supported_distance_m'] is None
        identity=dict(dataset=source['dataset'],session=source['session'],frame=k[1],time_sec=float(source['time_sec']),
            time_role=source['time_role'],model=source['model'],quality_reason=q['reason'])
        evidence_rows.append(dict(**identity,**asdict(e)))
        decisions.append(dict(**identity,**{key+'_json' if key in ('diagnostic_blockers','physical_blockers','all_blockers') else key:
            json.dumps(value) if key in ('diagnostic_blockers','physical_blockers','all_blockers') else value for key,value in result.items()}))
        seen[k]+=1
    assert set(seen.values())=={2}
    coverage=read_csv(OBJECT/'results_r01/bbox_coverage.csv')
    object_sessions={r['session']:r for r in read_csv(OBJECT/'results_r01/session_hypotheses.csv') if r['mode']=='object_and_reference'}
    joined_sessions={r['session']:r for r in read_csv(JOIN/'results_r01/session_hypotheses.csv') if r['mode']=='join_refit'}
    session_rows=[]
    for plan in plans:
        session=plan['session'];metrics=[r for r in decisions if r['session']==session]
        per_model={m:sum(r['model']==m and r['offline_diagnostic_available'] for r in metrics) for m in own_poses}
        covered=[r for r in coverage if r['session']==session]
        session_rows.append(dict(session=session,raw_frames=int(plan['raw_frames']),sampled_scene_images=len(plan['selected']),
            cone_metric_frames=len(metrics)//2,input_role='cone_metric_audit' if metrics else 'floor_reference_only_no_cone_metric_ledger',
            sampled_saved_bbox_frames=sum(explicit_bool(r['saved_prediction_frame_present']) for r in covered),
            uniform_own_pose_candidate=session in own_poses['uniform_images'],pooled_own_pose_candidate=session in own_poses['pooled_planes'],
            object_screen_sample_temporal_candidate=explicit_bool(object_sessions[session]['temporal_candidate_eligible']),
            joined_sample_temporal_candidate=explicit_bool(joined_sessions[session]['temporal_candidate_eligible']),
            uniform_diagnostic_frames=per_model['uniform_images'],pooled_diagnostic_frames=per_model['pooled_planes'],
            physical_metric_frames=0,usable_for_ffb=False))
    # Record every missing prerequisite; these are overlapping causes, not a partition.
    reason_rows=[]
    for model in own_poses:
        selected=[r for r in decisions if r['model']==model]
        for field in ('diagnostic_blockers_json','physical_blockers_json'):
            counts=Counter(reason for r in selected for reason in json.loads(r[field]))
            reason_rows.extend(dict(model=model,layer='diagnostic' if field.startswith('diagnostic') else 'physical',reason=reason,
                frame_count=count,model_frames=len(selected),causes_overlap=True) for reason,count in sorted(counts.items()))
    requirement_rows=[dict(requirement=reason,status='UNVERIFIED_IN_CURRENT_ARTIFACTS',
        evidence_basis=basis,proof_inferred_from_small_fit_error=False) for reason,basis in [
        ('operational_intrinsics_acceptance_unverified',str(candidate)+' : offline candidate, not an operational acceptance record'),
        ('recording_specific_extrinsics_unverified',str(floor)+' : physical_transform_independently_measured=false; scene up is conditional'),
        ('physical_floor_contact_unverified',str(metric/'all_frame_metrics.csv')+' : floor_contact_verified=false'),
        ('distance_uncertainty_budget_unverified',str(metric/'empirical_pose_sensitivity.csv')+' : empirical scenarios, not confidence bounds')]]
    output.mkdir()
    for name,data in [('frame_evidence.csv',evidence_rows),('frame_decisions.csv',decisions),('session_readiness.csv',session_rows),
        ('blocking_reasons.csv',reason_rows),('physical_requirements.csv',requirement_rows)]:write_csv(output/name,data)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    record=dict(status='COMPLETED_FROZEN_DISTANCE_ELIGIBILITY_AUDIT_NOT_RUNTIME_GATE',work_date='2026-10-23',source_sha256=sources,
        models=len(own_poses),metric_frames_per_model=6876,total_model_frame_rows=len(decisions),recordings_in_readiness_matrix=len(session_rows),
        diagnostic_available_by_model={m:sum(r['model']==m and r['offline_diagnostic_available'] for r in decisions) for m in own_poses},
        physical_metric_rows=sum(r['physical_metric_checks_satisfied'] for r in decisions),
        historical_diagnostic_value_or_decision_mismatches=0,physical_output=False,source_images_edited=False,
        new_geometry_computed=False,production_settings_changed=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
