"""Independent curve-detector comparison using the same frozen split/guards."""
from collections import defaultdict
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
from scene_geometry import infer_up,angle_degrees,align_up_preserving_heading_reference
from curve_geometry import extract_curve_planes


def main():
    output=HERE/'curve_results_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    candidate=HERE.parent/'front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    previous=HERE.parent/'angular_metric_validation_r01/results_r01/summary.json'
    frames_path=HERE/'results_r01/image_diagnostics.csv'
    files=[candidate,previous,frames_path,HERE/'curve_method.md',HERE/'scene_geometry.py',HERE/'curve_geometry.py',Path(__file__),
           ROOT/'src/angular_fisheye_geometry.py',ROOT/'src/fisheye_floor_geometry.py',ROOT/'src/cone_dataset.py']
    sources={str(p):sha256(p) for p in files}
    old=json.loads((HERE/'results_r01/summary.json').read_text())
    assert sha256(frames_path)==old['output_sha256'][frames_path.name]
    info=json.loads(previous.read_text())['floor_fit'];Tpaper=np.array(info['transform_target_from_source'])
    prior=np.array(info['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    camera=camera_from_candidate(json.loads(candidate.read_text()))
    grouped=defaultdict(list)
    for r in read_csv(frames_path):grouped[r['session']].append(r)
    all_frames=[];all_lines=[];sessions=[];transforms={}
    for session,frames in sorted(grouped.items()):
        current=[]
        for r in frames:
            path=Path(r['source_native_png']);assert sha256(path)==r['png_sha256'];sources[str(path)]=sha256(path)
            lines=extract_curve_planes(cv2.imread(str(path)),camera)
            normals=np.array([r['normal'] for r in lines if r['accepted']]).reshape(-1,3)
            hypothesis=infer_up(normals,prior)
            item=dict(session=session,frame=int(r['frame']),role=r['role'],source_native_png=str(path),
                distinct_ray_planes=len(normals),accepted=hypothesis['accepted'],reason=hypothesis['reason'],
                up_optical_json=json.dumps(hypothesis['up']) if hypothesis['accepted'] else '',
                inliers=hypothesis['inliers'],median_residual_deg=hypothesis['median_residual_deg'],
                normal_span_deg=hypothesis['normal_span_deg'],rank_gap_ratio=hypothesis['rank_gap_ratio'],usable_for_ffb=False)
            current.append(item);all_frames.append(item)
            for line in lines:
                row=dict(session=session,frame=int(r['frame']))
                for k in ('line_index','part','hough_votes','rho','theta','native_y_span','accepted','reason','plane_rms_deg','plane_max_deg','ray_span_deg'):
                    row[k]=line.get(k)
                row.update(actual_edge_pixels_json=json.dumps(line['actual_edge_pixels_json']),
                    normal_json=json.dumps(line.get('normal')),usable_for_ffb=False)
                all_lines.append(row)
        train=[r for r in current if r['role']=='estimate' and r['accepted']]
        test=[r for r in current if r['role']=='heldout' and r['accepted']]
        accepted=False;g=None;spread=None;difference=None;holdout=None;T=None
        reason='fewer_than_two_usable_estimate_images'
        if len(train)>=2:
            g=np.mean([json.loads(r['up_optical_json']) for r in train],axis=0);g/=np.linalg.norm(g)
            spread=max(angle_degrees(g,np.array(json.loads(r['up_optical_json']))) for r in train)
            accepted=spread<=2
            reason='conditional_scene_up_not_floor_survey' if accepted else 'estimate_directions_not_repeatable'
            if accepted:
                T=align_up_preserving_heading_reference(Tpaper,g);transforms[session]=T
                difference=angle_degrees(g,Tpaper[:3,:3].T@np.array([0.,0.,1.]))
                holdout=max((angle_degrees(g,np.array(json.loads(r['up_optical_json']))) for r in test),default=None)
        sessions.append(dict(session=session,images=len(current),usable_estimate_frames=len(train),usable_heldout_frames=len(test),
            accepted=accepted,reason=reason,up_optical_json=json.dumps(g.tolist()) if accepted else '',
            estimate_spread_max_deg=spread,heldout_direction_max_difference_deg=holdout,delta_from_paper5_up_deg=difference,
            conditional_transform_json=json.dumps(T.tolist()) if accepted else '',
            architectural_vertical_independently_verified=False,usable_for_ffb=False))
        print(session,accepted,'train',len(train),'heldout',len(test),'delta',difference,flush=True)
    # Metric evaluation is strictly after all scene-direction inference.
    observations=HERE.parent/'cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    sources[str(observations)]=sha256(observations)
    metrics=[]
    for r in read_csv(observations):
        T=transforms.get(r['session']);pair=json.loads(r['native_colour_pair_json']) if r['native_colour_pair_json'] else None
        row=dict(dataset=r['dataset'],session=r['session'],frame=int(r['frame']),condition=r['condition'],
            reference_z_m=float(r['reference_z_m']) if r['reference_z_m'] else None,estimated=False,
            reason='no_accepted_scene_up' if T is None else 'no_observed_pair',floor_forward_m=None,floor_radial_m=None,
            height_forward_m=None,height_base_m=None,tip_elevation_deg=None,usable_for_ffb=False)
        if T is not None and pair is not None:
            rays,valid=unproject(pair,camera,image_size=(1280,720))
            if valid.all():
                point,ok=floor_from_rays(rays[1:],valid[1:],T)
                height=segment_from_rays(rays,T)
                row['tip_elevation_deg']=float(np.degrees(np.arcsin(np.clip((T[:3,:3]@rays[0])[2],-1,1))))
                if ok[0] and height['estimated']:
                    row.update(estimated=True,reason='conditional_scene_geometry_not_verified_contact',floor_forward_m=float(point[0,0]),
                        floor_radial_m=float(np.linalg.norm(point[0,:2])),height_forward_m=height['base_target_m'][0],height_base_m=height['base_target_m'][2])
        metrics.append(row)
    summary=[];groups=defaultdict(list)
    for r in metrics:groups[r['dataset'],r['session'],r['condition']].append(r)
    for (dataset,session,condition),group in sorted(groups.items()):
        selected=[r for r in group if r['estimated']]
        med=lambda k:float(np.median([r[k] for r in selected])) if selected else None
        summary.append(dict(dataset=dataset,session=session,condition=condition,frames=len(group),estimated=len(selected),
            reference_z_m=group[0]['reference_z_m'],floor_forward_median_m=med('floor_forward_m'),floor_radial_median_m=med('floor_radial_m'),
            height_forward_median_m=med('height_forward_m'),height_base_median_m=med('height_base_m'),tip_elevation_median_deg=med('tip_elevation_deg'),usable_for_ffb=False))
    assert all(sha256(Path(p))==v for p,v in sources.items())
    output.mkdir()
    for name,rows in [('image_diagnostics.csv',all_frames),('line_candidates.csv',all_lines),('session_hypotheses.csv',sessions),
                      ('cone_all_frames.csv',metrics),('cone_condition_summary.csv',summary)]:write_csv(output/name,rows)
    record=dict(status='COMPLETED_CONDITIONAL_CURVE_DIAGNOSIS',source_sha256=sources,native_images=len(all_frames),
        accepted_session_hypotheses=len(transforms),metric_frames=len(metrics),pose_inference_used_metric_labels=False,
        intrinsics_refitted=False,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':main()
