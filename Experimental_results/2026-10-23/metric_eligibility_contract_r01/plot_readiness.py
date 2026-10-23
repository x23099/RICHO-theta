"""Presentation layout only; preserve the first report and all numeric data."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from audit_metrics import HERE
from cone_dataset import read_csv,sha256


def main():
    output=HERE/'plots_r01'
    if output.exists():raise ValueError('new plot output required')
    source=HERE/'report_r01';record=json.loads((source/'summary.json').read_text())
    for name,h in record['output_sha256'].items():assert sha256(source/name)==h
    sources={str(p):sha256(p) for p in (HERE/'plot_readiness.py',source/'summary.json',source/'uniform_frame_availability.csv')}
    rows=read_csv(source/'uniform_frame_availability.csv')
    labels=['Static center 1.3 m','Static center 2.0 m','Static left 1.3 m','No cone',
        'Static right 1.3 m','Floor + cone same capture','Static center 0.8 m','Paper + cone Oct 19']
    assert len(rows)==len(labels)==8
    available=[int(r['offline_diagnostic_frames']) for r in rows]
    held=[int(r['diagnostic_withheld_frames']) for r in rows]
    fig,ax=plt.subplots(figsize=(11,6.2));y=list(range(8))
    ax.barh(y,available,color='#2b7a9b',label='Offline diagnostic conditions met (not physical acceptance)')
    ax.barh(y,held,left=available,color='#c9ced3',label='Diagnostic distance withheld')
    ax.set_yticks(y);ax.set_yticklabels(labels,fontsize=9);ax.invert_yaxis()
    ax.set_xlabel('Unique frames, uniform-images model only (not independent trials)')
    ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    for i,r in enumerate(rows):ax.text(int(r['total_frames'])+12,i,f"{available[i]}/{r['total_frames']}",va='center',fontsize=8)
    ax.set_xlim(0,max(int(r['total_frames']) for r in rows)*1.15)
    fig.suptitle('Frozen distance evidence audit: 1,107 / 6,876 diagnostic frames\nPhysical evidence set remains unverified; no ROS / TF / FFB output',fontsize=11)
    fig.legend(loc='lower center',fontsize=8)
    fig.tight_layout(rect=(0,.10,1,1));output.mkdir()
    fig.savefig(output/'distance_evidence_availability.png',dpi=150);plt.close(fig)
    summary=dict(status='COMPLETED_LEGEND_LAYOUT_CORRECTION_ONLY',work_date='2026-10-23',source_sha256=sources,
        numeric_data_changed=False,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={'distance_evidence_availability.png':sha256(output/'distance_evidence_availability.png')})
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
