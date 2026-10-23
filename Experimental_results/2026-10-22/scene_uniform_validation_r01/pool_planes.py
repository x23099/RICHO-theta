"""Frame-balanced, capture-local plane pooling; no metric labels."""
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(ROOT/'src'),str(OLD)]
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import infer_up,unit,angle_degrees,align_up_preserving_heading_reference


def stable_planes(rows):
    clusters=[]
    for r in sorted(rows,key=lambda r:(float(r['plane_rms_deg']),int(r['frame']),int(r['line_index']),int(r['part']))):
        n=np.array(json.loads(r['normal_json']))
        distances=[np.degrees(np.arccos(np.clip(abs(n@c['seed']),-1,1))) for c in clusters]
        matches=[i for i,x in enumerate(distances) if x<=2]
        if matches:
            target=clusters[min(matches,key=lambda i:(distances[i],i))]
            n=n if n@target['seed']>=0 else -n
        else:
            target=dict(seed=n,members=[]);clusters.append(target)
        target['members'].append((r,n))
    output=[]
    for index,c in enumerate(clusters):
        by_frame={}
        for r,n in c['members']:
            f=int(r['frame'])
            if f not in by_frame:by_frame[f]=(r,n)
        representative=unit(np.mean([item[1] for item in by_frame.values()],axis=0))
        spread=max(angle_degrees(representative,item[1]) for item in by_frame.values())
        output.append(dict(cluster=index,seed=c['seed'].tolist(),normal=representative.tolist(),
            different_frames=len(by_frame),max_member_difference_deg=spread,
            frames=sorted(by_frame),accepted=len(by_frame)>=3 and spread<=2,reason='insufficient_repeats_or_unstable',usable_for_ffb=False))
    # One vote for each distinct representative plane, not each repeated frame.
    kept=[]
    for r in sorted((x for x in output if x['accepted']),key=lambda x:(-x['different_frames'],x['max_member_difference_deg'],x['cluster'])):
        if any(np.degrees(np.arccos(np.clip(abs(np.array(r['normal'])@np.array(k['normal'])),-1,1)))<2 for k in kept):
            r.update(accepted=False,reason='duplicate_representative_plane')
        else:r['reason']='stable_repeated_plane';kept.append(r)
    return output


def main():
    output=HERE/'pooled_results_r01'
    if output.exists():raise ValueError('new pooled output required')
    path=HERE/'scene_results_r01/line_candidates.csv'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    inputs=[path,HERE/'scene_results_r01/summary.json',HERE/'pooling_method.md',Path(__file__),floor,OLD/'scene_geometry.py']
    sources={str(p):sha256(p) for p in inputs}
    previous=json.loads((HERE/'scene_results_r01/summary.json').read_text())
    assert sha256(path)==previous['output_sha256'][path.name]
    frames=read_csv(HERE/'scene_results_r01/image_diagnostics.csv')
    groups=defaultdict(list)
    for r in read_csv(path):
        if r['accepted']=='True':groups[r['session'],r['role']].append(r)
    tf=json.loads(floor.read_text());T=np.array(tf['transform_target_from_source'])
    prior=np.array(tf['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    clusters=[];sessions=[]
    for session in sorted({r['session'] for r in frames}):
        hypotheses={}
        for role in ('estimate','heldout'):
            rows=stable_planes(groups[session,role])
            n=np.array([r['normal'] for r in rows if r['accepted']]).reshape(-1,3)
            hypotheses[role]=infer_up(n,prior)
            clusters.extend(dict(session=session,role=role,**r) for r in rows)
        a,b=hypotheses['estimate'],hypotheses['heldout']
        delta=angle_degrees(a['up'],b['up']) if a['accepted'] and b['accepted'] else None
        eligible=delta is not None and delta<=2
        row=dict(session=session,training_accepted=a['accepted'],heldout_accepted=b['accepted'],
            training_reason=a['reason'],heldout_reason=b['reason'],training_inlier_planes=a['inliers'],heldout_inlier_planes=b['inliers'],
            heldout_direction_difference_deg=delta,metric_eligible=eligible,temporal_validation='PASS' if eligible else 'FAIL_OR_INSUFFICIENT',
            up_optical_json=json.dumps(a['up']) if a['accepted'] else '',
            conditional_transform_json=json.dumps(align_up_preserving_heading_reference(T,a['up']).tolist()) if a['accepted'] else '',
            usable_for_ffb=False)
        sessions.append(row)
        print(session,'pooled train',a['inliers'],a['reason'],'heldout',b['inliers'],b['reason'],'eligible',eligible,flush=True)
    output.mkdir()
    csv_clusters=[{k+'_json' if k in ('seed','normal','frames') else k:json.dumps(v) if k in ('seed','normal','frames') else v for k,v in r.items()} for r in clusters]
    write_csv(output/'plane_clusters.csv',csv_clusters)
    write_csv(output/'session_hypotheses.csv',sessions)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    report=dict(status='COMPLETED_CAPTURE_LOCAL_POOLED_PLANE_DIAGNOSTIC',work_date='2026-10-22',source_sha256=sources,
        training_models=sum(r['training_accepted'] for r in sessions),temporally_checked_models=sum(r['metric_eligible'] for r in sessions),
        metric_labels_used_for_pose=False,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
