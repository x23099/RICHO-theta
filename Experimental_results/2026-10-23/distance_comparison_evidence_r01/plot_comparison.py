"""Numerical-only figures with explicit capture and frame-population scopes."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from compare_saved import HERE
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'plots_r01'
    if output.exists():raise ValueError('new plot output required')
    results=HERE/'results_r01';proof=json.loads((results/'summary.json').read_text())
    for name,h in proof['output_sha256'].items():assert sha256(results/name)==h
    sources={str(p):sha256(p) for p in (HERE/'plot_comparison.py',results/'summary.json',results/'matched_condition_summary.csv',results/'floor_scope_summary.csv')}
    points=read_csv(results/'floor_scope_summary.csv');matched=read_csv(results/'matched_condition_summary.csv')
    chart=[]
    floor_models=('angular_nominal','angular_paper5_rotation')
    floor_roles=('same_recording_holdout','cross_recording_not_fitted')
    for m in floor_models:
        for role in floor_roles:
            r=next(r for r in points if r['model']==m and r['source_location_role']==role)
            chart.append(dict(panel='floor_reference',variant=m,scope=role,condition='',n=int(r['points']),
                metric='planar_rmse_cm',value_cm=100*float(r['planar_rmse_m']),physical_metric_verified=False))
    variants=('angular_paper5_rotation/floor_bottom_proxy','angular_paper5_rotation/height_vertical_proxy','uniform_images/floor_bottom_proxy')
    for v in variants:
        for c in ('cone_130','cone_200'):
            r=next(r for r in matched if r['variant']==v and r['condition']==c and r['time_window']=='all')
            chart.append(dict(panel='paired_cone',variant=v,scope='same_frame_intersection_all_time',condition=c,n=int(r['n']),
                metric='signed_forward_median_bias_cm',value_cm=100*float(r['z_bias_m']),physical_metric_verified=False))
    fig,axes=plt.subplots(1,2,figsize=(12,5.5));x=np.arange(2);width=.24
    for i,m in enumerate(floor_models):
        rows=[r for r in chart if r['panel']=='floor_reference' and r['variant']==m]
        axes[0].bar(x+(i-.5)*width,[r['value_cm'] for r in rows],width,label='Nominal pose' if i==0 else 'Paper5 fitted rotation')
    axes[0].set_xticks(x);axes[0].set_xticklabels(['Same reference capture\n2 unused locations','Different capture\n1 location'],fontsize=8)
    axes[0].set_ylabel('Planar RMSE vs stated paper coordinates (cm)')
    axes[0].set_title('Floor references: capture scope matters',fontsize=10);axes[0].legend(fontsize=8)
    labels=['Transferred Paper5 / floor proxy','Transferred Paper5 / 73 cm height','Own-capture up + inherited heading / floor']
    for i,v in enumerate(variants):
        rows=[r for r in chart if r['panel']=='paired_cone' and r['variant']==v]
        axes[1].bar(x+(i-1)*width,[r['value_cm'] for r in rows],width,label=labels[i])
    axes[1].axhline(0,color='.3',lw=.8)
    axes[1].set_xticks(x);axes[1].set_xticklabels(['1.30 m / same 218 frames\nOnly 6 in later-time half','2.00 m / same 533 frames\nAll in later-time half'],fontsize=8)
    axes[1].set_ylabel('Signed forward median difference (cm)')
    axes[1].set_title('Cone: identical frames, different assumptions',fontsize=10)
    handles,legend_labels=axes[1].get_legend_handles_labels()
    fig.legend(handles,legend_labels,loc='lower center',fontsize=8)
    for ax in axes:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('Frozen numeric diagnostics, not new measurements or physical approval\nOne cone capture only; frame counts are not independent trials',fontsize=11)
    fig.tight_layout(rect=(0,.17,1,1));output.mkdir()
    write_csv(output/'chart_values.csv',chart);fig.savefig(output/'capture_scope_and_paired_comparison.png',dpi=150);plt.close(fig)
    summary=dict(status='COMPLETED_NUMERIC_SCOPE_COMPARISON_FIGURE',work_date='2026-10-23',source_sha256=sources,
        source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
