"""Pair manually read native screencast labels to immutable primary log frames."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from report_driver_motion_logs import distribution
from verify_driver_withheld_evidence import parse_json,read_regular


def require(condition,message):
    if not condition:raise ValueError(message)


def select_phase(rows,first,last):
    require(type(first) is int and type(last) is int and first<=last,'ordered integer phase required')
    return [r for r in rows if first<=r['frame']<=last]


def stats(rows):
    require(rows,'empty phase')
    n=len(rows);span=rows[-1]['source_time_sec']-rows[0]['source_time_sec']
    both=[r for r in rows if r['main_available'] and r['comparison_available']]
    return dict(rows=n,first_frame=rows[0]['frame'],last_frame=rows[-1]['frame'],source_span_sec=span,
        result_interval_hz=(n-1)/span if span else None,
        all_reference_active=all(r['reference_active'] for r in rows),bridge_accepted=sum(r['bridge_accepted'] for r in rows),
        main_numeric=sum(r['main_available'] for r in rows),comparison_numeric=sum(r['comparison_available'] for r in rows),
        both_numeric=len(both),both_numeric_exact_equal=sum(r['main_range_m']==r['comparison_range_m'] for r in both),
        main_reasons=dict(Counter(r['main_reason'] for r in rows)),comparison_reasons=dict(Counter(r['comparison_reason'] for r in rows)),
        main_range_m=distribution([r['main_range_m'] for r in rows if r['main_available']]),
        main_age_ms=distribution([r['main_age_ms'] for r in rows]),
        comparison_service_ms=distribution([r['comparison_service_ms'] for r in rows]),
        comparison_age_ms=distribution([r['comparison_age_ms'] for r in rows]),
        main_over_33p33ms=sum(r['main_age_ms']>1000/30 for r in rows),
        source_gap_ms=distribution([1000*(b['source_time_sec']-a['source_time_sec']) for a,b in zip(rows,rows[1:])]),
        source_sequence_ids_without_paired_result=rows[-1]['frame']-rows[0]['frame']+1-n)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--results-dir',type=Path,required=True)
    args=parser.parse_args();args.intake_dir=args.intake_dir.resolve();args.results_dir=args.results_dir.resolve()
    j=lambda p:parse_json(read_regular(p,256*1024))
    # CSV only retains scalar fields from already validated exact main/comparison pairs.
    with (args.results_dir/'paired_timing.csv').open() as stream:rows=list(csv.DictReader(stream))
    for r in rows:
        r['frame']=int(r['frame'])
        for k in ('reference_active','main_available','comparison_available','bridge_accepted'):r[k]={'True':True,'False':False}[r[k]]
        for k in ('source_time_sec','main_range_m','comparison_range_m','main_age_ms','comparison_service_ms','comparison_age_ms'):
            r[k]=float(r[k]) if r[k] else None
    by_frame={r['frame']:r for r in rows};require(len(by_frame)==len(rows),'duplicate paired frame')
    metadata={}
    for group in ('r01','r02'):
        folder=args.intake_dir/f'screen_samples_{group}'
        provenance=j(folder/'provenance.json')
        for f in provenance['frames']:
            require(hashlib.sha256((folder/f['file']).read_bytes()).hexdigest()==f['png_sha256'],'screen pixels changed')
            metadata[(group,f['file'])]=f
    anchors=[]
    with (BASE/'screen_readings.csv').open() as stream:
        for reading in csv.DictReader(stream):
            key=(reading['sample_set'],reading['file']);meta=metadata[key]
            number=int(reading['displayed_frame']);row=by_frame[number]
            require(row['bridge_accepted'] and row['main_available'],'screen numeric lacks accepted logged result')
            require(f"{row['main_range_m']:.3f}"==reading['displayed_range_m'],'screen/log rounded range mismatch')
            # receive-age is read from the recorded UI, not calculated as end-to-end latency.
            anchors.append(dict(**reading,pts_sec=meta['pts_sec'],source_time_sec=row['source_time_sec'],
                native_screen_sha256=meta['png_sha256'],logged_range_m=row['main_range_m'],
                comparison_available=row['comparison_available'],comparison_reason=row['comparison_reason']))
    ordered=sorted(anchors,key=lambda a:a['pts_sec'])
    require(all(int(b['displayed_frame'])>int(a['displayed_frame']) for a,b in zip(ordered,ordered[1:])),'nonincreasing screen anchors')
    results={}
    with (BASE/'phases.csv').open() as stream:
        for phase in csv.DictReader(stream):
            first,last=int(phase['first_frame']),int(phase['last_frame'])
            require(44063<=first<=last<=45275,'phase must stay in observed screen scope')
            results[phase['phase']]=dict(selection=phase,**stats(select_phase(rows,first,last)))
    offsets=[a['source_time_sec']-a['pts_sec'] for a in anchors]
    # Numeric comparisons in the screenshot are sampled; no claim all GUI refreshes were read.
    result=dict(schema='guarded_motion_screen_audit_v1',state='pass',session='24aad0a8d31d46eeb33ef252b0d18475',
        native_screen_anchors=len(anchors),all_anchors_match_rounded_primary=True,
        screen_minus_source_offset_variation_sec=max(offsets)-min(offsets),phases=results,
        prior_test_excluded_from_screen_phases=True,boundary_times_approximate=True,independent_motion_odometry_supplied=False,
        screen_not_native_camera_pixels=True,physical_accuracy_verified=False,end_to_end_latency_verified=False,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__),BASE/'screen_readings.csv',BASE/'phases.csv',args.results_dir/'paired_timing.csv')})
    with (args.results_dir/'screen_audit.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    with (args.results_dir/'screen_anchors.csv').open('x',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(anchors[0]));w.writeheader();w.writerows(anchors)
    with (args.results_dir/'screen_window.csv').open('x',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(select_phase(rows,44063,45275))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
