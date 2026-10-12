"""Safely ingest submitted A/B cone recordings; no detection or pseudo-labels."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
sys.path.insert(0,str(REPO/'src'))
from analyze_field_recording import safe_extract_archive
from cone_dataset import read_csv,sha256,write_csv

SOURCES=(
    ('a_cone','cone_train_block_a_r01_20261012_153804_108.tar.xz','block_a','train'),
    ('a_no_cone','cone_nasi_block_a_20261012_154213_645.tar.xz','block_a','train'),
    ('b_cone','cone_train_block_b_r01_20261012_155114_513.tar.xz','block_b','val'),
    ('b_no_cone','cone_nasi_block_b_r01_20261012_155435_017.tar.xz','block_b','val'))


def inspect(item,archive_dir,root):
    key,name,group,split=item
    archive=archive_dir/name
    destination=root/key
    destination.mkdir()
    safe_extract_archive(archive,destination,2*1024**3)
    paths=list(destination.rglob('metadata.json'))
    if len(paths)!=1:
        raise ValueError('exactly one session per archive required')
    session=paths[0].parent
    metadata=json.loads(paths[0].read_text())
    rows=read_csv(session/'detections.csv')
    if not rows or [int(r['frame']) for r in rows]!=list(range(1,len(rows)+1)):
        raise ValueError('CSV frame alignment invalid')
    times=[float(r['time_sec']) for r in rows]
    if not all(math.isfinite(t) for t in times) or any(b<=a for a,b in zip(times,times[1:])):
        raise ValueError('CSV elapsed times invalid')
    review_ids={1,max(1,len(rows)//2),len(rows)}
    manifest=[]
    capture=cv2.VideoCapture(str(session/'raw.avi'))
    if not capture.isOpened(): raise ValueError('cannot open raw video')
    shape=(int(metadata['requested_camera_height']),int(metadata['requested_camera_width']),3)
    review=root/'review'/key
    review.mkdir(parents=True)
    try:
        for n in range(1,len(rows)+1):
            ok,frame=capture.read()
            if not ok or frame.shape!=shape: raise ValueError('raw frame count/shape mismatch')
            if n in review_ids:
                path=review/f'{key}_raw_frame_{n:06d}.png'
                digest=hashlib.sha256(frame.tobytes()).hexdigest()
                if not cv2.imwrite(str(path),frame): raise ValueError('raw PNG export failed')
                if hashlib.sha256(cv2.imread(str(path)).tobytes()).hexdigest()!=digest:
                    raise ValueError('PNG differs from decoded pixels')
                manifest.append(dict(key=key,session=session.name,frame=n,time_sec=rows[n-1]['time_sec'],
                    png=str(path),decoded_bgr_sha256=digest))
        if capture.read()[0]: raise ValueError('raw longer than CSV')
    finally:
        capture.release()
    counts={'raw.avi':len(rows)}
    for name_video in ('bev.avi','detection.avi'):
        capture=cv2.VideoCapture(str(session/name_video))
        try:
            if not capture.isOpened(): raise ValueError('other video missing/unreadable')
            counts[name_video]=int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        finally: capture.release()
    if len(set(counts.values()))!=1: raise ValueError('video header counts differ')
    result=dict(key=key,archive=str(archive),archive_sha256=sha256(archive),session_dir=str(session),
        session=session.name,group_id=group,split=split,frames=len(rows),last_time_sec=times[-1],
        image_shape=list(shape),raw_full_sequential_decode='PASS',other_video_header_counts=counts,
        other_videos_full_decode='NOT_RUN_NOT_REQUIRED_FOR_IMAGE_DATASET',
        files_sha256={name:sha256(session/name) for name in ('raw.avi','metadata.json','detections.csv')},
        ffb_publish_enabled=metadata['parameters'].get('collision_ffb_publish_enabled'),
        ai_enabled=metadata['parameters'].get('enable_ai'),
        visual_truth='NOT_ASSIGNED_BY_FILENAME',review=manifest)
    print(f"{key}: {len(rows)} raw frames verified; {session.name}",flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-dir',type=Path,required=True)
    parser.add_argument('--recording-root',type=Path,required=True)
    args=parser.parse_args()
    root=args.recording_root.resolve()
    if root.exists(): parser.error('new extraction root required; no overwrite')
    root.mkdir(parents=True)
    cv2.setNumThreads(1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(inspect,item,args.archive_dir.resolve(),root) for item in SOURCES]
        results=[f.result() for f in futures]
    (HERE/'input_inventory.json').write_text(json.dumps(dict(sources=results,
        development_only=True,independent_test='DEFERRED_NOT_FABRICATED',script_sha256=sha256(Path(__file__))),indent=2)+'\n')
    write_csv(HERE/'review_frame_manifest.csv',[r for s in results for r in s['review']])
    write_csv(HERE/'recording_plan.csv',[dict(session_dir=s['session_dir'],group_id=s['group_id'],split=s['split'],
        start_frame=1,end_frame='',stride_frames=30,notes='A=train B=val prototype; similar backgrounds; test deferred') for s in results])


if __name__=='__main__': main()
