"""Fixed angular intrinsics vs floor references, rotation TF, and cone proxies."""
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from scipy.optimize import least_squares

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate,unproject,project,floor_from_rays,segment_from_rays
from fisheye_floor_geometry import legacy_front_diagnostic_geometry,optical_rays,checked_transform

FIT_IDS=('C080','C130','C200','L130','R130')


def fit_floor_rotation(pixels,world_points,camera,nominal_transform):
    pixels=np.asarray(pixels,float);world=np.asarray(world_points,float)
    T0=checked_transform(nominal_transform)
    if pixels.ndim!=2 or pixels.shape[1]!=2 or world.shape!=(len(pixels),3) or len(pixels)<3:
        raise ValueError('three or more matching fit-only points required')
    def transform(delta):
        T=T0.copy();T[:3,:3]=cv2.Rodrigues(delta)[0]@T0[:3,:3]
        return T
    def residual(delta):
        T=transform(delta)
        camera_points=(world-T[:3,3])@T[:3,:3]
        uv,valid=project(camera_points,camera)
        if not valid.all():raise ValueError('fit reference outside observed angular domain')
        return (uv-pixels).ravel()
    bounds=np.deg2rad(10.)
    result=least_squares(residual,np.zeros(3),jac='3-point',bounds=(-bounds,bounds),
        loss='linear',max_nfev=300,ftol=1e-12,xtol=1e-12,gtol=1e-12)
    s=np.linalg.svd(result.jac,compute_uv=False)
    return transform(result.x),dict(rotation_increment_target_xyz_deg=np.degrees(result.x).tolist(),
        fit_pixel_point_rmse=float(np.sqrt(np.mean(result.fun.reshape(-1,2)**2)*2)),
        optimizer_success=bool(result.success),optimizer_message=result.message,active_bounds=result.active_mask.tolist(),
        numerical_rank=int(np.linalg.matrix_rank(result.jac)),jacobian_singular_values=s.tolist(),
        fixed_height_m=float(T0[2,3]),fixed_xy_m=T0[:2,3].tolist(),intrinsics_refitted=False,
        physical_transform_independently_measured=False,usable_for_ffb=False)


def summary_rows(rows):
    groups=defaultdict(list)
    for r in rows:groups[(r['dataset'],r['condition'],r['model'],r['method'])].append(r)
    output=[]
    for key,group in sorted(groups.items()):
        valid=[r for r in group if r['estimated']]
        labeled=[r for r in valid if r['reference_z_m'] is not None]
        z=np.array([r['z_forward_m'] for r in valid]);err=np.array([r['z_forward_m']-r['reference_z_m'] for r in labeled])
        residual=np.array([r['segment_residual_m'] for r in valid if r['segment_residual_m'] is not None])
        heights=np.array([r['base_height_m'] for r in valid if r['base_height_m'] is not None])
        output.append(dict(dataset=key[0],condition=key[1],model=key[2],method=key[3],frames=len(group),estimated=len(valid),
            reference_z_m=labeled[0]['reference_z_m'] if labeled else None,
            z_median_m=float(np.median(z)) if len(z) else None,
            z_bias_m=float(np.median(err)) if len(err) else None,
            z_absolute_error_p95_m=float(np.percentile(abs(err),95)) if len(err) else None,
            base_height_median_m=float(np.median(heights)) if len(heights) else None,
            segment_residual_median_m=float(np.median(residual)) if len(residual) else None,
            segment_consistent_frames=sum(r['segment_consistent'] for r in valid),
            reason_counts=json.dumps(dict(Counter(r['reason'] for r in group))),usable_for_ffb=False))
    return output


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('no metric validation overwrite')
    candidate_path=HERE.parent/'front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    paper_path=ROOT/'Experimental_results/2026-10-15/paper_reference7_r01/analysis_r01/reference_points_primary170.csv'
    paired_path=ROOT/'Experimental_results/2026-10-19/paper_cone_2m_validation_r01/analysis_r01/summary.json'
    cone_path=HERE.parent/'cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    baseline_path=HERE.parent/'cone_known_height_pinhole_r01/results_r01/all_frame_estimates.csv'
    candidate=json.loads(candidate_path.read_text());camera=camera_from_candidate(candidate)
    paired=json.loads(paired_path.read_text())
    ideal_camera,T0=legacy_front_diagnostic_geometry(paired['models']['height_only59'])
    paths=[candidate_path,paper_path,paired_path,cone_path,baseline_path,HERE/'method.md',Path(__file__),
           ROOT/'src/angular_fisheye_geometry.py',ROOT/'src/fisheye_floor_geometry.py']
    # Metadata paths are traced from existing intake ledgers; no archive re-extraction.
    session_paths=set()
    old_audit=ROOT/'Experimental_results/2026-10-19/cone_recording_coordinate_audit_r01/results_r01/sessions.csv'
    paths.append(old_audit)
    for r in read_csv(old_audit):session_paths.add(Path(r['session_path']))
    for name in ['front_intrinsics_a4_real_r02','front_intrinsics_a4_real_r03']:
        p=HERE.parent/name/'intake_summary.json';paths.append(p)
        session_paths.add(Path(json.loads(p.read_text())['session']))
    p=ROOT/'Experimental_results/2026-10-19/paper_cone_2m_validation_r01/intake_summary.json'
    paths.append(p);session_paths.add(Path(json.loads(p.read_text())['session']))
    sources={str(p):sha256(p) for p in paths}
    capture_reference=json.loads((HERE.parent/'front_intrinsics_a4_real_r03/intake_summary.json').read_text())['metadata']
    metadata_rows=[]
    for session in sorted(session_paths):
        p=session/'metadata.json';sources[str(p)]=sha256(p)
        meta=json.loads(p.read_text())
        req=['requested_camera_width','requested_camera_height','requested_camera_fps']
        metadata_rows.append(dict(session=session.name,metadata_path=str(p),
            requested_capture_equal=all(meta.get(k)==capture_reference.get(k) for k in req),
            capture_properties_equal=meta.get('camera_capture_properties')==capture_reference.get('camera_capture_properties'),
            camera_capture_properties=json.dumps(meta.get('camera_capture_properties'),sort_keys=True),
            recorded_geometry=json.dumps({k:meta['parameters'].get(k) for k in ('camera_height','pitch_deg','roll_deg','yaw_deg','radius_scale','front_cx_offset','front_cy_offset')},sort_keys=True),
            serial_recorded=any(k in meta for k in ('serial','camera_serial')),optical_state_independently_verified=False))
    output.mkdir()
    write_csv(output/'metadata_comparison.csv',metadata_rows)
    paper=read_csv(paper_path)
    fit=[r for r in paper if r['point_id'] in FIT_IDS]
    assert tuple(r['point_id'] for r in fit)==FIT_IDS
    fit_uv=np.array([[float(r['pixel_x']),float(r['pixel_y'])] for r in fit])
    fit_world=np.array([[float(r['reference_z_m']),-float(r['reference_x_m']),0.] for r in fit])
    Tfit,tf_info=fit_floor_rotation(fit_uv,fit_world,camera,T0)
    tf_info.update(schema='conditional_paper5_floor_rotation_v1',fit_ids=list(FIT_IDS),
        target_frame='paper7_ground_reference',source_frame='front_optical',
        transform_target_from_source=Tfit.tolist(),nominal_transform=T0.tolist(),published_to_ros=False)
    (output/'floor_transform_candidate.json').write_text(json.dumps(tf_info,indent=2)+'\n')
    points=[]
    for r in paper:
        points.append(dict(point_id=r['point_id'],session='paper7',role='fit' if r['point_id'] in FIT_IDS else 'same_recording_holdout',
            pixel_x=float(r['pixel_x']),pixel_y=float(r['pixel_y']),reference_x_m=float(r['reference_x_m']),reference_z_m=float(r['reference_z_m'])))
    points.append(dict(point_id='paper_cone_2m',session='paper_cone_20261019',role='cross_recording_not_fitted',
        pixel_x=float(paired['paper_reference_native_xy'][0]),pixel_y=float(paired['paper_reference_native_xy'][1]),
        reference_x_m=0.,reference_z_m=2.))
    uv=np.array([[r['pixel_x'],r['pixel_y']] for r in points])
    ideal_rays,ideal_valid=optical_rays(uv,ideal_camera)
    angular_rays,angular_valid=unproject(uv,camera,image_size=(1280,720))
    models={'ideal59_nominal':(ideal_rays,ideal_valid,T0),
            'angular_nominal':(angular_rays,angular_valid,T0),'angular_paper5_rotation':(angular_rays,angular_valid,Tfit)}
    floor_rows=[]
    for name,(rays,valid,T) in models.items():
        xyz,available=floor_from_rays(rays,valid,T)
        for i,r in enumerate(points):
            if not available[i]:raise ValueError('required floor reference did not project')
            floor_rows.append(dict(r,model=name,x_right_m=float(-xyz[i,1]),z_forward_m=float(xyz[i,0]),
                error_x_m=float(-xyz[i,1]-r['reference_x_m']),error_z_m=float(xyz[i,0]-r['reference_z_m']),
                planar_error_m=float(np.hypot(-xyz[i,1]-r['reference_x_m'],xyz[i,0]-r['reference_z_m'])),
                physical_reference_independently_surveyed=False,usable_for_ffb=False))
    write_csv(output/'floor_reference_results.csv',floor_rows)
    # Same pixels for all models; no image detector rerun or fitted cone labels.
    observed=read_csv(cone_path)
    native=np.full((len(observed),2,2),np.nan)
    for i,r in enumerate(observed):
        if r['native_colour_pair_json']:
            pair=np.asarray(json.loads(r['native_colour_pair_json']),float)
            if pair.shape==(2,2) and np.isfinite(pair).all():native[i]=pair
    has_pair=np.isfinite(native).all(axis=(1,2))
    all_angular=np.full((len(observed),2,3),np.nan);all_ideal=all_angular.copy()
    angular_pair_valid=np.zeros(len(observed),bool);ideal_pair_valid=angular_pair_valid.copy()
    indices=np.flatnonzero(has_pair)
    a,av=unproject(native[indices].reshape(-1,2),camera,image_size=(1280,720))
    old,ov=optical_rays(native[indices].reshape(-1,2),ideal_camera)
    all_angular[indices]=a.reshape(-1,2,3);all_ideal[indices]=old.reshape(-1,2,3)
    angular_pair_valid[indices]=av.reshape(-1,2).all(axis=1);ideal_pair_valid[indices]=ov.reshape(-1,2).all(axis=1)
    cone_models={'ideal59_nominal':(all_ideal,ideal_pair_valid,T0),
        'angular_nominal':(all_angular,angular_pair_valid,T0),'angular_paper5_rotation':(all_angular,angular_pair_valid,Tfit)}
    estimates=[]
    for name,(rays,valid,T) in cone_models.items():
        floors,fvalid=floor_from_rays(rays[:,1],valid,T)
        for i,r in enumerate(observed):
            for method,offset in [('floor_bottom_proxy',None),('height_vertical_proxy',0.),('height_near_edge_assumption',.1875)]:
                row=dict(dataset=r['dataset'],session=r['session'],frame=int(r['frame']),time_sec=float(r['time_sec']),
                    condition=r['condition'],reference_z_m=float(r['reference_z_m']) if r['reference_z_m'] else None,
                    model=name,method=method,estimated=False,reason='no_valid_observed_pair',z_forward_m=None,x_right_m=None,
                    base_height_m=None,segment_residual_m=None,segment_consistent=False,
                    original_quality_accepted=r['quality_accepted']=='True',physical_endpoint_correspondence_verified=False,usable_for_ffb=False)
                if valid[i] and offset is None and fvalid[i]:
                    row.update(estimated=True,reason='conditional_floor_intersection_not_verified_contact',
                        z_forward_m=float(floors[i,0]),x_right_m=float(-floors[i,1]),base_height_m=float(floors[i,2]))
                elif valid[i] and offset is not None:
                    h=segment_from_rays(rays[i],T,tip_forward_offset_m=offset)
                    row.update(reason='nonpositive_or_degenerate_depth' if not h['estimated'] else 'conditional_known_segment_not_verified_endpoints',
                        segment_residual_m=h['residual_m'],segment_consistent=h['segment_consistent'])
                    if h['estimated']:
                        p=h['base_target_m'];row.update(estimated=True,z_forward_m=p[0],x_right_m=-p[1],base_height_m=p[2])
                estimates.append(row)
        print('projected',name,len(observed),'frames',flush=True)
    write_csv(output/'cone_all_frame_results.csv',estimates)
    summary=summary_rows(estimates);write_csv(output/'cone_summary.csv',summary)
    # Independent legacy replay check: exact same rays expressed with unit length.
    baseline={(r['session'],r['frame']):r for r in estimates if r['model']=='ideal59_nominal' and r['method']=='height_vertical_proxy'}
    differences=[]
    with baseline_path.open(newline='') as stream:
        for r in csv.DictReader(stream):
            if r['model']=='height_only59' and r['method']=='colour_vertical_proxy' and r['estimated']=='True':
                current=baseline[(r['session'],int(r['frame']))]
                assert current['estimated']
                differences.append(abs(current['z_forward_m']-float(r['z_forward_m'])))
    assert differences and max(differences)<1e-8
    floor_summary=[]
    for model in models:
        for role in ('fit','same_recording_holdout','cross_recording_not_fitted'):
            selected=[r for r in floor_rows if r['model']==model and r['role']==role]
            floor_summary.append(dict(model=model,role=role,points=len(selected),
                planar_rmse_m=float(np.sqrt(np.mean([r['planar_error_m']**2 for r in selected]))),
                maximum_planar_error_m=max(r['planar_error_m'] for r in selected),
                maximum_abs_z_error_m=max(abs(r['error_z_m']) for r in selected),usable_for_ffb=False))
    write_csv(output/'floor_summary.csv',floor_summary)
    assert all(sha256(Path(p))==v for p,v in sources.items())
    record=dict(status='COMPLETED_CONDITIONAL_METRIC_DIAGNOSTIC_NOT_RUNTIME_APPROVAL',
        source_sha256=sources,observed_frames=len(observed),observed_pairs=int(has_pair.sum()),
        all_frame_comparisons=len(estimates),floor_fit=tf_info,floor_summary=floor_summary,
        legacy_height_replayed_frames=len(differences),legacy_height_max_depth_difference_m=max(differences),
        input_files_unchanged=True,all_frame_rows_retained=True,physical_output=False,original_images_edited=False,
        intrinsics_refitted=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
