"""Coverage, matched distances and timeline; no edits to camera images."""
from collections import Counter,defaultdict
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from replay_saved import HERE,UNIFORM,key,flag
from causal_pose import MODES
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'report_r01'
    if output.exists():raise ValueError('new report output required')
    results=HERE/'results_r01';proof=json.loads((results/'summary.json').read_text())
    for name,h in proof['output_sha256'].items():assert sha256(results/name)==h
    oldpath=UNIFORM/'metric_results_r01/all_frame_metrics.csv'
    sources={str(p):sha256(p) for p in (HERE/'report.py',results/'summary.json',results/'frame_metrics.csv',results/'scene_events.csv',oldpath)}
    rows=read_csv(results/'frame_metrics.csv');events=read_csv(results/'scene_events.csv')
    old={key(r):r for r in read_csv(oldpath) if r['model']=='uniform_images'}
    coverage=[];matched=[];holds=[]
    for mode in MODES:
        group=[r for r in rows if r['mode']==mode];used=[r for r in group if flag(r['diagnostic_available'])]
        both=[r for r in used if flag(old[key(r)]['measurement_emitted'])]
        coverage.append(dict(mode=mode,all_unique_cone_frames=len(group),pose_available_frames=sum(flag(r['pose_available']) for r in group),
            diagnostic_frames=len(used),historical_offline_diagnostic_frames=sum(flag(r['measurement_emitted']) for r in old.values()),
            overlapping_diagnostic_frames=len(both),new_only_diagnostic_frames=len(used)-len(both),physical_metric_verified=False,usable_for_ffb=False))
        counts=Counter(r['pose_reason'] for r in group if not flag(r['pose_available']))
        holds.extend(dict(mode=mode,reason=reason,frames=count,layer='pose_availability',physical_metric_verified=False) for reason,count in sorted(counts.items()))
        labeled=defaultdict(list)
        for r in group:
            if r['reference_z_m']:labeled[r['dataset'],r['condition']].append(r)
        for (dataset,condition),population in sorted(labeled.items()):
            pair=[r for r in population if flag(r['diagnostic_available']) and flag(old[key(r)]['measurement_emitted'])]
            ref=float(population[0]['reference_z_m']);new=np.array([float(r['diagnostic_z_m']) for r in pair])
            previous=np.array([float(old[key(r)]['emitted_floor_z_m']) for r in pair])
            matched.append(dict(mode=mode,dataset=dataset,condition=condition,reference_z_m=ref,all_condition_frames=len(population),matched_frames=len(pair),
                causal_z_median_m=float(np.median(new)) if len(pair) else None,
                historical_matched_z_median_m=float(np.median(previous)) if len(pair) else None,
                paired_new_minus_old_median_m=float(np.median(new-previous)) if len(pair) else None,
                causal_max_abs_difference_m=float(max(abs(new-ref))) if len(pair) else None,
                historical_matched_max_abs_difference_m=float(max(abs(previous-ref))) if len(pair) else None,
                physical_metric_verified=False,usable_for_ffb=False))
    session=proof['first_initializations'][0]['session']
    selected=sorted([r for r in rows if r['session']==session and r['mode']==MODES[1]],key=lambda r:int(r['frame']))
    ev=[r for r in events if r['session']==session]
    time=np.array([float(r['time_sec']) for r in selected])
    z=np.array([float(r['diagnostic_z_m']) if r['diagnostic_z_m'] else np.nan for r in selected])
    oldz=np.array([float(old[key(r)]['emitted_floor_z_m']) if old[key(r)]['emitted_floor_z_m'] else np.nan for r in selected])
    ref=np.array([float(r['reference_z_m']) if r['reference_z_m'] else np.nan for r in selected])
    fig,axes=plt.subplots(2,1,figsize=(11,6.5),sharex=True,gridspec_kw={'height_ratios':[1,2]})
    good=[r for r in ev if flag(r['scene_accepted'])];bad=[r for r in ev if not flag(r['scene_accepted'])]
    axes[0].scatter([float(r['time_sec']) for r in bad],[0]*len(bad),color='#b3b7bd',s=20,label='Scene sample rejected')
    axes[0].scatter([float(r['time_sec']) for r in good],[1]*len(good),color='#24828e',s=25,label='Scene sample accepted')
    init=proof['first_initializations'][0]['first_initialization_time_sec']
    axes[0].axvline(init,color='#b36426',ls='--',label=f'Past-only initialization: {init:.2f} s')
    axes[0].set_yticks([0,1]);axes[0].set_yticklabels(['Rejected','Accepted']);axes[0].set_ylim(-.4,1.4)
    axes[0].legend(fontsize=8,loc='upper right')
    axes[1].plot(time,oldz,color='#a4a8ac',lw=1,label='Historical offline half-recording aggregate')
    axes[1].plot(time,z,color='#167d9d',lw=1.4,label='Past-only / latest valid scene proof <= 1 s (diagnostic assumption)')
    axes[1].plot(time,ref,color='#b65536',ls='--',lw=1,label='Stated near-base reference, labeled intervals only')
    axes[1].set_xlabel('Recording timestamp (s), not simulated processing latency');axes[1].set_ylabel('Forward distance (m)')
    axes[1].set_ylim(.5,2.5)
    for ax in axes:ax.grid(alpha=.2)
    handles,labels=axes[1].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',fontsize=8)
    fig.suptitle('Past-only initialization works in one of nine static captures\nDistance gaps remain; neither 30 fps operation nor physical accuracy is approved',fontsize=11)
    fig.tight_layout(rect=(0,.14,1,1));output.mkdir()
    for name,data in [('coverage_comparison.csv',coverage),('matched_old_causal.csv',matched),('pose_hold_counts.csv',holds)]:write_csv(output/name,data)
    fig.savefig(output/'past_only_pose_and_distance_timeline.png',dpi=150);plt.close(fig)
    record=dict(status='COMPLETED_CAUSAL_COVERAGE_AND_MATCHED_DISTANCE_REPORT',work_date='2026-10-23',source_sha256=sources,
        coverage=coverage,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':main()
