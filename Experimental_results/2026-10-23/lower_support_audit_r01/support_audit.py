"""Pixel provenance, withheld-candidate references and leave-one-plane-out."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PREVIOUS=HERE.parent/'scene_separate_bands_r01'
UNIFORM=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(ROOT/'src'),str(OLD),str(PREVIOUS),str(UNIFORM)]
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import infer_up,angle_degrees,plane_from_pixels
from curve_geometry import extract_curve_planes
from band_geometry import extract_band
from angular_fisheye_geometry import camera_from_candidate
from analyze_scenes import summarize_directions


def normal_angle(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float)
    if a.shape!=(3,) or b.shape!=(3,) or not np.isfinite([a,b]).all() or not np.isclose(np.linalg.norm(a),1) or not np.isclose(np.linalg.norm(b),1):
        raise ValueError('finite unit normals required')
    return float(np.degrees(np.arccos(np.clip(abs(a@b),-1,1))))


def nearest(normal,rows):
    if not rows:return None,None
    angles=[normal_angle(normal,json.loads(r['normal_json'])) for r in rows]
    i=min(range(len(rows)),key=lambda j:(angles[j],int(rows[j]['line_index']),int(rows[j]['part'])))
    return angles[i],rows[i]


def near_seam(upper_pixels,lower_pixels):
    upper=np.asarray(upper_pixels,float);lower=np.asarray(lower_pixels,float)
    if upper.ndim!=2 or lower.ndim!=2 or upper.shape[1]!=2 or lower.shape[1]!=2 or not len(upper) or not len(lower):
        raise ValueError('observed nonempty pixel lists required')
    delta=lower[0]-upper[-1]
    return bool(1<=delta[1]<=6 and abs(delta[0])<=6)


def refit_connected(upper_pixels,lower_pixels,camera):
    if not near_seam(upper_pixels,lower_pixels):raise ValueError('only predeclared seam neighbors are concatenated')
    pixels=np.concatenate((upper_pixels,lower_pixels)).astype(float)
    return pixels,plane_from_pixels(pixels,camera)


def leave_one_out(members,pose,prior):
    if not pose['accepted']:raise ValueError('accepted original pose required')
    output=[]
    for i in pose['inlier_indices']:
        remaining=[r for j,r in enumerate(members) if j!=i]
        new=infer_up(np.array([json.loads(r['normal_json']) for r in remaining]).reshape(-1,3),prior)
        output.append(dict(removed_index=i,removed_band=members[i]['band'],removed_line_index=members[i]['line_index'],
            removed_part=members[i]['part'],remaining_accepted=new['accepted'],remaining_reason=new['reason'],remaining_inliers=new['inliers'],
            direction_difference_deg=angle_degrees(pose['up'],new['up']) if new['accepted'] else None,usable_for_ffb=False))
    return output


def encode_pose(sample,pose):
    return dict(session=sample['session'],frame=int(sample['frame']),time_sec=float(sample['time_sec']),role=sample['role'],
        accepted=pose['accepted'],reason=pose['reason'],inliers=pose['inliers'],up_optical=pose['up'],usable_for_ffb=False)


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new complete output required; no overwrite')
    prior_manifest=PREVIOUS/'results_r01/summary.json'
    data=json.loads(prior_manifest.read_text())
    for name,h in data['output_sha256'].items():assert sha256(prior_manifest.parent/name)==h
    for p,h in data['source_sha256'].items():assert sha256(Path(p))==h
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    inputs=[prior_manifest,Path(__file__),HERE/'method.md',candidate,floor,PREVIOUS/'band_geometry.py',
        OLD/'scene_geometry.py',OLD/'curve_geometry.py',UNIFORM/'analyze_scenes.py',ROOT/'src/angular_fisheye_geometry.py',
        ROOT/'src/cone_dataset.py',PREVIOUS/'results_r01/fused_plane_ledger.csv',PREVIOUS/'results_r01/image_diagnostics.csv',
        UNIFORM/'scene_results_r01/line_candidates.csv',UNIFORM/'intake_r01/native_sample_manifest.csv']
    sources={str(p):sha256(p) for p in inputs}
    camera=camera_from_candidate(json.loads(candidate.read_text()));tf=json.loads(floor.read_text())
    T=np.array(tf['transform_target_from_source']);prior=np.array(tf['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    samples=read_csv(UNIFORM/'intake_r01/native_sample_manifest.csv')
    sample_index={(r['session'],r['frame']):r for r in samples}
    old_frames=read_csv(PREVIOUS/'results_r01/image_diagnostics.csv')
    old_index={(r['session'],r['frame'],r['mode']):r for r in old_frames}
    grouped=defaultdict(list);upper_all=defaultdict(list)
    for r in read_csv(PREVIOUS/'results_r01/fused_plane_ledger.csv'):grouped[r['session'],r['frame']].append(r)
    for r in read_csv(UNIFORM/'scene_results_r01/line_candidates.csv'):
        if r['reason'] in ('accepted_plane','duplicate_ray_plane'):upper_all[r['session'],r['frame']].append(r)
    references=[];loo=[];support_rows=[];seams=[];actual_rows=[];counterfactual=[]
    verified_images=[];verified_native=[]
    for sample in samples:
        key=sample['session'],sample['frame'];members=grouped[key];original=old_index[key[0],key[1],'late_fusion']
        normals=np.array([json.loads(r['normal_json']) for r in members]).reshape(-1,3)
        pose=infer_up(normals,prior)
        assert pose['accepted']==(original['accepted']=='True') and pose['reason']==original['reason'] and pose['inliers']==int(original['inliers'])
        if pose['accepted']:np.testing.assert_array_equal(pose['up'],json.loads(original['up_optical_json']))
        original_inliers=set(pose['inlier_indices']) if pose['accepted'] else set()
        keep=[];lower_inlier_indices=[]
        for i,r in enumerate(members):
            if r['band']=='upper':keep.append(r);continue
            angle,closest=nearest(json.loads(r['normal_json']),upper_all[key])
            kept_angle,_=nearest(json.loads(r['normal_json']),[x for x in upper_all[key] if x['accepted']=='True'])
            veto=angle is not None and angle<2
            is_new=original['accepted']=='True' and old_index[key[0],key[1],'upper']['accepted']!='True'
            references.append(dict(session=key[0],frame=key[1],role=sample['role'],fusion_index=i,
                lower_line_index=r['line_index'],lower_part=r['part'],lower_first_native_json=r['first_native_json'],lower_last_native_json=r['last_native_json'],
                original_pose_accepted=pose['accepted'],newly_accepted_image=is_new,is_inlier=i in original_inliers,
                closest_any_upper_angle_deg=angle,closest_kept_upper_angle_deg=kept_angle,
                closest_upper_reason=closest['reason'] if closest else '',closest_upper_line_index=closest['line_index'] if closest else '',
                closest_upper_part=closest['part'] if closest else '',closest_upper_first_native_json=closest['first_native_json'] if closest else '',
                closest_upper_last_native_json=closest['last_native_json'] if closest else '',
                counterfactual_veto=veto,physical_same_edge_verified=False,usable_for_ffb=False))
            if not veto:keep.append(r)
            if i in original_inliers:lower_inlier_indices.append(i)
        strict=infer_up(np.array([json.loads(r['normal_json']) for r in keep]).reshape(-1,3),prior)
        counterfactual.append(encode_pose(sample,strict))
        if pose['accepted']:
            loo.extend(dict(session=key[0],frame=key[1],role=sample['role'],newly_accepted_image=old_index[key[0],key[1],'upper']['accepted']!='True',**r)
                for r in leave_one_out(members,pose,prior))
        if not lower_inlier_indices:continue
        path=Path(sample['source_native_png']);assert sha256(path)==sample['png_sha256'];sources[str(path)]=sample['png_sha256']
        image=cv2.imread(str(path));assert image.shape==(720,1280,3)
        upper_curves=extract_curve_planes(image,camera);lower_curves=extract_band(image,camera,band='lower')
        curve_index={(r['line_index'],r['part']):r for r in lower_curves}
        # Verify every emitted upper curve against frozen native coordinate hashes.
        old_curve_index={(int(r['line_index']),int(r['part'])):r for r in upper_all[key]}
        for curve in upper_curves:
            if curve['reason'] not in ('accepted_plane','duplicate_ray_plane'):continue
            old=old_curve_index[curve['line_index'],curve['part']]
            points=np.array(curve['actual_edge_pixels_json'])
            assert hashlib.sha256(points.astype('<i4').tobytes()).hexdigest()==old['native_points_sha256']
            assert curve['reason']==old['reason']
        verified_images.append(dict(session=key[0],frame=key[1],source_native_png=str(path),png_sha256=sample['png_sha256']))
        verified_native.append(dict(session=key[0],frame=key[1],role=sample['role'],lower_inliers=len(lower_inlier_indices)))
        for i in lower_inlier_indices:
            r=members[i];curve=curve_index[int(r['line_index']),int(r['part'])]
            np.testing.assert_array_equal(curve['normal'],json.loads(r['normal_json']))
            lower_pixels=np.array(curve['actual_edge_pixels_json'])
            actual_rows.append(dict(session=key[0],frame=key[1],fusion_index=i,band='lower',line_index=r['line_index'],part=r['part'],
                actual_edge_pixels_json=json.dumps(lower_pixels.tolist()),png_sha256=sample['png_sha256'],
                native_points_sha256=hashlib.sha256(lower_pixels.astype('<i4').tobytes()).hexdigest()))
            matches=[]
            for upper in upper_curves:
                if upper['reason'] not in ('accepted_plane','duplicate_ray_plane'):continue
                pixels=np.array(upper['actual_edge_pixels_json'])
                if not near_seam(pixels,lower_pixels):continue
                combined,fit=refit_connected(pixels,lower_pixels,camera)
                matches.append(fit['accepted'])
                seams.append(dict(session=key[0],frame=key[1],fusion_index=i,upper_line_index=upper['line_index'],upper_part=upper['part'],
                    upper_reason=upper['reason'],lower_line_index=r['line_index'],lower_part=r['part'],
                    upper_last_native_json=json.dumps(pixels[-1].tolist()),lower_first_native_json=json.dumps(lower_pixels[0].tolist()),
                    plane_normal_angle_deg=normal_angle(upper['normal'],curve['normal']),
                    combined_accepted=fit['accepted'],combined_reason=fit['reason'],combined_rms_deg=fit.get('plane_rms_deg'),
                    combined_max_deg=fit.get('plane_max_deg'),combined_points_sha256=hashlib.sha256(combined.astype('<i4').tobytes()).hexdigest(),
                    physical_same_edge_verified=False,usable_for_ffb=False))
            support_rows.append(dict(session=key[0],frame=key[1],role=sample['role'],fusion_index=i,
                newly_accepted_image=old_index[key[0],key[1],'upper']['accepted']!='True',
                lower_first_native_json=r['first_native_json'],lower_last_native_json=r['last_native_json'],
                seam_neighbor_pairs=len(matches),merged_plane_pass_pairs=sum(matches),seam_continuation_possible=any(matches),
                physical_same_edge_verified=False,usable_for_ffb=False))
        print('pixels verified',key,'lower inliers',len(lower_inlier_indices),flush=True)
    summaries=[]
    for session in sorted({r['session'] for r in counterfactual}):
        summary=summarize_directions([r for r in counterfactual if r['session']==session],T)
        summary.pop('conditional_transform');summary['temporal_candidate_eligible']=summary.pop('metric_eligible')
        summaries.append(dict(session=session,**summary))
    output.mkdir()
    def structured(rows):
        return [{k+'_json' if k=='up_optical' else k:json.dumps(v) if k=='up_optical' else v for k,v in r.items()} for r in rows]
    exports=[('all_lower_references.csv',references),('leave_one_plane_out.csv',loo),('lower_inlier_support.csv',support_rows),
        ('seam_pairs.csv',seams),('actual_lower_support.csv',actual_rows),('verified_native_images.csv',verified_images),
        ('counterfactual_images.csv',structured(counterfactual)),('counterfactual_sessions.csv',structured(summaries))]
    for name,rows in exports:write_csv(output/name,rows)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    new_inliers=[r for r in references if r['newly_accepted_image'] and r['is_inlier']]
    record=dict(status='COMPLETED_PIXEL_SUPPORT_AND_INDEPENDENCE_DIAGNOSTIC_NOT_GATE_ADOPTION',work_date='2026-10-23',source_sha256=sources,
        sampled_images=len(samples),original_accepted_images=sum(r['mode']=='late_fusion' and r['accepted']=='True' for r in old_frames),
        lower_candidate_references=len(references),native_verified_images=len(verified_images),lower_inlier_observations=len(support_rows),
        new_lower_inliers=len(new_inliers),new_lower_inliers_close_to_pre_dedup_upper=sum(r['counterfactual_veto'] for r in new_inliers),
        new_lower_inliers_with_seam_continuation=sum(r['newly_accepted_image'] and r['seam_continuation_possible'] for r in support_rows),
        leave_one_out_trials=len(loo),counterfactual_accepted_images=sum(r['accepted'] for r in counterfactual),
        counterfactual_temporal_passes=sum(r['temporal_candidate_eligible'] for r in summaries),
        metric_labels_used=False,source_images_edited=False,production_settings_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
