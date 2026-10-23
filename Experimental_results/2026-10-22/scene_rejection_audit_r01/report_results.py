"""Coordinate ledgers and numerical figures, without camera-image editing."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from audit import HERE, PREVIOUS
from cone_dataset import read_csv, write_csv, sha256


def closest_plane(normal, rows):
    if not rows:
        return None, None
    angles=[float(np.degrees(np.arccos(np.clip(abs(normal @ np.array(json.loads(r['normal_json']))),-1,1)))) for r in rows]
    i=min(range(len(rows)),key=lambda j:(angles[j],int(rows[j]['line_index']),int(rows[j]['part'])))
    return angles[i],rows[i]


def short_name(session):
    if session.startswith('floor_cone_same_pose'):return 'Same-pose series'
    if session.startswith('itiawase2'):return 'Paper 7 points'
    if session.startswith('paper_cone_center'):return 'Oct19 paper+cone'
    return session.split('_r01_')[0].replace('cone_static_','').replace('one_static_','')


def main():
    output=HERE/'report_results_r01'
    if output.exists():raise ValueError('new report output required')
    audit=HERE/'results_r02';probe=HERE/'roi_probe_results_r01'
    inputs=[audit/'all_frame_consensus.csv',audit/'all_frame_plane_residuals.csv',
            audit/'representative_all_pieces.csv',audit/'representative_stage_counts.csv',audit/'representative_plan.json',
            audit/'summary.json',probe/'summary.json',probe/'line_candidates.csv',probe/'image_diagnostics.csv',
            probe/'session_hypotheses.csv',PREVIOUS/'scene_results_r01/session_hypotheses.csv',Path(__file__)]
    sources={str(p):sha256(p) for p in inputs}
    for folder in (audit,probe):
        manifest=json.loads((folder/'summary.json').read_text())
        for name,h in manifest['output_sha256'].items():assert sha256(folder/name)==h
    original=read_csv(audit/'all_frame_plane_residuals.csv')
    new=read_csv(probe/'line_candidates.csv')
    pre,kept=defaultdict(list),defaultdict(list)
    for r in new:
        key=r['session'],r['frame']
        if r['reason'] in ('accepted_plane','duplicate_ray_plane'):pre[key].append(r)
        if r['accepted']=='True':kept[key].append(r)
    retention=[]
    for row in original:
        normal=np.array(json.loads(row['normal_json']));key=row['session'],row['frame']
        pre_angle,pre_line=closest_plane(normal,pre[key]);kept_angle,kept_line=closest_plane(normal,kept[key])
        retention.append(dict(session=row['session'],frame=row['frame'],role=row['role'],
            baseline_line_index=row['line_index'],baseline_part=row['part'],
            baseline_first_native_json=row['first_native_json'],baseline_last_native_json=row['last_native_json'],
            baseline_accepted_pose=row['accepted_pose'],baseline_within_diagnostic_one_degree=row['within_one_degree'],
            closest_probe_pre_dedup_angle_deg=pre_angle,
            closest_probe_kept_angle_deg=kept_angle,
            direction_has_pre_dedup_match_within_two_deg=pre_angle is not None and pre_angle<2,
            direction_has_kept_match_within_two_deg=kept_angle is not None and kept_angle<2,
            closest_kept_line_index=kept_line['line_index'] if kept_line else None,
            closest_kept_part=kept_line['part'] if kept_line else None,
            closest_kept_first_native_json=kept_line['first_native_json'] if kept_line else '',
            closest_kept_last_native_json=kept_line['last_native_json'] if kept_line else '',
            same_physical_line_verified=False,usable_for_ffb=False))
    output.mkdir()
    write_csv(output/'plane_direction_retention.csv',retention)
    base_sessions={r['session']:r for r in read_csv(PREVIOUS/'scene_results_r01/session_hypotheses.csv')}
    probe_sessions=read_csv(probe/'session_hypotheses.csv')
    comparison=[]
    for r in probe_sessions:
        base=base_sessions[r['session']]
        rows=[x for x in retention if x['session']==r['session']]
        accepted_inliers=[x for x in rows if x['baseline_accepted_pose']=='True' and x['baseline_within_diagnostic_one_degree']=='True']
        comparison.append(dict(session=r['session'],
            baseline_train_images=base['usable_estimate_frames'],baseline_heldout_images=base['usable_heldout_frames'],
            baseline_temporal_pass=base['metric_eligible'],probe_train_images=r['usable_estimate_frames'],
            probe_heldout_images=r['usable_heldout_frames'],probe_temporal_pass=r['metric_eligible'],
            probe_train_spread_deg=r['training_spread_max_deg'],probe_heldout_spread_deg=r['heldout_spread_max_deg'],
            baseline_kept_plane_observations=len(rows),
            baseline_directions_missing_pre_dedup=sum(not x['direction_has_pre_dedup_match_within_two_deg'] for x in rows),
            baseline_directions_missing_after_dedup=sum(not x['direction_has_kept_match_within_two_deg'] for x in rows),
            baseline_accepted_inlier_observations=len(accepted_inliers),
            accepted_inlier_directions_missing_pre_dedup=sum(not x['direction_has_pre_dedup_match_within_two_deg'] for x in accepted_inliers),
            accepted_inlier_directions_missing_after_dedup=sum(not x['direction_has_kept_match_within_two_deg'] for x in accepted_inliers),
            usable_for_ffb=False))
    write_csv(output/'session_comparison.csv',comparison)
    frames=read_csv(audit/'all_frame_consensus.csv');pieces=read_csv(audit/'representative_all_pieces.csv')
    stage_counts=Counter(r['reason'] for r in pieces)
    write_csv(output/'representative_piece_reasons.csv',[dict(reason=k,pieces=v,total=len(pieces)) for k,v in sorted(stage_counts.items())])
    labels=[short_name(r['session']) for r in comparison];x=np.arange(len(labels))
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    bottom=np.zeros(len(labels))
    for reason,label,color in [('conditional_architectural_up','Original per-image accepted','#2a9d8f'),
                              ('insufficient_consensus','Seed consensus below 6 planes','#e9c46a'),
                              ('fewer_than_six_distinct_planes','Fewer than 6 input planes','#e76f51')]:
        counts=[sum(f['session']==r['session'] and f['terminal_reason']==reason for f in frames) for r in comparison]
        axes[0].bar(x,counts,bottom=bottom,label=label,color=color);bottom+=counts
    axes[0].set_ylabel('All 492 sampled images');axes[0].legend(fontsize=8);axes[0].grid(axis='y',alpha=.2)
    for shift,key,label,color in [(-.18,'baseline','Original ROI y=60..300','#777777'),(.18,'probe','Probe ROI y=60..430','#2980b9')]:
        axes[1].bar(x+shift,[int(r[key+'_train_images'])+int(r[key+'_heldout_images']) for r in comparison],.34,label=label,color=color)
    axes[1].set_ylabel('Per-image hypotheses (not metric accuracy)');axes[1].legend(fontsize=8);axes[1].grid(axis='y',alpha=.2)
    axes[1].set_xticks(x);axes[1].set_xticklabels(labels,rotation=28,ha='right',fontsize=8)
    fig.suptitle('Frozen-rule rejection audit + one predeclared ROI control\nMore candidates do not prove vertical accuracy; old successful series regresses under wider ROI')
    fig.tight_layout();fig.savefig(output/'rejection_and_roi_control.png',dpi=150);plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,5))
    reasons=list(stage_counts);counts=[stage_counts[k] for k in reasons]
    axes[0].barh(np.arange(len(reasons)),counts,color='#777777')
    axes[0].set_yticks(np.arange(len(reasons)));axes[0].set_yticklabels([
        'Kept independent plane' if k=='accepted_plane' else
        'Duplicate direction' if k=='duplicate_ray_plane' else
        'Under 30 observed pixels' if k=='fewer_than_30_actual_edge_points' else
        'Insufficient native slope' if k=='not_steep_enough_in_native_coordinates' else
        'Native vertical span < 60 px' for k in reasons],fontsize=8)
    for i,count in enumerate(counts):axes[0].text(count+30,i,str(count),va='center',fontsize=8)
    axes[0].set_xlim(0,max(counts)*1.18);axes[0].set_xlabel('Hough pieces (18 fixed representative images ONLY)')
    seed_counts=Counter(int(r['seed_inliers']) for r in frames if int(r['plane_count'])>=6)
    axes[1].bar(sorted(seed_counts),[seed_counts[k] for k in sorted(seed_counts)],color='#e9c46a')
    axes[1].axvline(5.5,color='k',ls=':',label='At least 6 before SVD')
    axes[1].set_xticks(range(2,7));axes[1].set_xlabel('Best initial seed consensus plane count')
    axes[1].set_ylabel('Images with at least 6 input planes');axes[1].legend(fontsize=8)
    fig.suptitle('Failure is before SVD, not a later temporal rejection\nPiece counts are not counts of independent physical vertical lines')
    fig.tight_layout();fig.savefig(output/'extraction_and_consensus_stages.png',dpi=150);plt.close(fig)

    # Context examples only; retain native byte identity, no overlays or crops.
    reps=json.loads((audit/'representative_plan.json').read_text());assets=[]
    for prefix,label in [('cone_static_center_z1p30','static_130'),('paper_cone_center_z2p00','oct19_paper_cone')]:
        sample=next(r for r in reps if r['session'].startswith(prefix) and r['role']=='estimate')
        source=Path(sample['source_native_png']);name=f"native_{label}_f{int(sample['frame']):06d}.png"
        shutil.copy2(source,output/name)
        assert sha256(output/name)==sample['png_sha256']==sha256(source)
        sources[str(source)]=sample['png_sha256']
        assets.append(dict(file=name,session=sample['session'],frame=int(sample['frame']),
            source=str(source),sha256=sample['png_sha256'],image_edited=False,width=1280,height=720))
    summary=dict(status='COMPLETED_REJECTION_LEDGER_AND_ROI_CONTROL_NOT_PRODUCTION_ADOPTION',work_date='2026-10-22',
        source_sha256=sources,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        plane_direction_matches_are_physical_correspondences=False,native_assets=assets,
        representative_piece_reasons=dict(stage_counts),
        baseline_temporal_passes=sum(r['baseline_temporal_pass']=='True' for r in comparison),
        probe_temporal_passes=sum(r['probe_temporal_pass']=='True' for r in comparison),
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    assert all(sha256(Path(p))==h for p,h in sources.items())
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256','native_assets')},indent=2))


if __name__=='__main__':main()
