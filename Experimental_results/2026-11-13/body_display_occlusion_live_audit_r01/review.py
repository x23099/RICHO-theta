"""Bounded closed-run intake and exact raw/display/bridge audit; no live I/O."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('body_audit_shared',
    ROOT/'Experimental_results/2026-11-13/body_display_static_live_audit_r01/review.py')
shared=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(shared)
require,file_sha=shared.require,shared.file_sha
SESSION='24e1146277d043fa8c01d36e2ebe0651'
STEMS=tuple(f'decoded_{SESSION}_f{n:06d}' for n in (1677,17327))
PREFIXES={'primary':'Experimental_results/2026-11-13/driver_body_guard_occlusion_r01',
          'comparison':'recordings/2026-11-13/body_guard_occlusion_r01'}
FILES={'primary':shared.FILES['primary'],
       'comparison':('comparison_frames.jsonl','comparison_status.json','reference.json','request.json',
                     *(stem+suffix for stem in STEMS for suffix in ('.png','.json')))}
VIDEO='Screencast from 2026年11月13日 20時27分27秒.webm'


def extract_checked(path,target,allowed,directories,*,total_limit=512*1024*1024):
    require(not target.exists() and path.stat().st_size<=256*1024*1024,'new target and bounded archive required')
    with tarfile.open(path,'r:xz') as archive:
        members=archive.getmembers();require(len(members)<=40,'too many archive entries')
        regular={};seen=set();total=0
        for item in members:
            name=item.name.rstrip('/');pure=PurePosixPath(name)
            require(name==str(pure) and not pure.is_absolute() and '..' not in pure.parts and '\\' not in name,'unsafe archive name')
            require(name not in seen,'duplicate archive entry');seen.add(name)
            if item.isdir():require(name in directories,'unexpected directory');continue
            require(item.isfile() and name in allowed,'unexpected file, link or special entry')
            destination=allowed[name]
            limit=(256*1024*1024 if destination.endswith('motion_distance_frames.jsonl') else
                   64*1024*1024 if destination.endswith(('.jsonl','.webm')) else
                   4*1024*1024 if destination.endswith('.png') else 1024*1024)
            total+=item.size
            require(0<=item.size<=limit and total<=total_limit,'archive size bound exceeded')
            regular[name]=item
        require(set(regular)==set(allowed),'missing required file')
        target.mkdir(parents=True)
        hashes={}
        for name,item in regular.items():
            destination=target/allowed[name];destination.parent.mkdir(parents=True,exist_ok=True)
            digest=hashlib.sha256();remaining=item.size
            with archive.extractfile(item) as source,destination.open('xb') as output:
                while remaining:
                    block=source.read(min(1024*1024,remaining));require(block,'truncated member')
                    output.write(block);digest.update(block);remaining-=len(block)
            hashes[allowed[name]]=digest.hexdigest()
    return hashes


def intake(args):
    require(not args.intake_dir.exists(),'new intake directory required')
    allowed={PREFIXES[role]+'/'+name:role+'/'+name for role,names in FILES.items() for name in names}
    directories={*PREFIXES.values(),PREFIXES['primary']+'/ultralytics_config',
        PREFIXES['primary']+'/ultralytics_config/matplotlib',PREFIXES['primary']+'/ultralytics_config/Ultralytics'}
    logs=extract_checked(args.archive,args.intake_dir/'logs',allowed,directories)
    video=extract_checked(args.screen_archive,args.intake_dir/'video',{VIDEO:'screen.webm'},set(),total_limit=64*1024*1024)
    manifest=dict(schema='body_occlusion_intake_v1',archive_sha256=file_sha(args.archive),
        screen_archive_sha256=file_sha(args.screen_archive),original_screen_name=VIDEO,
        supplied_files_sha256={**{'logs/'+k:v for k,v in logs.items()},**{'video/'+k:v for k,v in video.items()}})
    (args.intake_dir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('18 closed-run files + original screencast safely preserved.',flush=True)


def verify_manifest(directory):
    manifest=shared.parse_json(shared.read_regular(directory/'manifest.json',64*1024))
    require(manifest['schema']=='body_occlusion_intake_v1','wrong intake schema')
    expected={f'logs/{role}/{name}' for role,names in FILES.items() for name in names}|{'video/screen.webm'}
    require(set(manifest['supplied_files_sha256'])==expected,'intake file set mismatch')
    for name,digest in manifest['supplied_files_sha256'].items():
        require(file_sha(directory/name)==digest,'submitted bytes changed: '+name)
    return manifest


def verify_pins(directory):
    import cv2
    import numpy as np
    comparison=directory/'logs/comparison';wanted={1677,17327};lines={}
    with (directory/'logs/primary/motion_distance_frames.jsonl').open('rb') as stream:
        for line in stream:
            row=shared.parse_json(line)
            if row['frame'] in wanted:
                require(row['frame'] not in lines,'duplicate pin source frame')
                lines[row['frame']]=hashlib.sha256(line).hexdigest()
            if len(lines)==2:break
    pins=[]
    for stem,prior_name in zip(STEMS,('body_display_occlusion_pin_intake_r01','body_display_occlusion_repin_intake_r01')):
        pin=shared.parse_json(shared.read_regular(comparison/(stem+'.json'),16384))
        png=shared.read_regular(comparison/(stem+'.png'),4*1024*1024)
        require(pin['session']==SESSION and pin['image_file']==stem+'.png' and pin['image_modified'] is False,'pin identity mismatch')
        require(hashlib.sha256(png).hexdigest()==pin['png_sha256'],'pin PNG mismatch')
        image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
        require(image is not None and image.shape==(720,1280,3) and hashlib.sha256(image.tobytes()).hexdigest()==pin['decoded_bgr_sha256'],'pin native pixels mismatch')
        require(lines.get(pin['frame'])==pin['source_log_line_sha256'],'pin exact source line mismatch')
        for suffix in ('.json','.png'):
            require(file_sha(comparison/(stem+suffix))==file_sha(ROOT/'recordings/2026-11-13'/prior_name/(stem+suffix)), 'pin differs from prior intake')
        pins.append(dict(frame=pin['frame'],png_sha256=pin['png_sha256'],exact_source_line_and_native_pixels_verified=True))
    return pins


def analyze(args):
    args.intake_dir=args.intake_dir.resolve();args.output_dir=args.output_dir.resolve()
    require(not args.output_dir.exists(),'new output directory required')
    manifest=verify_manifest(args.intake_dir)
    result,timings=shared.analyze(args.intake_dir/'logs',pin_stem=STEMS[1],
        reference_folder='body_display_reference_occlusion_repin_r01',
        pin_intake_folder='body_display_occlusion_repin_intake_r01',request_count=3,pending_sent=1)
    result.update(schema='body_display_occlusion_full_audit_v1',saved_pins=verify_pins(args.intake_dir),
        intake_manifest=manifest,all_submitted_bytes_unchanged=True,
        authority_scope='diagnostic display only; NOT physical/contact/ROS/FFB verification')
    # Retain the complete 52k-row timing table with local raw evidence, and put
    # only the observed screencast window in Git after the independent readout.
    derived=args.intake_dir/'derived';derived.mkdir(exist_ok=True)
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=timings[0]);writer.writeheader();writer.writerows(timings)
    blob=stream.getvalue().encode();target=derived/'display_timing.csv'
    if target.exists():require(file_sha(target)==hashlib.sha256(blob).hexdigest(),'existing derived timing table differs')
    else:
        with target.open('xb') as output:output.write(blob)
    result['complete_timing_csv']=dict(path=str((derived/'display_timing.csv').relative_to(ROOT)),sha256=file_sha(derived/'display_timing.csv'))
    result['display_reason_runs']=reason_runs(timings)
    metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(args.intake_dir/'video/screen.webm')]))
    result['screen_metadata']=metadata
    result['audit_code_sha256']={str(p.relative_to(ROOT)):file_sha(p) for p in
        (Path(__file__),Path(shared.__file__),Path(shared.shared.__file__),ROOT/'src/report_driver_motion_logs.py')}
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(state=result['state'],first_reference_frame=result['first_reference_frame'],
        geometry_replayed=result['geometry_replayed_from_logged_support'],geometry_reasons=result['geometry_reason_counts'],
        post_load=result['phases']['post_load'],shutdown=result['shutdown'],video=metadata['format']),indent=2))


def reason_runs(rows):
    runs=[]
    for row in rows:
        label=row['display_reason']
        if not runs or runs[-1]['reason']!=label:
            runs.append(dict(reason=label,first_frame=row['frame'],last_frame=row['frame'],rows=1,
                first_source_sec=row['source_time_sec'],last_source_sec=row['source_time_sec']))
        else:
            runs[-1].update(last_frame=row['frame'],last_source_sec=row['source_time_sec'],rows=runs[-1]['rows']+1)
    return runs


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    extract=sub.add_parser('intake');extract.add_argument('--archive',type=Path,required=True)
    extract.add_argument('--screen-archive',type=Path,required=True);extract.add_argument('--intake-dir',type=Path,required=True)
    audit=sub.add_parser('audit');audit.add_argument('--intake-dir',type=Path,required=True);audit.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();(intake if args.action=='intake' else analyze)(args)


if __name__=='__main__':main()
