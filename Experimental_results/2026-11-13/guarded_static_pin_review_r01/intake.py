"""Bounded static pin intake; preserves original bytes, no camera/model/control."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path,PurePosixPath
import re
import struct
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from verify_driver_withheld_evidence import parse_json,read_regular
from report_driver_motion_logs import distribution

SOURCES=('driver_guarded_comparison.py','cone_guarded_stream_comparison.py',
    'cone_guarded_lower_edge_shadow.py','cone_bbox_boundary_shadow.py','cone_self_body_shadow.py',
    'cone_motion_range.py','cone_upper_support_candidate.py','cone_support_completion_candidate.py',
    'driver_motion_process.py')
FLAGS=('physical_metric_verified','floor_contact_verified','controlling_distance','usable_for_ffb','published_to_ros')


def require(value,message):
    if not value:raise ValueError(message)


def digest(blob):return hashlib.sha256(blob).hexdigest()


def payloads(path):
    out={};seen=set();size=0
    with tarfile.open(path,'r:xz') as archive:
        for n,item in enumerate(archive):
            require(n<16,'too many archive entries')
            name=item.name.rstrip('/');p=PurePosixPath(name)
            require(name==str(p) and not p.is_absolute() and '..' not in p.parts and '\\' not in name
                and p.parts[0]=='guarded_static_r01' and len(p.parts)<=2,'unsafe archive path')
            require(name not in seen,'duplicate archive member');seen.add(name)
            require(item.isdir() or item.isfile(),'links and special files rejected')
            if item.isdir():
                require(len(p.parts)==1,'unexpected directory');continue
            require(len(p.parts)==2 and 0<=item.size<=64*1024*1024,'bounded flat file required')
            limit=64*1024*1024 if p.name=='comparison_frames.jsonl' else (4*1024*1024 if p.suffix=='.png' else 16384)
            require(item.size<=limit,'archive member exceeds role limit')
            size+=item.size;require(size<=70*1024*1024,'expanded archive exceeds bound')
            blob=archive.extractfile(item).read(item.size+1);require(len(blob)==item.size,'incomplete archive member')
            out[p.name]=blob
    return out


def review(payload):
    import cv2
    import numpy as np
    status=parse_json(payload['comparison_status.json']);pin=status['pin']
    require(status['schema']=='driver_guarded_comparison_status_v1' and pin['schema']=='driver_guarded_pin_v1','pin/status schema')
    session,frame=pin['session'],pin['frame']
    require(isinstance(session,str) and re.fullmatch('[0-9a-f]{32}',session)
        and type(frame) is int and frame>=1,'bounded pin identity required')
    stem=f'decoded_{session}_f{frame:06d}'
    require(set(payload)=={'comparison_status.json','comparison_frames.jsonl','request.json',stem+'.png',stem+'.json'},'unexpected archive file set')
    require(pin==parse_json(payload[stem+'.json']) and pin['image_file']==stem+'.png','pin/sidecar mismatch')
    require(pin['image_size']==[1280,720] and pin['image_modified'] is False,'native unchanged pin required')
    for k in ('png_sha256','decoded_bgr_sha256','source_log_line_sha256'):
        require(isinstance(pin[k],str) and re.fullmatch('[0-9a-f]{64}',pin[k]),'bounded SHA required')
    png=payload[stem+'.png']
    require(png[:16]==b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' and struct.unpack('>II',png[16:24])==(1280,720)
        and digest(png)==pin['png_sha256'],'native PNG/hash mismatch')
    image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
    require(image is not None and image.shape==(720,1280,3) and digest(image.tobytes())==pin['decoded_bgr_sha256'],'native decoded pixels mismatch')
    require(all(pin[k] is False for k in ('physical_metric_verified','floor_contact_verified','usable_for_ffb'))
        and all(status[k] is False for k in (*FLAGS,'main_display_modified')),'invalid physical/control authority')
    require(status['error'] is None and status['snapshots_saved']==1,'pin writer error or unexpected snapshots')
    request=parse_json(payload['request.json'])
    require(request==dict(schema='driver_guarded_request_v1',request_id=pin['request_id'],action='pin')
        and status['request_id']==pin['request_id'] and status['request_action']=='pin','pin request mismatch')
    require(set(status['source_sha256'])==set(SOURCES),'unexpected recorded dependency list')
    for name,sha in status['source_sha256'].items():
        require(digest(read_regular(ROOT/'src'/name,256*1024))==sha,'local code differs: '+name)
    log=payload['comparison_frames.jsonl'];require(log.endswith(b'\n'),'incomplete comparison log tail')
    rows=[parse_json(line) for line in log.splitlines()]
    require(len(rows)==status['processed'] and len(log)==status['log_bytes'],'log/status accounting mismatch')
    require(status['offered']>=len(rows),'offered/processed accounting mismatch')
    last_frame=0;last_source=-math.inf
    for row in rows:
        require(row['schema']=='guarded_stream_comparison_v1' and row['session']==session
            and type(row['frame']) is int and row['frame']>last_frame,'comparison row identity/order')
        require(math.isfinite(row['source_time_sec']) and row['source_time_sec']>last_source,'comparison source order')
        require(all(row[k] is False for k in (*FLAGS,'main_display_modified','reference_used_posthoc')),'comparison authority changed')
        require(row['comparison_distance_available'] is False and row['comparison_range_m'] is None
            and row['reference_scope_verified'] is False,'unexpected comparison before load')
        require(row['source_time_sec']<=row['completed_time_sec']<=row['source_time_sec']+.5,'comparison causality/freshness')
        last_frame,last_source=row['frame'],row['source_time_sec']
    pinned=[row for row in rows if row['frame']==frame]
    require(len(pinned)==1 and pinned[0]['source_time_sec']==pin['source_time_sec'],'pin frame absent/different in comparison log')
    closed=status['state']=='closed' and status['writer_done'] is True and status['shutdown_complete'] is True
    return dict(schema='guarded_static_pin_archive_review_v1',state='pass',session=session,pin_frame=frame,
        image_file=stem+'.png',pin_png_and_pixels_verified=True,pin_sidecar_and_status_equal=True,
        source_files_local_rehashed=len(SOURCES),comparison_rows=len(rows),reason_counts=dict(Counter(r['reason'] for r in rows)),
        original_numeric_rows_reported=sum(r['original_distance_available'] is True for r in rows),
        comparison_numeric_rows=0,comparison_service_ms=distribution([r['comparison_service_ms'] for r in rows]),
        receiver_to_comparison_age_ms=distribution([1000*(r['completed_time_sec']-r['source_time_sec']) for r in rows]),
        comparison_source_span_sec=rows[-1]['source_time_sec']-rows[0]['source_time_sec'],
        offered=status['offered'],processed=status['processed'],latest_slot_overwrites=status['latest_slot_overwrites'],
        tap_busy_drops=status['tap_busy_drops'],worker_closed=closed,
        old_pin_loadable_after_restart=False,live_reference_load_verified=False,
        original_main_log_supplied=False,exact_main_log_line_sha_independently_verified=False,
        raw_source_log_line_sha_recorded=pin['source_log_line_sha256'],
        current_geometry_accuracy_or_mount_verified=False,local_camera_started=False,local_cuda_started=False,
        NOT_post_load_comparison_performance_or_end_to_end_latency_validation=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    require(not args.intake_dir.exists() and not args.output_dir.exists(),'new output paths required')
    require(args.archive.stat().st_size<=64*1024*1024,'compressed archive exceeds bound')
    data=payloads(args.archive);report=review(data)
    report.update(archive_sha256=digest(read_regular(args.archive,64*1024*1024)),
        source_sha256={str(Path(__file__).relative_to(ROOT)):digest(Path(__file__).read_bytes())},
        supplied_files_sha256={name:digest(blob) for name,blob in data.items()})
    args.intake_dir.mkdir(parents=True)
    for name,blob in data.items():
        with (args.intake_dir/name).open('xb') as stream:stream.write(blob)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('state','session','pin_frame','comparison_rows','original_numeric_rows_reported','worker_closed')},indent=2))


if __name__=='__main__':main()
