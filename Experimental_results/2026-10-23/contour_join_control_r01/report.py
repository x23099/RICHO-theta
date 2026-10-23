"""Keep rejected regressions and pose changes, without using distance labels."""
from collections import Counter
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from contour_join import HERE,BANDS,MODES
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import angle_degrees


def main():
    output=HERE/'report_r01'
    if output.exists():raise ValueError('new report output required')
    results=HERE/'results_r01';d=json.loads((results/'summary.json').read_text())
    for name,h in d['output_sha256'].items():assert sha256(results/name)==h
    source_files=[HERE/'report.py',results/'summary.json',results/'image_diagnostics.csv',results/'session_hypotheses.csv',
        results/'lower_decisions.csv',results/'post_refit_duplicate_votes.csv',BANDS/'results_r01/image_diagnostics.csv']
    sources={str(p):sha256(p) for p in source_files}
    frames=read_csv(results/'image_diagnostics.csv');sessions=read_csv(results/'session_hypotheses.csv')
    original={(r['session'],r['frame']) for r in read_csv(BANDS/'results_r01/image_diagnostics.csv') if r['mode']=='upper' and r['accepted']=='True'}
    index={(r['session'],r['frame'],r['mode']):r for r in frames}
    paired=[];lost=[];summaries=[]
    for row in (r for r in frames if r['mode']=='object_reference'):
        baseline=row['accepted']=='True'
        for mode in ('join_count_only','join_refit'):
            current=index[row['session'],row['frame'],mode];accepted=current['accepted']=='True'
            entry=dict(session=row['session'],frame=row['frame'],role=row['role'],mode=mode,
                baseline_accepted=baseline,joined_accepted=accepted,joined_reason=current['reason'],
                original_upper_accepted=(row['session'],row['frame']) in original,
                direction_delta_deg=angle_degrees(json.loads(row['up_optical_json']),json.loads(current['up_optical_json'])) if baseline and accepted else None,
                metric_accuracy_verified=False,usable_for_ffb=False)
            paired.append(entry)
            if entry['original_upper_accepted'] and not accepted:lost.append(entry)
    for mode in MODES:
        accepted={(r['session'],r['frame']) for r in frames if r['mode']==mode and r['accepted']=='True'}
        summaries.append(dict(mode=mode,accepted_images=len(accepted),old_27_retained=len(accepted&original),old_27_lost=len(original-accepted),
            accepted_not_in_old_27=len(accepted-original),temporal_sessions=sum(r['mode']==mode and r['temporal_candidate_eligible']=='True' for r in sessions),
            metric_accuracy_verified=False,usable_for_ffb=False))
    output.mkdir();write_csv(output/'mode_comparison.csv',summaries);write_csv(output/'paired_pose_changes.csv',paired)
    write_csv(output/'lost_original_acceptances.csv',lost)
    decision_counts=Counter(r['decision'] for r in read_csv(results/'lower_decisions.csv'))
    write_csv(output/'join_decision_counts.csv',[dict(reason=k,observations=n) for k,n in sorted(decision_counts.items())])
    fig,axes=plt.subplots(1,2,figsize=(11,4.8));x=np.arange(3)
    labels=['Object + reference\ncontrol','Same contour\ncounted once','Same contour\nrefitted once']
    retained=[r['old_27_retained'] for r in summaries];extra=[r['accepted_not_in_old_27'] for r in summaries]
    axes[0].bar(x,retained,label='Retained from original 27 images',color='#2980b9')
    axes[0].bar(x,extra,bottom=retained,label='Other accepted images',color='#c49a38')
    axes[0].axhline(27,color='.4',ls=':');axes[0].set_ylabel('Accepted image hypotheses (not accuracy)');axes[0].legend(fontsize=8)
    axes[1].bar(x,[r['old_27_lost'] for r in summaries],color='#c95a4a')
    axes[1].set_ylabel('Original accepted images now withheld');axes[1].set_yticks(range(5))
    for ax in axes:
        ax.set_xticks(x);ax.set_xticklabels(labels,fontsize=8);ax.grid(axis='y',alpha=.2)
    fig.suptitle('Same observed support, no extra seam vote\nAll three modes: one temporally screened capture; no metric or hardware approval')
    fig.tight_layout();fig.savefig(output/'single_contour_vote_comparison.png',dpi=150);plt.close(fig)
    assert all(sha256(__import__('pathlib').Path(p))==h for p,h in sources.items())
    record=dict(status='COMPLETED_SINGLE_VOTE_COMPARISON_NO_PRODUCTION_ADOPTION',work_date='2026-10-23',source_sha256=sources,
        mode_summary=summaries,decision_counts=dict(decision_counts),source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
