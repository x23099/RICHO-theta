"""Capture-local upper/lower diagnostic; fixed old samples, no metric labels."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PREVIOUS=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
AUDIT=ROOT/'Experimental_results/2026-10-22/scene_rejection_audit_r01'
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(ROOT/'src'),str(OLD),str(PREVIOUS)]
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate
from scene_geometry import infer_up
from curve_geometry import extract_curve_planes
from analyze_scenes import summarize_directions
from band_geometry import extract_band,fuse_planes,independent_agreement

MODES=('upper','lower','late_fusion','independent_agreement')


def describe_frame(sample,mode,pose,members,upper,lower):
    indices=pose.get('inlier_indices',[]) if pose['accepted'] else []
    # Agreement uses the retained upper pose, whose indices refer to upper rows.
    return dict(session=sample['session'],frame=int(sample['frame']),role=sample['role'],time_sec=float(sample['time_sec']),
        mode=mode,accepted=pose['accepted'],reason=pose['reason'],inliers=pose['inliers'],
        distinct_input_planes=len(members),up_optical=pose['up'],
        upper_input_planes=len(upper),lower_input_planes=len(lower),
        accepted_inliers_from_upper=sum(members[i]['band']=='upper' for i in indices) if pose['accepted'] else None,
        accepted_inliers_from_lower=sum(members[i]['band']=='lower' for i in indices) if pose['accepted'] else None,
        band_direction_difference_deg=pose.get('band_direction_difference_deg'),
        physical_vertical_verified=False,usable_for_ffb=False)


def main():
    output=HERE/'results_r01'
    if (output/'summary.json').exists():raise ValueError('completed results are frozen')
    manifests=[PREVIOUS/'intake_r01/summary.json',PREVIOUS/'scene_results_r01/summary.json',
               AUDIT/'roi_probe_results_r01/summary.json']
    for path in manifests:
        record=json.loads(path.read_text())
        for name,h in record['output_sha256'].items():assert sha256(path.parent/name)==h
        for p,h in record['source_sha256'].items():assert sha256(Path(p))==h
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    inputs=manifests+[Path(__file__),HERE/'band_geometry.py',HERE/'method.md',candidate,floor,
        PREVIOUS/'analyze_scenes.py',OLD/'scene_geometry.py',OLD/'curve_geometry.py',ROOT/'src/angular_fisheye_geometry.py',
        ROOT/'src/fisheye_floor_geometry.py',ROOT/'src/cone_dataset.py',PREVIOUS/'intake_r01/native_sample_manifest.csv',
        PREVIOUS/'scene_results_r01/line_candidates.csv',PREVIOUS/'scene_results_r01/image_diagnostics.csv',
        AUDIT/'results_r02/representative_plan.json']
    sources={str(p):sha256(p) for p in inputs}
    camera=camera_from_candidate(json.loads(candidate.read_text()));tf=json.loads(floor.read_text())
    T=np.array(tf['transform_target_from_source']);prior=np.array(tf['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    samples=read_csv(PREVIOUS/'intake_r01/native_sample_manifest.csv')
    upper_index=defaultdict(list)
    for row in read_csv(PREVIOUS/'scene_results_r01/line_candidates.csv'):
        if row['accepted']=='True':upper_index[row['session'],int(row['frame'])].append(row)
    baseline={(r['session'],int(r['frame'])):r for r in read_csv(PREVIOUS/'scene_results_r01/image_diagnostics.csv')}
    reps=json.loads((AUDIT/'results_r02/representative_plan.json').read_text())
    rep_keys={(r['session'],int(r['frame'])) for r in reps}
    spec=dict(work_date='2026-10-23',source_sha256=sources,modes=MODES,
        native_bands={'upper':[40,60,600,300],'lower':[40,301,600,430]},metric_labels_used=False)
    # JSON round trip normalizes tuples before a resumable spec comparison.
    spec=json.loads(json.dumps(spec))
    if output.exists():assert json.loads((output/'run_spec.json').read_text())==spec
    else:
        output.mkdir();(output/'run_spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    groups=defaultdict(list)
    for r in samples:groups[r['session']].append(r)
    checkpoint=output/'sessions';checkpoint.mkdir(exist_ok=True)
    all_frames=[];all_lines=[];all_fusion=[];all_duplicates=[];sessions=[];baseline_checks=0
    for session,group in sorted(groups.items()):
        folder=checkpoint/session;done=folder/'complete.json'
        if done.exists():
            completion=json.loads(done.read_text());assert completion['run_spec_sha256']==sha256(output/'run_spec.json')
            assert completion['data_sha256']==sha256(folder/'data.json')
            for sample in group:assert sha256(Path(sample['source_native_png']))==sample['png_sha256']
            data=json.loads((folder/'data.json').read_text());print('resumed',session,flush=True)
        else:
            if folder.exists():raise ValueError('incomplete checkpoint preserved; use a new version')
            frames=[];lines=[];fusion_rows=[];duplicates=[];checks=0
            for sample in group:
                key=(session,int(sample['frame']));path=Path(sample['source_native_png'])
                assert sha256(path)==sample['png_sha256'];image=cv2.imread(str(path))
                if key in rep_keys:
                    assert extract_band(image,camera,band='upper')==extract_curve_planes(image,camera);checks+=1
                upper=[dict(band='upper',line_index=int(r['line_index']),part=int(r['part']),
                            normal=json.loads(r['normal_json']),first_native_json=r['first_native_json'],
                            last_native_json=r['last_native_json']) for r in upper_index[key]]
                curves=extract_band(image,camera,band='lower');lower=[]
                for row in curves:
                    pixels=np.array(row['actual_edge_pixels_json']);identity=dict(band='lower',line_index=row['line_index'],part=row['part'])
                    coords=dict(first_native_json=json.dumps(pixels[0].tolist()),last_native_json=json.dumps(pixels[-1].tolist()))
                    if row['accepted']:lower.append(dict(**identity,**coords,normal=row['normal']))
                    lines.append(dict(session=session,frame=sample['frame'],role=sample['role'],**identity,**coords,
                        accepted=row['accepted'],reason=row['reason'],normal_json=json.dumps(row.get('normal')),
                        edge_points=len(pixels),native_points_sha256=hashlib.sha256(pixels.astype('<i4').tobytes()).hexdigest(),
                        usable_for_ffb=False))
                fused,rejected=fuse_planes(upper,lower)
                for i,row in enumerate(fused):
                    fusion_rows.append(dict(session=session,frame=sample['frame'],role=sample['role'],fusion_index=i,
                        band=row['band'],line_index=row['line_index'],part=row['part'],normal_json=json.dumps(row['normal']),
                        first_native_json=row['first_native_json'],last_native_json=row['last_native_json'],usable_for_ffb=False))
                duplicates.extend(dict(session=session,frame=sample['frame'],role=sample['role'],**r,usable_for_ffb=False) for r in rejected)
                poses={}
                for mode,members in [('upper',upper),('lower',lower),('late_fusion',fused)]:
                    n=np.array([r['normal'] for r in members]).reshape(-1,3);poses[mode]=infer_up(n,prior)
                    frames.append(describe_frame(sample,mode,poses[mode],members,upper,lower))
                base=baseline[key];u=poses['upper']
                assert u['accepted']==(base['accepted']=='True') and u['reason']==base['reason'] and u['inliers']==int(base['inliers'])
                if u['accepted']:np.testing.assert_array_equal(u['up'],json.loads(base['up_optical_json']))
                agreement=independent_agreement(u,poses['lower'])
                frames.append(describe_frame(sample,'independent_agreement',agreement,upper,upper,lower))
            session_rows=[]
            for mode in MODES:
                summary=summarize_directions([r for r in frames if r['mode']==mode],T)
                # Reuse temporal checks only. Do not export a metric transform.
                summary.pop('conditional_transform');summary['temporal_candidate_eligible']=summary.pop('metric_eligible')
                session_rows.append(dict(session=session,mode=mode,**summary))
            data=dict(frames=frames,lines=lines,fusion=fusion_rows,duplicates=duplicates,sessions=session_rows,baseline_checks=checks)
            folder.mkdir();(folder/'data.json').write_text(json.dumps(data,indent=2)+'\n')
            (folder/'complete.json').write_text(json.dumps(dict(run_spec_sha256=sha256(output/'run_spec.json'),
                data_sha256=sha256(folder/'data.json')),indent=2)+'\n')
            print(session,[(r['mode'],r['usable_estimate_frames'],r['usable_heldout_frames'],r['temporal_candidate_eligible']) for r in session_rows],flush=True)
        all_frames.extend(data['frames']);all_lines.extend(data['lines']);all_fusion.extend(data['fusion'])
        all_duplicates.extend(data['duplicates']);sessions.extend(data['sessions']);baseline_checks+=data['baseline_checks']
    def structured(rows):
        return [{k+'_json' if k=='up_optical' else k:json.dumps(v) if k=='up_optical' else v for k,v in r.items()} for r in rows]
    for name,rows in [('image_diagnostics.csv',structured(all_frames)),('lower_line_candidates.csv',all_lines),
        ('fused_plane_ledger.csv',all_fusion),('cross_band_duplicates.csv',all_duplicates),('session_hypotheses.csv',structured(sessions))]:
        write_csv(output/name,rows)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    summary=dict(status='COMPLETED_SEPARATE_BAND_CONTROL_NOT_METRIC_OR_HARDWARE_VALIDATION',work_date='2026-10-23',
        source_sha256=sources,sampled_images=len(samples),retained_image_mode_rows=len(all_frames),
        baseline_equivalence_representatives=baseline_checks,baseline_pose_comparisons=len(samples),
        accepted_images_by_mode={mode:sum(r['accepted'] for r in all_frames if r['mode']==mode) for mode in MODES},
        temporally_checked_sessions_by_mode={mode:sum(r['temporal_candidate_eligible'] for r in sessions if r['mode']==mode) for mode in MODES},
        cross_band_duplicate_rows=len(all_duplicates),metric_labels_used=False,physical_vertical_verified=False,
        source_images_edited=False,production_settings_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
