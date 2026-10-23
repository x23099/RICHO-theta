"""Numerical graphs and one byte-identical native report image for 10/22."""
from collections import defaultdict
import json
from pathlib import Path
import shutil
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256


def main():
    output=HERE/'plots_r01';assets=HERE.parent/'report_assets'
    if output.exists():raise ValueError('new plot output required')
    output.mkdir();assets.mkdir(exist_ok=True)
    metric=HERE/'metric_results_r01/condition_summary.csv'
    frames=HERE/'metric_results_r01/occlusion_comparison.csv'
    quality=HERE/'quality_results_r01/occlusion_recovery.csv'
    sensitivity=HERE/'metric_results_r01/empirical_pose_sensitivity.csv'
    images=HERE/'intake_r01/native_sample_manifest.csv'
    session=HERE/'scene_results_r01/session_hypotheses.csv';pooled=HERE/'pooled_results_r01/session_hypotheses.csv'
    sources={str(p):sha256(p) for p in (metric,frames,quality,sensitivity,images,session,pooled,Path(__file__))}
    summary=read_csv(metric);sample=read_csv(images)
    conditions=('cone_130','cone_200')
    lookup={(r['model'],r['condition'],r['time_window'],r['population']):r for r in summary if r['dataset']=='sequence'}
    ranges=read_csv(sensitivity)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8))
    for model,label,color,shift in [('uniform_images','Per-image directions','#2980b9',-.04),('pooled_planes','Pooled repeated planes','#d35400',.04)]:
        rows=[lookup[model,c,'all','quality_gated'] for c in conditions]
        axes[0].plot(np.arange(2)+shift,[float(r['z_median_m']) for r in rows],'o-',label=label,color=color)
    for i,c in enumerate(conditions):
        z=[float(r['z_forward_m']) for r in ranges if r['condition']==c and r['estimated']=='True']
        axes[0].vlines(i,min(z),max(z),color='.5',lw=5,alpha=.35,label='8 held-out direction scenarios (NOT CI)' if i==0 else None)
    axes[0].plot([0,1],[1.3,2.],'k_',ms=18,label='Placed near-edge reference')
    axes[0].set_ylabel('Forward distance (m)');axes[0].legend(fontsize=7)
    for shift,population,label,color in [(-.17,'geometry_only','No image-quality gate','#999999'),(.17,'quality_gated','Unchanged causal image-quality gate','#2980b9')]:
        rows=[lookup['uniform_images',c,'all',population] for c in conditions]
        axes[1].bar(np.arange(2)+shift,[100*float(r['z_abs_error_max_m']) for r in rows],.32,color=color,label=label)
    axes[1].set_yscale('log');axes[1].set_ylabel('Maximum absolute distance error (cm; LOG scale)');axes[1].legend(fontsize=7)
    for ax in axes:
        ax.set_xticks([0,1]);ax.set_xticklabels(['1.30 m reference','2.00 m reference']);ax.grid(axis='y',alpha=.25)
    fig.suptitle('Same saved observations, fixed intrinsics, no distance-label pose fitting\nAll-frame and held-out-time results are reported separately; NOT hardware approval')
    fig.tight_layout();fig.savefig(output/'metric_quality_and_pose_sensitivity.png',dpi=150);plt.close(fig)

    metric_rows=[r for r in read_csv(frames) if r['model']=='uniform_images']
    quality_rows={int(r['frame']):r for r in read_csv(quality)}
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True)
    x=[int(r['frame']) for r in metric_rows]
    axes[0].plot(x,[float(r['raw_floor_z_m']) if r['raw_floor_z_m'] else np.nan for r in metric_rows],'.-',color='.55',label='Geometry before image-quality gate')
    axes[1].plot(x,[float(r['emitted_floor_z_m']) if r['emitted_floor_z_m'] else np.nan for r in metric_rows],'.-',color='#2980b9',label='Current-frame emitted measurement only')
    for ax in axes[:2]:ax.axhline(2,color='k',ls=':',label='Placed 2.00 m');ax.set_ylabel('Forward distance (m)');ax.legend(fontsize=8)
    axes[2].step(x,[int(quality_rows[f]['quality_accepted']=='True') for f in x],where='mid',label='Image quality accepted')
    axes[2].plot(x,[int(quality_rows[f]['confirmation_count']) for f in x],'.-',label='Consecutive confirmations')
    axes[2].set_ylabel('Flag / count');axes[2].set_xlabel('Original frame number (not elapsed processing time)');axes[2].legend(fontsize=8)
    for ax in axes:ax.axvspan(1125,1134,color='orange',alpha=.15);ax.grid(alpha=.25)
    fig.suptitle('Occlusion: large raw distances retained for audit; rejected values are NOT held or filled')
    fig.tight_layout();fig.savefig(output/'occlusion_measurement_withholding.png',dpi=150);plt.close(fig)

    sessions=read_csv(session);pooled_rows={r['session']:r for r in read_csv(pooled)}
    labels=[]
    for r in sessions:
        name=r['session'].split('_r01_')[0].replace('cone_static_','').replace('one_static_','').replace('floor_cone_same_pose','sequence').replace('itiawase2_20261015_183552_599','paper7').replace('paper_cone_center_z2p00','Oct19 paper+cone')
        labels.append(name)
    x=np.arange(len(sessions));fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True)
    axes[0].bar(x-.17,[int(r['usable_estimate_frames']) for r in sessions],.32,label='First-half usable images')
    axes[0].bar(x+.17,[int(r['usable_heldout_frames']) for r in sessions],.32,label='Held-out usable images')
    axes[0].axhline(2,color='k',ls=':');axes[0].set_ylabel('Image up hypotheses');axes[0].legend(fontsize=8)
    axes[1].bar(x-.17,[int(pooled_rows[r['session']]['training_inlier_planes']) for r in sessions],.32,label='First-half pooled inlier planes')
    axes[1].bar(x+.17,[int(pooled_rows[r['session']]['heldout_inlier_planes']) for r in sessions],.32,label='Held-out pooled inlier planes')
    axes[1].axhline(6,color='k',ls=':',label='Required independent plane count');axes[1].set_ylabel('Plane count (not frame count)');axes[1].legend(fontsize=8)
    for ax in axes:ax.grid(axis='y',alpha=.25)
    axes[1].set_xticks(x);axes[1].set_xticklabels(labels,rotation=25,ha='right',fontsize=8)
    fig.suptitle('492 uniform native samples / 9 captures: one temporally checked capture in both methods\nNo fallback from a different recording; insufficient geometry stays unavailable')
    fig.tight_layout();fig.savefig(output/'scene_evidence_coverage.png',dpi=150);plt.close(fig)

    records=[]
    for name in ('metric_quality_and_pose_sensitivity.png','occlusion_measurement_withholding.png','scene_evidence_coverage.png'):
        target=assets/name
        if target.exists():raise ValueError('no report-asset overwrite')
        shutil.copy2(output/name,target)
        assert sha256(target)==sha256(output/name)
        records.append(dict(file=name,source=str(output/name),sha256=sha256(target),kind='numerical_plot'))
    # Predefined representative time: midpoint of the sequence, independent of fit/error.
    group=[r for r in sample if r['session']=='floor_cone_same_pose_r01_20261015_160621_378']
    native=group[len(group)//2];source=Path(native['source_native_png'])
    name=f"raw_sequence_f{int(native['frame']):06d}.png";target=assets/name
    if target.exists():raise ValueError('no native report-image overwrite')
    shutil.copy2(source,target);assert sha256(source)==sha256(target)==native['png_sha256']
    sources[str(source)]=sha256(source)
    records.append(dict(file=name,source=str(source),sha256=sha256(target),kind='native_camera',
        session=native['session'],frame=int(native['frame']),time_sec=float(native['time_sec']),width=1280,height=720,image_edited=False))
    manifest=dict(work_date='2026-10-22',assets=records,source_sha256=sources,
        source_camera_image_edited=False,physical_output=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (assets/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Saved three numeric graphs and one byte-identical native frame',native['frame'])


if __name__=='__main__':main()
