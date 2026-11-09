#!/usr/bin/env python3
"""Human image-coordinate review only. No image export, model loading, ROS or FFB.

Clicks are native decoded-image coordinates, not surveyed physical points.
Immutable per-item JSON records bind to a queue and exact PNG bytes. Ambiguous
observations may be explicitly withheld. Nothing is adopted by the live path.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

import cv2
import numpy as np

from cone_distance_core import ROOT, digest, load_config
from derive_fixed_floor_live_bundle import source
from floor_reference_pose import planar_floor_pose_candidates

QUEUE_SCHEMA='physical_reference_review_queue_v1'
DECISION_SCHEMA='physical_reference_visual_decision_v1'
FLAGS=('physical_metric_verified','floor_contact_verified','usable_for_ffb','controlling_distance')


def read_json(path):
    def reject(value):raise ValueError('nonfinite JSON: '+value)
    return json.loads(Path(path).read_text(),parse_constant=reject)


def dump_new(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('output symlinks forbidden')
    payload=json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    with path.open('x') as stream:stream.write(payload)


def item_image(item):
    rel=Path(item['image'])
    if rel.is_absolute() or '..' in rel.parts:raise ValueError('repository-relative image path required')
    path=ROOT/rel
    if path.is_symlink():raise ValueError('image symlinks forbidden')
    path.resolve().relative_to(ROOT)
    loaded=source(path)
    if (loaded['session'],loaded['frame'],loaded['sha256'])!=(item['session'],item['frame'],item['sha256']):
        raise ValueError('exact saved session/frame/image hash required')
    return loaded


def validate_queue(queue,verify_images=True):
    if not isinstance(queue,dict) or queue.get('schema')!=QUEUE_SCHEMA or any(queue.get(k) is not False for k in FLAGS):
        raise ValueError('non-authoritative review queue required')
    items=queue.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=32:raise ValueError('1..32 review items required')
    seen=set()
    for item in items:
        if (not isinstance(item,dict) or re.fullmatch(r'[a-z0-9_]{1,80}',str(item.get('id',''))) is None
                or item['id'] in seen or item.get('kind') not in ('paper','cone_near_edge')):
            raise ValueError('unique safe item id and supported kind required')
        seen.add(item['id'])
        if item.get('kind')=='paper' and item.get('paper_sides_mm')!=[296,210]:
            raise ValueError('explicit reported paper dimensions required')
        if verify_images:item_image(item)
    return queue


def prepare(spec_path,output):
    queue=validate_queue(read_json(spec_path))
    output=Path(output)
    if output.exists():raise ValueError('new review directory required')
    output.mkdir(parents=True,exist_ok=False)
    dump_new(output/'queue.json',queue)
    (output/'decisions').mkdir()
    return dict(items=len(queue['items']),queue_sha256=digest(output/'queue.json'),human_decisions=0)


def checked_points(points,kind):
    size=4 if kind=='paper' else 2
    if not isinstance(points,list) or len(points)!=size:raise ValueError(f'{size} native points required')
    for point in points:
        if (not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point)
                or not 0<=point[0]<640 or not 0<=point[1]<720):
            raise ValueError('finite native front-lens points required')
    a=np.asarray(points,float)
    if len(np.unique(a,axis=0))!=size:raise ValueError('distinct points required')
    if kind=='paper':
        cross=np.cross(np.roll(a,-1,axis=0)-a,np.roll(a,-2,axis=0)-np.roll(a,-1,axis=0))
        if not np.all(cross>0):raise ValueError('paper corners must be convex clockwise TL/TR/BR/BL in image coordinates')
    elif a[0,0]>=a[1,0]:raise ValueError('cone edge endpoints must be left then right')
    return points


def validate_decision(record,item,queue_sha):
    if (not isinstance(record,dict) or record.get('schema')!=DECISION_SCHEMA
            or record.get('queue_sha256')!=queue_sha or record.get('item_id')!=item['id']
            or record.get('image_sha256')!=item['sha256'] or record.get('session')!=item['session']
            or record.get('frame')!=item['frame'] or record.get('kind')!=item['kind']
            or any(record.get(k) is not False for k in FLAGS)):
        raise ValueError('decision identity/hash/authority mismatch')
    if (type(record.get('reviewer')) is not str or not record['reviewer'].strip()
            or type(record.get('note')) is not str or not record['note'].strip()
            or record.get('confirmation_method')!='explicit_manual_key'
            or record.get('independently_surveyed_ground_truth') is not False):
        raise ValueError('explicit visual-review provenance required; not surveyed ground truth')
    if record.get('status')=='reviewed':checked_points(record.get('points_native_xy'),item['kind'])
    elif record.get('status')=='unclear':
        if record.get('points_native_xy')!=[]:raise ValueError('unclear may not retain guessed points')
    else:raise ValueError('reviewed or unclear decision required')
    if record.get('side_assignment') not in ('long_01','short_01','unknown'):
        raise ValueError('explicit dimension assignment or unknown required')
    if item['kind']!='paper' and record['side_assignment']!='unknown':raise ValueError('side assignment belongs to paper only')
    if record['status']=='unclear' and record['side_assignment']!='unknown':raise ValueError('unclear dimensions must remain unknown')
    return record


def save_decision(folder,queue_sha,item,points,status,reviewer,side_assignment='unknown'):
    folder=Path(folder)
    if folder.is_symlink():raise ValueError('decision folder symlinks forbidden')
    record=dict(schema=DECISION_SCHEMA,queue_sha256=queue_sha,item_id=item['id'],kind=item['kind'],
        session=item['session'],frame=item['frame'],image_sha256=item['sha256'],
        status=status,points_native_xy=points if status=='reviewed' else [],
        side_assignment=side_assignment if status=='reviewed' else 'unknown',reviewer=reviewer,
        confirmation_method='explicit_manual_key',independently_surveyed_ground_truth=False,
        note='human selected visible image features; physical correspondence unverified' if status=='reviewed' else
            'human explicitly could not resolve the requested physical feature in this saved image',
        **{k:False for k in FLAGS})
    validate_decision(record,item,queue_sha)
    item_image(item)  # Never accept clicks for changed image bytes.
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(item['id']+'.json')
    if path.exists():
        if path.is_symlink() or read_json(path)!=record:raise ValueError('existing decision differs; use a new decisions directory')
    else:dump_new(path,record)
    return record


def load_decisions(folder,queue,queue_sha):
    folder=Path(folder);known={i['id']:i for i in queue['items']};found={}
    if folder.is_symlink():raise ValueError('decision folder symlinks forbidden')
    for path in sorted(folder.glob('*.json')):
        if path.is_symlink() or path.stem not in known:raise ValueError('unknown/symlink decision file')
        record=validate_decision(read_json(path),known[path.stem],queue_sha)
        found[path.stem]=record
    return found


def review(queue_path,decisions_dir,reviewer,backend='TkAgg'):
    # GUI is imported only after validating the immutable queue and sources.
    if not reviewer.strip():raise ValueError('reviewer label required')
    queue=validate_queue(read_json(queue_path));hashed=digest(queue_path)
    done=load_decisions(decisions_dir,queue,hashed)
    import matplotlib
    matplotlib.use(backend,force=True)
    matplotlib.rcParams['toolbar']='None'
    matplotlib.rcParams['keymap.save']=[]
    from matplotlib import pyplot as plt
    if 'agg'==str(matplotlib.get_backend()).lower():raise ValueError('interactive GUI required; no display or forced Agg backend')
    print('Scroll: zoom. H: whole frame. Left click: point. Backspace: undo. R: reset.\n'
          'Y: save reviewed. U: save unclear. N: skip. Q: quit.\n'
          'Paper: white-paper TL,TR,BR,BL (NOT black board or grid). W: edge01=296mm; D: edge01=210mm.\n'
          'Leave dimensions UNKNOWN if not sure. Cone: visible NEAR BASE EDGE left endpoint, right endpoint.\n'
          'No distance/algorithm points are shown. On-screen markers only; no image is saved.',flush=True)
    for item in queue['items']:
        if item['id'] in done:continue
        loaded=item_image(item);original=loaded['image'];before=original.copy()
        fig,ax=plt.subplots(figsize=(12,8));fig.subplots_adjust(bottom=.13,top=.9)
        ax.imshow(cv2.cvtColor(original,cv2.COLOR_BGR2RGB));ax.set_xlim(-.5,1279.5);ax.set_ylim(719.5,-.5)
        ax.set_xlabel('Native decoded-image x/y coordinates. NO metric or contact approval.')
        points=[];state=dict(side='unknown',quit=False,message='')
        markers,=ax.plot([],[],'c+',markersize=9)
        help_text=fig.text(.02,.02,'',fontsize=10)
        need=4 if item['kind']=='paper' else 2
        prompt='WHITE PAPER: TL -> TR -> BR -> BL' if need==4 else 'NEAR BASE EDGE: LEFT endpoint -> RIGHT endpoint'
        def update():
            markers.set_data([p[0] for p in points],[p[1] for p in points])
            ax.set_title(item['id']+' | '+prompt+' | '+str(len(points))+'/'+str(need))
            help_text.set_text(f'Scroll=zoom H=whole frame | Y=confirm U=unclear N=skip Q=quit | Backspace=undo R=reset | paper side={state["side"]}\n'
                f'Points={points} | {state["message"]}')
            fig.canvas.draw_idle()
        def clicked(event):
            toolbar=getattr(fig.canvas.manager,'toolbar',None)
            if event.inaxes is not ax or event.button!=1 or (toolbar and toolbar.mode):return
            if event.xdata is None or event.ydata is None or not 0<=event.xdata<640 or not 0<=event.ydata<720:return
            if len(points)<need:points.append([round(float(event.xdata),3),round(float(event.ydata),3)])
            update()
        def scrolled(event):
            if event.inaxes is not ax or event.xdata is None or event.ydata is None:return
            scale=.8 if event.button=='up' else 1.25
            for value,getter,setter in [(event.xdata,ax.get_xlim,ax.set_xlim),(event.ydata,ax.get_ylim,ax.set_ylim)]:
                a,b=getter();setter(value+(a-value)*scale,value+(b-value)*scale)
            fig.canvas.draw_idle()
        def pressed(event):
            key=(event.key or '').lower()
            if key in ('backspace','delete') and points:points.pop()
            elif key=='r':points.clear()
            elif key=='h':ax.set_xlim(-.5,1279.5);ax.set_ylim(719.5,-.5)
            elif key in ('w','d') and need==4:state['side']='long_01' if key=='w' else 'short_01'
            elif key=='a' and need==4:state['side']='unknown'
            elif key=='q':state['quit']=True;plt.close(fig);return
            elif key=='n':plt.close(fig);return
            elif key in ('y','u'):
                try:
                    record=save_decision(decisions_dir,hashed,item,points.copy(),'reviewed' if key=='y' else 'unclear',reviewer,state['side'])
                    done[item['id']]=record;print(item['id']+': '+record['status'],flush=True)
                    plt.close(fig);return
                except (ValueError,OSError) as exc:state['message']=str(exc)
            update()
        fig.canvas.mpl_connect('button_press_event',clicked)
        fig.canvas.mpl_connect('scroll_event',scrolled)
        fig.canvas.mpl_connect('key_press_event',pressed)
        update();plt.show(block=True)
        if not np.array_equal(before,original) or digest(loaded['path'])!=item['sha256']:raise ValueError('source image changed')
        if state['quit']:break
    return dict(decisions=len(done),pending=len(queue['items'])-len(done),**{k:False for k in FLAGS})


def report(queue_path,decisions_dir,output):
    queue=validate_queue(read_json(queue_path));sha=digest(queue_path)
    decisions=load_decisions(decisions_dir,queue,sha)
    _,camera,_,_=load_config();items=[]
    for item in queue['items']:
        d=decisions.get(item['id']);entry=dict(item_id=item['id'],kind=item['kind'],status=d['status'] if d else 'pending')
        if d and d['status']=='reviewed' and item['kind']=='paper':
            assignments=[('long_01',296,210),('short_01',210,296)]
            if d['side_assignment']!='unknown':assignments=[a for a in assignments if a[0]==d['side_assignment']]
            hypotheses=[]
            for name,w,h in assignments:
                world=np.array([[0,0,0],[w,0,0],[w,h,0],[0,h,0]],float)/1000
                pose=planar_floor_pose_candidates(d['points_native_xy'],world,camera)
                hypotheses.append(dict(side_assignment=name,pose=pose,
                    conditional_floor_heights_mm=[abs(p['camera_height_above_floor_m'])*1000+15 for p in pose['candidates']],
                    carried_board_thickness_mm=15,reported_external_height_mm=590))
            entry['unselected_paper_hypotheses']=hypotheses
        if d and d['status']=='reviewed' and item['kind']=='cone_near_edge':
            entry.update(observed_near_edge_endpoints_native_xy=d['points_native_xy'],
                physical_midpoint_not_inferred=True,straight_image_chord_not_verified_fisheye_edge=True)
        items.append(entry)
    output=Path(output)
    if output.exists():raise ValueError('new report directory required')
    output.mkdir(parents=True,exist_ok=False)
    result=dict(schema='physical_reference_visual_summary_v1',queue_sha256=sha,items=items,
        counts=dict(Counter(i['status'] for i in items)),selected_model=None,
        note='Pending/unclear are not approved. Human clicks are visual claims, not surveyed contact/metric ground truth.',
        **{k:False for k in FLAGS})
    dump_new(output/'summary.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare');a.add_argument('--spec',type=Path,required=True);a.add_argument('--output-dir',type=Path,required=True)
    for mode in ('check','review','report'):
        a=sub.add_parser(mode);a.add_argument('--queue',type=Path,required=True)
        if mode in ('review','report'):a.add_argument('--decisions-dir',type=Path,required=True)
        if mode=='review':a.add_argument('--reviewer',required=True)
        if mode=='review':a.add_argument('--backend',choices=['TkAgg','QtAgg'],default='TkAgg')
        if mode=='report':a.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    try:
        if args.mode=='prepare':result=prepare(args.spec,args.output_dir)
        elif args.mode=='check':
            queue=validate_queue(read_json(args.queue));result=dict(items=len(queue['items']),queue_sha256=digest(args.queue))
        elif args.mode=='review':result=review(args.queue,args.decisions_dir,args.reviewer,args.backend)
        else:result=report(args.queue,args.decisions_dir,args.output_dir)
        print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False));return 0
    except (ValueError,OSError,KeyError,ImportError,RuntimeError,cv2.error) as exc:
        print('[ERROR] '+str(exc));return 1


if __name__=='__main__':raise SystemExit(main())
