"""Bind frozen hypotheses to evidence; statistics only, no geometry or control."""
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01'
UNIFORM=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
CONTRACT=HERE.parent/'metric_eligibility_contract_r01'
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256

MODELS=('ideal59_nominal','angular_nominal','angular_paper5_rotation')
METHODS=('floor_bottom_proxy','height_vertical_proxy','height_near_edge_assumption')
SCENES=('uniform_images','pooled_planes')
VARIANTS=tuple(m+'/'+method for m in MODELS for method in METHODS)+tuple(m+'/floor_bottom_proxy' for m in SCENES)


def flag(s):
    if s not in ('True','False'):raise ValueError('explicit stored boolean required')
    return s=='True'


def frame_key(row):return row['session'],int(row['frame'])


def digest_frame_keys(keys):
    return hashlib.sha256(json.dumps(sorted(set(keys)),separators=(',',':')).encode()).hexdigest()


def row_digest(row):return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def lineage(model):
    if model in SCENES:
        return 'own_recording_up_cross_recording_heading_prior'
    if model=='angular_paper5_rotation':return 'cross_recording_paper5_rotation'
    if model in ('ideal59_nominal','angular_nominal'):return 'nominal_pose_not_recording_verified'
    raise ValueError('unknown frozen model')


def floor_scope(row):
    role=row['role']
    if role=='fit':return 'fit_residual' if row['model']=='angular_paper5_rotation' else 'five_reference_locations_no_fit'
    if role=='same_recording_holdout':return 'same_recording_two_unused_locations'
    if role=='cross_recording_not_fitted':return 'cross_recording_single_location'
    raise ValueError('unknown frozen floor role')


def describe(rows,reference):
    if not rows:return dict(n=0,z_median_m=None,z_bias_m=None,z_abs_error_p95_m=None,z_abs_error_max_m=None,base_height_median_m=None)
    z=np.array([float(r['raw_z_forward_m']) for r in rows]);errors=z-reference
    height=[float(r['raw_base_height_m']) for r in rows if r['raw_base_height_m']]
    return dict(n=len(rows),z_median_m=float(np.median(z)),z_bias_m=float(np.median(errors)),
        z_abs_error_p95_m=float(np.percentile(abs(errors),95)),z_abs_error_max_m=float(max(abs(errors))),
        base_height_median_m=float(np.median(height)) if height else None)


def registry():
    rows=[]
    for variant in VARIANTS:
        model,method=variant.split('/')
        rows.append(dict(variant=variant,model=model,method=method,pose_scope=lineage(model),
            intrinsic_basis='legacy_ideal_equidistant' if model=='ideal59_nominal' else 'fixed_angular_KB4_from_separate_checkerboard_recording',
            up_derived_from_own_recording=model in SCENES,full_extrinsics_independently_verified=False,
            heading_basis='cross_recording_paper5_prior' if model in SCENES else 'paper5_fitted' if model=='angular_paper5_rotation' else 'recorded_nominal',
            fixed_camera_height_m=.59,known_cone_height_m=None if method=='floor_bottom_proxy' else .73,
            assumed_tip_forward_offset_m=.1875 if method=='height_near_edge_assumption' else 0. if method=='height_vertical_proxy' else None,
            endpoint_correspondence_verified=False,usable_for_ffb=False))
    return rows


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new output required; frozen outputs cannot be overwritten')
    sources={str(p):sha256(p) for p in (Path(__file__),HERE/'method.md')}
    for folder in (OLD/'results_r01',UNIFORM/'metric_results_r01',UNIFORM/'quality_results_r01',CONTRACT/'results_r01'):
        path=folder/'summary.json';proof=json.loads(path.read_text());sources[str(path)]=sha256(path)
        for name,h in proof['output_sha256'].items():assert sha256(folder/name)==h,(folder,name)
        for path,h in proof['source_sha256'].items():assert sha256(Path(path))==h,path
    observed_path=ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    paths=[observed_path,OLD/'results_r01/cone_all_frame_results.csv',OLD/'results_r01/floor_reference_results.csv',
        OLD/'results_r01/floor_transform_candidate.json',OLD/'results_r01/floor_summary.csv',
        UNIFORM/'metric_results_r01/all_frame_metrics.csv',UNIFORM/'quality_results_r01/all_frame_quality.csv',
        CONTRACT/'results_r01/frame_decisions.csv',UNIFORM/'intake_r01/sampling_plan.json']
    sources.update({str(p):sha256(p) for p in paths})
    observed={frame_key(r):r for r in read_csv(observed_path)}
    quality={frame_key(r):r for r in read_csv(paths[6])}
    scene=read_csv(paths[5]);scenes={(frame_key(r),r['model']):r for r in scene}
    contract={(frame_key(r),r['model']):r for r in read_csv(paths[7])}
    assert len(observed)==len(quality)==6876 and len(scenes)==len(contract)==13752
    tf=json.loads(paths[3].read_text());assert not tf['physical_transform_independently_measured'] and not tf['published_to_ros']
    plan=json.loads(paths[8].read_text())['sessions'];middle={r['session']:(r['first_time_sec']+r['last_time_sec'])/2 for r in plan}
    own={};index=defaultdict(dict);normalized=[]

    def append(source,source_table,source_row_number,model,method,raw,estimated,base_height,diagnostic):
        k=frame_key(source);ob=observed[k];q=quality[k];s=scenes[k,'uniform_images']
        assert source['dataset']==ob['dataset']==q['dataset']==s['dataset']
        assert source['condition']==ob['condition']==q['condition']==s['condition']
        assert float(source['time_sec'])==float(ob['time_sec'])==float(q['time_sec'])==float(s['time_sec'])
        assert source['reference_z_m']==ob['reference_z_m']==s['reference_z_m']
        assert s['time_role']==('estimate' if float(source['time_sec'])<middle[k[0]] else 'heldout')
        if estimated:assert raw and math.isfinite(float(raw)) and float(raw)>0 and ob['native_colour_pair_json']
        else:assert raw==''
        assert not flag(source['usable_for_ffb']) and not flag(q['rows_imputed'])
        variant=model+'/'+method;assert variant in VARIANTS and variant not in index[k]
        row=dict(dataset=source['dataset'],session=k[0],frame=k[1],time_sec=source['time_sec'],condition=source['condition'],
            reference_z_m=source['reference_z_m'],audit_time_role=s['time_role'],variant=variant,pose_scope=lineage(model),
            raw_numerically_estimated=estimated,raw_z_forward_m=raw,raw_base_height_m=base_height,
            saved_image_quality_accepted=flag(q['quality_accepted']),source_diagnostic_available=diagnostic,
            source_reason=source['reason'],source_table=str(source_table.relative_to(ROOT)),source_csv_data_row=source_row_number,
            source_row_sha256=row_digest(source),physical_metric_verified=False,distance_imputed=False,usable_for_ffb=False)
        normalized.append(row);index[k][variant]=row

    for i,r in enumerate(read_csv(paths[1]),1):
        assert not flag(r['physical_endpoint_correspondence_verified'])
        append(r,paths[1],i,r['model'],r['method'],r['z_forward_m'],flag(r['estimated']),r['base_height_m'],False)
    for i,r in enumerate(scene,1):
        c=contract[frame_key(r),r['model']]
        assert c['offline_diagnostic_available']==r['measurement_emitted'] and not flag(c['physical_metric_checks_satisfied'])
        append(r,paths[5],i,r['model'],'floor_bottom_proxy',r['raw_floor_z_m'],flag(r['geometry_estimated']),'',flag(c['offline_diagnostic_available']))
        own[frame_key(r),r['model']]=flag(c['offline_diagnostic_available'])
    assert len(normalized)==75636 and set(index)==set(observed)
    assert all(set(v)==set(VARIANTS) for v in index.values())
    membership=[];matched=set();paired=set()
    for k,variants in sorted(index.items()):
        ob=observed[k];q=quality[k]
        all_numeric=all(r['raw_numerically_estimated'] for r in variants.values())
        both_diagnostic=all(own[k,m] for m in SCENES)
        shared=flag(q['quality_accepted']) and all_numeric and both_diagnostic
        labeled=bool(ob['reference_z_m'])
        if shared:matched.add(k)
        if shared and labeled:paired.add(k)
        membership.append(dict(session=k[0],frame=k[1],dataset=ob['dataset'],condition=ob['condition'],reference_z_m=ob['reference_z_m'],
            saved_image_quality_accepted=flag(q['quality_accepted']),all_eleven_have_numeric_value=all_numeric,
            both_scene_diagnostics_available=both_diagnostic,in_common_frame_set=shared,in_paired_reference_comparison=shared and labeled,
            distance_imputed=False,usable_for_ffb=False))
    groups=defaultdict(list)
    for k,r in observed.items():
        if r['reference_z_m']:groups[r['dataset'],r['condition']].append(k)
    numerical=[];comparisons=[]
    for (dataset,condition),keys in sorted(groups.items()):
        reference={observed[k]['reference_z_m'] for k in keys};assert len(reference)==1;reference=float(reference.pop())
        for window in ('all','heldout_time'):
            base=[k for k in keys if window=='all' or scenes[k,'uniform_images']['time_role']=='heldout']
            common=[k for k in base if k in paired]
            for variant in VARIANTS:
                identity=dict(dataset=dataset,condition=condition,variant=variant,time_window=window,reference_z_m=reference,
                    all_condition_frames=len(base),physical_metric_verified=False,usable_for_ffb=False)
                raw=[index[k][variant] for k in base if index[k][variant]['raw_numerically_estimated']]
                numerical.append(dict(**identity,**describe(raw,reference),frame_keys_sha256=digest_frame_keys(frame_key(r) for r in raw),
                    population='method_own_numeric_candidates_not_diagnostic_acceptance'))
                used=[index[k][variant] for k in common]
                delta=[float(index[k][variant]['raw_z_forward_m'])-float(index[k]['uniform_images/floor_bottom_proxy']['raw_z_forward_m']) for k in common]
                comparisons.append(dict(**identity,**describe(used,reference),frame_keys_sha256=digest_frame_keys(common),
                    paired_delta_to_scene_uniform_median_m=float(np.median(delta)) if delta else None,
                    population='same_frame_intersection_not_physical_acceptance'))
    floors=[]
    for r in read_csv(paths[2]):
        assert not flag(r['physical_reference_independently_surveyed']) and not flag(r['usable_for_ffb'])
        floors.append(dict(r,evidence_scope=floor_scope(r),this_point_used_for_this_model_fit=r['model']=='angular_paper5_rotation' and r['role']=='fit',
            actual_session='itiawase2_20261015_183552_599' if r['session']=='paper7' else 'paper_cone_center_z2p00_r01_20261019_180411_245',
            source_row_sha256=row_digest(r)))
    floor_summary=[]
    for model in MODELS:
        for role in ('fit','same_recording_holdout','cross_recording_not_fitted'):
            group=[r for r in floors if r['model']==model and r['role']==role]
            old=next(r for r in read_csv(paths[4]) if r['model']==model and r['role']==role)
            rmse=float(np.sqrt(np.mean([float(r['planar_error_m'])**2 for r in group])))
            assert abs(rmse-float(old['planar_rmse_m']))<1e-14
            floor_summary.append(dict(model=model,source_location_role=role,evidence_scope=group[0]['evidence_scope'],points=len(group),
                actual_model_fit_points=sum(r['this_point_used_for_this_model_fit'] for r in group),planar_rmse_m=rmse,
                maximum_abs_z_error_m=max(abs(float(r['error_z_m'])) for r in group),physical_metric_verified=False,usable_for_ffb=False))
    assert all(sha256(Path(p))==h for p,h in sources.items())
    output.mkdir()
    for name,rows in [('variant_registry.csv',registry()),('all_frame_comparison.csv',normalized),('common_frame_membership.csv',membership),
        ('method_own_numeric_summary.csv',numerical),('matched_condition_summary.csv',comparisons),('floor_point_lineage.csv',floors),
        ('floor_scope_summary.csv',floor_summary)]:write_csv(output/name,rows)
    summary=dict(status='COMPLETED_FROZEN_EVIDENCE_STRATIFIED_COMPARISON_NOT_GEOMETRY_OR_CONTROL',work_date='2026-10-23',
        source_sha256=sources,variants=len(VARIANTS),unique_cone_frames=len(observed),all_model_frame_rows=len(normalized),
        historical_numeric_or_diagnostic_values_changed=0,common_frames=len(matched),paired_reference_frames=len(paired),
        common_frames_without_reference=len(matched-paired),common_frame_keys_sha256=digest_frame_keys(matched),
        paired_reference_frame_keys_sha256=digest_frame_keys(paired),reference_conditions=len(groups),floor_point_rows=len(floors),
        raw_candidate_counts_by_variant=dict(Counter(r['variant'] for r in normalized if r['raw_numerically_estimated'])),
        no_new_geometry=True,no_new_recording=True,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256','raw_candidate_counts_by_variant')},indent=2))


if __name__=='__main__':main()
