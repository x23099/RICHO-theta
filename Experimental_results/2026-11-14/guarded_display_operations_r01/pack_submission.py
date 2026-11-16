"""Package local evidence only; NEVER pin/load/start a camera or control ROS."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import tarfile
import tempfile
import time

ROOT=Path(__file__).resolve().parents[3]
PRIMARY=('motion_bridge_events.jsonl','motion_profile_used.json','motion_display_reviews.jsonl',
         'motion_engine_summary.json','driver_motion_summary.json','motion_worker_stderr.log','motion_distance_frames.jsonl')
FLAGS=('physical_metric_verified','floor_contact_verified','controlling_distance','usable_for_ffb','published_to_ros')


def require(value,message):
    if not value:raise ValueError(message)


def pairs(items):
    result={}
    for key,value in items:
        require(key not in result,'duplicate JSON key');result[key]=value
    return result


def parse(blob):
    def reject(value):raise ValueError('nonfinite JSON')
    result=json.loads(blob,object_pairs_hook=pairs,parse_constant=reject)
    require(type(result) is dict,'JSON object required');return result


def read(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0<=info.st_size<=limit,'bounded regular file required')
        blob=stream.read(limit+1)
        require(len(blob)==info.st_size,'file changed while reading')
        return blob


def paths(repo,primary,comparison,output):
    repo=repo.resolve();primary=(repo/primary).resolve();comparison=(repo/comparison).resolve();output=output.absolute()
    require(primary.is_dir() and comparison.is_dir(),'existing run directories required')
    require(primary!=repo and comparison!=repo and repo in primary.parents and repo in comparison.parents,'run directories must be below repository')
    require(primary!=comparison and primary not in comparison.parents and comparison not in primary.parents,'separate primary/comparison directories required')
    require(output.parent.is_dir() and output.name.endswith('.tar.xz') and not output.exists(),'new .tar.xz output required; choose another filename, never delete old data')
    require(primary not in output.resolve().parents and comparison not in output.resolve().parents,'archive must be outside input directories')
    return repo,primary,comparison,output


def engine_check(primary,comparison):
    blob=read(primary/'motion_engine_summary.json',16384);engine=parse(blob);gate=engine.get('body_display_guard',{})
    require(engine.get('schema')=='driver_motion_engine_v1' and gate.get('enabled') is True
            and gate.get('display_rejection_only') is True and gate.get('raw_main_result_modified') is False,
            'body display guard ON and raw result unchanged required')
    require(all(engine.get(k) is False for k in ('physical_metric_verified','usable_for_ffb','published_to_ros')),
            'diagnostic non-controlling engine required')
    require(engine.get('guarded_comparison',{}).get('directory')==str(comparison),
            'primary engine belongs to a different comparison directory')
    return blob


def pin_payload(primary,comparison,now):
    status_blob=read(comparison/'comparison_status.json',16384);s=parse(status_blob);pin=s.get('pin');latest=s.get('latest')
    require(s.get('schema')=='driver_guarded_comparison_status_v1','known comparison status required')
    require(s.get('state')=='pinned' and s.get('writer_done') is False and s.get('error') is None,'running pinned status required')
    require(type(pin) is dict and type(latest) is dict and latest.get('reason')=='comparison_pin_requested',
            'pin continuity uncertain; share status instead of repeatedly pinning or loading')
    require(type(s.get('status_time_sec')) in (int,float) and math.isfinite(s['status_time_sec'])
            and type(latest.get('source_time_sec')) in (int,float) and math.isfinite(latest['source_time_sec'])
            and 0<=now-s['status_time_sec']<=2. and 0<=now-latest['source_time_sec']<=.5,'fresh GPU-local status required')
    require(isinstance(pin.get('session'),str) and re.fullmatch('[0-9a-f]{32}',pin['session'])
            and type(pin.get('frame')) is int and pin['frame']>0,'bounded pin identity required')
    require(pin.get('schema')=='driver_guarded_pin_v1' and latest.get('reference_scope_verified') is False,
            'unloaded explicit pin required')
    require(s.get('request_action')=='pin' and s.get('request_id')==pin.get('request_id')
            and latest.get('session')==pin['session'] and type(latest.get('frame')) is int and latest['frame']>pin['frame'],
            'matching latest pin request required')
    require(all(s.get(k) is False for k in (*FLAGS,'main_display_modified'))
            and all(pin.get(k) is False for k in ('physical_metric_verified','floor_contact_verified','usable_for_ffb')),
            'diagnostic status required')
    stem=f"decoded_{pin['session']}_f{pin['frame']:06d}"
    require(pin.get('image_file')==stem+'.png' and pin.get('image_modified') is False and pin.get('image_size')==[1280,720],
            'native unchanged pin required')
    sidecar=read(comparison/(stem+'.json'),16384);png=read(comparison/(stem+'.png'),4*1024*1024)
    require(parse(sidecar)==pin,'pin sidecar mismatch')
    require(len(png)>=24 and png[:16]==b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
            and struct.unpack('>II',png[16:24])==(1280,720)
            and hashlib.sha256(png).hexdigest()==pin.get('png_sha256'),'native PNG/hash mismatch')
    return {'comparison_status.json':status_blob,stem+'.json':sidecar,stem+'.png':png,
            'motion_engine_summary.json':engine_check(primary,comparison)}


def closed_files(repo,primary,comparison):
    engine_check(primary,comparison)
    status=parse(read(comparison/'comparison_status.json',16384));summary=parse(read(primary/'driver_motion_summary.json',16384))
    require(status.get('state')=='closed' and status.get('writer_done') is True and status.get('shutdown_complete') is True
            and status.get('error') is None,'comparison must be normally closed before packaging')
    require(summary.get('shutdown_complete') is True and summary.get('child_stopped') is True
            and summary.get('io_thread_stopped') is True and summary.get('worker_error') is None
            and summary.get('shutdown_error') is None and summary.get('forced_worker_kill') is False,'primary must be normally closed before packaging')
    require(all(status.get(k) is False for k in (*FLAGS,'main_display_modified'))
            and all(summary.get(k) is False for k in ('physical_metric_verified','usable_for_ffb','distance_published_to_ros','control_channel_modified')),
            'diagnostic non-controlling closed run required')
    for name in PRIMARY:require((primary/name).is_file(),'missing required primary file: '+name)
    for name in ('comparison_frames.jsonl','comparison_status.json','reference.json','request.json'):
        require((comparison/name).is_file(),'missing required comparison file: '+name)
    files={}
    for base in (primary,comparison):
        for path in base.rglob('*'):
            require(not path.is_symlink(),'input symlink rejected')
            if path.is_dir():continue
            relative=path.relative_to(base).as_posix()
            if base==primary:
                require(relative in PRIMARY or relative in ('ultralytics_config/matplotlib/fontlist-v390.json',
                    'ultralytics_config/Ultralytics/Arial.ttf','ultralytics_config/Ultralytics/settings.json'),'unexpected primary file')
            else:
                require(relative in ('comparison_frames.jsonl','comparison_status.json','reference.json','request.json')
                        or re.fullmatch(r'decoded_[0-9a-f]{32}_f[0-9]{6,}\.(png|json)',relative),'unexpected comparison file')
            require(not relative.endswith('.part'),'unfinished file rejected')
            files[path.relative_to(repo).as_posix()]=path
    require(len(files)<=32,'bounded full-run file count required')
    return files


def package(kind,repo,primary,comparison,output,*,now=None):
    repo,primary,comparison,output=paths(repo,primary,comparison,output)
    payload=pin_payload(primary,comparison,time.monotonic() if now is None else now) if kind=='pin' else None
    files=closed_files(repo,primary,comparison) if kind=='closed' else {}
    require(kind in ('pin','closed'),'known packaging kind required')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.theta_submission_',suffix='.part',dir=output.parent,delete=False) as stream:
            temporary=Path(stream.name)
        with tarfile.open(temporary,'w:xz') as archive:
            if payload is not None:
                for name,blob in payload.items():
                    item=tarfile.TarInfo('body_guard_pin_submit/'+name);item.size=len(blob)
                    archive.addfile(item,io.BytesIO(blob))
            else:
                total=0
                for name,path in sorted(files.items()):
                    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                    with os.fdopen(fd,'rb') as source:
                        before=os.fstat(source.fileno());limit=(256*1024*1024 if path.name=='motion_distance_frames.jsonl' else
                            64*1024*1024 if path.suffix=='.jsonl' else 4*1024*1024 if path.suffix=='.png' else 1024*1024)
                        total+=before.st_size
                        require(stat.S_ISREG(before.st_mode) and before.st_size<=limit and total<=512*1024*1024,'full-run size bound exceeded')
                        item=tarfile.TarInfo(name);item.size=before.st_size;archive.addfile(item,source)
                        after=os.fstat(source.fileno())
                        require((before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns),
                                'input changed during packaging; keep original data and share status')
                closed_files(repo,primary,comparison)
        os.link(temporary,output)  # atomic publication; existing output is never replaced
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)  # only our unpublished temporary copy
    return dict(output=str(output),kind=kind,files=len(payload) if payload is not None else len(files),
                source_files_changed=False,pin_or_load_request_sent=False,live_hardware_started=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=('pin','closed'));parser.add_argument('--repo',type=Path,default=ROOT)
    parser.add_argument('--primary-dir',type=Path,required=True);parser.add_argument('--comparison-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    try:result=package(args.kind,args.repo,args.primary_dir,args.comparison_dir,args.output)
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(f'[ERROR] {error}');return 1
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
