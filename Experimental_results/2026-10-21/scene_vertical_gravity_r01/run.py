"""Architectural ray planes first; metric object data only afterwards."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate,unproject,floor_from_rays,segment_from_rays
from scene_geometry import extract_planes,infer_up,angle_degrees,align_up_preserving_heading_reference


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    candidate=HERE.parent/'front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    previous=HERE.parent/'angular_metric_validation_r01/results_r01/summary.json'
    info=json.loads(previous.read_text())['floor_fit']
    Tnom=np.array(info['nominal_transform']);Tpaper=np.array(info['transform_target_from_source'])
    prior=Tnom[:3,:3].T@np.array([0.,0.,1.])
    camera=camera_from_candidate(json.loads(candidate.read_text()))
    inputs=[candidate,previous,HERE/'method.md',HERE/'scene_geometry.py',Path(__file__),
            ROOT/'src/angular_fisheye_geometry.py',ROOT/'src/fisheye_floor_geometry.py',ROOT/'src/cone_dataset.py']
    sources={str(p):sha256(p) for p in inputs}
    studies=['2026-10-15/cone_static_distance_r01','2026-10-15/floor_cone_same_pose_analysis_r01',
             '2026-10-15/paper_reference7_r01','2026-10-19/paper_cone_2m_validation_r01']
    sessions=defaultdict(list)
    for study in studies:
        folder=ROOT/'Experimental_results'/study
        manifest=folder/'raw_sample_manifest.csv';sources[str(manifest)]=sha256(manifest)
        for r in read_csv(manifest):sessions[r['session']].append((folder/r['file'],r))
    assert len(sessions)==9
    frame_rows=[];line_rows=[];session_rows=[];transforms={}
    for session,samples in sorted(sessions.items()):
        samples.sort(key=lambda item:int(item[1]['frame']))
        split=len(samples)//2
        session_frames=[];normal_sets={}
        for index,(png,original) in enumerate(samples):
            assert sha256(png)==original['png_sha256'],png
            sources[str(png)]=sha256(png)
            image=cv2.imread(str(png));assert image.shape==(720,1280,3)
            candidates=extract_planes(image,camera)
            normals=np.array([r['normal'] for r in candidates if r['accepted']]).reshape(-1,3)
            hypothesis=infer_up(normals,prior)
            frame=int(original['frame']);normal_sets[frame]=normals
            row=dict(session=session,frame=frame,source_native_png=str(png),png_sha256=original['png_sha256'],
                role='estimate' if index<split else 'heldout',accepted=hypothesis['accepted'],reason=hypothesis['reason'],
                candidate_segments=len(candidates),distinct_ray_planes=len(normals),inliers=hypothesis['inliers'],
                up_optical_json=json.dumps(hypothesis['up']) if hypothesis['up'] is not None else '',
                inlier_indices_json=json.dumps(hypothesis['inlier_indices']),median_residual_deg=hypothesis['median_residual_deg'],
                normal_span_deg=hypothesis['normal_span_deg'],rank_gap_ratio=hypothesis['rank_gap_ratio'],
                architectural_vertical_independently_verified=False,usable_for_ffb=False)
            frame_rows.append(row);session_frames.append(row)
            for line in candidates:
                selected_fields=('line_index','length_px','edge_points','accepted','reason','plane_rms_deg','plane_max_deg','ray_span_deg')
                item=dict(session=session,frame=frame,source_native_png=str(png))
                item.update({k:line.get(k) for k in selected_fields})
                item.update(lsd_endpoints_json=json.dumps(line['lsd_endpoints_json']),
                    actual_edge_pixels_json=json.dumps(line['edge_pixels_json']),normal_json=json.dumps(line.get('normal')),
                    usable_for_ffb=False)
                line_rows.append(item)
        train=[r for r in session_frames if r['role']=='estimate' and r['accepted']]
        test=[r for r in session_frames if r['role']=='heldout' and r['accepted']]
        accepted=False;g=None;spread=None;test_spread=None;delta=None;T=None
        reason='fewer_than_two_usable_estimate_images'
        if len(train)>=2:
            g=np.mean([json.loads(r['up_optical_json']) for r in train],axis=0);g/=np.linalg.norm(g)
            spread=max(angle_degrees(g,np.array(json.loads(r['up_optical_json']))) for r in train)
            accepted=spread<=2
            reason='conditional_scene_up_not_floor_survey' if accepted else 'estimate_directions_not_repeatable'
            if accepted:
                T=align_up_preserving_heading_reference(Tpaper,g);transforms[session]=T
                delta=angle_degrees(g,Tpaper[:3,:3].T@np.array([0.,0.,1.]))
                test_spread=max((angle_degrees(g,np.array(json.loads(r['up_optical_json']))) for r in test),default=None)
        heldout_residuals=[]
        if accepted:
            for r in session_frames:
                if r['role']=='heldout':
                    n=normal_sets[r['frame']]
                    heldout_residuals.extend(np.degrees(np.arcsin(np.clip(abs(n@g),0,1))).tolist())
        session_rows.append(dict(session=session,sample_frames=len(samples),estimate_frames=split,heldout_frames=len(samples)-split,
            usable_estimate_frames=len(train),usable_heldout_frames=len(test),accepted=accepted,reason=reason,
            up_optical_json=json.dumps(g.tolist()) if accepted else '',estimate_spread_max_deg=spread,
            heldout_direction_max_difference_deg=test_spread,delta_from_paper5_up_deg=delta,
            heldout_all_plane_count=len(heldout_residuals),
            heldout_all_plane_median_residual_deg=float(np.median(heldout_residuals)) if heldout_residuals else None,
            heldout_all_plane_within_one_degree=sum(x<=1 for x in heldout_residuals),
            conditional_transform_json=json.dumps(T.tolist()) if accepted else '',
            height_or_yaw_independently_measured=False,architectural_vertical_independently_verified=False,usable_for_ffb=False))
        print(session,'scene up:',accepted,reason,'train',len(train),'heldout',len(test),flush=True)
    # Only AFTER scene inference finishes do we read object observations / labels.
    observed_path=HERE.parent/'cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    sources[str(observed_path)]=sha256(observed_path)
    metrics=[]
    for r in read_csv(observed_path):
        T=transforms.get(r['session']);pair=json.loads(r['native_colour_pair_json']) if r['native_colour_pair_json'] else None
        row=dict(dataset=r['dataset'],session=r['session'],frame=int(r['frame']),condition=r['condition'],
            reference_z_m=float(r['reference_z_m']) if r['reference_z_m'] else None,estimated=False,
            reason='no_accepted_scene_up' if T is None else 'no_observed_pair',floor_forward_m=None,
            floor_radial_m=None,height_forward_m=None,height_base_m=None,tip_elevation_deg=None,
            floor_contact_verified=False,usable_for_ffb=False)
        if T is not None and pair is not None:
            rays,valid=unproject(pair,camera,image_size=(1280,720))
            if valid.all():
                points,fvalid=floor_from_rays(rays[1:],valid[1:],T)
                height=segment_from_rays(rays,T)
                row['tip_elevation_deg']=float(np.degrees(np.arcsin(np.clip((T[:3,:3]@rays[0])[2],-1,1))))
                if fvalid[0] and height['estimated']:
                    row.update(estimated=True,reason='conditional_scene_geometry_not_verified_contact',
                        floor_forward_m=float(points[0,0]),floor_radial_m=float(np.linalg.norm(points[0,:2])),
                        height_forward_m=height['base_target_m'][0],height_base_m=height['base_target_m'][2])
        metrics.append(row)
    metric_summary=[]
    groups=defaultdict(list)
    for r in metrics:groups[r['dataset'],r['session'],r['condition']].append(r)
    for (dataset,session,condition),group in sorted(groups.items()):
        estimated=[r for r in group if r['estimated']]
        med=lambda k:float(np.median([r[k] for r in estimated])) if estimated else None
        metric_summary.append(dict(dataset=dataset,session=session,condition=condition,frames=len(group),estimated=len(estimated),
            reference_z_m=group[0]['reference_z_m'],floor_forward_median_m=med('floor_forward_m'),
            floor_radial_median_m=med('floor_radial_m'),height_forward_median_m=med('height_forward_m'),
            height_base_median_m=med('height_base_m'),tip_elevation_median_deg=med('tip_elevation_deg'),usable_for_ffb=False))
    paper_path=ROOT/'Experimental_results/2026-10-15/paper_reference7_r01/analysis_r01/reference_points_primary170.csv'
    paired_path=ROOT/'Experimental_results/2026-10-19/paper_cone_2m_validation_r01/analysis_r01/summary.json'
    for path in (paper_path,paired_path):sources[str(path)]=sha256(path)
    paper_session='itiawase2_20261015_183552_599';pair_session='paper_cone_center_z2p00_r01_20261019_180411_245'
    paper=[dict(r,session=paper_session) for r in read_csv(paper_path)]
    pair_info=json.loads(paired_path.read_text())
    paper.append(dict(point_id='paper_cone_2m',pixel_x=pair_info['paper_reference_native_xy'][0],
        pixel_y=pair_info['paper_reference_native_xy'][1],reference_x_m=0.,reference_z_m=2.,session=pair_session))
    paper_rows=[]
    for r in paper:
        T=transforms.get(r['session']);row=dict(point_id=r['point_id'],session=r['session'],estimated=False,
            reference_x_m=float(r['reference_x_m']),reference_z_m=float(r['reference_z_m']),x_right_m=None,z_forward_m=None,
            floor_radial_m=None,planar_error_m=None,usable_for_ffb=False)
        if T is not None:
            rays,valid=unproject([[float(r['pixel_x']),float(r['pixel_y'])]],camera,image_size=(1280,720))
            point,valid=floor_from_rays(rays,valid,T)
            if valid[0]:
                row.update(estimated=True,x_right_m=float(-point[0,1]),z_forward_m=float(point[0,0]),
                    floor_radial_m=float(np.linalg.norm(point[0,:2])),
                    planar_error_m=float(np.hypot(-point[0,1]-row['reference_x_m'],point[0,0]-row['reference_z_m'])))
        paper_rows.append(row)
    assert all(sha256(Path(path))==digest for path,digest in sources.items())
    output.mkdir()
    for name,rows in [('image_diagnostics.csv',frame_rows),('line_candidates.csv',line_rows),('session_hypotheses.csv',session_rows),
                      ('cone_all_frames.csv',metrics),('cone_condition_summary.csv',metric_summary),('paper_reference_results.csv',paper_rows)]:
        write_csv(output/name,rows)
    record=dict(status='COMPLETED_CONDITIONAL_ARCHITECTURAL_DIAGNOSIS',source_sha256=sources,native_images=len(frame_rows),
        sessions=len(sessions),accepted_session_hypotheses=len(transforms),metric_frames=len(metrics),
        pose_inference_used_metric_labels=False,intrinsics_refitted=False,source_images_edited=False,
        physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
