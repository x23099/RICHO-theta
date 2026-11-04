"""Audit submitted simultaneous logs; no GPU, network, camera, or FFB."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from itertools import zip_longest
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from summarize_cone_distance_live import validate_row, reject_constant
from cone_upper_support_live import validate_record, summarize
from cone_distance_core import load_config, digest, DEFAULT_CONFIG
from cone_fixed_floor_live_load import validate_live_payload, png_digest
from cone_fixed_floor_candidate import measure_support
from cone_upper_support_candidate import observe_upper_completion


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def extract(archive, dest, reuse=False):
    existing=dest.exists()
    if existing and not reuse:
        raise ValueError('new extraction destination required (or --reuse-extraction with byte audit)')
    with tarfile.open(archive, 'r:xz') as stream:
        members = stream.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 1024**3:
            raise ValueError('archive exceeds audit bounds')
        seen = set()
        for m in members:
            p = PurePosixPath(m.name)
            if (p.is_absolute() or '..' in p.parts or not p.parts or p in seen
                    or not (m.isfile() or m.isdir())):
                raise ValueError('unsafe/duplicate archive member: '+m.name)
            seen.add(p)
        if not existing:dest.mkdir(parents=True, exist_ok=False)
        for m in members:
            target = dest.joinpath(*PurePosixPath(m.name).parts)
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif existing:
                if target.is_symlink() or not target.is_file() or target.stat().st_size!=m.size:
                    raise ValueError('existing extraction file mismatch')
                with stream.extractfile(m) as source:
                    h=hashlib.sha256()
                    for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
                if h.hexdigest()!=digest(target):raise ValueError('existing extraction hash mismatch')
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(m) as source, target.open('xb') as sink:
                    shutil.copyfileobj(source, sink, length=1024*1024)
    return dict(members=len(members), uncompressed_bytes=sum(m.size for m in members))


def stats(values):
    if not values:
        return dict(count=0)
    return dict(count=len(values), minimum=float(min(values)), median=float(np.median(values)),
                p95=float(np.percentile(values,95)), p99=float(np.percentile(values,99)), maximum=float(max(values)))


def numeric(shadow):
    return any(m['range_available'] for m in (shadow or {}).get('models', []))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--archive', type=Path, required=True)
    ap.add_argument('--extracted-dir', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--reuse-extraction', action='store_true')
    args=ap.parse_args()
    if args.output_dir.exists(): raise ValueError('new analysis output required')
    archive_info=extract(args.archive, args.extracted_dir,args.reuse_extraction)
    root=args.extracted_dir/'upper_support_capture_r01'
    output=args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    standard=summarize(root,output/'standard_upper_report')
    live=json.loads((root/'live_summary.json').read_text())
    events=[json.loads(x) for x in (root/'fixed_floor_model_events.jsonl').read_text().splitlines()]
    active_event=next(e for e in events if e['action']=='accepted')
    settings,camera,heading,_=load_config()
    config_sha=digest(DEFAULT_CONFIG)
    adapter,evidence=validate_live_payload((root/'prepared_floor.json').read_bytes(),settings,
        config_sha,root,active_event['requested_session'],active_event['activated_frame']-1,
        'support_completion_shadow')
    if adapter.bundle_sha256!=active_event['bundle_sha256']:raise ValueError('model event hash mismatch')
    counts=defaultdict(Counter);timings=defaultdict(lambda:defaultdict(list))
    values=defaultdict(list); quality=defaultdict(Counter)
    evidence_results=[]; compact=[]; geometry_count=0; geometry_error=0.; cache={}
    sessions=[]; last=None; active_times=[]; hashes={}
    files=['distance_frames.jsonl','upper_support_comparison.jsonl']
    hashers=[hashlib.sha256(),hashlib.sha256()]
    with (root/files[0]).open('rb') as olds, (root/files[1]).open('rb') as news:
        for index,pair in enumerate(zip_longest(olds,news),1):
            if any(p is None for p in pair):raise ValueError('paired row counts differ')
            for h,p in zip(hashers,pair):h.update(p)
            old,new=[json.loads(p,parse_constant=reject_constant) for p in pair]
            validate_row(old);validate_record(new)
            for field in ['session','frame','source_time_sec','completed_time_sec','frame_age_ms','fixed_floor_load','selected_detector_boxes','inference_source']:
                if old[field]!=new[field]:raise ValueError('paired mismatch: '+field)
            if (new['legacy_candidate']!=old['support_completion_shadow']['candidate']
                    or new['legacy_fixed_floor_shadow']!=old.get('fixed_floor_shadow')
                    or new['legacy_reason']!=old['reason']):raise ValueError('legacy branch changed in new log')
            if last and (old['source_time_sec']<=last['source_time_sec'] or
                    old['session']==last['session'] and old['frame']<=last['frame']):
                raise ValueError('nonmonotonic frame ordering')
            if not sessions or sessions[-1]!=old['session']:sessions.append(old['session'])
            last=old
            active=old['fixed_floor_load']['state']=='active'
            if active:active_times.append(old['source_time_sec'])
            oc=old['support_completion_shadow']['candidate'] or {}
            nc=new['upper_candidate'] or {}
            os=old.get('fixed_floor_shadow'); ns=new['upper_fixed_floor_shadow']
            on,nn=numeric(os),numeric(ns)
            both=on and nn
            record=dict(session=old['session'],frame=old['frame'],source_time_sec=old['source_time_sec'],
                active=active,legacy_numeric=on,upper_numeric=nn,
                legacy_point=oc.get('point'),upper_point=nc.get('point'),
                granted=nc.get('upper_completion_granted',False),
                legacy_candidate_reason=oc.get('reason','no_candidate'),
                upper_candidate_reason=nc.get('reason','no_candidate'),
                upper_completion_reason=nc.get('upper_completion_reason'),
                upper_quality_reason=new['upper_quality']['reason'],
                legacy_quality_reason=(os or {}).get('image_quality_reason'),
                frame_age_ms=old['frame_age_ms'],predict_ms=old['predict_ms'],
                support_geometry_ms=old['support_geometry_ms'],cone_service_ms=old['cone_service_ms'],
                evidence_status=new['evidence']['status'])
            for branch,shadow in [('legacy',os),('upper',ns)]:
                for m in (shadow or {}).get('models',[]):
                    if not m['range_available']:continue
                    key=(branch,m['model_name']);value=m['horizontal_camera_foot_range_m']
                    values[key].append(value)
                    record[branch+'__'+m['model_name']]=value
                    cache_key=(tuple(shadow['support_pixel']),m['model_name'])
                    if cache_key not in cache:
                        model=next(a for a in adapter.bundle['models'] if a['name']==m['model_name'])
                        cache[cache_key]=measure_support(shadow['support_pixel'],model,camera,heading,
                            session=old['session'],diagnostic_range_m=settings['diagnostic_range_m'])
                    measured=cache[cache_key]
                    error=abs(value-measured['horizontal_camera_foot_range_m'])
                    if not measured['range_available'] or error>1e-10:raise ValueError('geometry did not reproduce')
                    geometry_count+=1;geometry_error=max(geometry_error,error)
            if both:
                for a,b in zip(os['models'],ns['models']):
                    if a!=b:raise ValueError('shared accepted model values changed')
            for group in ['all']+(['active'] if active else ['inactive']):
                c=counts[group];c['rows']+=1;c['legacy_numeric']+=on;c['upper_numeric']+=nn
                c['upper_only_numeric']+=nn and not on;c['legacy_only_numeric']+=on and not nn
                c['both_numeric']+=both;c['neither_numeric']+=not on and not nn
                c['raw_granted']+=record['granted'];c['raw_attempted']+=nc.get('upper_completion_attempted',False)
                c['observation_errors']+='observation_error' in new
                c['stale_rows']+=old['frame_age_ms']>500
                for k in ['frame_age_ms','predict_ms','support_geometry_ms','cone_service_ms']:
                    timings[group][k].append(old[k])
                # Residual is not isolated upper cost; includes scheduling/evidence/other worker overhead.
                timings[group]['non_cone_service_residual_ms'].append(old['frame_age_ms']-old['cone_service_ms'])
                quality[(group,'legacy_candidate')][record['legacy_candidate_reason']]+=1
                quality[(group,'upper_candidate')][record['upper_candidate_reason']]+=1
                quality[(group,'upper_quality')][record['upper_quality_reason']]+=1
                quality[(group,'legacy_quality')][str(record['legacy_quality_reason'])]+=1
                quality[(group,'completion')][str(record['upper_completion_reason'])]+=1
            if new['evidence']['status']=='saved':
                path=root/new['evidence']['file']
                sha=png_digest(path)
                if sha!=new['evidence']['sha256']:raise ValueError('evidence hash mismatch')
                image=cv2.imread(str(path));before=image.copy()
                reproduced=observe_upper_completion(image,old['selected_detector_boxes'][0],camera)
                if reproduced!=new['upper_candidate']:raise ValueError('native evidence observation differs')
                if not np.array_equal(image,before):raise ValueError('observer modified evidence pixels')
                evidence_results.append(dict(file=new['evidence']['file'],sha256=sha,
                    session=old['session'],frame=old['frame'],legacy_point=oc.get('point'),
                    upper_point=nc.get('point'),raw_granted=record['granted'],
                    upper_numeric=nn,legacy_numeric=on,age_ms=old['frame_age_ms'],
                    upper_completion_reason=record['upper_completion_reason'],native_shape=list(image.shape),
                    same_frame_observation_reproduced=True,file_bytes_unchanged=True))
            compact.append(record)
    hashes.update({f:h.hexdigest() for f,h in zip(files,hashers)})
    for f in ['live_summary.json','fixed_floor_model_events.jsonl','prepared_floor.json']:
        hashes[f]=digest(root/f)
    fields=sorted(set().union(*(r.keys() for r in compact)))
    with (output/'paired_frames.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(compact)
    write_json(output/'evidence_verification.json',evidence_results)
    # Non-overlapping active 10-second bins expose relocation/warm-up; they are not physical labels.
    bins=defaultdict(list)
    for r in compact:
        if r['active']:bins[int((r['source_time_sec']-active_times[0])//10)].append(r)
    bin_rows=[]
    for b,rows in sorted(bins.items()):
        br=dict(relative_start_sec=10*b,rows=len(rows),
            legacy_numeric=sum(r['legacy_numeric'] for r in rows),upper_numeric=sum(r['upper_numeric'] for r in rows),
            raw_granted=sum(r['granted'] for r in rows),
            upper_only_numeric=sum(r['upper_numeric'] and not r['legacy_numeric'] for r in rows))
        for branch in ['legacy','upper']:
            names=[m['name'] for m in adapter.bundle['models']]
            v=[r[branch+'__'+names[0]] for r in rows if branch+'__'+names[0] in r]
            br[branch+'_first_model']=stats(v)
        bin_rows.append(br)
    shutdown=live.get('shutdown',{})
    finalized=(live.get('runtime_status')=='STOPPED' and live.get('worker_error') is None
        and live.get('run_error') is None and live.get('cleanup_errors')==[]
        and live.get('worker_stopped') is True and shutdown.get('shutdown_complete') is True
        and shutdown.get('worker_stopped') is True and shutdown.get('scene_job_running') is False
        and shutdown.get('model_load_running') is False)
    result=dict(schema='submitted_upper_capture_audit_v1',archive=str(args.archive),
        archive_sha256=digest(args.archive),archive_info=archive_info,
        extracted_root=str(root),input_sha256=hashes,normal_finalization=finalized,
        validated_paired_rows=len(compact),sessions=sessions,counts=dict(counts),
        source_span_sec=compact[-1]['source_time_sec']-compact[0]['source_time_sec'],
        active_span_sec=max(active_times)-min(active_times),active_event=active_event,
        model_sha256=adapter.bundle_sha256,live_evidence=evidence,
        timing_ms={g:{k:stats(v) for k,v in ks.items()} for g,ks in timings.items()},
        reasons={g+'__'+b:dict(c) for (g,b),c in quality.items()},
        model_ranges_m={b+'__'+m:stats(v) for (b,m),v in values.items()},
        native_evidence_count=len(evidence_results),all_native_evidence_verified=True,
        geometry_values_reproduced=geometry_count,maximum_geometry_error_m=geometry_error,
        active_ten_second_bins=bin_rows,physical_metric_verified=False,usable_for_ffb=False,
        displayed_frame_coverage_measured=False,isolated_upper_runtime_cost_measured=False,
        cross_pc_capture_latency_measured=False,actual_distance_reference_m=None)
    write_json(output/'audit.json',result)
    print(json.dumps({k:result[k] for k in ['normal_finalization','validated_paired_rows','sessions',
        'counts','source_span_sec','active_span_sec','native_evidence_count',
        'geometry_values_reproduced','maximum_geometry_error_m','model_ranges_m']},indent=2))


if __name__=='__main__':main()
