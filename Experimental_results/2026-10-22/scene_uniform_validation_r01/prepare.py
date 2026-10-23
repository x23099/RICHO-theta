"""Predeclare time-grid samples, then decode raw recordings without image edits."""
from bisect import bisect_left
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256


def time_grid(rows,interval=1.):
    if not rows or not np.isfinite(interval) or interval<=0:raise ValueError('positive interval and nonempty frames required')
    times=[float(r['time_sec']) for r in rows]
    if not np.isfinite(times).all() or np.any(np.diff(times)<=0):raise ValueError('finite increasing frame times required')
    if [int(r['frame']) for r in rows]!=list(range(1,len(rows)+1)):raise ValueError('contiguous 1-based frame sequence required')
    targets=times[0]+np.arange(int(np.floor((times[-1]-times[0])/interval))+1)*interval
    selected=[];seen=set();duplicates=0
    for target in targets:
        index=bisect_left(times,float(target))
        assert index<len(times)
        if index in seen:duplicates+=1;continue
        seen.add(index)
        selected.append(dict(frame=index+1,target_time_sec=float(target),time_sec=times[index],
            role='estimate' if times[index]<(times[0]+times[-1])/2 else 'heldout'))
    return selected,duplicates


def main():
    output=HERE/'intake_r01'
    local=ROOT/'recordings/2026-10-22_scene_uniform_sampling_r01'
    if output.exists() or local.exists():raise ValueError('new sampling destinations required; no overwrite')
    previous=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01/results_r01/image_diagnostics.csv'
    audit=ROOT/'Experimental_results/2026-10-19/cone_recording_coordinate_audit_r01/results_r01/sessions.csv'
    pair_intake=ROOT/'Experimental_results/2026-10-19/paper_cone_2m_validation_r01/intake_summary.json'
    required={r['session'] for r in read_csv(previous)}
    locations={r['session']:Path(r['session_path']) for r in read_csv(audit)}
    extra=Path(json.loads(pair_intake.read_text())['session']);locations[extra.name]=extra
    assert len(required)==9 and required<=set(locations)
    sources={str(p):sha256(p) for p in (previous,audit,pair_intake,HERE/'method.md',Path(__file__))}
    plan=[]
    for session in sorted(required):
        folder=locations[session]
        for name in ('raw.avi','detections.csv','metadata.json'):sources[str(folder/name)]=sha256(folder/name)
        rows=read_csv(folder/'detections.csv');selected,duplicates=time_grid(rows)
        plan.append(dict(session=session,session_path=str(folder),raw_frames=len(rows),
            first_time_sec=float(rows[0]['time_sec']),last_time_sec=float(rows[-1]['time_sec']),
            interval_sec=1.,duplicate_target_frames_skipped=duplicates,selected=selected))
    output.mkdir();local.mkdir(parents=True)
    fixed=dict(work_date='2026-10-22',source_sha256=sources,sessions=plan,
        selection_uses_metric_labels=False,selection_precedes_decode_and_scene_detection=True)
    (output/'sampling_plan.json').write_text(json.dumps(fixed,indent=2)+'\n')
    manifest=[];session_rows=[]
    for entry in plan:
        session=entry['session'];folder=Path(entry['session_path'])
        targets={r['frame']:r for r in entry['selected']}
        destination=local/session;destination.mkdir()
        cap=cv2.VideoCapture(str(folder/'raw.avi'));assert cap.isOpened()
        count=0
        try:
            while True:
                ok,image=cap.read()
                if not ok:break
                count+=1
                assert image.shape==(720,1280,3)
                if count in targets:
                    path=destination/f'raw_f{count:06d}.png'
                    assert cv2.imwrite(str(path),image)
                    decoded_hash=hashlib.sha256(image.tobytes()).hexdigest()
                    assert hashlib.sha256(cv2.imread(str(path)).tobytes()).hexdigest()==decoded_hash
                    manifest.append(dict(session=session,source_session_path=str(folder),frame=count,
                        **{k:v for k,v in targets[count].items() if k!='frame'},source_native_png=str(path),
                        png_sha256=sha256(path),decoded_bgr_sha256=decoded_hash,width=1280,height=720,
                        source_raw_sha256=sources[str(folder/'raw.avi')],image_edited=False,usable_for_ffb=False))
        finally:cap.release()
        assert count==entry['raw_frames'],(session,count,entry['raw_frames'])
        session_rows.append(dict(session=session,decoded_frames=count,sampled_frames=len(targets),
            estimate_frames=sum(r['role']=='estimate' for r in targets.values()),heldout_frames=sum(r['role']=='heldout' for r in targets.values()),
            first_time_sec=entry['first_time_sec'],last_time_sec=entry['last_time_sec'],usable_for_ffb=False))
        print('sampled',session,len(targets),'of',count,flush=True)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    write_csv(output/'native_sample_manifest.csv',manifest);write_csv(output/'sessions.csv',session_rows)
    record=dict(status='PASS_UNIFORM_NATIVE_SAMPLING_NOT_CALIBRATION_APPROVAL',work_date='2026-10-22',
        sessions=len(plan),sampled_native_frames=len(manifest),decoded_raw_frames=sum(r['decoded_frames'] for r in session_rows),
        source_sha256=sources,local_images_directory=str(local),source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
