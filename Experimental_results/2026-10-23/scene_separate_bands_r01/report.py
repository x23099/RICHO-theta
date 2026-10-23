"""Paired numerical comparisons and four dated report assets, no image edits."""
from collections import Counter
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from run import HERE,ROOT,PREVIOUS,AUDIT,MODES
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import angle_degrees


def short_name(s):
    if s.startswith('floor_cone_same_pose'):return 'Same-pose series'
    if s.startswith('itiawase2'):return 'Paper 7 points'
    if s.startswith('paper_cone_center'):return 'Oct19 paper+cone'
    return s.split('_r01_')[0].replace('cone_static_','').replace('one_static_','')


def main():
    output=HERE/'report_r01';assets=HERE.parent/'report_assets'
    if output.exists() or assets.exists():raise ValueError('report/asset outputs must be new')
    results=HERE/'results_r01';manifest=json.loads((results/'summary.json').read_text())
    for name,h in manifest['output_sha256'].items():assert sha256(results/name)==h
    frames_path=results/'image_diagnostics.csv';sessions_path=results/'session_hypotheses.csv'
    wide_path=AUDIT/'roi_probe_results_r01/image_diagnostics.csv'
    wide_sessions=AUDIT/'roi_probe_results_r01/session_hypotheses.csv'
    source_files=[frames_path,sessions_path,results/'summary.json',wide_path,wide_sessions,Path(__file__)]
    sources={str(p):sha256(p) for p in source_files}
    frames=read_csv(frames_path);sessions=read_csv(sessions_path)
    wide={(r['session'],r['frame']):r for r in read_csv(wide_path)}
    index={(r['session'],r['frame'],r['mode']):r for r in frames}
    pairs=[]
    for r in (x for x in frames if x['mode']=='upper'):
        fused=index[r['session'],r['frame'],'late_fusion'];broader=wide[r['session'],r['frame']]
        both=r['accepted']=='True' and fused['accepted']=='True'
        delta=angle_degrees(json.loads(r['up_optical_json']),json.loads(fused['up_optical_json'])) if both else None
        pairs.append(dict(session=r['session'],frame=r['frame'],role=r['role'],
            upper_accepted=r['accepted'],wide_accepted=broader['accepted'],fusion_accepted=fused['accepted'],
            fusion_inliers_upper=fused['accepted_inliers_from_upper'],fusion_inliers_lower=fused['accepted_inliers_from_lower'],
            both_accepted_direction_difference_deg=delta,usable_for_ffb=False))
    old_sessions={r['session']:r for r in sessions if r['mode']=='upper'}
    wide_session_index={r['session']:r for r in read_csv(wide_sessions)}
    comparisons=[]
    for session in sorted(old_sessions):
        current={r['mode']:r for r in sessions if r['session']==session}
        r=dict(session=session)
        for mode in MODES:
            c=current[mode]
            r.update({mode+'_train_images':c['usable_estimate_frames'],mode+'_heldout_images':c['usable_heldout_frames'],
                mode+'_temporal_pass':c['temporal_candidate_eligible']})
        w=wide_session_index[session]
        r.update(wide_train_images=w['usable_estimate_frames'],wide_heldout_images=w['usable_heldout_frames'],wide_temporal_pass=w['metric_eligible'])
        comparisons.append(r)
    contributions=Counter((r['accepted_inliers_from_upper'],r['accepted_inliers_from_lower'])
        for r in frames if r['mode']=='late_fusion' and r['accepted']=='True')
    output.mkdir();assets.mkdir()
    write_csv(output/'paired_images.csv',pairs);write_csv(output/'session_comparison.csv',comparisons)
    write_csv(output/'fusion_inlier_contributions.csv',[dict(upper_inliers=int(a),lower_inliers=int(b),images=n)
        for (a,b),n in sorted(contributions.items())])
    labels=[short_name(r['session']) for r in comparisons];x=np.arange(len(labels))
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    for shift,mode,label,color in [(-.25,'upper','Original upper band','#888888'),(0,'wide','Single expanded ROI','#e9a23b'),
                                    (.25,'late_fusion','Separate bands + late fusion','#2980b9')]:
        counts=[int(r[mode+'_train_images'])+int(r[mode+'_heldout_images']) for r in comparisons]
        axes[0].bar(x+shift,counts,.24,label=label,color=color)
        axes[1].bar(x+shift,[int(r[mode+'_temporal_pass']=='True') for r in comparisons],.24,color=color)
    axes[0].set_ylabel('Accepted image hypotheses');axes[0].legend(fontsize=8)
    axes[1].set_ylabel('Temporal screen pass (0/1)');axes[1].set_yticks([0,1])
    axes[1].set_xticks(x);axes[1].set_xticklabels(labels,rotation=27,ha='right',fontsize=8)
    for ax in axes:ax.grid(axis='y',alpha=.2)
    fig.suptitle('Same 492 images: preserve upper inputs, extract lower pixels independently\nNew fusion accepts 26 additional images; all have 5 upper + 1 lower inlier. NOT metric validation.')
    fig.tight_layout();fig.savefig(output/'separate_bands_comparison.png',dpi=150);plt.close(fig)
    source_asset_manifest=PREVIOUS.parent/'report_assets/manifest.json'
    native_source=PREVIOUS.parent/'report_assets/raw_sequence_f000780.png'
    specs=[(PREVIOUS/'plots_r01/metric_quality_and_pose_sensitivity.png','distance_quality_and_pose_sensitivity.png','numeric_plot'),
           (AUDIT/'report_results_r01/rejection_and_roi_control.png','rejection_and_wide_roi_control.png','numeric_plot'),
           (output/'separate_bands_comparison.png','separate_bands_comparison.png','numeric_plot'),
           (native_source,'raw_sequence_f000780.png','native_camera')]
    source_files += [source_asset_manifest]+[a for a,_,_ in specs]
    records=[]
    native_record=next(r for r in json.loads(source_asset_manifest.read_text())['assets'] if r['kind']=='native_camera')
    for source,name,kind in specs:
        shutil.copy2(source,assets/name);assert sha256(source)==sha256(assets/name)
        row=dict(file=name,kind=kind,source=str(source),sha256=sha256(source))
        if kind=='native_camera':
            assert sha256(source)==native_record['sha256']
            row.update(session=native_record['session'],frame=native_record['frame'],time_sec=native_record['time_sec'],
                       capture_date='2026-10-15',width=1280,height=720,image_edited=False)
        records.append(row)
    sources.update({str(p):sha256(p) for p in source_files})
    asset_manifest=dict(work_date='2026-10-23',includes_previous_20261022_work_by_user_request=True,
        assets=records,source_sha256={str(p):sha256(p) for p in source_files},source_images_edited=False,physical_output=False,
        output_sha256={r['file']:r['sha256'] for r in records})
    (assets/'manifest.json').write_text(json.dumps(asset_manifest,indent=2)+'\n')
    assert all(sha256(Path(p))==h for p,h in sources.items())
    summary=dict(status='COMPLETED_BAND_COMPARISON_AND_23_REPORT_ASSETS',work_date='2026-10-23',
        source_sha256=sources,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        old_accepted_images=sum(r['upper_accepted']=='True' for r in pairs),
        old_accepted_images_lost=sum(r['upper_accepted']=='True' and r['fusion_accepted']!='True' for r in pairs),
        newly_accepted_images=sum(r['upper_accepted']!='True' and r['fusion_accepted']=='True' for r in pairs),
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()},
        asset_manifest_sha256=sha256(assets/'manifest.json'))
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
