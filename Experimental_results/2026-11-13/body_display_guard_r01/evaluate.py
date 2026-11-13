"""Post-hoc support-log evaluation ONLY; does not replay video/model or operate UI."""
import argparse
from collections import Counter
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from driver_body_display_guard import BodyDisplayGuard,checked_display_review
from cone_self_body_shadow import checked_reference
from report_driver_motion_logs import distribution
from verify_driver_withheld_evidence import parse_json,read_regular


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):value.update(data)
    return value.hexdigest()


def require(condition,message):
    if not condition:raise ValueError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.intake_dir=args.intake_dir.resolve();args.output_dir=args.output_dir.resolve()
    require(not args.output_dir.exists(),'new output required')
    audited=ROOT/'Experimental_results/2026-11-13/guarded_motion_live_audit_r02/results_r01'
    audit=parse_json(read_regular(audited/'audit.json',128*1024))
    reference_path=args.intake_dir/'logs/comparison/reference.json'
    require(sha(reference_path)==audit['intake']['logs']['files_sha256']['comparison/reference.json'],'audited reference changed')
    reference=checked_reference(parse_json(read_regular(reference_path,32768)))
    primary=args.intake_dir/'logs/primary/motion_distance_frames.jsonl'
    original_sha=sha(primary)
    require(original_sha==audit['intake']['logs']['files_sha256']['primary/motion_distance_frames.jsonl'],'audited primary changed')
    with (audited/'paired_timing.csv').open() as stream:paired={int(r['frame']):r for r in csv.DictReader(stream)}
    activation=paired[audit['first_active_frame']]
    capability=dict(reference=reference,generation=2,activation_frame=audit['first_active_frame'],
        activated_at=float(activation['source_time_sec'])+float(activation['comparison_age_ms'])/1000)
    guard=BodyDisplayGuard();records=[];reviews=[];services=[]
    with primary.open('rb') as stream:
        while True:
            line=stream.readline(1024*1024+1)
            if not line:break
            require(len(line)<=1024*1024 and line.endswith(b'\n'),'bounded complete source line required')
            original=parse_json(line);n=original['frame']
            if not 44063<=n<=45275:continue
            source=original['source_time_sec'];p=paired[n]
            require(original['session']==reference['session'] and p['reference_active']=='True','same-session historically active reference required')
            old=copy.deepcopy(original)
            started=time.perf_counter();review=guard.review(original,capability,original['completed_time_sec'])
            service_ms=1000*(time.perf_counter()-started)
            checked_display_review(review,original)
            require(original==old,'raw original modified')
            if not original['distance_available']:require(not review['display_available'],'original withheld was rescued')
            if review['display_available']:
                require(review['display_range_m']==original['horizontal_camera_foot_range_m'],'numeric changed')
                require(p['comparison_available']=='True' and float(p['comparison_range_m'])==review['display_range_m'],'differs from recorded clear comparison')
            if p['comparison_reason']=='possible_self_body_occlusion':
                require(review['reason']==p['comparison_reason'] and not review['display_available'],'body veto missed')
            record=dict(frame=n,source_time_sec=source,source_log_line_sha256=hashlib.sha256(line).hexdigest(),
                original_available=original['distance_available'],original_range_m=original['horizontal_camera_foot_range_m'],
                display_available=review['display_available'],display_range_m=review['display_range_m'],display_reason=review['reason'],
                recorded_comparison_available=p['comparison_available']=='True',recorded_comparison_reason=p['comparison_reason'],
                local_gate_service_ms=service_ms)
            records.append(record);reviews.append(review);services.append(service_ms)
    require(len(records)==1186 and sum(r['display_available'] for r in records)==911,'screen scope/count differs')
    require(sum(r['display_reason']=='possible_self_body_occlusion' for r in records)==267,'body rejection count differs')
    near=[r for r in records if 44483<=r['frame']<=44662]
    require(len(near)==177 and all(not r['display_available'] for r in near),'near interval not fully withheld')
    require(sha(primary)==original_sha,'source bytes modified')
    result=dict(schema='body_display_guard_offline_evaluation_v1',state='pass',reference_session=reference['session'],
        reference_frame=reference['source_frame'],first_frame=records[0]['frame'],last_frame=records[-1]['frame'],rows=len(records),
        original_numeric=sum(r['original_available'] for r in records),display_numeric=sum(r['display_available'] for r in records),
        display_reasons=dict(Counter(r['display_reason'] for r in records)),near_rows=len(near),near_all_withheld=True,
        original_withheld_preserved=sum(not r['original_available'] and not r['display_available'] for r in records),
        clear_original_values_exactly_preserved=True,raw_log_bytes_unchanged=True,
        local_gate_service_ms=distribution(services),activation_time_proxy='first recorded active comparison completion, NOT actual live load time',
        offline_posthoc_only=True,new_live_display_recorded=False,real_cuda_replayed=False,new_images_extracted=False,
        physical_metric_verified=False,controlling_distance=False,usable_for_ffb=False,
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in
            (Path(__file__),ROOT/'src/driver_body_display_guard.py',ROOT/'src/cone_self_body_shadow.py',
             ROOT/'src/cone_motion_range.py',audited/'paired_timing.csv',reference_path,primary)})
    args.output_dir.mkdir(parents=True)
    with (args.output_dir/'evaluation.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    with (args.output_dir/'evaluation.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    with (args.output_dir/'offline_display_reviews.jsonl').open('x') as stream:
        for r in reviews:stream.write(json.dumps(r,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
