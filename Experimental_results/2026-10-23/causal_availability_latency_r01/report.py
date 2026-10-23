"""Plot local stage cost and availability; never imply measured live latency."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from replay_completion import HERE,SCENARIOS
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'report_r01'
    if output.exists():raise ValueError('new report output required')
    folders=[HERE/'benchmark_r01',HERE/'results_r01',HERE/'pending_control_r01']
    sources={str(HERE/'report.py'):sha256(HERE/'report.py')}
    for folder in folders:
        p=folder/'summary.json';d=json.loads(p.read_text());sources[str(p)]=sha256(p)
        for name,h in d['output_sha256'].items():assert sha256(folder/name)==h
    timings=read_csv(folders[0]/'scene_stage_measurements.csv')
    result={r['scenario']:r for r in read_csv(folders[1]/'completion_summary.csv')}
    control={r['scenario']:r for r in read_csv(folders[2]/'pending_control_summary.csv')}
    plot_rows=[dict(scenario=s,completion_aware_frames=int(result[s]['diagnostic_frames']),pending_hold_frames=int(control[s]['after_control_diagnostic_frames']),
        unfinished_rejection_output_frames=int(result[s]['outputs_with_newer_unfinished_rejection']),scope='one_static_capture_1547_frames',
        live_latency_measured=False,usable_for_ffb=False) for s in SCENARIOS]
    fig,axes=plt.subplots(1,2,figsize=(12,5.4))
    values=[float(r['scene_service_ms']) for r in timings]
    axes[0].hist(values,bins=20,color='#26869c',alpha=.85)
    axes[0].axvline(np.median(values),color='#ab5d2c',ls='--',label=f'Median {np.median(values):.1f} ms')
    axes[0].set_xlabel('CPU scene extraction + infer_up (ms), current PC only')
    axes[0].set_ylabel('Measured runs (52 fixed images x 3 passes)');axes[0].legend(fontsize=8)
    axes[0].set_title('Not the saved blue-pipeline time',fontsize=10)
    x=np.arange(3);w=.32
    axes[1].bar(x-w/2,[r['completion_aware_frames'] for r in plot_rows],w,label='Use completed scene results',color='#4686a8')
    axes[1].bar(x+w/2,[r['pending_hold_frames'] for r in plot_rows],w,label='Also hold while newer scene input is pending',color='#c9903c')
    axes[1].set_xticks(x);axes[1].set_xticklabels(['Zero-service\nreference','Local median\nper image','Local observed max\nper image'],fontsize=8)
    axes[1].set_ylabel('Diagnostic distance frames / 1,547 capture frames')
    axes[1].set_title('Current cone/query cost = 0 in these scenarios',fontsize=10)
    axes[1].legend(fontsize=7,loc='upper right')
    for i,r in enumerate(plot_rows):
        for offset,k in ((-w/2,'completion_aware_frames'),(w/2,'pending_hold_frames')):
            axes[1].text(i+offset,r[k]+3,str(r[k]),ha='center',fontsize=8)
    axes[1].set_ylim(0,470)
    for ax in axes:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('Completion-aware diagnostic counterfactual, not live FFB performance\nNo thresholds relaxed; freshness still measured from original scene input',fontsize=11)
    fig.tight_layout();output.mkdir();write_csv(output/'availability_chart_values.csv',plot_rows)
    fig.savefig(output/'local_scene_cost_and_availability.png',dpi=150);plt.close(fig)
    record=dict(status='COMPLETED_LOCAL_COST_AND_AVAILABILITY_PLOT',work_date='2026-10-23',source_sha256=sources,
        source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':main()
