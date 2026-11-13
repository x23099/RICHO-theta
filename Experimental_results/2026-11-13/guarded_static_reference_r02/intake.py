"""Validate three copied pin files; original bytes only, no live/model/control."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import struct
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from verify_driver_withheld_evidence import parse_json,read_regular


def require(value,message):
    if not value:raise ValueError(message)


def sha(blob):return hashlib.sha256(blob).hexdigest()


def read_archive(path, prefix='1113r02'):
    require(isinstance(prefix,str) and re.fullmatch('[A-Za-z0-9_]+',prefix),'invalid archive prefix')
    payload={};seen=set();total=0
    with tarfile.open(path,'r:xz') as archive:
        for n,item in enumerate(archive):
            require(n<8,'too many archive entries')
            name=item.name.rstrip('/');p=PurePosixPath(name)
            require(name==str(p) and not p.is_absolute() and '..' not in p.parts and '\\' not in name
                and p.parts[0]==prefix and len(p.parts)<=2,'unsafe archive name')
            require(name not in seen,'duplicate archive entry');seen.add(name)
            require(item.isdir() or item.isfile(),'links/special files rejected')
            if item.isdir():require(len(p.parts)==1,'unexpected directory');continue
            require(len(p.parts)==2,'flat copied files required')
            limit=4*1024*1024 if p.suffix=='.png' else 16384
            total+=item.size
            require(0<=item.size<=limit and total<=5*1024*1024,'archive size limit')
            blob=archive.extractfile(item).read(item.size+1);require(len(blob)==item.size,'truncated member')
            payload[p.name]=blob
    return payload


def check(payload):
    import cv2
    import numpy as np
    status=parse_json(payload['comparison_status.json']);pin=status['pin']
    require(status['schema']=='driver_guarded_comparison_status_v1'
        and status['state']=='pinned' and status['writer_done'] is False and status['error'] is None,
        'running pinned status snapshot required')
    require(pin['schema']=='driver_guarded_pin_v1' and isinstance(pin['session'],str)
        and re.fullmatch('[0-9a-f]{32}',pin['session']) and type(pin['frame']) is int and pin['frame']>=1,'bounded pin identity')
    stem=f"decoded_{pin['session']}_f{pin['frame']:06d}"
    require(set(payload)=={'comparison_status.json',stem+'.json',stem+'.png'},'exactly three copied pin files required')
    require(pin==parse_json(payload[stem+'.json']) and pin['image_file']==stem+'.png','status/sidecar mismatch')
    require(pin['image_size']==[1280,720] and pin['image_modified'] is False,'native unchanged image required')
    for key in ('png_sha256','decoded_bgr_sha256','source_log_line_sha256'):
        require(isinstance(pin[key],str) and re.fullmatch('[0-9a-f]{64}',pin[key]),'bounded digest required')
    png=payload[stem+'.png']
    require(png[:16]==b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' and struct.unpack('>II',png[16:24])==(1280,720)
        and sha(png)==pin['png_sha256'],'PNG/hash mismatch')
    pixels=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
    require(pixels is not None and pixels.shape==(720,1280,3) and sha(pixels.tobytes())==pin['decoded_bgr_sha256'],'native decoded pixels mismatch')
    require(all(pin[k] is False for k in ('physical_metric_verified','floor_contact_verified','usable_for_ffb'))
        and all(status[k] is False for k in ('physical_metric_verified','floor_contact_verified','controlling_distance',
            'usable_for_ffb','published_to_ros','main_display_modified')),'authority flags changed')
    require(status['request_action']=='pin' and status['request_id']==pin['request_id']
        and type(status['snapshots_saved']) is int and 1<=status['snapshots_saved']<=8,'pin request mismatch')
    latest=status['latest']
    require(latest['session']==pin['session'] and latest['frame']>pin['frame'] and latest['reference_scope_verified'] is False,
        'post-pin same-session unreferenced snapshot required')
    require(status['ingress'][0]==pin['session'] and 0<=status['status_time_sec']-latest['source_time_sec']<=.5,
        'fresh snapshot at time of copy required')
    source_hashes=status['source_sha256']
    expected=('driver_guarded_comparison.py','cone_guarded_stream_comparison.py','cone_guarded_lower_edge_shadow.py',
        'cone_bbox_boundary_shadow.py','cone_self_body_shadow.py','cone_motion_range.py','cone_upper_support_candidate.py',
        'cone_support_completion_candidate.py','driver_motion_process.py')
    require(set(source_hashes)==set(expected),'recorded source list differs')
    for name,digest in source_hashes.items():require(sha(read_regular(ROOT/'src'/name,256*1024))==digest,'source mismatch: '+name)
    return dict(state='pass',session=pin['session'],source_frame=pin['frame'],image_file=stem+'.png',
        source_png_sha256=pin['png_sha256'],decoded_bgr_sha256=pin['decoded_bgr_sha256'],
        source_files_local_rehashed=len(source_hashes),snapshot_state=status['state'],snapshot_latest_frame=latest['frame'],
        snapshot_latest_reason=latest['reason'],
        # The state label records the last request, not witness survival. A gap
        # can occur before or after _pin in the same admission iteration; these
        # copied files cannot establish that ordering. Conservatively repin.
        snapshot_requires_repin=latest['reason']!='comparison_pin_requested',
        snapshot_witness_continuity_uncertain=latest['reason']!='comparison_pin_requested',
        snapshot_saved_pin_count=status['snapshots_saved'],
        snapshot_worker_running=True,snapshot_pin_to_latest_sec=latest['source_time_sec']-pin['source_time_sec'],
        remote_worker_still_running_now_NOT_verified=True,witness_survival_until_load_NOT_verified=True,
        primary_and_comparison_logs_supplied=False,physical_metric_verified=False,
        local_camera_started=False,local_cuda_started=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--archive-prefix',default='1113r02')
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();require(not args.intake_dir.exists() and not args.output_dir.exists(),'new output paths required')
    require(args.archive.stat().st_size<=5*1024*1024,'compressed archive exceeds bound')
    payload=read_archive(args.archive,args.archive_prefix);report=check(payload)
    report.update(archive_sha256=sha(read_regular(args.archive,5*1024*1024)),
        supplied_files_sha256={name:sha(blob) for name,blob in payload.items()},
        source_sha256={str(Path(__file__).relative_to(ROOT)):sha(Path(__file__).read_bytes())})
    args.intake_dir.mkdir(parents=True)
    for name,blob in payload.items():
        with (args.intake_dir/name).open('xb') as stream:stream.write(blob)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('state','session','source_frame','snapshot_state','snapshot_latest_frame')},indent=2))


if __name__=='__main__':main()
