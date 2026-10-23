"""Uniform samples -> frozen scene algorithm, per-session resumable checkpoints."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(ROOT/'src'),str(OLD)]
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate
from scene_geometry import infer_up,angle_degrees,align_up_preserving_heading_reference
from curve_geometry import extract_curve_planes


def summarize_directions(frames,prior_transform):
    train=[r for r in frames if r['role']=='estimate' and r['accepted']]
    test=[r for r in frames if r['role']=='heldout' and r['accepted']]
    data=dict(images=len(frames),usable_estimate_frames=len(train),usable_heldout_frames=len(test),
        training_accepted=False,temporal_validation='NO_TRAINING_MODEL',metric_eligible=False,
        up_optical=None,training_spread_max_deg=None,heldout_spread_max_deg=None,
        conditional_transform=None,reason='fewer_than_two_usable_estimate_images',usable_for_ffb=False)
    if len(train)<2:return data
    g=np.mean([r['up_optical'] for r in train],axis=0);g/=np.linalg.norm(g)
    spread=max(angle_degrees(g,r['up_optical']) for r in train)
    data['training_spread_max_deg']=spread
    if spread>2:return dict(data,reason='estimate_directions_not_repeatable')
    data.update(training_accepted=True,up_optical=g.tolist(),conditional_transform=align_up_preserving_heading_reference(prior_transform,g).tolist())
    if test:data['heldout_spread_max_deg']=max(angle_degrees(g,r['up_optical']) for r in test)
    if len(test)<2:return dict(data,temporal_validation='INSUFFICIENT',reason='fewer_than_two_usable_heldout_images')
    if data['heldout_spread_max_deg']>2:return dict(data,temporal_validation='FAIL',reason='heldout_direction_disagrees')
    return dict(data,temporal_validation='PASS',metric_eligible=True,reason='conditional_scene_up_with_temporal_check')


def main():
    output=HERE/'scene_results_r01'
    if (output/'summary.json').exists():raise ValueError('completed output is frozen')
    manifest=HERE/'intake_r01/native_sample_manifest.csv'
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    inputs=[manifest,HERE/'intake_r01/summary.json',HERE/'intake_r01/sampling_plan.json',candidate,floor,
        HERE/'method.md',Path(__file__),OLD/'scene_geometry.py',OLD/'curve_geometry.py',ROOT/'src/angular_fisheye_geometry.py',
        ROOT/'src/fisheye_floor_geometry.py',ROOT/'src/cone_dataset.py']
    sources={str(p):sha256(p) for p in inputs}
    intake=json.loads((HERE/'intake_r01/summary.json').read_text())
    for name,h in intake['output_sha256'].items():assert sha256(HERE/'intake_r01'/name)==h
    camera=camera_from_candidate(json.loads(candidate.read_text()));tf=json.loads(floor.read_text())
    T=np.array(tf['transform_target_from_source']);prior=np.array(tf['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    samples=read_csv(manifest);groups=defaultdict(list)
    for r in samples:groups[r['session']].append(r)
    spec=dict(work_date='2026-10-22',source_sha256=sources,selection_uses_metric_labels=False)
    if output.exists():assert json.loads((output/'run_spec.json').read_text())==spec,'resume requires exactly identical sources'
    else:
        output.mkdir();(output/'run_spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    all_frames=[];all_lines=[];sessions=[]
    checkpoint_root=output/'sessions';checkpoint_root.mkdir(exist_ok=True)
    for session,group in sorted(groups.items()):
        folder=checkpoint_root/session;done=folder/'complete.json'
        if done.exists():
            state=json.loads(done.read_text())
            for name,h in state['output_sha256'].items():assert sha256(folder/name)==h
            data=json.loads((folder/'data.json').read_text())
            for r in group:assert sha256(Path(r['source_native_png']))==r['png_sha256']
            all_frames.extend(data['frames']);all_lines.extend(data['lines']);sessions.append(data['session'])
            print('resumed verified',session,flush=True);continue
        if folder.exists():raise ValueError('incomplete session checkpoint preserved; use a new output version')
        frame_rows=[];line_rows=[]
        for index,r in enumerate(group):
            path=Path(r['source_native_png']);assert sha256(path)==r['png_sha256']
            image=cv2.imread(str(path));assert image.shape==(720,1280,3)
            curves=extract_curve_planes(image,camera)
            normals=np.array([c['normal'] for c in curves if c['accepted']]).reshape(-1,3)
            pose=infer_up(normals,prior)
            frame_rows.append(dict(session=session,frame=int(r['frame']),time_sec=float(r['time_sec']),role=r['role'],
                source_native_png=str(path),png_sha256=r['png_sha256'],accepted=pose['accepted'],reason=pose['reason'],
                distinct_ray_planes=len(normals),inliers=pose['inliers'],up_optical=pose['up'],
                median_residual_deg=pose['median_residual_deg'],normal_span_deg=pose['normal_span_deg'],rank_gap_ratio=pose['rank_gap_ratio'],
                architectural_vertical_independently_verified=False,usable_for_ffb=False))
            for curve in curves:
                pixels=np.array(curve['actual_edge_pixels_json'])
                line=dict(session=session,frame=int(r['frame']),role=r['role'],line_index=curve['line_index'],part=curve['part'],
                    accepted=curve['accepted'],reason=curve['reason'],normal=curve.get('normal'),edge_points=len(pixels),
                    first_native=pixels[0].tolist(),last_native=pixels[-1].tolist(),
                    native_points_sha256=hashlib.sha256(pixels.astype('<i4').tobytes()).hexdigest(),
                    plane_rms_deg=curve.get('plane_rms_deg'),plane_max_deg=curve.get('plane_max_deg'),usable_for_ffb=False)
                line_rows.append(line)
            if index%20==0:print('scene',session,index+1,'/',len(group),flush=True)
        summary=dict(session=session,**summarize_directions(frame_rows,T))
        summary['prior_up_difference_deg']=angle_degrees(np.array(summary['up_optical']),T[:3,:3].T@np.array([0.,0.,1.])) if summary['up_optical'] is not None else None
        folder.mkdir()
        (folder/'data.json').write_text(json.dumps(dict(frames=frame_rows,lines=line_rows,session=summary),indent=2)+'\n')
        (folder/'complete.json').write_text(json.dumps(dict(output_sha256={'data.json':sha256(folder/'data.json')},
            run_spec_sha256=sha256(output/'run_spec.json')),indent=2)+'\n')
        all_frames.extend(frame_rows);all_lines.extend(line_rows);sessions.append(summary)
        print('finished',session,'train',summary['usable_estimate_frames'],'heldout',summary['usable_heldout_frames'],summary['reason'],flush=True)
    # CSVs carry explicit JSON for structured coordinates/vectors.
    # Keep stable field names even when structured values are None.
    def stable(rows,fields):
        output=[]
        for row in rows:
            output.append({k+'_json' if k in fields else k:json.dumps(v) if k in fields and v is not None else ('' if k in fields else v) for k,v in row.items()})
        return output
    write_csv(output/'image_diagnostics.csv',stable(all_frames,{'up_optical'}))
    write_csv(output/'line_candidates.csv',stable(all_lines,{'normal','first_native','last_native'}))
    write_csv(output/'session_hypotheses.csv',stable(sessions,{'up_optical','conditional_transform'}))
    assert all(sha256(Path(p))==h for p,h in sources.items())
    record=dict(status='COMPLETED_FIXED_RULE_UNIFORM_SCENE_DIAGNOSIS',work_date='2026-10-22',source_sha256=sources,
        sampled_images=len(samples),accepted_image_hypotheses=sum(r['accepted'] for r in all_frames),
        sessions=len(sessions),training_models=sum(r['training_accepted'] for r in sessions),
        temporally_checked_models=sum(r['metric_eligible'] for r in sessions),metric_labels_used_for_pose=False,
        original_images_edited=False,production_settings_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
