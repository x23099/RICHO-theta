"""Produce numeric timelines and unmodified review frames from the finished run."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import cv2

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'src'))
from cone_dataset import read_csv,sha256,write_csv


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    root=args.input_dir.resolve()
    report=json.loads((root/'video_summary.json').read_text())
    provenance=json.loads((root/'provenance.json').read_text())
    if report['status']!='COMPLETED_OFFLINE_VIDEO_NOT_DEPLOYMENT_APPROVAL' or provenance['status']!=report['status']:
        raise ValueError('completed offline run required')
    rows=read_csv(root/'frames.csv')
    gaps=read_csv(root/'zero_detection_runs.csv')
    if len(rows)!=report['total_frames']:
        raise ValueError('frame count differs from summary')
    sessions=provenance['source_sessions']
    anchor_pixels=read_csv(root/'anchor_pixels.csv')
    if sum(row['pixels_equal']=='0' for row in anchor_pixels)!=report['anchor_pixel_mismatches']:
        raise ValueError('anchor pixel check differs from summary')
    selected={}
    # Ten internal empty-output runs: inspect one original midpoint for each,
    # without interpolating ground truth to the entire run.
    for gap in gaps:
        if gap['bounded_by_detection']=='1':
            number=(int(gap['start_frame'])+int(gap['end_frame']))//2
            selected[(gap['session'],number)]=f"zero-output midpoint; run {gap['start_frame']}..{gap['end_frame']}"
    candidates=[row for row in rows if row['bottom_step_max_px']!='']
    largest=max(candidates,key=lambda row:float(row['bottom_step_max_px'])) if candidates else None
    if largest:
        for number in (int(largest['frame'])-1,int(largest['frame'])):
            selected[(largest['session'],number)]=f"largest linked bottom-point change; comparison frame; delta {largest['bottom_step_max_px']} px"
    raw=root/'raw_reviews';raw.mkdir(exist_ok=True)
    frame_rows={(row['session'],int(row['frame'])):row for row in rows}
    manifest=[]
    for session in sessions:
        source=Path(session['path'])/'raw.avi'
        if sha256(source)!=session['files_sha256']['raw.avi']:
            raise ValueError('original video changed')
        wanted={number for name,number in selected if name==session['session']}
        if not wanted: continue
        capture=cv2.VideoCapture(str(source))
        if not capture.isOpened(): raise ValueError('cannot reopen source')
        try:
            for number in range(1,max(wanted)+1):
                ok,frame=capture.read()
                if not ok: raise ValueError('source ended before selected frame')
                if number not in wanted: continue
                key=(session['session'],number)
                filename=f"{session['session']}_raw_f{number:06d}.png"
                target=raw/filename
                pixel_hash=hashlib.sha256(frame.tobytes()).hexdigest()
                if target.exists():
                    saved=cv2.imread(str(target))
                    if saved is None or hashlib.sha256(saved.tobytes()).hexdigest()!=pixel_hash:
                        raise ValueError('existing representative differs; no overwrite')
                elif not cv2.imwrite(str(target),frame): raise ValueError('PNG export failed')
                saved=cv2.imread(str(target))
                if saved.shape!=frame.shape or hashlib.sha256(saved.tobytes()).hexdigest()!=pixel_hash:
                    raise ValueError('raw PNG pixels changed')
                manifest.append(dict(file=str(target.relative_to(root)),session=key[0],frame=number,
                    time_sec=frame_rows[key]['time_sec'],width=frame.shape[1],height=frame.shape[0],
                    reason=selected[key],decoded_bgr_sha256=pixel_hash,png_sha256=sha256(target),
                    source_raw_sha256=session['files_sha256']['raw.avi']))
        finally: capture.release()
    if len(manifest)!=len(selected): raise ValueError('selected raw review frames missing')
    write_csv(root/'raw_review_manifest.csv',manifest)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(len(sessions),2,figsize=(12,3.5*len(sessions)),squeeze=False)
    for index,session in enumerate(sessions):
        group=[row for row in rows if row['session']==session['session']]
        times=[float(row['time_sec']) for row in group]
        axes[index,0].plot(times,[int(row['detections']) for row in group],linewidth=.6)
        for gap in gaps:
            if gap['session']==session['session'] and gap['bounded_by_detection']=='1':
                axes[index,0].axvspan(float(gap['start_time_sec']),float(gap['end_time_sec']),color='orange',alpha=.4)
        axes[index,0].set(ylabel='Detections / frame',xlabel='Recorded time (s)',
                          title=f"{'Red-present' if index==0 else 'Red-absent'} B: confidence 0.25")
        axes[index,0].set_ylim(-.1,max(2,max(int(row['detections']) for row in group))+.2)
        axes[index,1].plot(times[1:],[float(row['pipeline_ms']) for row in group[1:]],linewidth=.5)
        axes[index,1].axhline(1000/30,color='red',linestyle='--',label='33.3 ms reference (30 Hz)')
        axes[index,1].set(xlabel='Recorded time (s)',ylabel='Offline pipeline ms',title='First call excluded; NOT live end-to-end latency')
        axes[index,1].legend(fontsize=8)
        for axis in axes[index]:axis.grid(alpha=.25)
    figure.tight_layout()
    chart=root/'video_detection_and_timing.png';figure.savefig(chart,dpi=150);plt.close(figure)
    verification=dict(date='2026-10-13',decision='PASS_OFFLINE_VIDEO_INTAKE_NOT_DEPLOYMENT_APPROVAL',
        frames_checked=len(rows),anchors_checked=len(anchor_pixels),anchor_pixel_mismatches=report['anchor_pixel_mismatches'],
        raw_review_images=len(manifest),raw_pixels_unchanged=True,
        source_sha256={name:sha256(root/name) for name in ('frames.csv','predictions.csv','zero_detection_runs.csv',
                                                          'video_summary.json','provenance.json','anchor_pixels.csv')},
        script_sha256=sha256(Path(__file__)),graph_sha256=sha256(chart),
        no_ground_truth_interpolation=True,physical_output=False)
    (root/'postprocess_verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps(dict(raw_review_images=len(manifest),chart=str(chart),selected=manifest),indent=2))


if __name__=='__main__':main()
