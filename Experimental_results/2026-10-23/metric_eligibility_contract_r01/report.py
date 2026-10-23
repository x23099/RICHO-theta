"""Summarize evidence availability, not distance accuracy or safety."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from audit_metrics import HERE,explicit_bool
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'report_r01'
    if output.exists():raise ValueError('new report output required')
    results=HERE/'results_r01';record=json.loads((results/'summary.json').read_text())
    for name,h in record['output_sha256'].items():assert sha256(results/name)==h
    sources={str(p):sha256(p) for p in (HERE/'report.py',results/'summary.json',results/'session_readiness.csv',results/'blocking_reasons.csv')}
    matrix=read_csv(results/'session_readiness.csv');rows=[]
    for r in matrix:
        if not int(r['cone_metric_frames']):continue
        rows.append(dict(session=r['session'],model='uniform_images',total_frames=int(r['cone_metric_frames']),
            offline_diagnostic_frames=int(r['uniform_diagnostic_frames']),
            diagnostic_withheld_frames=int(r['cone_metric_frames'])-int(r['uniform_diagnostic_frames']),
            physical_checks_satisfied_frames=int(r['physical_metric_frames']),
            own_session_pose_candidate=explicit_bool(r['uniform_own_pose_candidate']),usable_for_ffb=False))
    output.mkdir();write_csv(output/'uniform_frame_availability.csv',rows)
    labels=['Static center 1.3 m','Static center 2.0 m','Static left 1.3 m','No cone',
        'Static right 1.3 m','Floor + cone same capture','Static center 0.8 m','Paper + cone Oct 19']
    assert len(labels)==len(rows)==8
    fig,ax=plt.subplots(figsize=(11,5.6));y=list(range(len(rows)))
    available=[r['offline_diagnostic_frames'] for r in rows];held=[r['diagnostic_withheld_frames'] for r in rows]
    ax.barh(y,available,color='#2b7a9b',label='Offline diagnostic conditions met (not physical acceptance)')
    ax.barh(y,held,left=available,color='#c9ced3',label='Diagnostic distance withheld')
    ax.set_yticks(y);ax.set_yticklabels(labels,fontsize=9);ax.invert_yaxis()
    ax.set_xlabel('Unique frames, uniform-images model only (not independent trials)')
    ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    for i,r in enumerate(rows):ax.text(r['total_frames']+12,i,f"{available[i]}/{r['total_frames']}",va='center',fontsize=8)
    ax.set_xlim(0,max(r['total_frames'] for r in rows)*1.15)
    ax.legend(loc='lower right',fontsize=8)
    fig.suptitle('Frozen distance evidence audit: 1,107 / 6,876 diagnostic frames\nPhysical evidence set remains unverified; no ROS / TF / FFB output',fontsize=11)
    fig.tight_layout();fig.savefig(output/'distance_evidence_availability.png',dpi=150);plt.close(fig)
    assert all(sha256(__import__('pathlib').Path(p))==h for p,h in sources.items())
    summary=dict(status='COMPLETED_EVIDENCE_AVAILABILITY_REPORT_NOT_ACCURACY_APPROVAL',work_date='2026-10-23',
        source_sha256=sources,diagnostic_frames=sum(available),withheld_frames=sum(held),unique_frames=sum(available)+sum(held),
        physical_checks_satisfied_frames=0,models_plotted=1,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
