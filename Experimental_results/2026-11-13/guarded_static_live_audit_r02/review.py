"""Static live full-run archive audit. No camera, model, network or control."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path,PurePosixPath
import struct
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from report_driver_motion_logs import FRAME_FIELDS,FLAGS,distribution,read_jsonl,summarize
from verify_driver_withheld_evidence import parse_json,read_regular
from cone_self_body_shadow import checked_reference

PIN='decoded_9e961a39b4f54b0395eb140f52625755_f000330'
PREFIXES={'primary':'Experimental_results/2026-11-13/driver_guarded_static_r02',
    'comparison':'recordings/2026-11-13/guarded_static_r02'}
SOURCES=('driver_guarded_comparison.py','cone_guarded_stream_comparison.py','cone_guarded_lower_edge_shadow.py',
    'cone_bbox_boundary_shadow.py','cone_self_body_shadow.py','cone_motion_range.py','cone_upper_support_candidate.py',
    'cone_support_completion_candidate.py','driver_motion_process.py')
FILES={'primary':('motion_bridge_events.jsonl','motion_profile_used.json','motion_engine_summary.json',
    'driver_motion_summary.json','motion_worker_stderr.log','motion_distance_frames.jsonl',
    'ultralytics_config/matplotlib/fontlist-v390.json','ultralytics_config/Ultralytics/Arial.ttf',
    'ultralytics_config/Ultralytics/settings.json'),
    'comparison':('comparison_frames.jsonl',PIN+'.png',PIN+'.json','request.json','comparison_status.json','reference.json')}


def require(value,message):
    if not value:raise ValueError(message)


def file_sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def extract_archive(path,target):
    require(not target.exists() and path.stat().st_size<=128*1024*1024,'new target and bounded archive required')
    allowed={PREFIXES[role]+'/'+name:(role,name) for role,names in FILES.items() for name in names}
    directories={*PREFIXES.values(),PREFIXES['primary']+'/ultralytics_config',
        PREFIXES['primary']+'/ultralytics_config/matplotlib',PREFIXES['primary']+'/ultralytics_config/Ultralytics'}
    with tarfile.open(path,'r:xz') as archive:
        members=archive.getmembers();seen=set();regular={};total=0
        require(len(members)<=40,'too many archive entries')
        for item in members:
            name=item.name.rstrip('/');p=PurePosixPath(name)
            require(name==str(p) and not p.is_absolute() and '..' not in p.parts and '\\' not in name,'unsafe archive name')
            require(name not in seen,'duplicate archive entry');seen.add(name)
            if item.isdir():require(name in directories,'unexpected archive directory');continue
            require(item.isfile() and name in allowed,'unexpected file, link or special entry')
            role,relative=allowed[name]
            limit=(128*1024*1024 if relative=='motion_distance_frames.jsonl' else
                64*1024*1024 if relative.endswith('.jsonl') else 4*1024*1024 if relative.endswith('.png') else 1024*1024)
            total+=item.size
            require(0<=item.size<=limit and total<=256*1024*1024,'archive size bound exceeded')
            regular[name]=item
        require(set(regular)==set(allowed),'missing full-run file')
        target.mkdir(parents=True)
        hashes={}
        for name,item in regular.items():
            role,relative=allowed[name];destination=target/role/relative
            destination.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256();remaining=item.size
            with archive.extractfile(item) as source,destination.open('xb') as output:
                while remaining:
                    block=source.read(min(1024*1024,remaining));require(block,'incomplete archive file')
                    output.write(block);digest.update(block);remaining-=len(block)
            hashes[role+'/'+relative]=digest.hexdigest()
    return hashes


def read_main(path,pin_frame):
    fields=(*FRAME_FIELDS,'front_candidates','support_pixel','target_roi_native_xyxy','input_source')
    rows=[];pin_line=None
    with path.open('rb') as stream:
        while True:
            line=stream.readline(4*1024*1024+1)
            if not line:break
            require(len(line)<=4*1024*1024 and line.endswith(b'\n'),'incomplete/oversized primary line')
            row=parse_json(line)
            if row['frame']==pin_frame:
                require(pin_line is None,'duplicate pin source frame');pin_line=line
            rows.append({k:row[k] for k in fields if k in row})
    return rows,pin_line


def matched_comparison(row,main,reference):
    key=row['session'],row['frame'];require(key==(main['session'],main['frame']),'comparison/main identity mismatch')
    require(row['source_time_sec']==main['source_time_sec'] and row['original_distance_available']==main['distance_available']
        and row['original_range_m']==main['horizontal_camera_foot_range_m'],'comparison/main source or original mismatch')
    require(all(row[k] is False for k in (*FLAGS,'main_display_modified','reference_used_posthoc')),'comparison authority changed')
    require(type(row['comparison_distance_available']) is bool,'boolean comparison availability required')
    if row['comparison_distance_available']:
        require(type(row['comparison_range_m']) in (int,float) and math.isfinite(row['comparison_range_m'])
            and row['comparison_range_m']>=0 and row['baseline_reproduced'] is True and row['reference_scope_verified'] is True,
            'numeric comparison lacks verification')
    else:require(row['comparison_range_m'] is None,'withheld comparison range must be null')
    require(main['completed_time_sec']<=row['completed_time_sec'],'comparison precedes main completion')
    age=1000*(row['completed_time_sec']-row['source_time_sec'])
    require(0<=age<=500.000001 or row['reason'] in ('comparison_failed','comparison_result_retired'),'stale comparison not revoked')
    require(type(row['comparison_service_ms']) in (int,float) and math.isfinite(row['comparison_service_ms'])
        and 0<=row['comparison_service_ms']<=age+.001,'invalid comparison service')
    if row['reference_scope_verified']:
        require(row['reference_generation']==1 and row['reference_frame']==reference['source_frame']
            and row['frame']>reference['source_frame'],'wrong/future reference binding')
    return age


def paired_stats(rows,main_by_key):
    mains=[main_by_key[(r['session'],r['frame'])] for r in rows]
    n=len(rows);span=rows[-1]['source_time_sec']-rows[0]['source_time_sec'] if n else 0
    both=[(r,m) for r,m in zip(rows,mains) if r['comparison_distance_available'] and m['distance_available']]
    return dict(rows=n,first_frame=rows[0]['frame'] if n else None,last_frame=rows[-1]['frame'] if n else None,
        source_span_sec=span,paired_interval_hz=(n-1)/span if span else None,
        original_numeric=sum(m['distance_available'] for m in mains),comparison_numeric=sum(r['comparison_distance_available'] for r in rows),
        original_reason_counts=dict(Counter(m['reason'] for m in mains)),comparison_reason_counts=dict(Counter(r['reason'] for r in rows)),
        both_numeric=len(both),both_numeric_exact_equal=sum(r['comparison_range_m']==m['horizontal_camera_foot_range_m'] for r,m in both),
        original_withheld_comparison_numeric=sum(not m['distance_available'] and r['comparison_distance_available'] for r,m in zip(rows,mains)),
        original_numeric_comparison_withheld=sum(m['distance_available'] and not r['comparison_distance_available'] for r,m in zip(rows,mains)),
        main_age_ms=distribution([m['frame_age_ms'] for m in mains]),
        comparison_service_ms=distribution([r['comparison_service_ms'] for r in rows]),
        comparison_age_ms=distribution([1000*(r['completed_time_sec']-r['source_time_sec']) for r in rows]),
        main_over_33p33ms=sum(m['frame_age_ms']>1000/30 for m in mains),
        main_numeric_range_m=distribution([m['horizontal_camera_foot_range_m'] for m in mains if m['distance_available']]),
        comparison_numeric_range_m=distribution([r['comparison_range_m'] for r in rows if r['comparison_distance_available']]))


def analyze(directory):
    import cv2
    import numpy as np
    primary=directory/'primary';comparison=directory/'comparison'
    j=lambda path:parse_json(read_regular(path,1024*1024))
    status=j(comparison/'comparison_status.json');pin=status['pin'];reference=checked_reference(j(comparison/'reference.json'))
    require(status['state']=='closed' and status['writer_done'] is True and status['shutdown_complete'] is True
        and status['error'] is None,'comparison writer not normally closed')
    require(all(status[k] is False for k in (*FLAGS,'main_display_modified')),'status authority changed')
    require(pin==j(comparison/(PIN+'.json')) and pin['image_file']==PIN+'.png' and pin['image_modified'] is False,'pin sidecar mismatch')
    require(pin['session']==reference['session'] and pin['frame']==reference['source_frame'],'reference/pin identity mismatch')
    local_reference=ROOT/'Experimental_results/2026-11-13/guarded_static_reference_r02/reference.json'
    require(file_sha(comparison/'reference.json')==file_sha(local_reference),'not the analyst-issued reference')
    prior=ROOT/'Experimental_results/2026-11-13/guarded_static_intake_r02'
    prior=ROOT/'recordings/2026-11-13/guarded_static_intake_r02'
    for name in (PIN+'.png',PIN+'.json'):
        require(file_sha(comparison/name)==file_sha(prior/name),'pin differs from verified intake')
    png=read_regular(comparison/(PIN+'.png'),4*1024*1024)
    require(hashlib.sha256(png).hexdigest()==pin['png_sha256']==reference['source_png_sha256']
        and struct.unpack('>II',png[16:24])==(1280,720),'PNG binding mismatch')
    image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
    require(image is not None and image.shape==(720,1280,3)
        and hashlib.sha256(image.tobytes()).hexdigest()==pin['decoded_bgr_sha256'],'pin native pixels mismatch')
    require(set(status['source_sha256'])==set(SOURCES),'unknown comparison dependency set')
    for name,digest in status['source_sha256'].items():require(file_sha(ROOT/'src'/name)==digest,'source hash differs: '+name)
    engine=j(primary/'motion_engine_summary.json');bridge=j(primary/'driver_motion_summary.json')
    require(engine['guarded_comparison']['worker_started'] is True and engine['guarded_comparison']['main_display_modified'] is False,'comparison worker not requested/isolated')
    require(engine['profile_sha256']==file_sha(primary/'motion_profile_used.json')==
        file_sha(ROOT/'Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'),'profile hash differs')
    require(engine['config_sha256']==file_sha(ROOT/'src/cone_distance_diagnostic_config.json'),'config differs')
    settings=j(ROOT/'src/cone_distance_diagnostic_config.json')
    require(engine['weights_sha256']==settings['weights_sha256'],'checkpoint record differs')
    require(bridge['shutdown_complete'] and bridge['child_stopped'] and bridge['io_thread_stopped']
        and bridge['worker_error'] is None and bridge['shutdown_error'] is None and bridge['forced_worker_kill'] is False,'primary/IO shutdown incomplete')
    require(all(bridge[k] is False for k in ('physical_metric_verified','usable_for_ffb','distance_published_to_ros','control_channel_modified')),'bridge authority changed')
    frames,pin_line=read_main(primary/'motion_distance_frames.jsonl',pin['frame'])
    require(pin_line is not None and hashlib.sha256(pin_line).hexdigest()==pin['source_log_line_sha256'],'pin exact primary log line hash differs')
    events,event_sha=read_jsonl(primary/'motion_bridge_events.jsonl')
    main_report,accepted=summarize(frames,events)
    require(len(main_report['sessions'])==1 and main_report['sessions'][0]['session']==pin['session'],'main session differs')
    require(len(frames)==len(events)==bridge['returned']==bridge['sent'],'primary/bridge row accounting differs')
    require(sum(not flag for flag in accepted.values())==bridge['retired_results'],'bridge retired count differs')
    by_key={(r['session'],r['frame']):r for r in frames}
    rows,_=read_jsonl(comparison/'comparison_frames.jsonl')
    require(len(rows)==status['processed'] and (comparison/'comparison_frames.jsonl').stat().st_size==status['log_bytes'],'comparison log accounting differs')
    require(status['offered']==len(frames) and len(rows)<=status['offered'],'comparison offered/primary count differs')
    previous=0;timings=[]
    for row in rows:
        require(row['frame']>previous,'comparison order/duplicate');previous=row['frame']
        key=row['session'],row['frame'];require(key in by_key,'comparison has no primary row')
        age=matched_comparison(row,by_key[key],reference);main=by_key[key]
        timings.append(dict(session=row['session'],frame=row['frame'],source_time_sec=row['source_time_sec'],
            reference_scope_verified=row['reference_scope_verified'],front_candidates=main['front_candidates'],
            main_available=main['distance_available'],main_range_m=main['horizontal_camera_foot_range_m'],main_reason=main['reason'],
            comparison_available=row['comparison_distance_available'],comparison_range_m=row['comparison_range_m'],comparison_reason=row['reason'],
            main_age_ms=main['frame_age_ms'],comparison_service_ms=row['comparison_service_ms'],comparison_age_ms=age))
    active=[r for r in rows if r['reference_scope_verified']]
    require(active,'reference was never active')
    phases={'pre_reference':[r for r in rows if r['frame']<active[0]['frame']],
        'active_reference':active,'active_single_candidate':[r for r in active if by_key[(r['session'],r['frame'])]['front_candidates']==1],
        'final_30_seconds':[r for r in rows if r['source_time_sec']>=frames[-1]['source_time_sec']-30.]}
    request=j(comparison/'request.json')
    require(request==dict(schema='driver_guarded_request_v1',request_id=status['request_id'],action='load')
        and status['request_count']==2 and status['request_action']=='load','load request mismatch')
    result=dict(schema='guarded_static_live_full_audit_v1',state='pass',required_files_complete=True,
        session=pin['session'],pin_frame=pin['frame'],main=main_report['sessions'][0],
        comparison_rows=len(rows),comparison_reason_counts=dict(Counter(r['reason'] for r in rows)),
        first_reference_frame=active[0]['frame'],first_reference_source_sec=active[0]['source_time_sec'],
        phases={label:paired_stats(items,by_key) for label,items in phases.items()},
        pin_exact_primary_line_and_pixels_verified=True,issued_reference_exact_bytes_verified=True,
        recorded_code_files_rehashed=len(SOURCES),checkpoint_file_supplied=False,
        shutdown=dict(primary=bridge,comparison=dict(state=status['state'],writer_done=status['writer_done'],
            shutdown_complete=status['shutdown_complete'],error=status['error'],offered=status['offered'],processed=status['processed'],
            latest_slot_overwrites=status['latest_slot_overwrites'],tap_busy_drops=status['tap_busy_drops'])),
        engine_metadata=engine,main_input_sources=dict(Counter(r.get('input_source') for r in frames)),
        event_sha256=event_sha,physical_metric_verified=False,gui_latency_verified=False,
        end_to_end_camera_latency_verified=False,all_live_frame_pixels_independently_recomputed=False,
        frame_selection_scope_does_NOT_monitor_full_image=True,current_mount_repeatability_verified=False,
        local_camera_started=False,local_cuda_started=False,vehicle_operated_locally=False)
    return result,timings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();require(not args.output_dir.exists(),'new result directory required')
    hashes=extract_archive(args.archive,args.intake_dir)
    print('All 15 required files safely preserved. Auditing closed main/comparison logs.',flush=True)
    result,timings=analyze(args.intake_dir)
    require(all(file_sha(args.intake_dir/name)==digest for name,digest in hashes.items()),'submitted bytes changed during audit')
    result.update(archive_sha256=file_sha(args.archive),supplied_files_sha256=hashes,
        source_sha256={str(Path(__file__).relative_to(ROOT)):file_sha(Path(__file__)),
            'src/report_driver_motion_logs.py':file_sha(ROOT/'src/report_driver_motion_logs.py')})
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    with (args.output_dir/'paired_timing.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(timings[0]),lineterminator='\n');writer.writeheader();writer.writerows(timings)
    print(json.dumps(dict(state=result['state'],main_rows=result['main']['processed_frames'],
        comparison_rows=result['comparison_rows'],first_reference_frame=result['first_reference_frame'],
        final_30_seconds=result['phases']['final_30_seconds']),indent=2))


if __name__=='__main__':main()
