"""Reapply unchanged causal image-quality gate to every saved observation."""
from collections import Counter,defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256
from cone_support_quality import ConeSupportQualityGate,SupportQualitySettings


def key(r):return r['dataset'],r['session'],int(r['frame'])


def replay(records):
    gates={};last={};rows=[]
    for source in records:
        session=(source['dataset'],source['session']);frame=int(source['frame'])
        if frame!=last.get(session,0)+1:raise ValueError('complete original frames required')
        last[session]=frame
        gate=gates.setdefault(session,ConeSupportQualityGate())
        # No condition, known distance, metric geometry, or future observation enters update.
        result=gate.update(source['time_sec'],source['candidates'])
        current=result.pop('observed_support')
        if not result['quality_accepted']:assert current is None
        if current is not None:
            assert len(source['candidates'])==1
            np.testing.assert_array_equal(current,source['candidates'][0]['support'])
        rows.append(dict(dataset=source['dataset'],session=source['session'],frame=frame,time_sec=source['time_sec'],
            condition=source['condition'],**result,observed_support_json=json.dumps(current) if current is not None else '',
            current_frame_observation_only=current is not None,rows_imputed=False))
    return rows


def load_records():
    day=ROOT/'Experimental_results/2026-10-19'
    observations=day/'cone_support_extent_r01/results_r01/observations.csv'
    envelope=day/'cone_support_extent_r01/results_r01/lower_envelopes.csv'
    original=day/'cone_support_quality_r01/results_r02/observations.csv'
    pair_quality=day/'paper_cone_2m_validation_r01/analysis_r01/support_quality.csv'
    extra=ROOT/'Experimental_results/2026-10-21/cone_known_size_pinhole_r01/results_r01/additional_full_envelopes.csv'
    settings=day/'cone_support_quality_r01/results_r02/provenance.json'
    paths=[observations,envelope,original,pair_quality,extra,settings,HERE/'method.md',Path(__file__),ROOT/'src/cone_support_quality.py',ROOT/'src/cone_dataset.py']
    sources={str(p):sha256(p) for p in paths}
    assert json.loads(settings.read_text())['settings']==asdict(SupportQualitySettings())
    curves=defaultdict(list)
    for r in read_csv(envelope):
        if r['in_observed_support']=='True':curves[key(r)].append([float(r['x']),float(r['y'])])
    records=[]
    for r in read_csv(observations):
        curve=curves.get(key(r));n=int(r['candidates'])
        assert bool(curve)==(r['envelope_available']=='True')
        candidates=[dict(support=curve,unavailable_reason=r['reason'])] if n==1 else [dict(support=None) for _ in range(n)]
        records.append(dict(dataset=r['dataset'],session=r['session'],frame=int(r['frame']),time_sec=float(r['time_sec']),
            condition=r['condition'],candidates=candidates))
    expected={key(r):dict(accepted=r['quality_accepted']=='True',reason=r['reason']) for r in read_csv(original)}
    full=defaultdict(list)
    for r in read_csv(extra):full[key(r)].append([float(r['x']),float(r['y'])])
    session='paper_cone_center_z2p00_r01_20261019_180411_245'
    for r in read_csv(pair_quality):
        k=('paper_cone_20261019',session,int(r['frame']))
        p=np.asarray(full.get(k,[]),float)
        selected=None
        if len(p):
            lo,hi=p[0,0],p[-1,0]
            selected=p[(p[:,0]>=lo+.1*(hi-lo))&(p[:,0]<=hi-.1*(hi-lo))].tolist()
        records.append(dict(dataset=k[0],session=session,frame=k[2],time_sec=float(r['time_sec']),condition=r['phase'],
            candidates=[dict(support=selected,unavailable_reason=r['segmentation_reason'])]))
        expected[k]=dict(accepted=r['quality_accepted']=='True',reason=r['reason'])
    assert len(records)==len(expected)==6876
    return records,expected,sources


def main():
    output=HERE/'quality_results_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    records,expected,sources=load_records();rows=replay(records)
    mismatches=[]
    for r in rows:
        prior=expected[key(r)]
        if prior['accepted']!=r['quality_accepted'] or prior['reason']!=r['reason']:
            mismatches.append(dict(dataset=r['dataset'],session=r['session'],frame=r['frame'],
                old_accepted=prior['accepted'],new_accepted=r['quality_accepted'],old_reason=prior['reason'],new_reason=r['reason']))
    cuts=sorted({len(records)//2,len(records)-3,next(i+1 for i,r in enumerate(records) if r['dataset']=='sequence' and r['frame']==1135)})
    for cut in cuts:assert replay(records[:cut])==rows[:cut],'future observations changed earlier gate output'
    groups=defaultdict(list)
    for r in rows:groups[r['dataset'],r['condition']].append(r)
    summary=[dict(dataset=d,condition=c,frames=len(g),quality_accepted=sum(r['quality_accepted'] for r in g),
        reasons=json.dumps(dict(Counter(r['reason'] for r in g))),usable_for_ffb=False) for (d,c),g in sorted(groups.items())]
    output.mkdir()
    write_csv(output/'all_frame_quality.csv',rows)
    write_csv(output/'condition_summary.csv',summary)
    fields=['dataset','session','frame','old_accepted','new_accepted','old_reason','new_reason']
    write_csv(output/'historical_comparison_mismatches.csv',mismatches,fields=fields)
    write_csv(output/'occlusion_recovery.csv',[r for r in rows if r['dataset']=='sequence' and 1110<=r['frame']<=1155])
    assert all(sha256(Path(p))==h for p,h in sources.items())
    record=dict(status='COMPLETED_UNCHANGED_CAUSAL_QUALITY_REPLAY',work_date='2026-10-22',frames=len(rows),
        historical_decision_or_reason_mismatches=len(mismatches),
        historical_decision_mismatches=sum(r['old_accepted']!=r['new_accepted'] for r in mismatches),
        prefix_cutpoints=cuts,prefix_invariance_verified=True,current_frame_support_membership_verified=True,
        settings=asdict(SupportQualitySettings()),source_sha256=sources,imputed_distance_observations=0,
        production_gate_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256','settings')},indent=2))


if __name__=='__main__':main()
