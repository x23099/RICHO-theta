"""Offline bounded motion-r02 intake and paired-log audit; no model/control."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from report_driver_motion_logs import FRAME_FIELDS,FLAGS,read_jsonl,summarize,distribution
from verify_driver_withheld_evidence import parse_json,read_regular,verify
from cone_self_body_shadow import checked_reference

SPEC=importlib.util.spec_from_file_location('static_full_review',ROOT/'Experimental_results/2026-11-13/guarded_static_live_audit_r02/review.py')
shared=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(shared)
require=shared.require
file_sha=shared.file_sha
SESSION='24aad0a8d31d46eeb33ef252b0d18475'
PINS=(1062,18497)
PREFIXES={'primary':'Experimental_results/2026-11-13/driver_guarded_motion_r02',
          'comparison':'recordings/2026-11-13/guarded_motion_r02',
          'evidence':'recordings/2026-11-13/guarded_motion_evidence_r02'}
BASE_FILES={'primary':shared.FILES['primary'],
 'comparison':('comparison_frames.jsonl','request.json','comparison_status.json','reference.json',
    *(f'decoded_{SESSION}_f{n:06d}.{ext}' for n in PINS for ext in ('png','json'))),
 'evidence':('evidence_index.jsonl','evidence_status.json')}
VIDEO='Screencast from 2026年11月13日 18時46分18秒.webm'


def classified(name):
    p=PurePosixPath(name)
    require(bool(name) and name==str(p) and not p.is_absolute() and '..' not in p.parts and '\\' not in name,'unsafe archive name')
    for role,prefix in PREFIXES.items():
        if name.startswith(prefix+'/'):
            relative=name[len(prefix)+1:]
            if relative in BASE_FILES[role]:return role,relative
            # Use a literal fullmatch; no recorded path is ever followed.
            if role=='evidence' and re.fullmatch(r'decoded_'+SESSION+r'_f[0-9]{6}\.(png|json)',relative):
                return role,relative
    raise ValueError('unexpected archive member: '+name)


def extract(archive_path,target,*,video=False):
    require(not target.exists() and archive_path.stat().st_size<=256*1024*1024,'new bounded intake required')
    members=[];seen=set();total=0
    directories={*PREFIXES.values(),PREFIXES['primary']+'/ultralytics_config',
        PREFIXES['primary']+'/ultralytics_config/matplotlib',PREFIXES['primary']+'/ultralytics_config/Ultralytics'}
    with tarfile.open(archive_path,'r:xz') as archive:
        for n,item in enumerate(archive):
            require(n<180,'archive entry limit')
            name=item.name.rstrip('/')
            require(name not in seen,'duplicate archive entry');seen.add(name)
            if item.isdir():
                require(not video and name in directories,'unexpected archive directory');continue
            require(item.isfile(),'links/special entries rejected')
            if video:
                require(name==VIDEO,'unexpected video member');role,relative='screen',VIDEO
            else:role,relative=classified(name)
            limit=(256*1024*1024 if video or relative=='motion_distance_frames.jsonl' else
                   64*1024*1024 if relative.endswith('.jsonl') else 4*1024*1024 if relative.endswith('.png') else 1024*1024)
            total+=item.size
            require(0<=item.size<=limit and total<=512*1024*1024,'archive size bound')
            members.append((item,role,relative))
        required={role+'/'+name for role,names in BASE_FILES.items() for name in names}
        found={role+'/'+relative for _,role,relative in members}
        require(found=={'screen/'+VIDEO} if video else required<=found,'missing required file')
        if not video:
            extras={s for s in found if s not in required}
            require(len(extras)<=80,'too many evidence pairs')
            stems={s.rsplit('.',1)[0] for s in extras}
            require(extras=={s+'.'+ext for s in stems for ext in ('json','png')},'unpaired evidence')
        target.mkdir(parents=True);hashes={}
        for item,role,relative in members:
            destination=target/role/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            digest=hashlib.sha256();remaining=item.size
            with archive.extractfile(item) as source,destination.open('xb') as output:
                while remaining:
                    block=source.read(min(1024*1024,remaining));require(block,'truncated member')
                    output.write(block);digest.update(block);remaining-=len(block)
            hashes[role+'/'+relative]=digest.hexdigest()
    return dict(archive_sha256=file_sha(archive_path),files_sha256=hashes,total_uncompressed_bytes=total)


def analyze(directory):
    import cv2
    import numpy as np
    j=lambda path:parse_json(read_regular(path,1024*1024))
    primary=directory/'primary';comparison=directory/'comparison'
    status=j(comparison/'comparison_status.json');reference=checked_reference(j(comparison/'reference.json'))
    require(status['state']=='closed' and status['writer_done'] is True and status['shutdown_complete'] is True
        and status['error'] is None,'comparison shutdown incomplete')
    require(all(status[k] is False for k in (*FLAGS,'main_display_modified')),'status authority changed')
    require(reference['session']==SESSION and reference['source_frame']==18497,'unexpected reference identity')
    issued=ROOT/'Experimental_results/2026-11-13/guarded_motion_reference_r02_repin/reference.json'
    require(file_sha(comparison/'reference.json')==file_sha(issued),'issued reference differs')
    require(set(status['source_sha256'])==set(shared.SOURCES),'unexpected source set')
    for name,digest in status['source_sha256'].items():require(file_sha(ROOT/'src'/name)==digest,'source differs: '+name)
    frames,_=shared.read_main(primary/'motion_distance_frames.jsonl',18497)
    events,event_sha=read_jsonl(primary/'motion_bridge_events.jsonl')
    main_report,accepted=summarize(frames,events)
    require(len(main_report['sessions'])==1 and main_report['sessions'][0]['session']==SESSION,'main session differs')
    by_key={(r['session'],r['frame']):r for r in frames}
    pins={n:j(comparison/f'decoded_{SESSION}_f{n:06d}.json') for n in PINS}
    pin_lines={}
    with (primary/'motion_distance_frames.jsonl').open('rb') as stream:
        for line in stream:
            row=parse_json(line)
            if row['frame'] in pins:
                require(row['frame'] not in pin_lines,'duplicate pin');pin_lines[row['frame']]=hashlib.sha256(line).hexdigest()
    for n,pin in pins.items():
        stem=f'decoded_{SESSION}_f{n:06d}'
        require(pin['session']==SESSION and pin['frame']==n and pin['image_file']==stem+'.png'
            and pin['image_modified'] is False and all(pin[k] is False for k in ('physical_metric_verified','floor_contact_verified','usable_for_ffb')),'pin identity/authority')
        png=read_regular(comparison/(stem+'.png'),4*1024*1024)
        pixels=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
        require(hashlib.sha256(png).hexdigest()==pin['png_sha256'] and pixels is not None and pixels.shape==(720,1280,3)
            and hashlib.sha256(pixels.tobytes()).hexdigest()==pin['decoded_bgr_sha256'],'pin PNG/pixels differ')
        require(pin_lines.get(n)==pin['source_log_line_sha256'],'pin exact primary line differs')
    require(status['pin']==pins[18497] and reference['source_png_sha256']==pins[18497]['png_sha256'],'latest pin/reference differs')
    engine=j(primary/'motion_engine_summary.json');bridge=j(primary/'driver_motion_summary.json')
    require(bridge['shutdown_complete'] and bridge['child_stopped'] and bridge['io_thread_stopped']
        and bridge['worker_error'] is None and bridge['shutdown_error'] is None and bridge['forced_worker_kill'] is False,'primary shutdown incomplete')
    require(all(bridge[k] is False for k in ('physical_metric_verified','usable_for_ffb','distance_published_to_ros','control_channel_modified')),'bridge authority changed')
    require(len(frames)==len(events)==bridge['returned'] and bridge['sent']>=bridge['returned'],'primary/bridge accounting')
    require(sum(not v for v in accepted.values())==bridge['retired_results'],'retired accounting')
    require(engine['guarded_comparison']['worker_started'] is True and engine['guarded_comparison']['main_display_modified'] is False,'comparison isolation')
    require(engine['profile_sha256']==file_sha(primary/'motion_profile_used.json')==file_sha(
        ROOT/'Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'),'profile differs')
    require(engine['config_sha256']==file_sha(ROOT/'src/cone_distance_diagnostic_config.json'),'config differs')
    require(engine['weights_sha256']==j(ROOT/'src/cone_distance_diagnostic_config.json')['weights_sha256'],'recorded checkpoint differs')
    rows,_=read_jsonl(comparison/'comparison_frames.jsonl')
    require(len(rows)==status['processed']
        and (comparison/'comparison_frames.jsonl').stat().st_size==status['log_bytes'],'comparison accounting')
    require(status['offered']==len(frames),'offered/main differs')
    previous=0;timings=[]
    for row in rows:
        require(row['frame']>previous,'comparison order');previous=row['frame']
        key=row['session'],row['frame'];require(key in by_key,'comparison/main missing identity')
        main=by_key[key]
        require(row['source_time_sec']==main['source_time_sec'] and row['original_distance_available']==main['distance_available']
            and row['original_range_m']==main['horizontal_camera_foot_range_m'],'comparison original differs')
        require(all(row[k] is False for k in (*FLAGS,'main_display_modified','reference_used_posthoc')),'comparison authority')
        require(type(row['comparison_distance_available']) is bool,'boolean comparison availability')
        if row['comparison_distance_available']:
            require(type(row['comparison_range_m']) in (int,float) and math.isfinite(row['comparison_range_m']) and row['comparison_range_m']>=0
                and row['baseline_reproduced'] is True and row['reference_scope_verified'] is True,'unverified numeric comparison')
        else:require(row['comparison_range_m'] is None,'withheld comparison must be null')
        age=1000*(row['completed_time_sec']-row['source_time_sec'])
        require(main['completed_time_sec']<=row['completed_time_sec'] and 0<=row['comparison_service_ms']<=age+.001,'comparison timing')
        require(age<=500.000001 or row['reason'] in ('comparison_failed','comparison_result_retired'),'stale comparison not revoked')
        if row['reference_scope_verified']:
            require(row['reference_generation']==2 and row['reference_frame']==18497 and row['frame']>18497,'reference generation/frame differs')
        timings.append(dict(frame=row['frame'],source_time_sec=row['source_time_sec'],reference_active=row['reference_scope_verified'],
            main_available=main['distance_available'],main_range_m=main['horizontal_camera_foot_range_m'],main_reason=main['reason'],
            support_x=(main.get('support_pixel') or [None,None])[0],support_y=(main.get('support_pixel') or [None,None])[1],
            comparison_available=row['comparison_distance_available'],comparison_range_m=row['comparison_range_m'],comparison_reason=row['reason'],
            main_age_ms=main['frame_age_ms'],comparison_service_ms=row['comparison_service_ms'],comparison_age_ms=age,
            bridge_accepted=accepted[key]))
    active=[r for r in rows if r['reference_scope_verified']]
    require(active,'reference never active')
    request=j(comparison/'request.json')
    require(request==dict(schema='driver_guarded_request_v1',request_id=status['request_id'],action='load')
        and status['request_count']==5 and status['snapshots_saved']==2,'request history differs')
    evidence=verify(directory/'evidence',primary/'motion_distance_frames.jsonl')
    require(evidence['capture_shutdown_complete'] and evidence['source_log_checked'],'evidence incomplete')
    result=dict(schema='guarded_motion_live_r02_audit_v1',state='pass',session=SESSION,pin_frames=list(PINS),
        main=main_report['sessions'][0],comparison_rows=len(rows),first_active_frame=active[0]['frame'],
        active_reference=shared.paired_stats(active,by_key),comparison_reason_counts=dict(Counter(r['reason'] for r in rows)),
        shutdown=dict(primary=bridge,comparison=status),evidence=evidence,engine_metadata=engine,event_sha256=event_sha,
        sent_without_return=bridge['sent']-bridge['returned'],comparison_not_processed=status['offered']-status['processed'],
        pin_exact_lines_and_pixels_verified=True,issued_reference_exact_bytes_verified=True,source_files_rehashed=len(shared.SOURCES),
        physical_accuracy_verified=False,screen_motion_segments_verified=False,gui_latency_verified=False,
        end_to_end_camera_latency_verified=False,current_mount_repeatability_verified=False,
        local_camera_started=False,local_cuda_started=False,vehicle_operated_locally=False)
    return result,timings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('extract','audit'))
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--video-archive',type=Path)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.action=='extract':
        report=dict(logs=extract(args.archive,args.intake_dir/'logs'),video=extract(args.video_archive,args.intake_dir/'video',video=True))
        report['source_sha256']={str(Path(__file__).relative_to(ROOT)):file_sha(Path(__file__))}
        with (args.output_dir/'intake.json').open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
        print('Original logs and screencast preserved with SHA256.',flush=True)
    else:
        result,timings=analyze(args.intake_dir/'logs')
        intake=parse_json(read_regular(args.output_dir/'intake.json',128*1024))
        for role,part in (('logs','logs'),('video','video')):
            for name,digest in intake[role]['files_sha256'].items():require(file_sha(args.intake_dir/part/name)==digest,'intake bytes changed')
        result.update(intake=intake,source_sha256={str(Path(__file__).relative_to(ROOT)):file_sha(Path(__file__)),
            str(Path(shared.__file__).relative_to(ROOT)):file_sha(Path(shared.__file__))})
        with (args.output_dir/'audit.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
        with (args.output_dir/'paired_timing.csv').open('x',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(timings[0]),lineterminator='\n');writer.writeheader();writer.writerows(timings)
        print(json.dumps(dict(state=result['state'],main_rows=result['main']['processed_frames'],comparison_rows=result['comparison_rows'],
            active=result['active_reference'],evidence_pairs=result['evidence']['verified_pairs']),indent=2))


if __name__=='__main__':main()
