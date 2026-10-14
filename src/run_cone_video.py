#!/usr/bin/env python3
"""Sequential offline cone video diagnostics. No camera/ROS/FFB or training."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import cv2

from cone_dataset import read_csv, sha256, validate, write_csv
from cone_detection_diagnostics import (aggregate, extract_predictions, intersection_over_union,
                                        prediction_kwargs, prepare_inputs)
from run_cone_yolo import check_cuda

FRAME_FIELDS = ('session','frame','time_sec','detections','new_tracks','continued_tracks',
                'bottom_step_median_px','bottom_step_max_px','decode_ms','predict_export_ms',
                'preprocess_ms','inference_ms','postprocess_ms','pipeline_ms','first_call')
PRED_FIELDS = ('session','frame','time_sec','prediction_index','class_id','confidence','x1','y1','x2','y2',
               'image_half','track_id','previous_iou','bottom_dx_px','bottom_dy_px','bottom_step_px')


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['video'])
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--dataset',type=Path)
    parser.add_argument('--object-attributes',type=Path)
    parser.add_argument('--diagnostic-split',choices=['val','test'],default='val')
    parser.add_argument('--device',type=int,default=0)
    parser.add_argument('--imgsz',type=int,default=960)
    parser.add_argument('--confidence',type=float,default=.25)
    parser.add_argument('--nms-iou',type=float,default=.7)
    parser.add_argument('--track-iou',type=float,default=.3)
    parser.add_argument('--max-det',type=int,default=300)
    parser.add_argument('--dry-run',action='store_true')
    return parser


def load_plan(path,output,weights):
    entries = read_csv(path)
    if not entries or any(not row.get('session_dir','').strip() for row in entries):
        raise ValueError('nonempty video plan with session_dir required')
    sessions,seen_names,seen_hashes = [],set(),set()
    for entry in entries:
        root = Path(entry['session_dir']).expanduser()
        root = (path.parent/root).resolve() if not root.is_absolute() else root.resolve()
        if root.name in seen_names:
            raise ValueError('duplicate session name in video plan')
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError('video output and input session must not overlap')
        seen_names.add(root.name)
        files = {name:root/name for name in ('raw.avi','metadata.json','detections.csv')}
        if any(not value.is_file() or value.is_symlink() for value in files.values()):
            raise ValueError('regular raw.avi/metadata.json/detections.csv session files required')
        rows=read_csv(files['detections.csv'])
        if not rows or [int(row['frame']) for row in rows] != list(range(1,len(rows)+1)):
            raise ValueError('contiguous one-based recording frames required')
        times=[float(row['time_sec']) for row in rows]
        if not all(math.isfinite(value) and value>=0 for value in times) or any(b<=a for a,b in zip(times,times[1:])):
            raise ValueError('finite strictly increasing recording times required')
        metadata=json.loads(files['metadata.json'].read_text())
        width,height=int(metadata['requested_camera_width']),int(metadata['requested_camera_height'])
        if min(width,height)<1:
            raise ValueError('positive original geometry required')
        hashes={name:sha256(value) for name,value in files.items()}
        if hashes['raw.avi'] in seen_hashes:
            raise ValueError('duplicate raw video content in plan')
        seen_hashes.add(hashes['raw.avi'])
        sessions.append(dict(root=root,session=root.name,rows=rows,times=times,width=width,height=height,
                             hashes=hashes,note=entry.get('note','')))
    return sessions


def validated_args(args):
    if args.device<0 or args.imgsz<32 or args.imgsz%32 or args.max_det<1:
        raise ValueError('GPU device>=0, imgsz positive multiple of32, max_det>=1 required')
    if not all(math.isfinite(value) and 0<value<=1 for value in (args.confidence,args.nms_iou,args.track_iou)):
        raise ValueError('finite confidence/IoU in (0,1] required')
    for name in ('plan','weights','output_dir'):
        setattr(args,name,getattr(args,name).expanduser().resolve())
    if args.output_dir.exists():
        raise ValueError('new output directory required; no existing run overwrite')
    if not args.weights.is_file() or args.output_dir.is_relative_to(args.weights.parent):
        raise ValueError('local checkpoint outside output required')
    if args.dataset:
        args.dataset=args.dataset.expanduser().resolve()
        if args.output_dir.is_relative_to(args.dataset) or args.dataset.is_relative_to(args.output_dir):
            raise ValueError('output and dataset must not overlap')
    if args.object_attributes:
        args.object_attributes=args.object_attributes.expanduser().resolve()
        if args.dataset is None or not args.object_attributes.is_file():
            raise ValueError('attributes require an existing dataset and attribute CSV')
    args.prediction_floor=args.confidence
    return args


def associate(previous,current,width,next_id,minimum_iou):
    """Consecutive-frame IoU associations only; not persistent object identity."""
    pairs=[]
    half=lambda row: 'left' if (row['x1']+row['x2'])/2<width/2 else 'right'
    for p_index,past in enumerate(previous):
        for c_index,present in enumerate(current):
            overlap=intersection_over_union(past,present)
            if half(past)==half(present) and overlap>=minimum_iou:
                pairs.append((-overlap,p_index,c_index))
    used_p,used_c=set(),set()
    predecessors={}
    for negative,p_index,c_index in sorted(pairs):
        if p_index not in used_p and c_index not in used_c:
            used_p.add(p_index);used_c.add(c_index)
            predecessors[c_index]=(previous[p_index],-negative)
    result=[]
    for index,row in enumerate(current):
        out=dict(row,image_half=half(row))
        if index in predecessors:
            past,overlap=predecessors[index]
            dx=(row['x1']+row['x2']-past['x1']-past['x2'])/2
            dy=row['y2']-past['y2']
            out.update(track_id=past['track_id'],previous_iou=overlap,
                       bottom_dx_px=dx,bottom_dy_px=dy,bottom_step_px=math.hypot(dx,dy))
        else:
            out.update(track_id=next_id,previous_iou='',bottom_dx_px='',bottom_dy_px='',bottom_step_px='')
            next_id+=1
        result.append(out)
    return result,next_id


def zero_runs(rows):
    result=[]
    index=0
    while index<len(rows):
        if rows[index]['detections']:
            index+=1;continue
        start=index
        while index+1<len(rows) and not rows[index+1]['detections']:
            index+=1
        end=index
        result.append(dict(session=rows[start]['session'],start_frame=rows[start]['frame'],
            end_frame=rows[end]['frame'],zero_frames=end-start+1,start_time_sec=rows[start]['time_sec'],
            end_time_sec=rows[end]['time_sec'],sample_span_sec=rows[end]['time_sec']-rows[start]['time_sec'],
            bounded_by_detection=int(start>0 and end+1<len(rows)),
            truth='unknown: no per-frame visibility labels; NOT an automatic FN interval'))
        index+=1
    return result


def stats(values):
    values=sorted(values)
    if not values:
        return dict(count=0,mean=None,p50=None,p95=None,max=None)
    return dict(count=len(values),mean=statistics.mean(values),p50=statistics.median(values),
                p95=values[math.ceil(.95*len(values))-1],max=max(values))


def run_video(model,args,sessions,inputs):
    anchor_images,anchor_truths=inputs
    anchors={}
    for image in anchor_images:
        key=(image['source_raw_sha256'],int(image['frame']))
        if key in anchors:
            raise ValueError('duplicate video anchor')
        anchors[key]=image
    all_frames,all_gaps,track_rows,anchor_predictions,processed_anchors=[],[],[],[],[]
    anchor_pixels=[]
    reports=[]
    with (args.output_dir/'predictions.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=PRED_FIELDS,lineterminator='\n');writer.writeheader()
        for session in sessions:
            print(f"[INFO] Video {session['session']}: {len(session['rows'])} frames",flush=True)
            capture=cv2.VideoCapture(str(session['root']/'raw.avi'))
            if not capture.isOpened():
                raise ValueError('cannot open raw video')
            previous,next_id,frames,tracks=[],1,[],{}
            started=time.perf_counter()
            try:
                for position,record in enumerate(session['rows']):
                    tick=time.perf_counter()
                    ok,frame=capture.read()
                    decoded=time.perf_counter()
                    if not ok or frame.shape!=(session['height'],session['width'],3):
                        raise ValueError('raw video shorter than CSV or geometry differs')
                    image=dict(image=f"{session['session']}/{record['frame']}",
                               width=session['width'],height=session['height'])
                    before=time.perf_counter()
                    results=model.predict(source=frame,**prediction_kwargs(args))
                    if len(results)!=1:
                        raise ValueError('one decoded frame must yield one detector result')
                    predictions=extract_predictions(results[0],image)
                    if len(predictions)>args.max_det or any(row['confidence']<args.confidence-1e-7 for row in predictions):
                        raise ValueError('prediction confidence/max_det contract violated')
                    after=time.perf_counter()
                    current,next_id=associate(previous,predictions,session['width'],next_id,args.track_iou)
                    when=float(record['time_sec']);number=int(record['frame'])
                    steps=[row['bottom_step_px'] for row in current if row['bottom_step_px']!='']
                    for row in current:
                        writer.writerow({field:(session['session'] if field=='session' else number if field=='frame'
                            else when if field=='time_sec' else row[field]) for field in PRED_FIELDS})
                        key=row['track_id']
                        if key not in tracks:
                            tracks[key]=dict(session=session['session'],track_id=key,image_half=row['image_half'],
                                first_frame=number,last_frame=number,frames=0,
                                first_time_sec=when,last_time_sec=when,
                                identity_scope='consecutive-frame IoU association only; no semantic identity guarantee')
                        tracks[key].update(last_frame=number,last_time_sec=when,frames=tracks[key]['frames']+1)
                    speed=results[0].speed
                    if not all(isinstance(speed[key],(int,float)) and math.isfinite(speed[key]) and speed[key]>=0
                               for key in ('preprocess','inference','postprocess')):
                        raise ValueError('invalid framework timing')
                    entry=dict(session=session['session'],frame=number,time_sec=when,detections=len(current),
                        new_tracks=sum(row['previous_iou']=='' for row in current),continued_tracks=len(steps),
                        bottom_step_median_px=statistics.median(steps) if steps else '',
                        bottom_step_max_px=max(steps) if steps else '',decode_ms=1000*(decoded-tick),
                        predict_export_ms=1000*(after-before),preprocess_ms=speed['preprocess'],
                        inference_ms=speed['inference'],postprocess_ms=speed['postprocess'],
                        pipeline_ms=1000*(time.perf_counter()-tick),first_call=int(position==0))
                    frames.append(entry)
                    anchor=anchors.get((session['hashes']['raw.avi'],number))
                    if anchor:
                        processed_anchors.append(anchor)
                        anchor_predictions.extend(dict(row,image=anchor['image']) for row in predictions)
                        pixel_hash=hashlib.sha256(frame.tobytes()).hexdigest()
                        anchor_pixels.append(dict(image=anchor['image'],session=session['session'],frame=number,
                            decoded_bgr_sha256=pixel_hash,recorded_png_pixels_sha256=anchor['decoded_bgr_sha256'],
                            pixels_equal=int(pixel_hash==anchor['decoded_bgr_sha256'])))
                    previous=current
                    if number%300==0 or number==len(session['rows']):
                        print(f"[INFO] {session['session']}: {number}/{len(session['rows'])}",flush=True)
                if capture.read()[0]:
                    raise ValueError('raw video longer than CSV')
            finally:
                capture.release()
            elapsed=time.perf_counter()-started
            gaps=zero_runs(frames)
            post_first=[row for row in frames if not row['first_call']]
            reports.append(dict(session=session['session'],frames=len(frames),
                detection_frames=sum(row['detections']>0 for row in frames),
                multi_detection_frames=sum(row['detections']>1 for row in frames),tracks=len(tracks),
                zero_runs=len(gaps),internal_zero_runs=sum(row['bounded_by_detection'] for row in gaps),
                max_zero_sample_span_sec=max((row['sample_span_sec'] for row in gaps),default=0),
                wall_time_sec=elapsed,sequential_processing_fps=len(frames)/elapsed,
                post_first_pipeline_ms=stats([row['pipeline_ms'] for row in post_first]),
                post_first_inference_ms=stats([row['inference_ms'] for row in post_first]),
                bottom_step_max_per_frame_px=stats([row['bottom_step_max_px'] for row in frames if row['bottom_step_max_px']!=''])))
            all_frames.extend(frames);all_gaps.extend(gaps);track_rows.extend(tracks.values())
    write_csv(args.output_dir/'frames.csv',all_frames,FRAME_FIELDS)
    write_csv(args.output_dir/'zero_detection_runs.csv',all_gaps,
              ('session','start_frame','end_frame','zero_frames','start_time_sec','end_time_sec','sample_span_sec','bounded_by_detection','truth'))
    write_csv(args.output_dir/'tracks.csv',track_rows,
              ('session','track_id','image_half','first_frame','last_frame','frames','first_time_sec','last_time_sec','identity_scope'))
    write_csv(args.output_dir/'anchor_pixels.csv',anchor_pixels,
              ('image','session','frame','decoded_bgr_sha256','recorded_png_pixels_sha256','pixels_equal'))
    processed_names={row['image'] for row in processed_anchors}
    truths=[row for row in anchor_truths if row['image'] in processed_names]
    anchor_summary=[]
    if processed_anchors:
        config=dict(confidence_thresholds=[args.confidence],match_iou=.5)
        per_image,matches,anchor_summary,strata=aggregate(processed_anchors,truths,anchor_predictions,config)
        write_csv(args.output_dir/'anchor_per_image.csv',per_image)
        write_csv(args.output_dir/'anchor_matches.csv',matches)
        write_csv(args.output_dir/'anchor_stratum_recall.csv',strata)
    report=dict(status='COMPLETED_OFFLINE_VIDEO_NOT_DEPLOYMENT_APPROVAL',confidence=args.confidence,
        track_iou=args.track_iou,total_frames=len(all_frames),sessions=reports,
        annotated_anchor_images=len(processed_anchors),annotated_anchor_gt=len(truths),anchor_summary=anchor_summary,
        anchor_pixel_mismatches=sum(not row['pixels_equal'] for row in anchor_pixels),
        max_det_reached_frames=sum(row['detections']==args.max_det for row in all_frames),
        physical_output=False,independent_test_approval=False,
        limitations=['Zero detection intervals are not automatically false negatives without visibility labels.',
                     'Bottom-coordinate changes include real object/camera motion, not pure measurement jitter.',
                     'Consecutive IoU track fragments do not establish physical object identity.',
                     'Sequential offline throughput is not live camera/GUI/ROS/FFB latency.',
                     'Dataset-anchor GT remains sparse; all-frame precision/recall is not measured.'])
    (args.output_dir/'video_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=build_parser()
    try:
        args=validated_args(parser.parse_args())
        sessions=load_plan(args.plan,args.output_dir,args.weights)
        if args.dry_run:
            print(json.dumps(dict(status='PREVIEW_ONLY_NOT_GPU_VERIFIED',kwargs=prediction_kwargs(args),
                sessions=[dict(session=s['session'],frames=len(s['rows'])) for s in sessions]),indent=2));return
        dataset_check=validate(args.dataset,require_test=args.diagnostic_split=='test') if args.dataset else None
        inputs=prepare_inputs(args.dataset,args.diagnostic_split,args.object_attributes) if args.dataset else ([],[])
        import torch
        gpu=check_cuda(torch,args.device)
        args.output_dir.mkdir(parents=True,exist_ok=False)
        (args.output_dir/'ultralytics_config/Ultralytics').mkdir(parents=True)
        os.environ['YOLO_CONFIG_DIR']=str(args.output_dir/'ultralytics_config')
        from ultralytics import YOLO,settings
        for key in ('wandb','comet','clearml','mlflow','neptune','hub'):
            if key in settings: settings.update({key:False})
        model=YOLO(str(args.weights))
        if model.names!={0:'traffic_cone'}:
            raise ValueError('trained single-class traffic_cone detector required')
        provenance=dict(status='STARTED_OFFLINE_VIDEO_NOT_APPROVAL',gpu=gpu,
            weights_sha256=sha256(args.weights),plan_sha256=sha256(args.plan),dataset_check=dataset_check,
            object_attributes_sha256=sha256(args.object_attributes) if args.object_attributes else None,
            prediction_kwargs=prediction_kwargs(args),track_iou=args.track_iou,
            versions={name:importlib.metadata.version(name) for name in ('torch','torchvision','ultralytics','opencv-python')},
            source_sessions=[dict(session=s['session'],path=str(s['root']),frames=len(s['rows']),
                                  files_sha256=s['hashes'],note=s['note']) for s in sessions],
            code_sha256={name:sha256(Path(__file__).with_name(name)) for name in
                         ('run_cone_video.py','cone_detection_diagnostics.py','run_cone_yolo.py')},
            physical_output=False,training_performed=False)
        path=args.output_dir/'provenance.json'
        path.write_text(json.dumps(provenance,indent=2)+'\n')
        (args.output_dir/'environment_freeze.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True))
        report=run_video(model,args,sessions,inputs)
        provenance['status']=report['status'];path.write_text(json.dumps(provenance,indent=2)+'\n')
        print(f"[INFO] Video analysis complete: {args.output_dir/'video_summary.json'}")
    except (ValueError,OSError,KeyError,ImportError) as error:
        parser.exit(2,f'[ERROR] {error}\n')


if __name__=='__main__':
    main()
