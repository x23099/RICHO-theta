"""CUDA YOLO on saved native PNGs; NO camera, RTC, ROS, UI or vehicle control.

No cached-box/CPU inference fallback. --validate-only checks data without CUDA.
Timing is predictor/primary wall time on preloaded images, NOT live latency.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_distance_core import DEFAULT_CONFIG,load_config
from cone_distance_worker import YoloConePredictor
from cone_motion_range import FLAGS,MotionRangeEngine,load_motion_profile,revoke_range
from cone_upper_support_candidate import observe_upper_completion
from driver_guarded_comparison import GuardedComparisonWorker,comparison_path
from manage_guarded_comparison import issue
from report_driver_motion_logs import distribution
from run_guarded_recording_comparison import hash_regular
from theta_rtc_frames import NativeFrame
from verify_driver_withheld_evidence import read_regular,parse_json,verify

FRAMES=[6861,14203,14267,14297,14329,14382,14604,14922]
PRIMARY_FIELDS=('distance_available','horizontal_camera_foot_range_m','reason','support_pixel',
    'models','front_candidates','support_observation','selected_detector_boxes','primary_model',
    'profile_sha256',*FLAGS)


def digest_bytes(data):return hashlib.sha256(data).hexdigest()


def signature(value):
    return digest_bytes(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())


def detector_values(boxes):
    # extract_predictions adds the new replay session/frame in `image`.
    # Keep the full boxes in raw logs; omit ONLY that provenance for pairing.
    return [{key:value for key,value in box.items() if key!='image'} for box in boxes]


def primary_signature(result):
    value={key:result.get(key) for key in PRIMARY_FIELDS}
    if value['selected_detector_boxes'] is not None:
        value['selected_detector_boxes']=detector_values(value['selected_detector_boxes'])
    return signature(value)


def load_inputs(source,evidence,config=DEFAULT_CONFIG):
    import cv2
    import numpy as np
    source,evidence=Path(source).resolve(),Path(evidence).resolve()
    settings,camera,_,_=load_config(config)
    verified=verify(evidence,source/'motion_distance_frames.jsonl')
    if verified['verified_pairs']!=8 or not verified['capture_shutdown_complete']:
        raise ValueError('eight complete source-verified native pairs required')
    reference_path=ROOT/'Experimental_results/2026-11-10/self_body_boundary_shadow_r01/reference.json'
    reference=parse_json(read_regular(reference_path,32768))
    paths={source/'motion_distance_frames.jsonl':512*1024*1024,
        source/'motion_engine_summary.json':256*1024,source/'motion_profile_used.json':256*1024,
        evidence/'evidence_index.jsonl':256*1024,evidence/'evidence_status.json':16384,
        reference_path:32768,Path(config).absolute():512*1024}
    paths.update({ROOT/settings[key+'_candidate']:512*1024 for key in ('camera','floor')})
    hashes={str(path):hash_regular(path,cap) for path,cap in paths.items()}
    profile,profile_sha=load_motion_profile(source/'motion_profile_used.json',settings)
    metadata=parse_json(read_regular(source/'motion_engine_summary.json',256*1024))
    if metadata['profile_sha256']!=profile_sha or metadata['config_sha256']!=hash_regular(Path(config),512*1024):
        raise ValueError('source profile/config mismatch')
    index=[parse_json(line) for line in read_regular(evidence/'evidence_index.jsonl',256*1024).splitlines()]
    index.sort(key=lambda item:item['frame'])
    if [item['frame'] for item in index]!=FRAMES:
        raise ValueError('expected eight historical sample identities')
    jobs=[]
    for item in index:
        if item['session']!=reference['session']:
            raise ValueError('historical session/reference mismatch')
        png_path,sidecar_path=evidence/item['image_file'],evidence/item['sidecar_file']
        png=read_regular(png_path,3*1280*720+65536)
        sidecar=read_regular(sidecar_path,1024*1024+16384)
        if digest_bytes(png)!=item['png_sha256'] or digest_bytes(sidecar)!=item['sidecar_sha256']:
            raise ValueError('verified source changed')
        old=parse_json(sidecar)
        image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
        if (image is None or image.shape!=(720,1280,3)
                or digest_bytes(image.tobytes())!=old['decoded_bgr_sha256']):
            raise ValueError('native source pixels mismatch')
        image.flags.writeable=False
        hashes[str(png_path)],hashes[str(sidecar_path)]=item['png_sha256'],item['sidecar_sha256']
        jobs.append(dict(image=image,session=item['session'],frame=item['frame'],
            pixel_sha256=old['decoded_bgr_sha256'],png_sha256=item['png_sha256'],
            historical_measurement=old['measurement']))
    ref_job=next(job for job in jobs if job['frame']==reference['source_frame'])
    if ref_job['png_sha256']!=reference['source_png_sha256']:
        raise ValueError('historical reference image hash mismatch')
    return dict(settings=settings,camera=camera,profile=profile,profile_sha=profile_sha,
        jobs=jobs,reference=reference,input_sha256=hashes,verification=verified)


class Budget:
    def __init__(self,maximum=64*1024*1024):self.maximum,self.used=maximum,0
    def write(self,stream,value):
        data=json.dumps(value,allow_nan=False)+'\n';size=len(data.encode())
        if size>1024*1024 or self.used+size>self.maximum:
            raise ValueError('benchmark log budget exhausted')
        stream.write(data);stream.flush();self.used+=size


def wait_for(predicate,worker,deadline):
    until=min(deadline,time.monotonic()+5.)
    while True:
        if worker.error:raise RuntimeError(worker.error)
        if predicate():return
        if time.monotonic()>=until:raise TimeoutError('benchmark setup/finish wait expired')
        time.sleep(.005)


def measure(engine,predictor,job,session,sequence,execution_kind):
    source=time.monotonic()
    frame=NativeFrame(session,sequence,sequence/30.,source,job['image'])
    boxes=predictor(frame)  # NEW prediction each call; saved boxes never enter here.
    inferred=time.monotonic()
    result=engine.measure(frame,boxes,inferred)
    finished=time.monotonic()
    result.update(completed_time_sec=finished,frame_age_ms=1000*(finished-source),
        predict_ms=1000*(inferred-source),support_geometry_ms=1000*(finished-inferred),
        inference_source='cuda_yolo_on_saved_native_png_NOT_live_camera' if execution_kind=='actual_cuda' else 'synthetic_test_NOT_CUDA',
        input_source='preloaded_historical_native_png_NOT_camera_or_RTC',
        source_time_kind='synthetic_monotonic_arrival_at_predictor_call',
        original_session=job['session'],original_frame=job['frame'],
        input_pixel_sha256=job['pixel_sha256'],raw_detector_boxes=boxes)
    if finished-source>engine.settings['frame_max_age_sec']:
        revoke_range(result,'frame_processing_too_old')
    return frame,result


def benchmark(data,predictor,output,*,cycles=20,fps=30.,warmup=8,max_duration=180.,execution_kind='synthetic_test'):
    """Pure orchestration accepts a test predictor; actual CLI always uses CUDA."""
    if (type(cycles) is not int or not 1<=cycles<=100 or type(warmup) is not int or not 1<=warmup<=64
            or type(fps) not in (int,float) or not 1<=fps<=60
            or type(max_duration) not in (int,float) or not 1<=max_duration<=600
            or execution_kind not in ('synthetic_test','actual_cuda')):
        raise ValueError('bounded benchmark options required')
    output=Path(output);jobs=data['jobs'];deadline=time.monotonic()+max_duration
    budget=Budget();warmup_rows=[]
    with (output/'warmup.jsonl').open('x') as stream:
        for n in range(warmup):
            if time.monotonic()>deadline:raise TimeoutError('benchmark duration exceeded')
            job=jobs[n%len(jobs)];started=time.monotonic()
            predictor(NativeFrame(uuid.uuid4().hex,n+1,n/30.,started,job['image']))
            row=dict(call=n+1,original_frame=job['frame'],predict_ms=1000*(time.monotonic()-started),
                     excluded_from_measured_distributions=True)
            warmup_rows.append(row);budget.write(stream,row)
    blocks=[]
    ref_job=next(job for job in jobs if job['frame']==data['reference']['source_frame'])
    for block_id,enabled in enumerate((False,True,True,False)):
        if time.monotonic()>deadline:raise TimeoutError('benchmark duration exceeded')
        directory=output/f'block_{block_id:02d}_{"on" if enabled else "off"}'
        directory.mkdir()
        engine=MotionRangeEngine(data['settings'],data['camera'],data['profile'],data['profile_sha'],
            acknowledged=True,target_roi=[270,0,350,720],observer=observe_upper_completion)
        session=uuid.uuid4().hex;worker=None;records=[];shutdown=None;last_offered=None
        try:
            if enabled:
                worker=GuardedComparisonWorker(directory/'comparison',data['settings'],data['camera'],
                    data['profile'],data['profile_sha'],target_roi=[270,0,350,720])
                state_path=directory/'comparison/comparison_status.json'
                status=lambda:parse_json(read_regular(state_path,16384))
                wait_for(lambda:state_path.exists(),worker,deadline)
                issue(worker.directory,'pin')
                wait_for(lambda:status()['state']=='pin_pending',worker,deadline)
            frame,result=measure(engine,predictor,ref_job,session,1,execution_kind)
            with (directory/'setup.jsonl').open('x') as setup:
                budget.write(setup,result)
            if worker:
                if not worker.offer(frame,json.dumps(result,allow_nan=False)+'\n'):
                    raise ValueError('reference setup frame was not accepted')
                wait_for(lambda:worker.processed>=1 and status()['state']=='pinned',worker,deadline)
                pin=status()['pin']
                if pin['decoded_bgr_sha256']!=ref_job['pixel_sha256']:
                    raise ValueError('replay pin differs from original pixels')
                reference=copy.deepcopy(data['reference'])
                reference.update(session=session,source_frame=1,source_png_sha256=pin['png_sha256'],
                    offline_replay_binding_NOT_live_mount_evidence=True)
                (worker.directory/'reference.json').write_text(json.dumps(reference)+'\n')
                issue(worker.directory,'load')
                wait_for(lambda:status()['state'] in ('active','load_rejected'),worker,deadline)
                if status()['state']!='active':raise ValueError('same-pixel replay reference load rejected: '+str(status()))
            next_start=time.monotonic();previous_source=None
            block_started=time.monotonic()
            with (directory/'primary_frames.jsonl').open('x') as log:
                for n in range(cycles*len(jobs)):
                    if time.monotonic()>deadline:raise TimeoutError('benchmark duration exceeded')
                    delay=next_start-time.monotonic()
                    if delay>0:time.sleep(delay)
                    job=jobs[n%len(jobs)]
                    frame,result=measure(engine,predictor,job,session,n+2,execution_kind)
                    line=json.dumps(result,allow_nan=False)+'\n'
                    budget.write(log,result)
                    tap_started=time.monotonic()
                    accepted=worker.offer(frame,line) if worker else None
                    tap_ms=1000*(time.monotonic()-tap_started) if worker else 0.
                    if accepted:last_offered=frame.sequence
                    records.append(dict(block=block_id,comparison_enabled=enabled,
                        ordinal=n,cycle=n//len(jobs),original_frame=job['frame'],replay_frame=frame.sequence,
                        primary_signature=primary_signature(result),
                        detector_signature=signature(detector_values(result['raw_detector_boxes'])),
                        distance_available=result['distance_available'],range_m=result['horizontal_camera_foot_range_m'],
                        reason=result['reason'],predict_ms=result['predict_ms'],
                        primary_ms=result['frame_age_ms'],support_ms=result['support_geometry_ms'],
                        comparison_tap_ms=tap_ms,
                        primary_log_and_tap_ms=1000*(time.monotonic()-frame.received_at),
                        start_interval_ms=1000*(frame.received_at-previous_source) if previous_source is not None else None,
                        period_overrun=result['frame_age_ms']>1000/fps,comparison_offer_accepted=accepted))
                    previous_source=frame.received_at
                    next_start=frame.received_at+1./fps  # No catch-up burst/backlog.
                    if n%max(1,len(jobs)*5)==0:
                        print(f'block {block_id+1}/4 comparison={enabled} {n+1}/{cycles*len(jobs)}',flush=True)
            block_finished=time.monotonic()
            if worker:
                # No per-frame waiting during measurement. Drain only at block end.
                if last_offered is None:raise ValueError('no measured frame offered to comparison')
                wait_for(lambda:worker.latest is not None and worker.latest['frame']==last_offered,worker,deadline)
        finally:
            if worker:shutdown=worker.close(.25)
        comparisons=[];final=None
        if worker:
            if not shutdown['shutdown_complete']:raise ValueError('comparison shutdown incomplete: '+str(shutdown))
            final=parse_json(read_regular(worker.directory/'comparison_status.json',16384))
            comparisons=[parse_json(line) for line in read_regular(worker.directory/'comparison_frames.jsonl',64*1024*1024).splitlines()]
            if final['error'] is not None or not final['shutdown_complete']:raise ValueError('comparison writer failed')
        for job in jobs:
            if digest_bytes(job['image'].tobytes())!=job['pixel_sha256']:
                raise ValueError('predictor/comparison modified source pixels')
        blocks.append(dict(id=block_id,comparison_enabled=enabled,session=session,records=records,
            measured_wall_sec=block_finished-block_started,measured_frames=len(records),
            reason_counts=dict(Counter(r['reason'] for r in records)),
            predict_ms=distribution([r['predict_ms'] for r in records]),
            primary_ms=distribution([r['primary_ms'] for r in records]),
            period_overruns=sum(r['period_overrun'] for r in records),
            comparison_rows=len(comparisons),comparison_numeric_rows=sum(r['comparison_distance_available'] for r in comparisons),
            comparison_reference_rows=sum(r['reference_scope_verified'] for r in comparisons),
            comparison_reason_counts=dict(Counter(r['reason'] for r in comparisons)),
            comparison_final_status=final,comparison_shutdown=shutdown))
    return summarize(blocks,warmup_rows,fps,execution_kind)


def summarize(blocks,warmup,fps,execution_kind):
    if len(blocks)!=4 or [b['comparison_enabled'] for b in blocks]!=[False,True,True,False]:
        raise ValueError('four ABBA blocks required')
    pairs=[]
    for off,on in ((blocks[0],blocks[1]),(blocks[3],blocks[2])):
        if len(off['records'])!=len(on['records']):raise ValueError('unpaired block length')
        for a,b in zip(off['records'],on['records']):
            if (a['original_frame'],a['cycle'])!=(b['original_frame'],b['cycle']):
                raise ValueError('unpaired input identity')
            delta=abs(a['range_m']-b['range_m']) if a['range_m'] is not None and b['range_m'] is not None else None
            pairs.append(dict(off_block=off['id'],on_block=on['id'],original_frame=a['original_frame'],
                cycle=a['cycle'],primary_exact=a['primary_signature']==b['primary_signature'],
                detector_exact=a['detector_signature']==b['detector_signature'],range_abs_delta_m=delta))
    groups={}
    for name,enabled in (('off',False),('on',True)):
        rows=[row for block in blocks if block['comparison_enabled'] is enabled for row in block['records']]
        groups[name]=dict(measured_frames=len(rows),predict_ms=distribution([r['predict_ms'] for r in rows]),
            primary_ms=distribution([r['primary_ms'] for r in rows]),
            comparison_tap_ms=distribution([r['comparison_tap_ms'] for r in rows]),
            primary_log_and_tap_ms=distribution([r['primary_log_and_tap_ms'] for r in rows]),
            start_interval_ms=distribution([r['start_interval_ms'] for r in rows if r['start_interval_ms'] is not None]),
            numeric_frames=sum(r['distance_available'] for r in rows),period_overruns=sum(r['period_overrun'] for r in rows),
            reason_counts=dict(Counter(r['reason'] for r in rows)))
    changes=sum(not row['primary_exact'] for row in pairs)
    return dict(schema='guarded_cuda_saved_image_benchmark_v1',state='complete',
        execution_kind=execution_kind,actual_cuda_inference=execution_kind=='actual_cuda',
        actual_camera=False,actual_vehicle_operation=False,live_latency_verified=False,
        physical_metric_verified=False,usable_for_ffb=False,published_to_ros=False,
        primary_reproducibility='exact_in_sample' if changes==0 else 'differences_observed_NOT_causally_attributed',
        paired_samples=len(pairs),primary_changed_pairs=changes,
        detector_changed_pairs=sum(not row['detector_exact'] for row in pairs),
        warmup_excluded_calls=len(warmup),warmup_predict_ms=distribution([r['predict_ms'] for r in warmup]),
        requested_fps=fps,block_order=['off','on','on','off'],groups=groups,blocks=blocks,pairs=pairs,
        timing_kind='predictor_and_primary_wall_time_on_preloaded_PNG_NOT_pure_GPU_or_live_latency')


def options(parser):
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--weights',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--device',type=int,default=0)
    parser.add_argument('--cycles',type=int,default=20)
    parser.add_argument('--warmup',type=int,default=8)
    parser.add_argument('--fps',type=float,default=30.)
    parser.add_argument('--max-duration-sec',type=float,default=180.)
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--experimental-rigid-mount',action='store_true',required=True)


def run(args):
    import math
    if (not 1<=args.cycles<=100 or not 1<=args.warmup<=64 or not math.isfinite(args.fps) or not 1<=args.fps<=60
            or not math.isfinite(args.max_duration_sec) or not 1<=args.max_duration_sec<=600 or not 0<=args.device<=32):
        raise ValueError('bounded cycles/warmup/fps/duration/device required')
    output=comparison_path(args.output_dir)
    for source in (args.input_dir.resolve(),args.evidence_dir.resolve()):
        if output==source or source in output.parents or output in source.parents:
            raise ValueError('new output outside original input directories required')
    data=load_inputs(args.input_dir,args.evidence_dir,args.config)
    if not args.validate_only:
        if args.weights is None:raise ValueError('explicit local --weights required; no cached/CPU fallback')
        if hash_regular(args.weights.absolute(),512*1024*1024)!=data['settings']['weights_sha256']:
            raise ValueError('checkpoint SHA mismatch; no model loaded')
        data['input_sha256'][str(args.weights.absolute())]=data['settings']['weights_sha256']
    output.mkdir(parents=True,exist_ok=False)
    report=dict(state='running',actual_cuda_inference=False,cuda_model_initialization_attempted=False,
        actual_camera=False,physical_metric_verified=False,
        input_sha256=data['input_sha256'])
    try:
        if args.validate_only:
            report.update(schema='guarded_cuda_input_preflight_v1',state='validated_inputs_only',
                images=len(data['jobs']),cuda_started=False)
        else:
            print('Loading trusted local CUDA model; no camera/ROS/control.',flush=True)
            model_dir=output/'model';model_dir.mkdir()
            report['cuda_model_initialization_attempted']=True
            started=time.monotonic()
            predictor=YoloConePredictor(args.weights,data['settings'],model_dir,args.device)
            model_init_ms=1000*(time.monotonic()-started)
            completed=benchmark(data,predictor,output,cycles=args.cycles,fps=args.fps,warmup=args.warmup,
                max_duration=args.max_duration_sec,execution_kind='actual_cuda')
            report.update(completed)
            report.update(gpu=predictor.gpu,weights_sha256=predictor.weights_sha256,model_initialization_ms=model_init_ms)
        for name,digest in data['input_sha256'].items():
            if hash_regular(Path(name),512*1024*1024)!=digest:raise ValueError('original input changed during benchmark: '+name)
        report['input_sha256']=data['input_sha256']
        report['all_original_inputs_unchanged']=True
        paths=[Path(__file__),*[ROOT/'src'/name for name in ('cone_distance_worker.py','run_cone_yolo.py',
            'cone_detection_diagnostics.py','cone_distance_core.py','angular_fisheye_geometry.py',
            'cone_motion_range.py','cone_upper_support_candidate.py','cone_support_completion_candidate.py',
            'cone_colour_support_candidate.py',
            'cone_support_quality.py','cone_observation.py','theta_rtc_frames.py',
            'driver_guarded_comparison.py','manage_guarded_comparison.py','driver_motion_protocol.py',
            'driver_withheld_evidence.py','cone_guarded_stream_comparison.py',
            'cone_guarded_lower_edge_shadow.py','cone_bbox_boundary_shadow.py','cone_self_body_shadow.py',
            'verify_driver_withheld_evidence.py','run_guarded_recording_comparison.py','report_driver_motion_logs.py')]]
        report['source_sha256']={str(path.relative_to(ROOT)):hash_regular(path,512*1024) for path in paths}
        from importlib.metadata import version,PackageNotFoundError
        report['runtime_versions']={'python':sys.version,'executable':sys.executable}
        for package in ('numpy','opencv-python','torch','ultralytics'):
            try:report['runtime_versions'][package]=version(package)
            except PackageNotFoundError:report['runtime_versions'][package]='distribution_metadata_not_found'
    except BaseException as error:
        report.update(state='failed',error=f'{type(error).__name__}: {error}'[:1000],
            actual_cuda_inference=False,actual_camera=False,physical_metric_verified=False)
        (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        raise
    (output/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({key:report[key] for key in ('state','actual_cuda_inference','actual_camera')},indent=2))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);options(parser)
    try:run(parser.parse_args())
    except Exception as error:
        print(f'[ERROR] saved-image CUDA test failed: {type(error).__name__}: {error}',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
