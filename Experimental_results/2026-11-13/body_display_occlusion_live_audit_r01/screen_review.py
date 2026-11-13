"""Readout of unedited screencast samples and closed, validated scalar logs."""
import argparse
from collections import Counter
import csv
import importlib.util
import json
import math
from pathlib import Path

BASE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('occlusion_log_audit',BASE/'review.py')
audit=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(audit)
ROOT,require,file_sha=audit.ROOT,audit.require,audit.file_sha
distribution=audit.shared.distribution


def parse_row(row):
    row=dict(row);row['frame']=int(row['frame'])
    for name in ('original_available','display_permitted','bridge_accepted','comparison_available'):
        require(row[name] in ('True','False',''),'bad CSV bool')
        row[name]={'True':True,'False':False,'':None}[row[name]]
    for name in ('source_time_sec','original_range_m','display_range_m','raw_age_ms','review_age_ms','raw_to_review_ms',
                 'comparison_range_m','comparison_service_ms','comparison_age_ms'):
        row[name]=float(row[name]) if row[name] else None
        require(row[name] is None or math.isfinite(row[name]),'nonfinite timing CSV')
    return row


def check_numeric(reading,row):
    require(row['bridge_accepted'] is True and row['display_permitted'] is True and row['reference_generation']=='1',
            'screen numeric lacks same-frame accepted display permission')
    require(row['session']==audit.SESSION and row['frame']==int(reading['displayed_frame']),'wrong screen identity')
    require(f"{row['display_range_m']:.3f}"==reading['displayed_range_m'],'screen/display rounded value mismatch')
    require(row['display_range_m']==row['original_range_m'],'display changed raw numeric value')


def check_withheld(reading,pts,rows,offsets):
    # WITHHELD deliberately has no session/frame label in the current UI. Do not
    # invent one. Test temporal consistency over the observed numeric-anchor
    # offset envelope, and retain the envelope as an explicit limitation.
    candidates=[r for r in rows if pts+min(offsets)<=r['source_time_sec']<=pts+max(offsets)]
    require(candidates,'no log rows in observed anchor-offset envelope')
    require(all(r['display_permitted'] is False and r['bridge_accepted'] is True
                and r['display_reason']==reading['displayed_reason'] for r in candidates),
            'withheld screen conflicts with candidate log interval')
    return dict(first_candidate_frame=candidates[0]['frame'],last_candidate_frame=candidates[-1]['frame'],
                candidate_rows=len(candidates),exact_same_frame_identity_verified=False)


def stats(rows):
    require(rows,'empty phase')
    n=len(rows);span=rows[-1]['source_time_sec']-rows[0]['source_time_sec']
    return dict(rows=n,first_frame=rows[0]['frame'],last_frame=rows[-1]['frame'],source_span_sec=span,
        result_interval_hz=(n-1)/span if span else None,
        source_sequence_ids_without_result=rows[-1]['frame']-rows[0]['frame']+1-n,
        bridge_accepted=sum(r['bridge_accepted'] for r in rows),
        original_numeric=sum(r['original_available'] for r in rows),
        display_permitted=sum(r['display_permitted'] for r in rows),
        permitted_exact_original=sum(r['display_permitted'] and r['display_range_m']==r['original_range_m'] for r in rows),
        original_withheld_display_numeric=sum(not r['original_available'] and r['display_permitted'] for r in rows),
        original_reason_counts=dict(Counter(r['original_reason'] for r in rows)),
        display_reason_counts=dict(Counter(r['display_reason'] for r in rows)),
        body_numeric_veto=sum(r['original_available'] and r['display_reason']=='possible_self_body_occlusion' and not r['display_permitted'] for r in rows),
        raw_range_m=distribution([r['original_range_m'] for r in rows if r['original_available']]),
        permitted_range_m=distribution([r['display_range_m'] for r in rows if r['display_permitted']]),
        main_age_ms=distribution([r['raw_age_ms'] for r in rows]),
        review_completion_age_ms=distribution([r['review_age_ms'] for r in rows]),
        raw_to_review_completion_ms=distribution([r['raw_to_review_ms'] for r in rows]),
        review_age_over_33p33ms=sum(r['review_age_ms']>1000/30 for r in rows),
        source_gap_ms=distribution([1000*(b['source_time_sec']-a['source_time_sec']) for a,b in zip(rows,rows[1:])]),
        comparison_numeric=sum(r['comparison_available'] is True for r in rows),
        comparison_reason_counts=dict(Counter(r['comparison_reason'] for r in rows)),
        comparison_service_ms=distribution([r['comparison_service_ms'] for r in rows]),
        comparison_completion_age_ms=distribution([r['comparison_age_ms'] for r in rows]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intake-dir',type=Path,required=True);parser.add_argument('--results-dir',type=Path,required=True)
    args=parser.parse_args();args.intake_dir=args.intake_dir.resolve();args.results_dir=args.results_dir.resolve()
    require(not (args.results_dir/'screen_audit.json').exists(),'new screen audit required')
    log_audit=json.loads((args.results_dir/'audit.json').read_bytes())
    timing=ROOT/log_audit['complete_timing_csv']['path']
    require(file_sha(timing)==log_audit['complete_timing_csv']['sha256'],'validated timing table changed')
    with timing.open() as stream:rows=[parse_row(r) for r in csv.DictReader(stream)]
    by_frame={r['frame']:r for r in rows};require(len(by_frame)==len(rows),'duplicate log identity')
    metadata={};sources={}
    for group in ('r01','r02'):
        folder=args.intake_dir/f'screen_samples_{group}'
        provenance=json.loads((folder/'provenance.json').read_bytes())
        require(provenance['video_sha256']==file_sha(args.intake_dir/'video/screen.webm'),'screencast provenance mismatch')
        sources[str((folder/'provenance.json').relative_to(ROOT))]=file_sha(folder/'provenance.json')
        for frame in provenance['frames']:
            require(frame['width']==1920 and frame['height']==1200 and file_sha(folder/frame['file'])==frame['png_sha256'],'native screen bytes changed')
            metadata[(group,frame['file'])]=frame
    with (BASE/'screen_readings.csv').open() as stream:readings=list(csv.DictReader(stream))
    numeric=[];withheld=[];obscured=[];offsets=[]
    for reading in readings:
        meta=metadata[(reading['sample_set'],reading['file'])]
        record=dict(**reading,pts_sec=meta['pts_sec'],native_screen_sha256=meta['png_sha256'])
        if reading['kind']=='numeric':
            row=by_frame[int(reading['displayed_frame'])];check_numeric(reading,row)
            offsets.append(row['source_time_sec']-meta['pts_sec'])
            numeric.append(dict(**record,exact_frame_match=True,logged_range_m=row['display_range_m']))
        elif reading['kind']=='withheld':withheld.append(record)
        else:require(reading['kind']=='obscured','unknown reading kind');obscured.append(record)
    require(len(numeric)>=3,'numeric anchors insufficient')
    for reading in withheld:reading.update(check_withheld(reading,reading['pts_sec'],rows,offsets))
    low,high=min(int(r['displayed_frame']) for r in numeric),max(int(r['displayed_frame']) for r in numeric)
    window=[r for r in rows if low<=r['frame']<=high]
    require((low,high)==(49664,51472),'manually observed screen window changed')
    bounds={'before_veto':(low,50557),'body_veto_interval':(50558,50935),'after_veto':(50936,high)}
    phases={name:stats([r for r in window if a<=r['frame']<=b]) for name,(a,b) in bounds.items()}
    with (args.results_dir/'screen_window.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=window[0]);writer.writeheader();writer.writerows(window)
    result=dict(schema='body_occlusion_screen_audit_v1',state='pass',session=audit.SESSION,
        conditions=dict(user_confirmed_vehicle_forward_reverse=True,stationary_vehicle_cone_move_trial=False,
            vehicle_motion_visible_in_background=True,independent_odometry_supplied=False,physical_accuracy_verified=False),
        inspected_samples=len(readings),numeric_exact_frame_anchors=len(numeric),withheld_temporal_samples=len(withheld),
        other_application_samples_excluded=len(obscured),numeric_anchors=numeric,withheld_samples=withheld,obscured_samples=obscured,
        observed_anchor_offset_sec=distribution(offsets),observed_offset_span_sec=max(offsets)-min(offsets),
        withheld_frame_identity_not_shown_in_ui=True,withheld_matching_is_temporal_consistency_not_exact_frame_proof=True,
        all_gui_frames_or_end_to_end_latency_verified=False,screen_window=stats(window),phases=phases,
        only_recorded_screen_window_evaluated_not_full_waiting_run=True,
        source_sha256={**sources,**{str(p.relative_to(ROOT)):file_sha(p) for p in (Path(__file__),BASE/'screen_readings.csv',timing,args.results_dir/'audit.json')}})
    (args.results_dir/'screen_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('state','inspected_samples','numeric_exact_frame_anchors','withheld_temporal_samples','screen_window','phases')},indent=2))


if __name__=='__main__':main()
