"""Causal replay, refusal detail and plots from the immutable submitted logs."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_support_quality import ConeSupportQualityGate
from cone_distance_core import digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis-dir',required=True,type=Path)
    p.add_argument('--output-dir',required=True,type=Path)
    args=p.parse_args()
    audit=json.loads((args.analysis_dir/'audit.json').read_text())
    root=Path(audit['extracted_root'])
    source=root/'upper_support_comparison.jsonl'
    if digest(source)!=audit['input_sha256']['upper_support_comparison.jsonl']:
        raise ValueError('analysis input changed')
    if args.output_dir.exists():raise ValueError('new detail destination required')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    gates={b:ConeSupportQualityGate() for b in ('legacy','upper')}
    owner=None;compared=0;failures=[];refusals=[];edges=Counter();active=[]
    for line in source.open():
        r=json.loads(line)
        load=r['fixed_floor_load']
        if load['state']!='active':owner=None;continue
        current=(r['session'],load['bundle_sha256'],load['generation'])
        if current!=owner:
            for g in gates.values():g.reset()
            owner=current
        for branch in gates:
            c=r[branch+'_candidate'] or {}
            shadow=r[branch+'_fixed_floor_shadow']
            q=gates[branch].update(r['source_time_sec'],[dict(
                support=c.get('support') if c.get('point') is not None else None,
                unavailable_reason=c.get('reason','no_selected_support'))])
            expected=(shadow['image_quality_accepted'],shadow['image_quality_reason'])
            if (q['quality_accepted'],q['reason'])!=expected:
                failures.append(dict(frame=r['frame'],branch=branch,replayed=q,expected=expected))
            if branch=='upper' and json.loads(json.dumps(q))!=r['upper_quality']:
                failures.append(dict(frame=r['frame'],branch=branch,full_record_mismatch=True))
            compared+=1
        c=r['upper_candidate'] or {}
        if c.get('point') is None:
            contexts=c.get('upper_contexts') or []
            touches=(contexts[0].get('component') or {}).get('touches',{}) if contexts else {}
            touching='+'.join(k for k,v in touches.items() if v)
            edges[touching]+=1
            attempted_point=(contexts[-1].get('observation') or {}).get('point') if contexts else None
            bbox=r['selected_detector_boxes'][0] if len(r['selected_detector_boxes'])==1 else {}
            refusals.append(dict(frame=r['frame'],source_time_sec=r['source_time_sec'],
                upper_completion_reason=c.get('upper_completion_reason'),touching_edges=touching,
                attempted_point_x=attempted_point[0] if attempted_point else None,
                attempted_point_y=attempted_point[1] if attempted_point else None,
                bbox_bottom=bbox.get('y2'),point_below_bbox_px=(attempted_point[1]-bbox['y2']) if attempted_point else None))
        active.append(r)
    if failures:raise ValueError('causal gate replay mismatch: '+str(failures[:2]))
    with (args.output_dir/'refused_candidates.csv').open('x',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(refusals[0]));w.writeheader();w.writerows(refusals)
    reference=json.loads(Path(__file__).with_name('reference.json').read_text())
    apparent={}
    for model,s in audit['model_ranges_m'].items():
        apparent[model]=dict(median_m=s['median'],reported_reference_m=reference['distance_m'],
            median_minus_reported_reference_cm=100*(s['median']-reference['distance_m']),
            physical_point_equivalence_verified=False,used_for_model_selection=False)
    start=active[0]['source_time_sec'];times=np.array([r['source_time_sec']-start for r in active])
    gap=np.diff(times)
    differences=[r['frame'] for r in active if r['status']=='UNVERIFIED_UPPER_COMPARISON' and
        not any(m['range_available'] for m in (r['legacy_fixed_floor_shadow'] or {}).get('models',[]))]
    replay=dict(active_rows=len(active),causal_branch_verdicts_reproduced=compared,mismatch_count=0,
        full_upper_quality_records_reproduced=len(active),refusal_touching_edges=dict(edges),
        extra_numeric_frames=differences,mean_processed_rows_per_sec=(len(active)-1)/(times[-1]-times[0]),
        maximum_processed_source_gap_sec=float(gap.max()),
        processed_source_gaps_over_200ms=int(sum(gap>.2)),
        model_reference_differences=apparent,reference=reference,
        calibration_updated=False,runtime_source_modified=False,physical_metric_verified=False,
        usable_for_ffb=False,plotted_model_chosen_for_order_not_accuracy=True)
    (args.output_dir/'detail.json').write_text(json.dumps(replay,indent=2)+'\n')
    first=next(iter(active[0]['upper_fixed_floor_shadow']['models']))['model_name']
    def series(branch):
        out=[]
        for r in active:
            m=next(m for m in r[branch+'_fixed_floor_shadow']['models'] if m['model_name']==first)
            out.append(m['horizontal_camera_foot_range_m'] if m['range_available'] else np.nan)
        return np.array(out)
    old,new=series('legacy'),series('upper')
    with (args.output_dir/'active_plot_data.csv').open('x',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['session','frame','relative_sec','legacy_first_model_m','upper_first_model_m',
            'legacy_numeric','upper_numeric','upper_granted','frame_age_ms'])
        for i,r in enumerate(active):
            writer.writerow([r['session'],r['frame'],times[i],
                old[i] if np.isfinite(old[i]) else '',new[i] if np.isfinite(new[i]) else '',
                int(np.isfinite(old[i])),int(np.isfinite(new[i])),
                int((r['upper_candidate'] or {}).get('upper_completion_granted',False)),
                r['frame_age_ms']])
    fig,axes=plt.subplots(3,1,figsize=(10,8),sharex=True,layout='constrained')
    axes[0].plot(times,new,'.',ms=1.5,label='Upper candidate (first listed model)')
    axes[0].plot(times,old,'.',ms=.6,label='Legacy (same model)')
    axes[0].axhline(reference['distance_m'],color='k',ls='--',label='User reference; point correspondence unverified')
    axes[0].set_ylabel('Conditional range [m]');axes[0].legend(fontsize=7)
    bins=audit['active_ten_second_bins']
    for key,label in [('legacy_numeric','Legacy'),('upper_numeric','Upper')]:
        axes[1].plot([b['relative_start_sec'] for b in bins],[100*b[key]/b['rows'] for b in bins],'.-',label=label)
    axes[1].set_ylabel('Numeric rows / bin [%]');axes[1].legend(fontsize=8)
    axes[2].plot(times,[r['frame_age_ms'] for r in active],lw=.5)
    axes[2].axhline(500,color='r',ls='--',label='Existing 500 ms withholding limit')
    axes[2].set_ylabel('Receiver-local age [ms]');axes[2].set_xlabel('Seconds since model activation')
    axes[2].legend(fontsize=8)
    fig.suptitle('Same-frame live comparison; diagnostic only / no ROS or FFB')
    fig.savefig(args.output_dir/'live_comparison.png',dpi=150);plt.close(fig)
    rescue=next(r for r in active if r['frame']==35562)
    t0=rescue['source_time_sec']-start
    selected=(times>=t0-.3)&(times<=t0+.3)
    fig,ax=plt.subplots(figsize=(9,3),layout='constrained')
    ax.plot(times[selected]-t0,np.isfinite(old[selected]).astype(int),'o-',label='Legacy')
    ax.plot(times[selected]-t0,np.isfinite(new[selected]).astype(int),'x--',label='Upper')
    ax.set_yticks([0,1],['Withheld','Numeric']);ax.set_xlabel('Seconds relative to frame 35562')
    ax.legend();ax.set_title('One recovered observation avoids two legacy reconfirmation frames')
    fig.savefig(args.output_dir/'recovered_event.png',dpi=150);plt.close(fig)
    prior_path=ROOT/'Experimental_results/2026-11-04/upper_support_live_r01/verification_r01/verification.json'
    prior=json.loads(prior_path.read_text())
    mismatches=[name for name,sha in prior['source_sha256'].items() if digest(ROOT/name)!=sha]
    software=dict(reused_tests=prior['tests'],prior_verification=str(prior_path.relative_to(ROOT)),
        prior_sha256=digest(prior_path),source_hash_mismatches=mismatches,
        analysis_scripts_sha256={str(path.relative_to(ROOT)):digest(path) for path in
            [Path(__file__),Path(__file__).with_name('analyze.py'),Path(__file__).with_name('reference.json')]},
        runtime_code_changed=False)
    (args.output_dir/'software_verification.json').write_text(json.dumps(software,indent=2)+'\n')
    print(json.dumps({k:v for k,v in replay.items() if k!='model_reference_differences'},indent=2))


if __name__=='__main__':main()
